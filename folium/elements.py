from functools import wraps
from typing import Any, Optional, TypedDict, Union

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


class CaptionControl(MacroElement):
    """Map 级统一元数据说明控件。

    从 CaptionRegistry 获取当前可见图层的 metadata 并动态渲染内容。
    多图层叠加时会按顺序合并显示所有可见图层的元数据。

    Parameters
    ----------
    registry : CaptionRegistry
        关联的元数据注册表实例。
    position : str, default 'bottomright'
        控件位置。
    collapsible : bool, default True
        面板是否可折叠。
    collapsed : bool, default False
        面板是否默认折叠。
    """

    _template = Template("""
        {% macro header(this, kwargs) %}
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
            </style>
        {% endmacro %}

        {% macro script(this, kwargs) %}
            (function() {
                var CaptionControl = L.Control.extend({
                    options: {
                        position: 'bottomright',
                        collapsible: true,
                        collapsed: false
                    },

                    initialize: function(options) {
                        L.setOptions(this, options);
                        this._registryId = options.registryId;
                        this._visibleLayers = [];
                    },

                    onAdd: function(map) {
                        this._container = L.DomUtil.create('div', 'leaflet-control-caption');
                        this._buildContent();
                        L.DomEvent.disableClickPropagation(this._container);
                        L.DomEvent.disableScrollPropagation(this._container);
                        return this._container;
                    },

                    _renderMetadata: function(meta) {
                        var html = '';
                        if (!meta) return html;

                        if (meta.title) {
                            html += '<div class="caption-title">' + meta.title + '</div>';
                        }

                        if (meta.description) {
                            html += '<div class="caption-row caption-description">' +
                                meta.description + '</div>';
                        }

                        if (meta.unit || meta.resolution || meta.updated_time) {
                            var metaRows = [];
                            if (meta.unit) {
                                metaRows.push('<span class="caption-label">Unit:</span>' +
                                    '<span class="caption-value">' + meta.unit + '</span>');
                            }
                            if (meta.resolution) {
                                metaRows.push('<span class="caption-label">Resolution:</span>' +
                                    '<span class="caption-value">' + meta.resolution + '</span>');
                            }
                            if (meta.updated_time) {
                                metaRows.push('<span class="caption-label">Updated:</span>' +
                                    '<span class="caption-value">' + meta.updated_time + '</span>');
                            }
                            html += '<div class="caption-row">' + metaRows.join(' | ') + '</div>';
                        }

                        if (meta.source_url) {
                            var sourceText = meta.source_text || meta.source_url;
                            html += '<div class="caption-row caption-source">' +
                                '<span class="caption-label">Source:</span>' +
                                '<a href="' + meta.source_url + '" target="_blank" rel="noopener">' +
                                sourceText + '</a></div>';
                        }

                        if (meta.legend && meta.legend.length > 0) {
                            var legendHtml = '<div class="caption-legend">';
                            for (var i = 0; i < meta.legend.length; i++) {
                                var item = meta.legend[i];
                                legendHtml += '<div class="caption-legend-item">' +
                                    '<span class="caption-legend-color" style="background-color:' +
                                    item.color + '"></span>' +
                                    '<span class="caption-legend-label">' + item.label + '</span>' +
                                    '</div>';
                            }
                            legendHtml += '</div>';
                            html += legendHtml;
                        }

                        if (meta.copyright) {
                            html += '<div class="caption-copyright">' +
                                meta.copyright + '</div>';
                        }

                        return html;
                    },

                    _buildContent: function() {
                        var html = '';

                        if (this.options.collapsible) {
                            html += '<span class="caption-toggle" title="Toggle">' +
                                (this.options.collapsed ? '+' : '&minus;') + '</span>';
                        }

                        html += '<div class="caption-body">';

                        if (this._visibleLayers.length === 0) {
                            html += '<div class="caption-empty">No active layer metadata</div>';
                        } else {
                            for (var i = 0; i < this._visibleLayers.length; i++) {
                                var layerMeta = this._visibleLayers[i];
                                var sectionClass = 'caption-section';
                                if (i === this._visibleLayers.length - 1) {
                                    sectionClass += ' last';
                                }
                                html += '<div class="' + sectionClass + '">' +
                                    this._renderMetadata(layerMeta) + '</div>';
                            }
                        }

                        html += '</div>';

                        this._container.innerHTML = html;

                        if (this.options.collapsible) {
                            var toggle = this._container.querySelector('.caption-toggle');
                            var self = this;
                            L.DomEvent.on(toggle, 'click', function(e) {
                                L.DomEvent.stopPropagation(e);
                                self._toggle();
                            });
                        }

                        if (this.options.collapsed) {
                            L.DomUtil.addClass(this._container, 'caption-collapsed');
                        }
                    },

                    _toggle: function() {
                        var collapsed = L.DomUtil.hasClass(
                            this._container, 'caption-collapsed');
                        if (collapsed) {
                            L.DomUtil.removeClass(this._container, 'caption-collapsed');
                            this._container.querySelector('.caption-toggle').innerHTML = '&minus;';
                        } else {
                            L.DomUtil.addClass(this._container, 'caption-collapsed');
                            this._container.querySelector('.caption-toggle').innerHTML = '+';
                        }
                    },

                    setVisibleLayers: function(layerMetas) {
                        this._visibleLayers = layerMetas;
                        if (this._container) {
                            this._buildContent();
                        }
                        this._container.style.display =
                            (layerMetas.length > 0) ? '' : 'none';
                    }
                });

                L.control.caption = function(options) {
                    return new CaptionControl(options);
                };

                window.__captionRegistry_{{ this.registry_id }} = {
                    control: null,
                    layers: {},
                    visibleOrder: [],

                    register: function(layerId, layerVar, metadata) {
                        this.layers[layerId] = {
                            layerVar: layerVar,
                            metadata: metadata,
                            visible: false
                        };
                        var self = this;

                        if (layerVar && layerVar.on) {
                            layerVar.on('add', function() {
                                self.layers[layerId].visible = true;
                                var idx = self.visibleOrder.indexOf(layerId);
                                if (idx === -1) {
                                    self.visibleOrder.push(layerId);
                                }
                                self._update();
                            });
                            layerVar.on('remove', function() {
                                self.layers[layerId].visible = false;
                                var idx = self.visibleOrder.indexOf(layerId);
                                if (idx !== -1) {
                                    self.visibleOrder.splice(idx, 1);
                                }
                                self._update();
                            });
                        }
                    },

                    setInitialVisible: function(layerId, visible) {
                        if (this.layers[layerId]) {
                            this.layers[layerId].visible = visible;
                            if (visible) {
                                var idx = this.visibleOrder.indexOf(layerId);
                                if (idx === -1) {
                                    this.visibleOrder.push(layerId);
                                }
                            }
                        }
                    },

                    _update: function() {
                        if (!this.control) return;
                        var visibleMetas = [];
                        for (var i = 0; i < this.visibleOrder.length; i++) {
                            var layerId = this.visibleOrder[i];
                            if (this.layers[layerId] && this.layers[layerId].visible) {
                                visibleMetas.push(this.layers[layerId].metadata);
                            }
                        }
                        this.control.setVisibleLayers(visibleMetas);
                    },

                    initControl: function(control) {
                        this.control = control;
                        this._update();
                    }
                };

                var {{ this.get_name() }} = L.control.caption({
                    position: {{ this.options.position | tojson }},
                    collapsible: {{ this.options.collapsible | tojson }},
                    collapsed: {{ this.options.collapsed | tojson }},
                    registryId: {{ this.registry_id | tojson }}
                });
                {{ this.get_name() }}.addTo({{ this._parent.get_name() }});
                window.__captionRegistry_{{ this.registry_id }}.initControl({{ this.get_name() }});
            })();
        {% endmacro %}
    """)

    def __init__(
        self,
        registry_id: str,
        position: str = "bottomright",
        collapsible: bool = True,
        collapsed: bool = False,
    ):
        super().__init__()
        self._name = "CaptionControl"
        self.registry_id = registry_id
        self.options = {
            "position": position,
            "collapsible": collapsible,
            "collapsed": collapsed,
        }


