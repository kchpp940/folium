from functools import wraps

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
    Add a JavaScript event handler to a layer.

    .. note::
        As of Folium 0.18+, ``add_child(EventHandler(...))`` on layers that
        support the :class:`folium.utilities.EventMixin` (Circle, Polygon,
        Marker, GeoJson, etc.) is automatically absorbed into the unified
        event system.  This means the EventHandler is no longer rendered as
        a standalone MacroElement child; instead its event and handler are
        merged into the layer's internal ``_event_handlers`` dictionary and
        rendered through the same path as the ``events`` / ``feature_events``
        / ``layer_events`` constructor parameters.

        If the same event name was already set via a constructor parameter,
        the ``add_child(EventHandler(...))`` call is ignored and a
        ``UserWarning`` is emitted to avoid duplicate bindings.

    For layers that do **not** use EventMixin (e.g. ``Map`` itself),
    ``EventHandler`` still behaves as a classic MacroElement that renders
    ``{parent_name}.on(event, handler)`` / ``{parent_name}.once(event, handler)``.

    Parameters
    ----------
    event : str
        Name of the Leaflet event to bind (e.g. ``"click"``, ``"mouseover"``).
    handler : JsCode
        The JavaScript event handler.  Must be a :class:`folium.JsCode`
        wrapping a ``function(e) { ... }`` body.
    once : bool, default False
        If True, use ``.once()`` so the handler fires only the first time
        the event occurs.  Otherwise use ``.on()`` (fires every time).

    See Also
    --------
    :func:`folium.utilities.EventMixin.set_event`
        Programmatic alternative for adding a single event.

    Examples
    --------
    >>> import folium
    >>> from folium.utilities import JsCode
    >>>
    >>> # Simple layer: EventHandler is absorbed into the layer's event dict.
    >>> c = folium.Circle(location=[0, 0], radius=100)
    >>> c.add_child(folium.EventHandler(
    ...     "click",
    ...     JsCode("function(e) { console.log('clicked', e.latlng); }"),
    ... ))

    >>> # GeoJson: absorbed into the layer-level event handlers
    >>> # (bound to the whole GeoJson layer, not to individual features).
    >>> g = folium.GeoJson({"type": "Point", "coordinates": [0, 0]})
    >>> g.add_child(folium.EventHandler(
    ...     "layeradd",
    ...     JsCode("function(e) { console.log('layer added'); }"),
    ... ))
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
