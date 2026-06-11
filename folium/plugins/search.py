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
from folium.utilities import JsCode, remove_empty


LayerType = Union[GeoJson, TopoJson, FeatureGroup, MarkerCluster, FeatureGroupSubGroup]

_TPL_OPEN = "__TPL_OPEN__"
_TPL_CLOSE = "__TPL_CLOSE__"


def _encode_template(tpl: Optional[str]) -> Optional[str]:
    if tpl is None:
        return None
    return tpl.replace("{{", _TPL_OPEN).replace("}}", _TPL_CLOSE)


# ---------------------------------------------------------------------------
# Unified search entry – the result of serializing a single "thing" (a GeoJson
# feature, a Marker, etc.) out of any supported layer type.
# ---------------------------------------------------------------------------
@dataclass
class SearchEntry:
    layer_var: str
    child_ref: str
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
# Field reading / id generation – dispatcher per layer type.
# These operate purely on the Python object graph; no JS-side guessing.
# ---------------------------------------------------------------------------
def _read_property_bag(kind: str, obj: Any, id_field: Optional[str]) -> dict:
    """Return the dict-like bag we read search/id fields from."""
    if kind == "geojson_feature":
        return dict(obj.get("properties") or {})
    if kind == "marker":
        # Marker's field bag is its JS options dict (title, alt, …)
        bag = dict(getattr(obj, "options", None) or {})
        # Special: MarkerCluster's popups/icons are attached via add_child(),
        # but for searching we only look at the user-supplied options.
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
        # Use the id_field value alone so features from different layer
        # configs that share the same logical id still get deduplicated.
        return f"id_{bag[id_field]}"
    return f"cfg{cfg_idx}_{fallback}"


def _geometry_of(kind: str, obj: Any) -> dict:
    if kind == "geojson_feature":
        return dict(obj.get("geometry") or {"type": "Point", "coordinates": [0, 0]})
    if kind == "marker":
        loc = getattr(obj, "location", None)
        if loc and len(loc) == 2:
            # GeoJson uses [lon, lat]; Marker stores [lat, lon]
            return {"type": "Point", "coordinates": [loc[1], loc[0]]}
        return {"type": "Point", "coordinates": [0, 0]}
    return {"type": "Point", "coordinates": [0, 0]}


def _iter_marker_children(container: Any) -> list[Marker]:
    """Recursively collect Marker instances from a container's children.

    Handles FeatureGroup, MarkerCluster and FeatureGroupSubGroup.  For
    FeatureGroupSubGroup/MarkerCluster we also walk the `_group` relationship so
    that subgroups which were added directly to the map (not as Python children
    of the container) still get their markers included.
    """
    markers: list[Marker] = []
    for child in getattr(container, "_children", {}).values():
        if isinstance(child, Marker):
            markers.append(child)
        elif isinstance(child, (FeatureGroup, MarkerCluster, FeatureGroupSubGroup)):
            markers.extend(_iter_marker_children(child))
    # For containers that can host conceptual children via the `_group` reference
    # (MarkerCluster and FeatureGroupSubGroup), walk the entire object tree
    # starting from root map and include any FeatureGroupSubGroup whose
    # `_group == container` by walking up the _group chain.
    return markers