class CaptionRegistry(MacroElement):
    """Map 级元数据注册表。

    统一管理所有图层的 metadata，监听图层显示/隐藏事件，
    通知 CaptionControl 动态更新显示内容。

    Parameters
    ----------
    position : str, default 'bottomright'
        说明面板位置。
    collapsible : bool, default True
        面板是否可折叠。
    collapsed : bool, default False
        面板是否默认折叠。
    """

    def __init__(
        self,
        position: str = "bottomright",
        collapsible: bool = True,
        collapsed: bool = False,
    ):
        super().__init__()
        self._name = "CaptionRegistry"
        self.registry_id = self.get_name().replace(".", "_")
        self._caption_control = CaptionControl(
            registry_id=self.registry_id,
            position=position,
            collapsible=collapsible,
            collapsed=collapsed,
        )
        self._layers: dict[str, dict] = {}
        self._initialized = False

    def render(self, **kwargs):
        if not self._initialized:
            self.add_child(self._caption_control, name="caption_control")
            self._initialized = True
        super().render(**kwargs)

    def register_layer(
        self,
        layer_id: str,
        layer_var_name: str,
        metadata: Union[LayerMetadata, dict, None],
        initially_visible: bool = True,
    ):
        """注册一个图层的 metadata。

        Parameters
        ----------
        layer_id : str
            图层唯一标识。
        layer_var_name : str
            图层对应的 JavaScript 变量名。
        metadata : LayerMetadata or dict or None
            图层元数据。
        initially_visible : bool, default True
            图层初始是否可见。
        """
        if metadata is None:
            return

        normalized = self._normalize_metadata(metadata)
        self._layers[layer_id] = {
            "layer_var_name": layer_var_name,
            "metadata": normalized,
            "visible": initially_visible,
        }

        class _RegisterScript(MacroElement):
            _template = Template("""
                {% macro script(this, kwargs) %}
                    (function() {
                        var registry = window.__captionRegistry_{{ this.registry_id }};
                        if (registry) {
                            var layerVar = {{ this.layer_var_name }};
                            registry.register(
                                {{ this.layer_id | tojson }},
                                layerVar,
                                {{ this.metadata | tojson }}
                            );
                            registry.setInitialVisible(
                                {{ this.layer_id | tojson }},
                                {{ this.initially_visible | tojson }}
                            );
                        }
                    })();
                {% endmacro %}
            """)

            def __init__(self, registry_id, layer_id, layer_var_name, metadata, initially_visible):
                super().__init__()
                self._name = "RegisterScript"
                self.registry_id = registry_id
                self.layer_id = layer_id
                self.layer_var_name = layer_var_name
                self.metadata = metadata
                self.initially_visible = initially_visible

        script_el = _RegisterScript(
            registry_id=self.registry_id,
            layer_id=layer_id,
            layer_var_name=layer_var_name,
            metadata=normalized,
            initially_visible=initially_visible,
        )
        self.add_child(script_el, name=f"reg_{layer_id}")

    def _normalize_metadata(self, meta: Union[LayerMetadata, dict]) -> dict:
        """将 metadata 转换为标准化格式。"""
        normalized: dict[str, Any] = {
            "title": meta.get("title"),
            "description": meta.get("description"),
            "unit": meta.get("unit"),
            "resolution": meta.get("resolution"),
            "source_url": meta.get("source_url"),
            "source_text": meta.get("source_text"),
            "updated_time": meta.get("updated_time"),
            "copyright": meta.get("copyright"),
            "legend": meta.get("legend"),
        }
        return {k: v for k, v in normalized.items() if v is not None}


