from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from typing import Any, Optional, Union

from branca.element import MacroElement

from folium import FeatureGroup, GeoJson, TopoJson
from folium.elements import JSCSSMixin
from folium.folium import Map
from folium.map import Marker
from folium.plugins import FeatureGroupSubGroup, MarkerCluster
from folium.template import Template
from folium.utilities import remove_empty


LayerType = Union[GeoJson, TopoJson, FeatureGroup, MarkerCluster, FeatureGroupSubGroup]

_TPL_OPEN = "__TPL_OPEN__"
_TPL_CLOSE = "__TPL_CLOSE__"


def _encode_template(tpl: Optional[str]) -> Optional[str]:
    if tpl is None:
        return None
    return tpl.replace("{{", _TPL_OPEN).replace("}}", _TPL_CLOSE)


@dataclass
class SearchEntry:
    layer_var: str
    stable_id: str
    weight: float
    geom_type: str
    search_zoom: Optional[int]
    haystack: str
    properties: dict
    geometry: dict
    style_options: dict
    source_label: Optional[str]

    def as_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Registration record: pairs a stable_id with the information needed to
# locate the real Leaflet layer at runtime.  Produced during Python-side
# serialization and consumed by the JS registration code emitted by render().
# ---------------------------------------------------------------------------
@dataclass
class _RegEntry:
    stable_id: str
    layer_var: str
    kind: str
    match_key: Optional[str]
    match_value: Optional[str]
    feature_index: Optional[int]
    js_var: Optional[str] = None

    def as_dict(self) -> dict:
        return asdict(self)


def _read_property_bag(kind: str, obj: Any, id_field: Optional[str]) -> dict:
    if kind == "geojson_feature":
        return dict(obj.get("properties") or {})
    if kind == "marker":
        bag = dict(getattr(obj, "options", None) or {})
        return bag
    return {}


def _read_field_values(
    fields: Optional[list[str]],
    bag: dict,
) -> list[str]:
    if not fields:
        return []
    return [str(bag[f]) for f in fields if f in bag and bag[f] is not None]


def _make_stable_id(
    id_field: Optional[str],
    bag: dict,
    fallback: str,
    cfg_idx: int,
) -> str:
    if id_field and id_field in bag and bag[id_field] is not None:
        return f"id_{bag[id_field]}"
    return f"cfg{cfg_idx}_{fallback}"


def _geometry_of(kind: str, obj: Any) -> dict:
    if kind == "geojson_feature":
        return dict(obj.get("geometry") or {"type": "Point", "coordinates": [0, 0]})
    if kind == "marker":
        loc = getattr(obj, "location", None)
        if loc and len(loc) == 2:
            return {"type": "Point", "coordinates": [loc[1], loc[0]]}
        return {"type": "Point", "coordinates": [0, 0]}
    return {"type": "Point", "coordinates": [0, 0]}


def _iter_marker_children(container: Any) -> list[Marker]:
    markers: list[Marker] = []
    for child in getattr(container, "_children", {}).values():
        if isinstance(child, Marker):
            markers.append(child)
        elif isinstance(child, (FeatureGroup, MarkerCluster, FeatureGroupSubGroup)):
            markers.extend(_iter_marker_children(child))
    return markers


def _find_child_group_refs(container: Any, root_map: Any) -> list[Any]:
    results: list[Any] = []
    found_ids: set[int] = set()

    def matches(node: Any) -> bool:
        if not isinstance(node, FeatureGroupSubGroup):
            return False
        if id(node) in found_ids:
            return False
        if node._group is container:
            return True
        for sub in results:
            if node._group is sub:
                return True
        return False

    changed = True
    while changed:
        changed = False

        def walk(node: Any) -> None:
            nonlocal changed
            for child in getattr(node, "_children", {}).values():
                if matches(child):
                    results.append(child)
                    found_ids.add(id(child))
                    changed = True
                if isinstance(
                    child,
                    (FeatureGroup, MarkerCluster, FeatureGroupSubGroup),
                ):
                    walk(child)

        walk(root_map)
    return results


