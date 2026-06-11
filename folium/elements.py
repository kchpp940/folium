from functools import wraps
from typing import Any, Optional, TypedDict, Union
import json

from branca.element import (
    CssLink,
    Element,  # NoQA: F401  needed as a reexport
    Figure,
    JavascriptLink,
    MacroElement,
)

from folium.template import Template
from folium.utilities import JsCode, camelize


class LegendItem(TypedDict, total=False):
    """
    A single item in a legend color bar.

    Use this to define legend entries for raster layer captions.
    Each item is rendered as a color swatch followed by its label.

    Parameters
    ----------
    label : str
        The text label describing this legend entry.
    color : str
        CSS color value for the swatch, e.g. ``"#ff0000"``, ``"red"``,
        ``"rgba(255,0,0,0.5)"``.

    Examples
    --------
    >>> LegendItem(label="High", color="#ff0000")
    {'label': 'High', 'color': '#ff0000'}
    """

    label: str
    color: str


class LayerMetadata(TypedDict, total=False):
    """
    Typed structure for raster layer metadata and legend captions.

    All caption-enabled raster layers (``ImageOverlay``, ``VideoOverlay``,
    ``TileLayer``, ``FloatImage``) accept this structure through their
    ``caption`` parameter.  Pass either a plain ``dict`` with matching keys
    or a ``LayerMetadata`` instance.

    The Map maintains a single unified CaptionRegistry control: when
    multiple layers are visible at once their metadata sections are
    merged in order, and LayerControl toggles are automatically wired to
    show/hide the corresponding section.

    Parameters
    ----------
    title : str, optional
        Short title shown in bold at the top of the section.
    description : str, optional
        One-paragraph description of the dataset.
    unit : str, optional
        Unit of measurement, e.g. ``"°C"``, ``"m/s"``, ``"kg/m³"``.
    resolution : str, optional
        Spatial or temporal resolution, e.g. ``"1km"``, ``"30m"``,
        ``"daily"``.
    source_url : str, optional
        URL linking to the original data source.
    source_text : str, optional
        Human-readable label for ``source_url``; if omitted the URL
        itself is displayed.
    updated_time : str, optional
        Free-form last-updated string, e.g. ``"2024-01-15"``.
    copyright : str, optional
        Copyright / attribution line rendered in small italic type.
    legend : list of :class:`LegendItem`, optional
        Color-bar legend.  Each entry must have at least the keys
        ``"label"`` and ``"color"``.
    position : str, default ``"bottomright"``
        Leaflet control position.  One of ``"topleft"``, ``"topright"``,
        ``"bottomleft"``, ``"bottomright"``.  Only the first registered
        layer's position is used (Map-level singleton).
    collapsible : bool, default ``True``
        Whether the panel can be collapsed with a toggle button.
        Only the first registered layer's value is used.
    collapsed : bool, default ``False``
        Whether the panel starts collapsed.
        Only the first registered layer's value is used.

    See Also
    --------
    folium.raster_layers.ImageOverlay
    folium.raster_layers.VideoOverlay
    folium.raster_layers.TileLayer
    folium.plugins.FloatImage
    normalize_layer_metadata : validation and defaults applied internally
    """

    title: str
    description: str
    unit: str
    resolution: str
    source_url: str
    source_text: str
    updated_time: str
    copyright: str
    legend: list[LegendItem]
    collapsible: bool
    collapsed: bool
    position: str


_VALID_POSITIONS = frozenset({
    "topleft", "topright", "bottomleft", "bottomright",
})