class CaptionMixin:
    """Mixin class that adds caption/metadata support to raster layers.

    图层只需注册 metadata 到 Map 级的 CaptionRegistry，
    由统一的 CaptionControl 根据当前可见图层动态展示内容。
    """

    def _init_caption(
        self,
        caption: Optional[Union[LayerMetadata, dict]],
        show: bool = True,
    ):
        """初始化图层的 metadata 注册。

        Parameters
        ----------
        caption : LayerMetadata or dict or None
            图层元数据配置。
        show : bool, default True
            图层初始是否可见。
        """
        self._caption_meta = caption
        self._caption_show = show
        self._caption_registered = False
        self._caption_parent = None

    @property
    def _parent(self):
        return self._caption_parent

    @_parent.setter
    def _parent(self, value):
        self._caption_parent = value
        if value is not None and not self._caption_registered:
            self._register_to_registry()

    def add_to(self, parent, name=None):
        """将图层添加到父元素，并注册 metadata 到 CaptionRegistry。"""
        result = super().add_to(parent, name=name)
        return result

    def _register_to_registry(self):
        """将当前图层的 metadata 注册到 Map 的 CaptionRegistry。"""
        if self._caption_meta is None or self._caption_parent is None:
            return
        if self._caption_registered:
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
        )
        self._caption_registered = True

    def _find_map(self):
        """向上查找父链中的 Map 对象。"""
        from folium.folium import Map
        from folium.map import FeatureGroup, Layer

        current = self._caption_parent
        while current is not None:
            if isinstance(current, Map):
                return current
            if isinstance(current, (FeatureGroup, Layer)):
                current = getattr(current, "_caption_parent", None) or getattr(
                    current, "_parent", None
                )
            else:
                break
        return None

    def _get_or_create_registry(self, map_obj) -> CaptionRegistry:
        """获取或创建 Map 上的 CaptionRegistry。"""
        registry = getattr(map_obj, "_caption_registry", None)
        if registry is None:
            registry = CaptionRegistry()
            map_obj._caption_registry = registry
            registry.add_to(map_obj)
        return registry