def _collect_all_markers(container: Any, root_map: Any) -> list[Marker]:
    markers = list(_iter_marker_children(container))
    for sub in _find_child_group_refs(container, root_map):
        markers.extend(_iter_marker_children(sub))
    return markers


def _serialize_layer(
    cfg: "SearchLayerConfig",
    cfg_idx: int,
    root_map: Any = None,
) -> tuple[list[SearchEntry], list[_RegEntry]]:
    entries: list[SearchEntry] = []
    regs: list[_RegEntry] = []
    layer = cfg.layer
    search_fields = cfg.search_fields or []
    display_fields = cfg.display_fields or []

    # -------- GeoJson --------
    if isinstance(layer, GeoJson):
        features = (layer.data or {}).get("features", [])
        for idx, feat in enumerate(features):
            kind = "geojson_feature"
            bag = _read_property_bag(kind, feat, cfg.id_field)
            sid = _make_stable_id(
                cfg.id_field,
                bag,
                f"{cfg.layer_var}_f{idx}",
                cfg_idx,
            )
            haystack_parts = _read_field_values(search_fields, bag)
            if not haystack_parts:
                haystack_parts = [str(v) for v in bag.values() if v is not None]
            props_for_js = {
                **bag,
                "__displayFields": _read_field_values(display_fields, bag),
            }
            geom = feat.get("geometry")
            entries.append(
                SearchEntry(
                    layer_var=cfg.layer_var,
                    stable_id=sid,
                    weight=cfg.weight,
                    geom_type=cfg.geom_type,
                    search_zoom=cfg.search_zoom,
                    haystack=" ".join(haystack_parts),
                    properties=props_for_js,
                    geometry=dict(geom) if geom else _geometry_of(kind, feat),
                    style_options=dict(cfg.options or {}),
                    source_label=cfg.layer_var,
                )
            )
            # Registration: GeoJson sub-layers are the Nth child produced
            # by eachLayer on the source layer.  We record the feature
            # index so JS can walk eachLayer and tag the right one.
            regs.append(
                _RegEntry(
                    stable_id=sid,
                    layer_var=cfg.layer_var,
                    kind="geojson",
                    match_key=cfg.id_field,
                    match_value=str(bag[cfg.id_field]) if cfg.id_field and cfg.id_field in bag else None,
                    feature_index=idx,
                )
            )
        return entries, regs

    # -------- TopoJson --------
    if isinstance(layer, TopoJson):
        obj_name = layer.object_path.split(".")[-1]
        topo_objs = (layer.data or {}).get("objects", {}).get(obj_name, {})
        geometries = topo_objs.get("geometries", [])
        for idx, geom in enumerate(geometries):
            kind = "geojson_feature"
            bag = _read_property_bag(kind, geom, cfg.id_field)
            sid = _make_stable_id(
                cfg.id_field,
                bag,
                f"{cfg.layer_var}_g{idx}",
                cfg_idx,
            )
            haystack_parts = _read_field_values(search_fields, bag)
            if not haystack_parts:
                haystack_parts = [str(v) for v in bag.values() if v is not None]
            props_for_js = {
                **bag,
                "__displayFields": _read_field_values(display_fields, bag),
            }
            entries.append(
                SearchEntry(
                    layer_var=cfg.layer_var,
                    stable_id=sid,
                    weight=cfg.weight,
                    geom_type=cfg.geom_type,
                    search_zoom=cfg.search_zoom,
                    haystack=" ".join(haystack_parts),
                    properties=props_for_js,
                    geometry={"type": "Point", "coordinates": [0, 0]},
                    style_options=dict(cfg.options or {}),
                    source_label=cfg.layer_var,
                )
            )
            regs.append(
                _RegEntry(
                    stable_id=sid,
                    layer_var=cfg.layer_var,
                    kind="topojson",
                    match_key=cfg.id_field,
                    match_value=str(bag[cfg.id_field]) if cfg.id_field and cfg.id_field in bag else None,
                    feature_index=idx,
                )
            )
        return entries, regs

    # -------- Marker containers --------
    if isinstance(layer, (FeatureGroup, MarkerCluster, FeatureGroupSubGroup)):
        if root_map is None:
            markers = _iter_marker_children(layer)
        else:
            markers = _collect_all_markers(layer, root_map)
        for marker in markers:
            kind = "marker"
            bag = _read_property_bag(kind, marker, cfg.id_field)
            sid = _make_stable_id(
                cfg.id_field,
                bag,
                f"{marker.get_name()}",
                cfg_idx,
            )
            haystack_parts = _read_field_values(search_fields, bag)
            if not haystack_parts and "title" in bag:
                haystack_parts = [str(bag["title"])]
            props_for_js = {
                **bag,
                "__displayFields": _read_field_values(display_fields, bag)
                or ([str(bag["title"])] if "title" in bag else []),
            }
            entries.append(
                SearchEntry(
                    layer_var=cfg.layer_var,
                    stable_id=sid,
                    weight=cfg.weight,
                    geom_type=cfg.geom_type,
                    search_zoom=cfg.search_zoom,
                    haystack=" ".join(haystack_parts),
                    properties=props_for_js,
                    geometry=_geometry_of(kind, marker),
                    style_options=dict(cfg.options or {}),
                    source_label=cfg.layer_var,
                )
            )
            regs.append(
                _RegEntry(
                    stable_id=sid,
                    layer_var=cfg.layer_var,
                    kind="marker",
                    match_key=None,
                    match_value=None,
                    feature_index=None,
                    js_var=marker.get_name(),
                )
            )
        return entries, regs

    raise TypeError(f"Unsupported layer type: {type(layer).__name__}")