def normalize_layer_metadata(meta: Union[LayerMetadata, dict, None]) -> Optional[dict]:
    """将任意 metadata 输入规范化为统一格式。

    - 过滤 None 值
    - 校验 legend 项结构
    - 规范化 position 到 Leaflet 合法值
    - 填充 collapsible / collapsed / position 默认值

    Parameters
    ----------
    meta : LayerMetadata or dict or None
        原始元数据。

    Returns
    -------
    dict or None
        规范化后的元数据；输入为 None 时返回 None。
    """
    if meta is None:
        return None

    result: dict[str, Any] = {}

    for key in (
        "title", "description", "unit", "resolution",
        "source_url", "source_text", "updated_time", "copyright",
    ):
        value = meta.get(key)
        if value is not None:
            result[key] = value

    legend = meta.get("legend")
    if legend is not None:
        if not isinstance(legend, list):
            raise TypeError(
                f"caption['legend'] must be a list, got {type(legend).__name__}"
            )
        validated = []
        for i, item in enumerate(legend):
            if not isinstance(item, dict) or "label" not in item or "color" not in item:
                raise ValueError(
                    f"caption['legend'][{i}] must contain 'label' and 'color' keys, "
                    f"got {item!r}"
                )
            validated.append({"label": item["label"], "color": item["color"]})
        if validated:
            result["legend"] = validated

    position = meta.get("position", "bottomright")
    if position not in _VALID_POSITIONS:
        raise ValueError(
            f"caption['position'] must be one of {sorted(_VALID_POSITIONS)}, "
            f"got {position!r}"
        )
    result["position"] = position

    result["collapsible"] = bool(meta.get("collapsible", True))
    result["collapsed"] = bool(meta.get("collapsed", False))

    return result


def leaflet_method(fn):
    @wraps(fn)
    def inner(self, *args, **kwargs):
        self.add_child(MethodCall(self, fn.__name__, *args, **kwargs))

    return inner


class JSCSSMixin(MacroElement):
    """Render links to external Javascript and CSS resources."""

    default_js: list[tuple[str, str]] = []
    default_css: list[tuple[str, str]] = []

    # Since this is typically used as a mixin, we cannot
    # override the _template member variable here. It would
    # be overwritten by any subclassing class that also has
    # a _template variable.
    def render(self, **kwargs):
        figure = self.get_root()
        assert isinstance(
            figure, Figure
        ), "You cannot render this Element if it is not in a Figure."

        for name, url in self.default_js:
            figure.header.add_child(JavascriptLink(url), name=name)

        for name, url in self.default_css:
            figure.header.add_child(CssLink(url), name=name)

        super().render(**kwargs)

    def add_css_link(self, name: str, url: str):
        """Add or update css resource link."""
        self._add_link(name, url, self.default_css)

    def add_js_link(self, name: str, url: str):
        """Add or update JS resource link."""
        self._add_link(name, url, self.default_js)

    def _add_link(self, name: str, url: str, default_list: list[tuple[str, str]]):
        """Modify a css or js link.

        If `name` does not exist, the link will be appended
        """

        for i, pair in enumerate(default_list):
            if pair[0] == name:
                default_list[i] = (name, url)
                break
        else:
            default_list.append((name, url))


class EventHandler(MacroElement):
    '''
    Add javascript event handlers.

    Examples
    --------
    >>> import folium
    >>> from folium.utilities import JsCode
    >>>
    >>> m = folium.Map()
    >>>
    >>> geo_json_data = {
    ...     "type": "FeatureCollection",
    ...     "features": [
    ...         {
    ...             "type": "Feature",
    ...             "geometry": {
    ...                 "type": "Polygon",
    ...                 "coordinates": [
    ...                     [
    ...                         [100.0, 0.0],
    ...                         [101.0, 0.0],
    ...                         [101.0, 1.0],
    ...                         [100.0, 1.0],
    ...                         [100.0, 0.0],
    ...                     ]
    ...                 ],
    ...             },
    ...             "properties": {"prop1": {"title": "Somewhere on Sumatra"}},
    ...         }
    ...     ],
    ... }
    >>>
    >>> g = folium.GeoJson(geo_json_data).add_to(m)
    >>>
    >>> highlight = JsCode("""
    ...    function highlight(e) {
    ...        e.target.original_color = e.layer.options.color;
    ...        e.target.setStyle({ color: "green" });
    ...    }
    ... """)
    >>>
    >>> reset = JsCode("""
    ...    function reset(e) {
    ...       e.target.setStyle({ color: e.target.original_color });
    ...    }
    ... """)
    >>>
    >>> g.add_child(EventHandler("mouseover", highlight))
    >>> g.add_child(EventHandler("mouseout", reset))
    '''

    _template = Template("""
        {% macro script(this, kwargs) %}
            {{ this._parent.get_name()}}.{{ this.method }}(
                {{ this.event|tojson}},
                {{ this.handler.js_code }}
            );
        {% endmacro %}
        """)

    def __init__(self, event: str, handler: JsCode, once: bool = False):
        super().__init__()
        self._name = "EventHandler"
        self.event = event
        self.handler = handler
        self.method = "once" if once else "on"


