from __future__ import annotations

from typing import Any, Optional, Union

from branca.element import MacroElement

from folium import FeatureGroup, GeoJson, TopoJson
from folium.elements import JSCSSMixin

from folium.folium import Map
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

                // -------------------------------------------------------------
                // 1. Build a unified layer group that leaflet-search will index.
                // -------------------------------------------------------------
                var unifiedLayer = L.layerGroup();
                var seenIds = {};

                {% for cfg in this.layer_configs %}
                (function () {
                    var src = {{ cfg.layer_var }};
                    var children = [];

                    if (src.eachLayer && typeof src.eachLayer === 'function') {
                        src.eachLayer(function (l) { children.push(l); });
                    } else if (src.getLayers) {
                        children = src.getLayers();
                    }

                    children.forEach(function (l) {
                        var id;
                        {% if cfg.id_field %}
                            if (l.feature && l.feature.properties &&
                                l.feature.properties.hasOwnProperty('{{ cfg.id_field }}')) {
                                id = 'cfg{{ loop.index }}_' +
                                     String(l.feature.properties['{{ cfg.id_field }}']);
                            } else if (l.options &&
                                       l.options.hasOwnProperty('{{ cfg.id_field }}')) {
                                id = 'cfg{{ loop.index }}_' +
                                     String(l.options['{{ cfg.id_field }}']);
                            }
                        {% endif %}
                        if (!id) {
                            id = 'auto_' + (l._leaflet_id || L.stamp(l));
                        }

                        if (seenIds[id]) {
                            if (seenIds[id].__searchWeight < {{ cfg.weight }}) {
                                unifiedLayer.removeLayer(seenIds[id]);
                                delete seenIds[id];
                            } else {
                                return;
                            }
                        }

                        l.__searchConfig = {
                            weight: {{ cfg.weight }},
                            searchFields: {{ cfg.search_fields|tojson|safe }},
                            displayFields: {{ cfg.display_fields|tojson|safe }},
                            labelTemplate: {{ cfg.label_template|tojson|safe }},
                            id: id,
                            geomType: '{{ cfg.geom_type }}',
                            layerName: '{{ cfg.layer_var }}',
                            zoom: {% if cfg.search_zoom %} {{ cfg.search_zoom }} {% else %} null {% endif %},
                            style: {{ cfg.options|tojavascript }}
                        };
                        l.__searchWeight = {{ cfg.weight }};

                        var haystack = '';
                        var props = (l.feature && l.feature.properties)
                                    ? l.feature.properties
                                    : (l.options || {});
                        {% if cfg.search_fields %}
                            haystack = ({{ cfg.search_fields|tojson|safe }})
                                .map(function (k) { return props[k] != null ? String(props[k]) : ''; })
                                .join(' ');
                        {% endif %}
                        if (!l.feature) l.feature = {};
                        if (!l.feature.properties) l.feature.properties = {};
                        l.feature.properties.__searchHaystack = haystack;

                        unifiedLayer.addLayer(l);
                        seenIds[id] = l;
                    });
                })();
                {% endfor %}

                // -------------------------------------------------------------
                // 2. Helper – compile tiny label templates.
                //    Wrapped in {% raw %} ... {% endraw %} because the regex
                //    uses {{ and }} which clash with Jinja2's own syntax.
                // -------------------------------------------------------------
                {% raw %}
                function compileTemplate(tpl, ctx) {
                    if (!tpl) return '';
                    var re = new RegExp('__TPL_OPEN__\\s*([\\w.]+)\\s*__TPL_CLOSE__', 'g');
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

                function buildLabel(layer, globalTpl) {
                    var cfg = layer.__searchConfig || {};
                    var props = (layer.feature && layer.feature.properties)
                                ? layer.feature.properties
                                : (layer.options || {});
                    var ctx = {
                        properties: props,
                        options: layer.options || {},
                        weight: cfg.weight,
                        layerName: cfg.layerName
                    };
                    var tpl = cfg.labelTemplate || globalTpl;
                    if (tpl) return compileTemplate(tpl, ctx);
                    var fields = cfg.displayFields || [];
                    return fields.map(function (k) {
                        return props[k] != null ? String(props[k]) : '';
                    }).filter(Boolean).join(' \u00b7 ');
                }

                // -------------------------------------------------------------
                // 3. Instantiate L.Control.Search over the unified layer.
                // -------------------------------------------------------------
                var {{ this.get_name() }} = new L.Control.Search({
                    layer: unifiedLayer,
                    propertyName: '__searchHaystack',
                    collapsed: {{ this.collapsed|tojson|safe }},
                    textPlaceholder: '{{ this.placeholder }}',
                    textNotFound: '{{ this.text_not_found }}',
                    position: '{{ this.position }}',
                    sortFeatures: function (a, b) {
                        var wa = a.layer.__searchConfig
                               ? a.layer.__searchConfig.weight : 1;
                        var wb = b.layer.__searchConfig
                               ? b.layer.__searchConfig.weight : 1;
                        if (wb !== wa) return wb - wa;
                        return a.value.length - b.value.length;
                    },
                    buildTip: function (text, val) {
                        var tip = buildLabel(val.layer,
                            {{ this.label_template|tojson|safe }});
                        return L.DomUtil.create('div', 'search-tip')
                               .appendChild(document.createTextNode(
                                   tip || text)).parentNode;
                    },
                    initial: false,
                    hideMarkerOnCollapse: true,
                    marker: false,
                    moveToLocation: function (latlng, title, map) {
                        var layer = latlng.layer || latlng;
                        var cfg = layer.__searchConfig || {};
                        var geomType = cfg.geomType || 'Point';
                        var targetZoom = cfg.zoom;
                        {% if this.search_zoom %}
                            if (targetZoom == null) targetZoom = {{ this.search_zoom }};
                        {% endif %}
                        if (geomType === 'Point') {
                            if (targetZoom == null) targetZoom = map.getZoom();
                            map.flyTo(latlng.latlng || latlng, targetZoom);
                        } else if (layer.getBounds) {
                            var bounds = layer.getBounds();
                            if (targetZoom == null) {
                                targetZoom = map.getBoundsZoom(bounds);
                            }
                            map.flyToBounds(bounds, { maxZoom: targetZoom });
                        } else {
                            map.flyTo(latlng.latlng || latlng, targetZoom || map.getZoom());
                        }
                    }
                });

                // -------------------------------------------------------------
                // 4. Apply highlight styling on match.
                // -------------------------------------------------------------
                function mergedStyle(layer) {
                    var cfg = layer.__searchConfig || {};
                    var globalOpts = {{ this.options|tojavascript }};
                    var perLayer = cfg.style || {};
                    return L.extend({}, globalOpts, perLayer);
                }

                function resetAllLayerStyles() {
                    {% for cfg in this.layer_configs %}
                    (function () {
                        var src = {{ cfg.layer_var }};
                        if (src.setStyle && typeof src.setStyle === 'function') {
                            try {
                                src.setStyle(function (feature) {
                                    return feature && feature.properties
                                           ? feature.properties.style
                                           : {};
                                });
                            } catch (e) { /* ignore */ }
                        }
                        if (src.eachLayer) {
                            src.eachLayer(function (l) {
                                if (l.resetStyle) {
                                    try { l.resetStyle(); } catch (e) {}
                                }
                            });
                        }
                    })();
                    {% endfor %}
                }

                {{ this.get_name() }}.on('search:locationfound', function (e) {
                    resetAllLayerStyles();
                    if (e.layer && e.layer.setStyle) {
                        var s = mergedStyle(e.layer);
                        if (Object.keys(s).length) e.layer.setStyle(s);
                    }
                    if (e.layer && e.layer._popup) e.layer.openPopup();
                    if (e.layer && e.layer.bindTooltip && !e.layer._tooltip) {
                        var label = buildLabel(e.layer,
                            {{ this.label_template|tojson|safe }});
                        if (label) e.layer.bindTooltip(label).openTooltip();
                    }
                });

                {{ this.get_name() }}.on('search:collapsed', resetAllLayerStyles);

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

        super().render(**kwargs)