def _dedupe_pairs(
    pairs: list[tuple[SearchEntry, _RegEntry]],
) -> tuple[list[SearchEntry], list[_RegEntry]]:
    """Deduplicate (entry, reg) pairs by ``stable_id``, keeping the one
    with the highest ``weight``.

    Stable: if two pairs share the same weight, the first one wins.
    """
    best: dict[str, tuple[SearchEntry, _RegEntry]] = {}
    for entry, reg in pairs:
        existing_pair = best.get(entry.stable_id)
        if (
            existing_pair is None
            or existing_pair[0].weight < entry.weight
        ):
            best[entry.stable_id] = (entry, reg)
    entries = [p[0] for p in best.values()]
    regs = [p[1] for p in best.values()]
    return entries, regs


class SearchLayerConfig:
    """
    Configuration for a single searchable layer within a unified Search control.

    Parameters
    ----------
    layer : GeoJson, TopoJson, FeatureGroup, MarkerCluster or FeatureGroupSubGroup
        The layer whose features should be indexed for search.
    search_fields : str or list of str, optional
        The property field(s) to search on.
    display_fields : str or list of str, optional
        The property field(s) shown in the result suggestion.
    label_template : str, optional
        A custom template string used to render each result row.
    id_field : str, optional
        A property name used as a stable identifier across layers.
    weight : int or float, default 1
        A weight applied to this layer's matches.
    search_zoom : int, optional
        Zoom level used when flying to a match from this layer.
    geom_type : str, default ``"Point"``
        One of ``"Point"``, ``"Line"`` or ``"Polygon"``.
    **kwargs
        Additional style options applied to a matched feature on this layer only.
    """

    def __init__(
        self,
        layer: LayerType,
        search_fields: Optional[Union[str, list[str]]] = None,
        display_fields: Optional[Union[str, list[str]]] = None,
        label_template: Optional[str] = None,
        id_field: Optional[str] = None,
        weight: Union[int, float] = 1,
        search_zoom: Optional[int] = None,
        geom_type: str = "Point",
        **kwargs: Any,
    ):
        if not isinstance(
            layer,
            (GeoJson, TopoJson, FeatureGroup, MarkerCluster, FeatureGroupSubGroup),
        ):
            raise TypeError(
                "SearchLayerConfig.layer must be a GeoJson, TopoJson, "
                "FeatureGroup, MarkerCluster or FeatureGroupSubGroup instance."
            )
        self.layer = layer
        self.search_fields = (
            [search_fields] if isinstance(search_fields, str) else search_fields
        )
        self.display_fields = (
            [display_fields]
            if isinstance(display_fields, str)
            else (display_fields or self.search_fields)
        )
        self.label_template = _encode_template(label_template)
        self.id_field = id_field
        self.weight = weight
        self.search_zoom = search_zoom
        self.geom_type = geom_type
        self.options = remove_empty(**kwargs)

    @property
    def layer_var(self) -> str:
        return self.layer.get_name()

    def get_properties_keys(self) -> Optional[tuple[str, ...]]:
        if isinstance(self.layer, GeoJson):
            features = self.layer.data.get("features")
            if features and len(features) > 0:
                props = features[0].get("properties") or {}
                return tuple(props.keys())
        if isinstance(self.layer, TopoJson):
            obj_name = self.layer.object_path.split(".")[-1]
            geometries = self.layer.data.get("objects", {}).get(obj_name, {}).get(
                "geometries"
            )
            if geometries and len(geometries) > 0:
                props = geometries[0].get("properties") or {}
                return tuple(props.keys())
        return None

    def validate(self) -> None:
        keys = self.get_properties_keys()
        if keys is None:
            return
        for field_list in (self.search_fields or [], self.display_fields or []):
            if field_list is None:
                continue
            for f in field_list:
                if f not in keys:
                    raise AssertionError(
                        f"The field '{f}' was not available in {keys}"
                    )