class ElementAddToElement(MacroElement):
    """Abstract class to add an element to another element."""

    _template = Template("""
        {% macro script(this, kwargs) %}
            {{ this.element_name }}.addTo({{ this.element_parent_name }});
        {% endmacro %}
    """)

    def __init__(self, element_name: str, element_parent_name: str):
        super().__init__()
        self.element_name = element_name
        self.element_parent_name = element_parent_name


class IncludeStatement(MacroElement):
    """Generate an include statement on a class."""

    _template = Template("""
        {{ this.leaflet_class_name }}.include(
            {{ this.options | tojavascript }}
        )
    """)

    def __init__(self, leaflet_class_name: str, **kwargs):
        super().__init__()
        self.leaflet_class_name = leaflet_class_name
        self.options = kwargs

    def render(self, *args, **kwargs):
        return super().render(*args, **kwargs)


class MethodCall(MacroElement):
    """Abstract class to add an element to another element."""

    _template = Template("""
        {% macro script(this, kwargs) %}
            {{ this.target }}.{{ this.method }}(
                {% for arg in this.args %}
                    {{ arg | tojavascript }},
                {% endfor %}
                {{ this.kwargs | tojavascript }}
            );
        {% endmacro %}
    """)

    def __init__(self, target: MacroElement, method: str, *args, **kwargs):
        super().__init__()
        self.target = target.get_name()
        self.method = camelize(method)
        self.args = args
        self.kwargs = kwargs


_CAPTION_CSS = """\
<style>
    .leaflet-control-caption {
        background: rgba(255, 255, 255, 0.95);
        border-radius: 4px;
        box-shadow: 0 1px 5px rgba(0, 0, 0, 0.3);
        padding: 8px 12px;
        font-size: 12px;
        line-height: 1.5;
        color: #333;
        max-width: 300px;
    }
    .leaflet-control-caption .caption-section {
        padding-bottom: 8px;
        margin-bottom: 8px;
        border-bottom: 1px solid #eee;
    }
    .leaflet-control-caption .caption-section:last-child {
        padding-bottom: 0;
        margin-bottom: 0;
        border-bottom: none;
    }
    .leaflet-control-caption .caption-title {
        font-weight: bold;
        font-size: 13px;
        margin-bottom: 4px;
        color: #222;
    }
    .leaflet-control-caption .caption-header {
        margin-bottom: 4px;
    }
    .leaflet-control-caption .caption-toggle {
        float: right;
        cursor: pointer;
        font-weight: bold;
        color: #666;
        margin-left: 8px;
        user-select: none;
    }
    .leaflet-control-caption .caption-body {
        margin-top: 4px;
    }
    .leaflet-control-caption .caption-row {
        margin: 2px 0;
    }
    .leaflet-control-caption .caption-label {
        color: #666;
        margin-right: 4px;
    }
    .leaflet-control-caption .caption-source a {
        color: #0078a8;
        text-decoration: none;
    }
    .leaflet-control-caption .caption-source a:hover {
        text-decoration: underline;
    }
    .leaflet-control-caption .caption-legend {
        margin-top: 6px;
    }
    .leaflet-control-caption .caption-legend-item {
        display: flex;
        align-items: center;
        margin: 2px 0;
    }
    .leaflet-control-caption .caption-legend-color {
        display: inline-block;
        width: 20px;
        height: 14px;
        margin-right: 6px;
        border: 1px solid #ccc;
        border-radius: 2px;
    }
    .leaflet-control-caption .caption-copyright {
        margin-top: 6px;
        color: #888;
        font-size: 11px;
        font-style: italic;
    }
    .leaflet-control-caption.caption-collapsed .caption-body,
    .leaflet-control-caption.caption-collapsed .caption-section {
        display: none;
    }
    .leaflet-control-caption .caption-empty {
        color: #999;
        font-style: italic;
    }
</style>"""