def _find_child_group_refs(container: Any, root_map: Any) -> list[Any]:
    """Return a list of FeatureGroupSubGroups conceptually inside `container`.

    A FeatureGroupSubGroup counts as conceptually inside a container if its
    ``_group`` attribute is the container, OR if its ``_group`` is another
    subgroup already inside the container (transitive closure).

    Results are ordered by the time of discovery so subgroups are discovered
    after their parents.
    """
    results: list[Any] = []
    found_ids: set[int] = set()

    def matches(node: Any) -> bool:
        if not isinstance(node, FeatureGroupSubGroup):
            return False
        if id(node) in found_ids:
            return False
        if node._group is container:
            return True
        # Check if _group points to a subgroup we already identified as
        # being part of this container (transitive).
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
                if id(child) in found_ids:
                    # Continue walking so deeply nested children still get seen
                    pass
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
) -> list[SearchEntry]:
    """Convert any supported layer into a list of SearchEntry records.

    This is the single point where layer-type differences are resolved.
    """
    entries: list[SearchEntry] = []
    layer = cfg.layer
    search_fields = cfg.search_fields or []
    display_fields = cfg.display_fields or []

    # -------- GeoJson / TopoJson --------
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
                # Fall back to all string-ish property values so the entry
                # still matches on something when the user forgot fields.
                haystack_parts = [str(v) for v in bag.values() if v is not None]
            props_for_js = {
                **bag,
                "__displayFields": _read_field_values(display_fields, bag),
            }
            geom = feat.get("geometry")
            entries.append(
                SearchEntry(
                    layer_var=cfg.layer_var,
                    child_ref="",
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
        return entries

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
            # leaflet-search needs real coordinates; for TopoJson we cannot
            # easily decode arcs server-side, so we fall back to centroid
            # stubs and let the JS locate via the original layer reference.
            entries.append(
                SearchEntry(
                    layer_var=cfg.layer_var,
                    child_ref="",
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
        return entries

    # -------- Marker containers: FeatureGroup / MarkerCluster /
    #          FeatureGroupSubGroup --------
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
                    child_ref=marker.get_name(),
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
        return entries

    raise TypeError(f"Unsupported layer type: {type(layer).__name__}")


def _dedupe_entries(entries: list[SearchEntry]) -> list[SearchEntry]:
    """Keep the highest-weight occurrence of each stable_id."""
    best: dict[str, SearchEntry] = {}
    for e in entries:
        existing = best.get(e.stable_id)
        if existing is None or existing.weight < e.weight:
            best[e.stable_id] = e
    return list(best.values())


# ---------------------------------------------------------------------------
# Public configuration objects
# ---------------------------------------------------------------------------
class SearchLayerConfig:
    """
    Configuration for a single searchable layer within a unified Search control.

    Parameters
    ----------
    layer : GeoJson, TopoJson, FeatureGroup, MarkerCluster or FeatureGroupSubGroup
        The layer whose features should be indexed for search.
    search_fields : str or list of str, optional
        The property field(s) to search on. If a list is provided, all fields
        will be concatenated for matching.  For GeoJson/TopoJson these are
        keys in the feature's ``properties``; for FeatureGroup/MarkerCluster
        they are attribute names on each child layer (e.g. ``"title"``).
    display_fields : str or list of str, optional
        The property field(s) shown in the result suggestion. Defaults to the
        same value as ``search_fields``.
    label_template : str, optional
        A custom template string used to render each result row. The string
        may reference ``{{properties.fieldname}}`` (for GeoJson/TopoJson) or
        ``{{options.fieldname}}`` plus any attributes attached directly to
        the layer.  When omitted a sensible default is built from
        ``display_fields``.  This value overrides the global ``label_template``
        on :class:`Search` for this layer only.
    id_field : str, optional
        A property name used as a stable identifier across layers.  Features
        appearing in more than one configured layer that share the same id
        value are deduplicated so only the first (highest-weight) match is
        kept.  When omitted the Leaflet internal ``_leaflet_id`` is used,
        which only deduplicates within a single layer instance.
    weight : int or float, default 1
        A weight applied to this layer's matches.  Results are ordered by
        weight (descending) first, then by the default leaflet-search
        relevance.  Higher values surface this layer's results earlier.
    search_zoom : int, optional
        Zoom level used when flying to a match from this layer.  If omitted
        the map will use either the global ``search_zoom`` setting on
        :class:`Search` or, for polygons/lines, the natural bounds of the
        matched feature.
    geom_type : str, default ``"Point"``
        One of ``"Point"``, ``"Line"`` or ``"Polygon"``.  Determines whether
        a marker is drawn on match and how the map animates to the feature.
    **kwargs
        Additional style options that are applied to a matched feature on
        this layer only (e.g. ``color``, ``weight``).
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

    Layer-data differences (GeoJson ``properties``, Marker ``options``,
    recursive subgroups inside ``MarkerCluster``, …) are resolved on the
    Python side during render: each configurable layer is flattened into a
    list of :class:`SearchEntry` records, deduplicated by ``id_field``,
    sorted by ``weight`` and then handed to the client as a single JSON
    index.  The JavaScript side no longer walks ``eachLayer()`` trying to
    guess each source's data layout.

    Parameters
    ----------
    layer : GeoJson, TopoJson, FeatureGroup, MarkerCluster or FeatureGroupSubGroup, optional
        Legacy single-layer parameter.  If provided together with the
        existing ``search_label`` / ``geom_type`` arguments behaviour is
        identical to the pre-multi-source API.
    search_label : str, optional
        Legacy parameter – the single ``'properties'`` key to index for a
        GeoJson/TopoJson layer.  Shorthand for setting
        ``search_fields=search_label`` on a :class:`SearchLayerConfig`.
    search_zoom : int, optional
        Global default zoom level applied to any matched feature whose
        :class:`SearchLayerConfig` does not specify its own ``search_zoom``.
    geom_type : str, default ``"Point"``
        Global default geometry type used when the parameter is not set on a
        per-layer :class:`SearchLayerConfig`.
    position : str, default ``'topleft'``
        Position of the search bar.  One of ``'topleft'``, ``'topright'``,
        ``'bottomright'`` or ``'bottomleft'``.
    placeholder : str, default ``'Search'``
        Placeholder text inside the search box.
    collapsed : bool, default False
        Whether the search box should be collapsed by default.
    text_not_found : str, default ``'Not found'``
        Message shown when the query matches no feature.
    label_template : str, optional
        Global default template used to render each search result row.
        Overridable on each :class:`SearchLayerConfig`.  The string may
        contain ``{{properties.name}}`` placeholders (for GeoJson/TopoJson
        properties) as well as ``{{weight}}`` and ``{{layerName}}``.  When
        not provided a simple label is built from each config's
        ``display_fields``.
    layers : list of SearchLayerConfig, optional
        The multi-source configuration.  Either ``layers`` or the legacy
        ``layer`` argument must be supplied.
    **kwargs
        Assorted style options applied to every matched feature (merged with
        any per-layer options).  Use the same syntax as for vector layer
        arguments (e.g. ``color``, ``weight``).

    Examples
    --------
    Single-layer legacy usage – unchanged from earlier releases::

        Search(layer=stategeo, geom_type='Polygon', search_label='name')

    Multi-layer unified search with per-layer weighting and deduplication::

        Search(
            layers=[
                SearchLayerConfig(stategeo, search_fields='name',
                                  display_fields=['name', 'density'],
                                  id_field='state_id', weight=3,
                                  geom_type='Polygon'),
                SearchLayerConfig(citygeo, search_fields='nameascii',
                                  id_field='city_id', weight=1,
                                  geom_type='Point'),
            ],
            text_not_found='No matching state or city.',
            label_template='<b>{{properties.name}}</b>',
        )
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
                // Rebuild a tiny L.GeoJson layer from the server-side index
                // so leaflet-search can index it uniformly.  Each fake
                // feature carries a pointer (__entry) back to the
                // authoritative Python-generated record.
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
                // Template compiler (Python pre-encoded handlebars-style
                // placeholders into __TPL_OPEN__ / __TPL_CLOSE__ tokens
                // so Jinja2 never touches them).
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
                // Given an entry, locate the *original* layer on the map
                // so highlighting / popups work against the user's real
                // features rather than the invisible index layer.
                // ---------------------------------------------------------
                function resolveOriginalLayer(entry) {
                    var src = window[entry.layerVar];
                    if (!src || typeof src.eachLayer !== 'function') return null;
                    var found = null;
                    src.eachLayer(function (l) {
                        if (found) return;
                        // GeoJson features match by stable_id carried in
                        // properties; Markers match by child_ref (Python
                        // get_name() → Leaflet variable name).
                        if (entry.childRef &&
                            typeof window[entry.childRef] !== 'undefined' &&
                            window[entry.childRef] === l) {
                            found = l; return;
                        }
                        var p = l.feature && l.feature.properties;
                        if (p && p.__searchStableId === entry.stableId) {
                            found = l; return;
                        }
                        // Fallback: compare search haystack – good enough
                        // for TopoJson arcs where we can't decode coords.
                        if (p && p.__searchHaystack &&
                            p.__searchHaystack === entry.haystack && entry.haystack) {
                            found = l; return;
                        }
                    });
                    return found;
                }

                // Decorate each source layer's features with the stable id
                // so resolveOriginalLayer can match them back quickly.
                index.forEach(function (entry) {
                    var src = window[entry.layerVar];
                    if (!src || typeof src.eachLayer !== 'function') return;
                    src.eachLayer(function (l) {
                        var p = l.feature && l.feature.properties;
                        if (!p) return;
                        var bag = Object.assign({}, p);
                        var hay = (entry.searchFields || [])
                            .map(function (k) { return bag[k]; })
                            .filter(function (v) { return v != null; })
                            .join(' ');
                        if (!hay) hay = [].map.call(
                            Object.values(bag), String
                        ).join(' ');
                        if (hay === entry.haystack && entry.haystack) {
                            p.__searchStableId = entry.stableId;
                        }
                    });
                });

                // ---------------------------------------------------------
                // Build the search control.
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
                    // Results: weight desc, then haystack length asc.
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
                        // Fall back to per-layer label template encoded in
                        // the haystack index by Python (if any).
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
                        var orig = resolveOriginalLayer(entry) || latlng.layer;
                        var targetZoom = entry.searchZoom;
                        {% if this.search_zoom %}
                            if (targetZoom == null) targetZoom = {{ this.search_zoom }};
                        {% endif %}
                        var geom = entry.geomType || 'Point';
                        if (geom === 'Point') {
                            var pos = orig.getLatLng
                                      ? orig.getLatLng()
                                      : (latlng.latlng || latlng);
                            if (targetZoom == null) targetZoom = map.getZoom();
                            map.flyTo(pos, targetZoom);
                        } else if (orig.getBounds) {
                            var bounds = orig.getBounds();
                            if (targetZoom == null) {
                                targetZoom = map.getBoundsZoom(bounds);
                            }
                            map.flyToBounds(bounds, { maxZoom: targetZoom });
                        } else {
                            map.flyTo(latlng.latlng || latlng,
                                      targetZoom || map.getZoom());
                        }
                        // Stash the resolved original layer so the
                        // locationfound handler can style the right thing.
                        latlng.__resolvedOriginal = orig;
                    }
                });

                // ---------------------------------------------------------
                // Highlight & style handling – always apply to the
                // resolved original layer, never the invisible index one.
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
                            } catch (e) { /* ignore non-stylable */ }
                        }
                        if (src && typeof src.eachLayer === 'function') {
                            src.eachLayer(function (l) {
                                if (typeof l.resetStyle === 'function') {
                                    try { l.resetStyle(); } catch (e) {}
                                }
                                // For Circle/Polygon layers inside
                                // FeatureGroups, try plain setStyle({}) if
                                // the layer carries feature.properties.style.
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
                    var orig = e.__resolvedOriginal
                               || (entry ? resolveOriginalLayer(entry) : null)
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

        # Placeholder – filled in during render() once all layers have
        # stable JS variable names assigned by branca.
        self.search_index: list = []

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
        raw_entries: list[SearchEntry] = []
        root_map = getattr(self, "_parent", None)
        for idx, cfg in enumerate(self.layer_configs):
            raw_entries.extend(_serialize_layer(cfg, idx, root_map))

        entries = _dedupe_entries(raw_entries)
        # Per-layer label template has to travel alongside each entry so
        # the client's buildTip() can honour per-config overrides.  We
        # inject it via the style-free source_label + layerTpl on the JS
        # side: attach a small dict of extras.
        per_config_tpl: dict[str, Optional[str]] = {
            cfg.layer_var: cfg.label_template for cfg in self.layer_configs
        }
        # Stable sort: descending by weight, then original order preserved.
        entries.sort(key=lambda e: (-e.weight, e.stable_id))

        payload = []
        for e in entries:
            d = e.as_dict()
            d["layerTpl"] = per_config_tpl.get(e.layer_var)
            # Expose search_fields to JS so resolveOriginalLayer can tag
            # the original features with __searchStableId even when the
            # haystack was auto-constructed.
            for cfg in self.layer_configs:
                if cfg.layer_var == e.layer_var:
                    d["searchFields"] = cfg.search_fields or []
                    break
            payload.append(d)

        self.search_index = payload

        super().render(**kwargs)
