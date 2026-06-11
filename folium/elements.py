from functools import wraps
from typing import Optional

from branca.element import (
    CssLink,
    Element,  # NoQA: F401  needed as a reexport
    Figure,
    JavascriptLink,
    MacroElement,
)

from folium.template import Template
from folium.utilities import JsCode, camelize


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
    """A Leaflet control that displays metadata/caption for raster layers.

    Parameters
    ----------
    caption : dict
        Caption configuration with the following optional keys:
        - title: str, title of the layer
        - description: str, detailed description
        - unit: str, unit of measurement (e.g., '°C', 'm/s')
        - resolution: str, spatial resolution (e.g., '1km', '30m')
        - source_url: str, URL to the data source
        - source_text: str, display text for the source link
        - updated_time: str, last update time (e.g., '2024-01-15')
        - copyright: str, copyright information
        - legend: list of dicts with 'label' and 'color' keys,
          color legend items
        - collapsible: bool, whether the panel is collapsible (default True)
        - collapsed: bool, whether the panel is initially collapsed (default False)
        - position: str, control position (default 'bottomright')
    layer_name : str, optional
        Name of the associated layer for visibility syncing.
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
                    max-width: 280px;
                }
                .leaflet-control-caption .caption-title {
                    font-weight: bold;
                    font-size: 13px;
                    margin-bottom: 4px;
                    color: #222;
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
                .leaflet-control-caption.caption-collapsed .caption-body {
                    display: none;
                }
            </style>
        {% endmacro %}

        {% macro script(this, kwargs) %}
            (function() {
                var CaptionControl = L.Control.extend({
                    options: {
                        position: 'bottomright'
                    },

                    initialize: function(options) {
                        L.setOptions(this, options);
                    },

                    onAdd: function(map) {
                        this._container = L.DomUtil.create('div', 'leaflet-control-caption');
                        this._buildContent();
                        L.DomEvent.disableClickPropagation(this._container);
                        L.DomEvent.disableScrollPropagation(this._container);
                        return this._container;
                    },

                    _buildContent: function() {
                        var opts = this.options;
                        var html = '';

                        if (opts.collapsible) {
                            html += '<span class="caption-toggle" title="Toggle">' +
                                (opts.collapsed ? '+' : '&minus;') + '</span>';
                        }

                        if (opts.title) {
                            html += '<div class="caption-title">' + opts.title + '</div>';
                        }

                        var bodyHtml = '';

                        if (opts.description) {
                            bodyHtml += '<div class="caption-row caption-description">' +
                                opts.description + '</div>';
                        }

                        if (opts.unit || opts.resolution || opts.updated_time) {
                            var metaRows = [];
                            if (opts.unit) {
                                metaRows.push('<span class="caption-label">Unit:</span>' +
                                    '<span class="caption-value">' + opts.unit + '</span>');
                            }
                            if (opts.resolution) {
                                metaRows.push('<span class="caption-label">Resolution:</span>' +
                                    '<span class="caption-value">' + opts.resolution + '</span>');
                            }
                            if (opts.updated_time) {
                                metaRows.push('<span class="caption-label">Updated:</span>' +
                                    '<span class="caption-value">' + opts.updated_time + '</span>');
                            }
                            bodyHtml += '<div class="caption-row">' + metaRows.join(' | ') + '</div>';
                        }

                        if (opts.source_url) {
                            var sourceText = opts.source_text || opts.source_url;
                            bodyHtml += '<div class="caption-row caption-source">' +
                                '<span class="caption-label">Source:</span>' +
                                '<a href="' + opts.source_url + '" target="_blank" rel="noopener">' +
                                sourceText + '</a></div>';
                        }

                        if (opts.legend && opts.legend.length > 0) {
                            var legendHtml = '<div class="caption-legend">';
                            for (var i = 0; i < opts.legend.length; i++) {
                                var item = opts.legend[i];
                                legendHtml += '<div class="caption-legend-item">' +
                                    '<span class="caption-legend-color" style="background-color:' +
                                    item.color + '"></span>' +
                                    '<span class="caption-legend-label">' + item.label + '</span>' +
                                    '</div>';
                            }
                            legendHtml += '</div>';
                            bodyHtml += legendHtml;
                        }

                        if (opts.copyright) {
                            bodyHtml += '<div class="caption-copyright">' +
                                opts.copyright + '</div>';
                        }

                        if (bodyHtml) {
                            html += '<div class="caption-body">' + bodyHtml + '</div>';
                        }

                        this._container.innerHTML = html;

                        if (opts.collapsible) {
                            var toggle = this._container.querySelector('.caption-toggle');
                            var self = this;
                            L.DomEvent.on(toggle, 'click', function(e) {
                                L.DomEvent.stopPropagation(e);
                                self._toggle();
                            });
                        }

                        if (opts.collapsed) {
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

                    setVisibility: function(visible) {
                        if (this._container) {
                            this._container.style.display = visible ? '' : 'none';
                        }
                    }
                });

                L.control.caption = function(options) {
                    return new CaptionControl(options);
                };

                var {{ this.get_name() }} = L.control.caption(
                    {{ this.options | tojson }}
                );

                {% if this.layer_name %}
                    var layer = {{ this.layer_name }};
                    if (layer) {
                        var attachCaption = function() {
                            if (layer._map) {
                                {{ this.get_name() }}.addTo(layer._map);
                                layer.off('add', attachCaption);
                            }
                        };
                        if (layer._map) {
                            {{ this.get_name() }}.addTo(layer._map);
                        } else if (layer.on) {
                            layer.on('add', attachCaption);
                        }

                        if (layer.on) {
                            layer.on('add', function() {
                                {{ this.get_name() }}.setVisibility(true);
                            });
                            layer.on('remove', function() {
                                {{ this.get_name() }}.setVisibility(false);
                            });
                        }
                        {% if this.initial_visible is not none %}
                            if (layer._map) {
                                {{ this.get_name() }}.setVisibility({{ this.initial_visible | tojson }});
                            } else {
                                layer.on('add', function() {
                                    {{ this.get_name() }}.setVisibility({{ this.initial_visible | tojson }});
                                });
                            }
                        {% endif %}
                    }
                {% else %}
                    {{ this.get_name() }}.addTo({{ this._parent.get_name() }});
                {% endif %}
            })();
        {% endmacro %}
    """)

    def __init__(
        self,
        caption: dict,
        layer_name: Optional[str] = None,
        initial_visible: Optional[bool] = None,
    ):
        super().__init__()
        self._name = "CaptionControl"
        self.layer_name = layer_name
        self.initial_visible = initial_visible

        caption = caption or {}
        self.options = {
            "title": caption.get("title"),
            "description": caption.get("description"),
            "unit": caption.get("unit"),
            "resolution": caption.get("resolution"),
            "source_url": caption.get("source_url"),
            "source_text": caption.get("source_text"),
            "updated_time": caption.get("updated_time"),
            "copyright": caption.get("copyright"),
            "legend": caption.get("legend"),
            "collapsible": caption.get("collapsible", True),
            "collapsed": caption.get("collapsed", False),
            "position": caption.get("position", "bottomright"),
        }


class CaptionMixin:
    """Mixin class that adds caption/metadata support to raster layers.

    Add this mixin to a layer class to enable the `caption` parameter,
    which renders a metadata panel on the map.
    """

    def _init_caption(self, caption: Optional[dict], show: bool = True):
        """Initialize the caption control.

        Parameters
        ----------
        caption : dict or None
            Caption configuration dict.
        show : bool, default True
            Whether the caption is initially visible.
        """
        if caption is None:
            self._caption_control = None
            return

        self._caption_control = CaptionControl(
            caption=caption,
            layer_name=self.get_name(),
            initial_visible=show,
        )
        self.add_child(self._caption_control, name="caption_control")