_CAPTION_JS_TEMPLATE = """\
(function() {{
    var CaptionControl = L.Control.extend({{
        options: {{
            position: {position_js},
            collapsible: {collapsible_js},
            collapsed: {collapsed_js}
        }},

        initialize: function(options) {{
            L.setOptions(this, options);
            this._registryId = options.registryId;
            this._visibleLayers = [];
        }},

        onAdd: function(map) {{
            this._container = L.DomUtil.create('div', 'leaflet-control-caption');
            this._buildContent();
            L.DomEvent.disableClickPropagation(this._container);
            L.DomEvent.disableScrollPropagation(this._container);
            return this._container;
        }},

        _safeUrl: function(url) {{
            if (!url || typeof url !== 'string') return null;
            try {{
                var parsed = new URL(url, window.location.href);
                var allowed = ['http:', 'https:', 'ftp:', 'ftps:', 'mailto:'];
                if (allowed.indexOf(parsed.protocol) === -1) return null;
                return parsed.href;
            }} catch (e) {{
                return null;
            }}
        }},

        _safeColor: function(color) {{
            if (!color || typeof color !== 'string') return null;
            if (color.length > 200) return null;
            if (/[\\x00-\\x1f<>]/.test(color)) return null;
            var test = document.createElement('div');
            test.style.backgroundColor = '';
            test.style.backgroundColor = color;
            if (test.style.backgroundColor === '') return null;
            return test.style.backgroundColor;
        }},

        _appendText: function(parent, className, text) {{
            if (!text) return;
            var el = document.createElement('div');
            if (className) el.className = className;
            el.textContent = text;
            parent.appendChild(el);
        }},

        _appendRow: function(parent, label, value, rowClass) {{
            if (!value) return;
            var row = document.createElement('div');
            row.className = rowClass || 'caption-row';
            if (label) {{
                var labelSpan = document.createElement('span');
                labelSpan.className = 'caption-label';
                labelSpan.textContent = label;
                row.appendChild(labelSpan);
            }}
            var valueSpan = document.createElement('span');
            valueSpan.className = 'caption-value';
            valueSpan.textContent = value;
            row.appendChild(valueSpan);
            parent.appendChild(row);
        }},

        _renderMetadata: function(meta, container) {{
            if (!meta) return;

            this._appendText(container, 'caption-title', meta.title);
            this._appendText(container, 'caption-row caption-description', meta.description);

            var hasMetaRow = meta.unit || meta.resolution || meta.updated_time;
            if (hasMetaRow) {{
                var metaRow = document.createElement('div');
                metaRow.className = 'caption-row';
                var parts = [];
                if (meta.unit) parts.push('Unit: ' + meta.unit);
                if (meta.resolution) parts.push('Resolution: ' + meta.resolution);
                if (meta.updated_time) parts.push('Updated: ' + meta.updated_time);
                metaRow.textContent = parts.join(' | ');
                container.appendChild(metaRow);
            }}

            var safeUrl = this._safeUrl(meta.source_url);
            if (safeUrl) {{
                var sourceRow = document.createElement('div');
                sourceRow.className = 'caption-row caption-source';
                var label = document.createElement('span');
                label.className = 'caption-label';
                label.textContent = 'Source:';
                sourceRow.appendChild(label);
                var link = document.createElement('a');
                link.href = safeUrl;
                link.target = '_blank';
                link.rel = 'noopener noreferrer';
                link.textContent = meta.source_text || meta.source_url;
                sourceRow.appendChild(link);
                container.appendChild(sourceRow);
            }}

            if (meta.legend && meta.legend.length > 0) {{
                var legendEl = document.createElement('div');
                legendEl.className = 'caption-legend';
                for (var i = 0; i < meta.legend.length; i++) {{
                    var item = meta.legend[i];
                    if (!item) continue;
                    var itemEl = document.createElement('div');
                    itemEl.className = 'caption-legend-item';
                    var colorEl = document.createElement('span');
                    colorEl.className = 'caption-legend-color';
                    var safeColor = this._safeColor(item.color);
                    if (safeColor) {{
                        colorEl.style.backgroundColor = safeColor;
                    }} else {{
                        colorEl.style.backgroundColor = '#cccccc';
                    }}
                    itemEl.appendChild(colorEl);
                    var labelEl = document.createElement('span');
                    labelEl.className = 'caption-legend-label';
                    labelEl.textContent = item.label || '';
                    itemEl.appendChild(labelEl);
                    legendEl.appendChild(itemEl);
                }}
                container.appendChild(legendEl);
            }}

            this._appendText(container, 'caption-copyright', meta.copyright);
        }},

        _buildContent: function() {{
            var container = this._container;
            while (container.firstChild) {{
                container.removeChild(container.firstChild);
            }}

            if (this.options.collapsible) {{
                var toggle = document.createElement('span');
                toggle.className = 'caption-toggle';
                toggle.title = 'Toggle';
                toggle.textContent = this.options.collapsed ? '+' : '−';
                container.appendChild(toggle);
                var self = this;
                L.DomEvent.on(toggle, 'click', function(e) {{
                    L.DomEvent.stopPropagation(e);
                    self._toggle();
                }});
            }}

            var body = document.createElement('div');
            body.className = 'caption-body';

            if (this._visibleLayers.length === 0) {{
                var empty = document.createElement('div');
                empty.className = 'caption-empty';
                empty.textContent = 'No active layer metadata';
                body.appendChild(empty);
            }} else {{
                for (var i = 0; i < this._visibleLayers.length; i++) {{
                    var layerMeta = this._visibleLayers[i];
                    var section = document.createElement('div');
                    section.className = 'caption-section';
                    if (i === this._visibleLayers.length - 1) {{
                        section.className += ' last';
                    }}
                    this._renderMetadata(layerMeta, section);
                    body.appendChild(section);
                }}
            }}

            container.appendChild(body);

            if (this.options.collapsed) {{
                L.DomUtil.addClass(container, 'caption-collapsed');
            }}
        }},

        _toggle: function() {{
            var collapsed = L.DomUtil.hasClass(
                this._container, 'caption-collapsed');
            var toggle = this._container.querySelector('.caption-toggle');
            if (collapsed) {{
                L.DomUtil.removeClass(this._container, 'caption-collapsed');
                if (toggle) toggle.textContent = '−';
            }} else {{
                L.DomUtil.addClass(this._container, 'caption-collapsed');
                if (toggle) toggle.textContent = '+';
            }}
        }},

        setVisibleLayers: function(layerMetas) {{
            this._visibleLayers = layerMetas;
            if (this._container) {{
                this._buildContent();
            }}
            this._container.style.display =
                (layerMetas.length > 0) ? '' : 'none';
        }}
    }});

    L.control.caption = function(options) {{
        return new CaptionControl(options);
    }};

    window.__captionRegistry_{registry_id} = {{
        control: null,
        layers: {{}},
        visibleOrder: [],

        register: function(layerId, layerVar, metadata) {{
            this.layers[layerId] = {{
                layerVar: layerVar,
                metadata: metadata,
                visible: false
            }};
            var self = this;

            if (layerVar && layerVar.on) {{
                layerVar.on('add', function() {{
                    self.layers[layerId].visible = true;
                    var idx = self.visibleOrder.indexOf(layerId);
                    if (idx === -1) {{
                        self.visibleOrder.push(layerId);
                    }}
                    self._update();
                }});
                layerVar.on('remove', function() {{
                    self.layers[layerId].visible = false;
                    var idx = self.visibleOrder.indexOf(layerId);
                    if (idx !== -1) {{
                        self.visibleOrder.splice(idx, 1);
                    }}
                    self._update();
                }});
            }}
        }},

        setInitialVisible: function(layerId, visible) {{
            if (this.layers[layerId]) {{
                this.layers[layerId].visible = visible;
                if (visible) {{
                    var idx = this.visibleOrder.indexOf(layerId);
                    if (idx === -1) {{
                        this.visibleOrder.push(layerId);
                    }}
                }}
            }}
        }},

        _update: function() {{
            if (!this.control) return;
            var visibleMetas = [];
            for (var i = 0; i < this.visibleOrder.length; i++) {{
                var layerId = this.visibleOrder[i];
                if (this.layers[layerId] && this.layers[layerId].visible) {{
                    visibleMetas.push(this.layers[layerId].metadata);
                }}
            }}
            this.control.setVisibleLayers(visibleMetas);
        }},

        initControl: function(control) {{
            this.control = control;
            this._update();
        }}
    }};

    var {ctrl_var} = L.control.caption({{
        position: {position_js},
        collapsible: {collapsible_js},
        collapsed: {collapsed_js},
        registryId: {registry_id_js}
    }});
    {ctrl_var}.addTo({map_var});
    window.__captionRegistry_{registry_id}.initControl({ctrl_var});
}})();
"""


