import base64
import os
from functools import wraps
from typing import Optional
from urllib.parse import urlparse

from branca.element import (
    CssLink,
    Element,  # NoQA: F401  needed as a reexport
    Figure,
    JavascriptLink,
    MacroElement,
)
from jinja2 import Template as JinjaTemplate

from folium.template import Template
from folium.utilities import (
    ResourceMode,
    JsCode,
    camelize,
    get_local_path,
    get_resource_mode,
    get_resource_override,
)


def leaflet_method(fn):
    @wraps(fn)
    def inner(self, *args, **kwargs):
        self.add_child(MethodCall(self, fn.__name__, *args, **kwargs))

    return inner


def _url_to_filename(url: str) -> str:
    path = urlparse(url).path
    return os.path.basename(path)


def _read_file_to_base64(filepath: str) -> str:
    with open(filepath, "rb") as f:
        content = f.read()
    return base64.b64encode(content).decode("ascii")


class InlineJavascriptLink(JavascriptLink):
    """JavascriptLink that always embeds content regardless of render kwargs."""

    _template = JinjaTemplate(
        "<script>{{this._get_code_str()}}</script>"
    )

    def __init__(self, url: str = "", download: bool = True, content: Optional[str] = None):
        has_content = content is not None
        if has_content:
            download = False
        super().__init__(url=url, download=download)
        if has_content:
            self.code = content.encode("utf-8")

    def _get_code_str(self) -> str:
        code = self.get_code()
        if isinstance(code, bytes):
            return code.decode("utf-8")
        return str(code)


class InlineCssLink(CssLink):
    """CssLink that always embeds content regardless of render kwargs."""

    _template = JinjaTemplate(
        "<style>{{this._get_code_str()}}</style>"
    )

    def __init__(self, url: str = "", download: bool = True, content: Optional[str] = None):
        has_content = content is not None
        if has_content:
            download = False
        super().__init__(url=url, download=download)
        if has_content:
            self.code = content.encode("utf-8")

    def _get_code_str(self) -> str:
        code = self.get_code()
        if isinstance(code, bytes):
            return code.decode("utf-8")
        return str(code)


def _resolve_resource(
    name: str,
    url: str,
    resource_mode: str,
    resource_type: str,
    local_path: Optional[str] = None,
) -> tuple[type, str, dict]:
    """Resolve a resource to the appropriate Link class and parameters.

    Parameters
    ----------
    resource_type : str
        Either "js" or "css".
    """
    is_css = resource_type == "css"
    RemoteLinkCls = CssLink if is_css else JavascriptLink
    InlineLinkCls = InlineCssLink if is_css else InlineJavascriptLink

    override = get_resource_override(name)
    if override is not None:
        if override.startswith(("http://", "https://")):
            return RemoteLinkCls, override, {"download": False}
        if override.startswith("data:"):
            if "," in override:
                content_b64 = override.split(",", 1)[1]
                content = base64.b64decode(content_b64).decode("utf-8")
                return InlineLinkCls, "", {"content": content}
            return RemoteLinkCls, override, {"download": False}
        search_paths = []
        if os.path.isabs(override):
            search_paths.append(override)
        else:
            if local_path:
                search_paths.append(os.path.join(local_path, override))
            search_paths.append(override)
        for path in search_paths:
            if os.path.exists(path):
                content = open(path, "r", encoding="utf-8").read()
                return InlineLinkCls, "", {"content": content}
        raise FileNotFoundError(
            f"Resource override for '{name}' not found: {override}. "
            f"Searched paths: {search_paths}"
        )

    if resource_mode == ResourceMode.CDN:
        return RemoteLinkCls, url, {"download": False}

    if resource_mode == ResourceMode.INLINE:
        return InlineLinkCls, url, {"download": True}

    if resource_mode == ResourceMode.LOCAL:
        filename = _url_to_filename(url)
        search_paths = []
        if local_path:
            search_paths.append(os.path.join(local_path, filename))
        for path in search_paths:
            if os.path.exists(path):
                content = open(path, "r", encoding="utf-8").read()
                return InlineLinkCls, "", {"content": content}
        raise FileNotFoundError(
            f"Cannot find local resource '{name}': {filename}. "
            f"Searched in: {local_path or '(no local_path set)'}. "
            f"Use set_resource_override('{name}', 'path/to/file') to specify the exact path."
        )

    return RemoteLinkCls, url, {"download": False}


class JSCSSMixin(MacroElement):
    """Render links to external Javascript and CSS resources.

    Supports three resource loading modes (see :class:`ResourceMode`):
    - ``"cdn"``: Load from CDN URLs (default, backwards compatible)
    - ``"inline"``: Download resources and inline them directly into HTML
    - ``"local"``: Use locally cached resource files from ``local_path``

    The resource mode can be set globally via :func:`folium.set_resource_mode`
    or per-instance via the ``resource_mode`` parameter.
    """

    default_js: list[tuple[str, str]] = []
    default_css: list[tuple[str, str]] = []

    def __init__(
        self,
        *args,
        resource_mode: Optional[str] = None,
        local_path: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.resource_mode = resource_mode
        self.local_path = local_path

    def _get_effective_resource_mode(self) -> tuple[str, Optional[str]]:
        mode = self.resource_mode or get_resource_mode()
        local = self.local_path or get_local_path()
        return mode, local

    # Since this is typically used as a mixin, we cannot
    # override the _template member variable here. It would
    # be overwritten by any subclassing class that also has
    # a _template variable.
    def render(self, **kwargs):
        figure = self.get_root()
        assert isinstance(
            figure, Figure
        ), "You cannot render this Element if it is not in a Figure."

        resource_mode, local_path = self._get_effective_resource_mode()

        for name, url in self.default_js:
            link_cls, resolved_url, link_kwargs = _resolve_resource(
                name, url, resource_mode, "js", local_path
            )
            js_link = link_cls(resolved_url, **link_kwargs)
            figure.header.add_child(js_link, name=name)

        for name, url in self.default_css:
            link_cls, resolved_url, link_kwargs = _resolve_resource(
                name, url, resource_mode, "css", local_path
            )
            css_link = link_cls(resolved_url, **link_kwargs)
            figure.header.add_child(css_link, name=name)

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