class Search(JSCSSMixin, MacroElement):
    """
    Adds a search tool to your map.

    Supports indexing features from multiple layers at once, with optional
    deduplication by a stable identifier, weighted sorting and per-layer
    configuration.

    Layer-data differences are resolved on the Python side during render.
    Each configured layer is flattened into a list of :class:`SearchEntry`
    records.  A deterministic JS registration table (``window.__searchReg``)
    maps each ``stable_id`` to the real Leaflet layer object so that
    highlight / popup / fly-to always operate on the authoritative layer,
    never on the invisible index layer and never via heuristic matching.

    Parameters
    ----------
    layer : GeoJson, TopoJson, FeatureGroup, MarkerCluster or FeatureGroupSubGroup, optional
        Legacy single-layer parameter.
    search_label : str, optional
        Legacy parameter – shorthand for ``search_fields=search_label``.
    search_zoom : int, optional
        Global default zoom level.
    geom_type : str, default ``"Point"``
        Global default geometry type.
    position : str, default ``'topleft'``
    placeholder : str, default ``'Search'``
    collapsed : bool, default False
    text_not_found : str, default ``'Not found'``
    label_template : str, optional
        Global default template for result rows.
    layers : list of SearchLayerConfig, optional
        The multi-source configuration.
    **kwargs
        Style options applied to every matched feature.
    """

    _template = Template(
        r"""
        {% macro script(this, kwargs) %}
            (function () {
                var map = {{ this._parent.get_name() }};
                var index = {{ this.search_index|tojson }};
                var globalStyle = {{ this.options|tojavascript }};
                var globalTpl = {{ this.label_template|tojson|safe }};

                // ---------------------------------------------------------
                // Deterministic registry: stable_id → real Leaflet layer.
                // Populated by code emitted from Python render() which
                // knows exactly which sub-layer maps to which stable_id.
                // No heuristic matching; deterministic registry only.
                // ---------------------------------------------------------
                if (!window.__searchReg) window.__searchReg = {};
                {{ this._registration_js }}

                // ---------------------------------------------------------
                // Build the invisible index layer for leaflet-search.
                // ---------------------------------------------------------
                var unifiedLayer = L.geoJson(null, {
                    pointToLayer: function (feature, latlng) {
                        return L.circleMarker(latlng, { radius: 0, opacity: 0 });
                    },
                    style: function () { return { opacity: 0, fillOpacity: 0 }; }
                });

                index.forEach(function (entry) {
                    var feature = {
                        type: 'Feature',
                        properties: Object.assign(
                            { __searchHaystack: entry.haystack },
                            entry.properties
                        ),
                        geometry: entry.geometry
                    };
                    var layer = unifiedLayer.addData(feature).getLayers().slice(-1)[0];
                    layer.__searchEntry = entry;
                });

                // ---------------------------------------------------------
                // Template compiler.
                // ---------------------------------------------------------
                {% raw %}
                function compileTemplate(tpl, ctx) {
                    if (!tpl) return '';
                    var OPEN = '__TPL_OPEN__';
                    var CLOSE = '__TPL_CLOSE__';
                    var backslash = '\\';
                    var re = new RegExp(
                        OPEN + backslash + 's*([\\w.]+)' + backslash + 's*' + CLOSE, 'g'
                    );
                    return tpl.replace(re, function (_, path) {
                        var parts = path.split('.');
                        var val = ctx;
                        for (var i = 0; i < parts.length; i++) {
                            if (val == null) return '';
                            val = val[parts[i]];
                        }
                        return (val == null) ? '' : String(val);
                    });
                }
                {% endraw %}

                function buildLabel(entry, layerTpl) {
                    var props = entry.properties || {};
                    var ctx = {
                        properties: props,
                        options: props,
                        weight: entry.weight,
                        layerName: entry.sourceLabel
                    };
                    var tpl = layerTpl || globalTpl;
                    if (tpl) return compileTemplate(tpl, ctx);
                    var fields = props.__displayFields || [];
                    if (Array.isArray(fields) && fields.length) {
                        return fields.join(' \u00b7 ');
                    }
                    return entry.haystack;
                }

                // ---------------------------------------------------------
                // Instantiate the search control.
                // ---------------------------------------------------------
                var {{ this.get_name() }} = new L.Control.Search({
                    layer: unifiedLayer,
                    propertyName: '__searchHaystack',
                    collapsed: {{ this.collapsed|tojson|safe }},
                    textPlaceholder: '{{ this.placeholder }}',
                    textNotFound: '{{ this.text_not_found }}',
                    position: '{{ this.position }}',
                    initial: false,
                    hideMarkerOnCollapse: true,
                    marker: false,
                    sortFeatures: function (a, b) {
                        var wa = a.layer.__searchEntry
                               ? a.layer.__searchEntry.weight : 1;
                        var wb = b.layer.__searchEntry
                               ? b.layer.__searchEntry.weight : 1;
                        if (wb !== wa) return wb - wa;
                        return a.value.length - b.value.length;
                    },
                    buildTip: function (text, val) {
                        var entry = val.layer.__searchEntry;
                        var layerTpl = null;
                        if (entry && entry.layerTpl) layerTpl = entry.layerTpl;
                        var tip = entry ? buildLabel(entry, layerTpl) : text;
                        return L.DomUtil.create('div', 'search-tip')
                               .appendChild(document.createTextNode(
                                   tip || text)).parentNode;
                    },
                    moveToLocation: function (latlng, title, map) {
                        var entry = latlng.layer
                                  ? latlng.layer.__searchEntry : null;
                        if (!entry) return;
                        // Deterministic lookup – no guessing.
                        var orig = window.__searchReg[entry.stableId] || null;
                        var targetZoom = entry.searchZoom;
                        {% if this.search_zoom %}
                            if (targetZoom == null) targetZoom = {{ this.search_zoom }};
                        {% endif %}
                        var geom = entry.geomType || 'Point';
                        if (geom === 'Point') {
                            var pos = orig && orig.getLatLng
                                      ? orig.getLatLng()
                                      : (latlng.latlng || latlng);
                            if (targetZoom == null) targetZoom = map.getZoom();
                            map.flyTo(pos, targetZoom);
                        } else if (orig && orig.getBounds) {
                            var bounds = orig.getBounds();
                            if (targetZoom == null) {
                                targetZoom = map.getBoundsZoom(bounds);
                            }
                            map.flyToBounds(bounds, { maxZoom: targetZoom });
                        } else {
                            map.flyTo(latlng.latlng || latlng,
                                      targetZoom || map.getZoom());
                        }
                        latlng.__resolvedOriginal = orig;
                    }
                });

                // ---------------------------------------------------------
                // Highlight & style handling.
                // ---------------------------------------------------------
                function applyStyle(entry, layer) {
                    if (!layer || typeof layer.setStyle !== 'function') return;
                    var merged = L.extend({}, globalStyle, entry.styleOptions || {});
                    if (Object.keys(merged).length) layer.setStyle(merged);
                }

                function resetAllStyles() {
                    {% for cfg in this.layer_configs %}
                    (function () {
                        var src = {{ cfg.layer_var }};
                        if (src && typeof src.setStyle === 'function') {
                            try {
                                src.setStyle(function (feature) {
                                    return feature && feature.properties
                                           ? feature.properties.style
                                           : {};
                                });
                            } catch (e) {}
                        }
                        if (src && typeof src.eachLayer === 'function') {
                            src.eachLayer(function (l) {
                                if (typeof l.resetStyle === 'function') {
                                    try { l.resetStyle(); } catch (e) {}
                                }
                                if (l.feature && l.feature.properties &&
                                    l.feature.properties.style &&
                                    typeof l.setStyle === 'function') {
                                    try { l.setStyle(l.feature.properties.style); }
                                    catch (e) {}
                                }
                            });
                        }
                    })();
                    {% endfor %}
                }

                {{ this.get_name() }}.on('search:locationfound', function (e) {
                    resetAllStyles();
                    var entry = e.layer ? e.layer.__searchEntry : null;
                    // Deterministic lookup – no guessing.
                    var orig = (e.__resolvedOriginal)
                               || (entry ? window.__searchReg[entry.stableId] : null)
                               || e.layer;
                    if (entry && orig) applyStyle(entry, orig);
                    if (orig && orig._popup) orig.openPopup();
                    if (orig && typeof orig.bindTooltip === 'function' &&
                        !orig._tooltip && entry) {
                        var label = buildLabel(entry, entry.layerTpl || null);
                        if (label) orig.bindTooltip(label).openTooltip();
                    }
                });

                {{ this.get_name() }}.on('search:collapsed', resetAllStyles);

                map.addControl({{ this.get_name() }});
            })();
        {% endmacro %}
        """
    )

    default_js = [
        (
            "Leaflet.Search.js",
            "https://cdn.jsdelivr.net/npm/leaflet-search@2.9.7/dist/leaflet-search.min.js",
        )
    ]
    default_css = [
        (
            "Leaflet.Search.css",
            "https://cdn.jsdelivr.net/npm/leaflet-search@2.9.7/dist/leaflet-search.min.css",
        )
    ]

    def __init__(
        self,
        layer: Optional[LayerType] = None,
        search_label: Optional[str] = None,
        search_zoom: Optional[int] = None,
        geom_type: str = "Point",
        position: str = "topleft",
        placeholder: str = "Search",
        collapsed: bool = False,
        text_not_found: str = "Not found",
        label_template: Optional[str] = None,
        layers: Optional[list[SearchLayerConfig]] = None,
        **kwargs: Any,
    ):
        super().__init__()
        self._name = "Search"

        if layers is None and layer is None:
            raise ValueError(
                "Search requires either a 'layer' (legacy single-layer) "
                "argument or a 'layers' (list of SearchLayerConfig) argument."
            )
        if layers is not None and layer is not None:
            raise ValueError(
                "Search accepts either 'layer' OR 'layers', not both."
            )

        if layer is not None:
            layers = [
                SearchLayerConfig(
                    layer=layer,
                    search_fields=search_label,
                    display_fields=search_label,
                    search_zoom=search_zoom,
                    geom_type=geom_type,
                    **kwargs,
                )
            ]
            kwargs = {}

        for cfg in layers:
            if not isinstance(cfg, SearchLayerConfig):
                raise TypeError(
                    "Every entry in 'layers' must be a SearchLayerConfig "
                    f"instance; got {type(cfg).__name__}."
                )

        self.layer_configs = layers
        self.search_zoom = search_zoom
        self.position = position
        self.placeholder = placeholder
        self.collapsed = collapsed
        self.text_not_found = text_not_found
        self.label_template = _encode_template(label_template)
        self.options = remove_empty(**kwargs)

        self.search_index: list = []
        self._registration_js: str = ""

        # Back-compat attributes.
        self.layer = self.layer_configs[0].layer if layer is not None else None
        self.search_label = search_label
        self.geom_type = geom_type

    def test_params(self, keys):
        if keys is not None and self.search_label is not None:
            assert self.search_label in keys, (
                f"The label '{self.search_label}' was not " f"available in {keys}" ""
            )
        assert isinstance(
            self._parent, Map
        ), "Search can only be added to folium Map objects."

    def _build_registration_js(
        self,
        regs: list[_RegEntry],
        entries: list[SearchEntry],
    ) -> str:
        """Generate deterministic JS that writes ``stable_id → real layer``
        into ``window.__searchReg`` for every registered search entry.

        The JS code walks each source layer's eachLayer() exactly once,
        matching sub-layers by the criteria encoded in _RegEntry:

        * GeoJson/TopoJson sub-layers are matched by their ordinal
          position (``feature_index``) which is the order that
          L.geoJson.eachLayer yields sub-layers in.
        * Markers are matched by their Python-assigned ``get_name()``
          which is the global JS variable name assigned by branca.

        This is fully deterministic – no haystack comparison, no
        childRef variable-scope guessing.
        """
        lines: list[str] = []

        # Group registrations by layer_var so we walk each source layer
        # once.
        by_layer: dict[str, list[_RegEntry]] = {}
        for r in regs:
            by_layer.setdefault(r.layer_var, []).append(r)

        for layer_var, layer_regs in by_layer.items():
            # Separate marker regs (matched by global variable name)
            # from geojson/topojson regs (matched by feature_index).
            marker_regs = [r for r in layer_regs if r.kind == "marker"]
            geojson_regs = [r for r in layer_regs if r.kind in ("geojson", "topojson")]

            # --- Register markers by their global JS variable name. ---
            for r in marker_regs:
                if r.js_var:
                    lines.append(
                        f"if (typeof {r.js_var} !== 'undefined') {{ "
                        f"window.__searchReg['{r.stable_id}'] = "
                        f"{r.js_var}; }}"
                    )

            # --- Register GeoJson/TopoJson sub-layers by feature index. ---
            if geojson_regs:
                sid_by_idx = {
                    r.feature_index: r.stable_id for r in geojson_regs
                }
                sid_map_json = json.dumps(sid_by_idx)
                lines.append(
                    f"(function () {{"
                    f"  var src = {layer_var};"
                    f"  if (!src || typeof src.eachLayer !== 'function') return;"
                    f"  var idx = 0;"
                    f"  var sidMap = {sid_map_json};"
                    f"  src.eachLayer(function (l) {{"
                    f"    var sid = sidMap[idx];"
                    f"    if (sid) window.__searchReg[sid] = l;"
                    f"    idx++;"
                    f"  }});"
                    f"}})();"
                )

        return "\n".join(lines)

    def render(self, **kwargs):
        # Legacy validation path.
        if self.layer is not None:
            if isinstance(self.layer, GeoJson):
                keys = tuple(self.layer.data["features"][0]["properties"].keys())
            elif isinstance(self.layer, TopoJson):
                obj_name = self.layer.object_path.split(".")[-1]
                keys = tuple(
                    self.layer.data["objects"][obj_name]["geometries"][0][
                        "properties"
                    ].keys()
                )
            else:
                keys = None
            self.test_params(keys=keys)

        for cfg in self.layer_configs:
            cfg.validate()

        # ---- Build the unified search index entirely in Python. ----
        raw_pairs: list[tuple[SearchEntry, _RegEntry]] = []
        root_map = getattr(self, "_parent", None)
        for idx, cfg in enumerate(self.layer_configs):
            entries, regs = _serialize_layer(cfg, idx, root_map)
            raw_pairs.extend(zip(entries, regs))

        entries, regs = _dedupe_pairs(raw_pairs)

        per_config_tpl: dict[str, Optional[str]] = {
            cfg.layer_var: cfg.label_template for cfg in self.layer_configs
        }
        entries.sort(key=lambda e: (-e.weight, e.stable_id))

        payload = []
        for e in entries:
            d = e.as_dict()
            d["layerTpl"] = per_config_tpl.get(e.layer_var)
            payload.append(d)

        self.search_index = payload
        self._registration_js = self._build_registration_js(regs, entries)

        super().render(**kwargs)