class CaptionRegistry:
    """
    Internal implementation — Map-level metadata registry.

    .. warning::
        This is a private implementation detail and **not part of the
        public API**.  Users should only interact with captions via the
        ``caption`` parameter on raster layer classes (see
        :class:`LayerMetadata`).  The class name, constructor signature
        and all attributes may change at any time without notice.

    This is a pure-Python manager (not part of the branca render tree)
    that collects metadata from every caption-enabled layer on a Map
    and injects a single unified Leaflet control into the document's
    ``<head>`` / ``<script>`` sections.  By writing to the Figure's
    ``header`` and ``script`` Elements directly (rather than as
    children of the Map) it avoids timing issues that would otherwise
    cause ``add_child()`` registrations to be missed during render.
    """

    def __init__(
        self,
        position: str = "bottomright",
        collapsible: bool = True,
        collapsed: bool = False,
    ):
        self._position = position
        self._collapsible = collapsible
        self._collapsed = collapsed
        self._layers: dict[str, dict] = {}
        self._control_added = False
        self._map_obj = None
        self._registry_id = None
        self._ctrl_var = None

    def _ensure_control(self, map_obj):
        if self._control_added:
            return
        self._map_obj = map_obj
        self._registry_id = id(self)
        self._ctrl_var = f"caption_control_{self._registry_id}"

        figure = map_obj.get_root()
        figure.header.add_child(
            Element(_CAPTION_CSS), name="caption_styles",
        )

        control_js = _CAPTION_JS_TEMPLATE.format(
            registry_id=self._registry_id,
            registry_id_js=json.dumps(self._registry_id),
            ctrl_var=self._ctrl_var,
            map_var=map_obj.get_name(),
            position_js=json.dumps(self._position),
            collapsible_js=json.dumps(self._collapsible),
            collapsed_js=json.dumps(self._collapsed),
        )
        figure.script.add_child(
            Element(control_js), name="caption_control",
        )

        self._control_added = True

    def register_layer(
        self,
        layer_id: str,
        layer_var_name: str,
        metadata: Union[LayerMetadata, dict, None],
        initially_visible: bool = True,
        map_obj=None,
    ):
        if metadata is None:
            return

        normalized = normalize_layer_metadata(metadata)
        if normalized is None:
            return

        if map_obj is not None:
            self._ensure_control(map_obj)

        self._layers[layer_id] = {
            "layer_var_name": layer_var_name,
            "metadata": normalized,
            "visible": initially_visible,
        }

        if not self._control_added:
            return

        register_js = (
            f"(function() {{"
            f"var registry = window.__captionRegistry_{self._registry_id};"
            f"if (registry) {{"
            f"var layerVar = {layer_var_name};"
            f"registry.register({json.dumps(layer_id)}, layerVar, {json.dumps(normalized)});"
            f"registry.setInitialVisible({json.dumps(layer_id)}, {json.dumps(initially_visible)});"
            f"}}"
            f"}})();"
        )
        self._map_obj.get_root().script.add_child(
            Element(register_js), name=f"caption_reg_{layer_id}",
        )


