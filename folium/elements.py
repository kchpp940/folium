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
    """色标图例项"""
    label: str
    color: str


class LayerMetadata(TypedDict, total=False):
    """图层元数据规范结构

    所有栅格图层统一使用此结构声明元数据，避免行为漂移。
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

        _renderMetadata: function(meta) {{
            var html = '';
            if (!meta) return html;

            if (meta.title) {{
                html += '<div class="caption-title">' + meta.title + '</div>';
            }}

            if (meta.description) {{
                html += '<div class="caption-row caption-description">' +
                    meta.description + '</div>';
            }}

            if (meta.unit || meta.resolution || meta.updated_time) {{
                var metaRows = [];
                if (meta.unit) {{
                    metaRows.push('<span class="caption-label">Unit:</span>' +
                        '<span class="caption-value">' + meta.unit + '</span>');
                }}
                if (meta.resolution) {{
                    metaRows.push('<span class="caption-label">Resolution:</span>' +
                        '<span class="caption-value">' + meta.resolution + '</span>');
                }}
                if (meta.updated_time) {{
                    metaRows.push('<span class="caption-label">Updated:</span>' +
                        '<span class="caption-value">' + meta.updated_time + '</span>');
                }}
                html += '<div class="caption-row">' + metaRows.join(' | ') + '</div>';
            }}

            if (meta.source_url) {{
                var sourceText = meta.source_text || meta.source_url;
                html += '<div class="caption-row caption-source">' +
                    '<span class="caption-label">Source:</span>' +
                    '<a href="' + meta.source_url + '" target="_blank" rel="noopener">' +
                    sourceText + '</a></div>';
            }}

            if (meta.legend && meta.legend.length > 0) {{
                var legendHtml = '<div class="caption-legend">';
                for (var i = 0; i < meta.legend.length; i++) {{
                    var item = meta.legend[i];
                    legendHtml += '<div class="caption-legend-item">' +
                        '<span class="caption-legend-color" style="background-color:' +
                        item.color + '"></span>' +
                        '<span class="caption-legend-label">' + item.label + '</span>' +
                        '</div>';
                }}
                legendHtml += '</div>';
                html += legendHtml;
            }}

            if (meta.copyright) {{
                html += '<div class="caption-copyright">' +
                    meta.copyright + '</div>';
            }}

            return html;
        }},

        _buildContent: function() {{
            var html = '';

            if (this.options.collapsible) {{
                html += '<span class="caption-toggle" title="Toggle">' +
                    (this.options.collapsed ? '+' : '&minus;') + '</span>';
            }}

            html += '<div class="caption-body">';

            if (this._visibleLayers.length === 0) {{
                html += '<div class="caption-empty">No active layer metadata</div>';
            }} else {{
                for (var i = 0; i < this._visibleLayers.length; i++) {{
                    var layerMeta = this._visibleLayers[i];
                    var sectionClass = 'caption-section';
                    if (i === this._visibleLayers.length - 1) {{
                        sectionClass += ' last';
                    }}
                    html += '<div class="' + sectionClass + '">' +
                        this._renderMetadata(layerMeta) + '</div>';
                }}
            }}

            html += '</div>';

            this._container.innerHTML = html;

            if (this.options.collapsible) {{
                var toggle = this._container.querySelector('.caption-toggle');
                var self = this;
                L.DomEvent.on(toggle, 'click', function(e) {{
                    L.DomEvent.stopPropagation(e);
                    self._toggle();
                }});
            }}

            if (this.options.collapsed) {{
                L.DomUtil.addClass(this._container, 'caption-collapsed');
            }}
        }},

        _toggle: function() {{
            var collapsed = L.DomUtil.hasClass(
                this._container, 'caption-collapsed');
            if (collapsed) {{
                L.DomUtil.removeClass(this._container, 'caption-collapsed');
                this._container.querySelector('.caption-toggle').innerHTML = '&minus;';
            }} else {{
                L.DomUtil.addClass(this._container, 'caption-collapsed');
                this._container.querySelector('.caption-toggle').innerHTML = '+';
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
    """Map 级元数据注册表（纯 Python 管理器，不参与渲染树）。

    统一管理所有图层的 metadata，向 Figure 的 header/script
    直接注入 CSS/JS，不依赖 Map 的 render 遍历时序。
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
    """Mixin class that adds caption/metadata support to raster layers.

    图层只需注册 metadata 到 Map 级的 CaptionRegistry，
    由统一的 CaptionControl 根据当前可见图层动态展示内容。

    注册时机通过两条显式路径保证：
    - ``add_to()`` : 调用 ``super().add_to()`` 后，_parent 已就绪，立即注册
    - ``render()`` : 兜底路径，覆盖 ``add_child()`` 等未经过 ``add_to`` 的场景
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