class CaptionMixin:
    """
    Internal implementation — Mixin that wires up the Map-level
    CaptionRegistry for raster layer classes.

    .. warning::
        This is a private implementation detail and **not part of the
        public API**.  Users should never subclass or directly
        instantiate this mixin; they pass :class:`LayerMetadata`-style
        dicts through each layer's ``caption`` argument instead.

    A layer opts in simply by::

        class MyLayer(CaptionMixin, Layer):
            def __init__(self, caption=None, show=True, ...):
                ...
                self._init_caption(caption, show=show)

    Registration is triggered through two explicit, safe paths:

    * ``add_to(parent)`` — immediately after the layer's ``_parent``
      pointer is populated by ``super().add_to()``.
    * ``render()`` — a fallback path so users who call
      ``map.add_child(layer)`` instead of ``layer.add_to(map)`` still
      get their caption registered in time.

    Both paths eventually funnel through :meth:`_try_register`, which
    walks the parent chain to find the :class:`folium.Map`, lazily
    creates the :class:`CaptionRegistry` on it, and hands over the
    normalized metadata.
    """

    def _init_caption(
        self,
        caption: Optional[Union[LayerMetadata, dict]],
        show: bool = True,
    ):
        self._caption_meta = caption
        self._caption_show = show
        self._caption_registered = False

    def add_to(self, parent, name=None):
        result = super().add_to(parent, name=name)
        self._try_register()
        return result

    def render(self, **kwargs):
        self._try_register()
        super().render(**kwargs)

    def _try_register(self):
        if self._caption_meta is None or self._caption_registered:
            return
        if not hasattr(self, "_parent") or self._parent is None:
            return

        map_obj = self._find_map()
        if map_obj is None:
            return

        registry = self._get_or_create_registry(map_obj)
        registry.register_layer(
            layer_id=self.get_name(),
            layer_var_name=self.get_name(),
            metadata=self._caption_meta,
            initially_visible=self._caption_show,
            map_obj=map_obj,
        )
        self._caption_registered = True

    def _find_map(self):
        from folium.folium import Map
        from folium.map import FeatureGroup, Layer

        current = self._parent
        while current is not None:
            if isinstance(current, Map):
                return current
            if isinstance(current, (FeatureGroup, Layer)):
                current = getattr(current, "_parent", None)
            else:
                current = None
        return None

    def _get_or_create_registry(self, map_obj) -> CaptionRegistry:
        registry = getattr(map_obj, "_caption_registry", None)
        if registry is None:
            registry = CaptionRegistry()
            map_obj._caption_registry = registry
        return registry
