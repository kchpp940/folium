import base64
import os
import warnings
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
    ResourceConfig,
    ResourceMode,
    JsCode,
    camelize,
)


def leaflet_method(fn):
    @wraps(fn)
    def inner(self, *args, **kwargs):
        self.add_child(MethodCall(self, fn.__name__, *args, **kwargs))

    return inner


def _url_to_filename(url: str) -> str:
    path = urlparse(url).path
    return os.path.basename(path)


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


def _read_local_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _resolve_resource(
    name: str,
    url: str,
    config: ResourceConfig,
    resource_type: str,
) -> tuple[type, str, dict]:
    """Resolve a resource to the appropriate Link class and parameters.

    This is the single unified entry point for all resource resolution.
    It handles overrides, CDN, inline, and local modes, as well as
    fallback and error reporting.

    Parameters
    ----------
    name : str
        The resource identifier (e.g. "leaflet", "Control.Fullscreen.js").
    url : str
        The original CDN URL for the resource.
    config : ResourceConfig
        The active resource configuration (from Figure context or global).
    resource_type : str
        Either "js" or "css".
    """
    is_css = resource_type == "css"
    RemoteLinkCls = CssLink if is_css else JavascriptLink
    InlineLinkCls = InlineCssLink if is_css else InlineJavascriptLink

    override = config.get_override(name)
    if override is not None:
        try:
            return _resolve_override(override, local_path=config.local_path, inline_cls=InlineLinkCls, remote_cls=RemoteLinkCls)
        except FileNotFoundError as exc:
            warnings.warn(
                f"Resource override for '{name}' failed: {exc}. "
                f"Falling back to CDN.",
                stacklevel=4,
            )
            return RemoteLinkCls, url, {"download": False}

    if config.mode == ResourceMode.CDN:
        return RemoteLinkCls, url, {"download": False}

    if config.mode == ResourceMode.INLINE:
        return InlineLinkCls, url, {"download": True}

    if config.mode == ResourceMode.LOCAL:
        filename = _url_to_filename(url)
        search_paths = []
        if config.local_path:
            search_paths.append(os.path.join(config.local_path, filename))
        for path in search_paths:
            if os.path.exists(path):
                try:
                    content = _read_local_file(path)
                    return InlineLinkCls, "", {"content": content}
                except OSError as exc:
                    warnings.warn(
                        f"Failed to read local resource '{name}' from {path}: {exc}. "
                        f"Falling back to CDN.",
                        stacklevel=4,
                    )
                    return RemoteLinkCls, url, {"download": False}
        warnings.warn(
            f"Cannot find local resource '{name}': {filename}. "
            f"Searched in: {config.local_path or '(no local_path set)'}. "
            f"Falling back to CDN. "
            f"Use set_resource_override('{name}', 'path/to/file') to specify the exact path.",
            stacklevel=4,
        )
        return RemoteLinkCls, url, {"download": False}

    return RemoteLinkCls, url, {"download": False}


def _resolve_override(
    override: str,
    local_path: Optional[str],
    inline_cls: type,
    remote_cls: type,
) -> tuple[type, str, dict]:
    if override.startswith(("http://", "https://")):
        return remote_cls, override, {"download": False}
    if override.startswith("data:"):
        if "," in override:
            content_b64 = override.split(",", 1)[1]
            content = base64.b64decode(content_b64).decode("utf-8")
            return inline_cls, "", {"content": content}
        return remote_cls, override, {"download": False}
    search_paths = []
    if os.path.isabs(override):
        search_paths.append(override)
    else:
        if local_path:
            search_paths.append(os.path.join(local_path, override))
        search_paths.append(override)
    for path in search_paths:
        if os.path.exists(path):
            content = _read_local_file(path)
            return inline_cls, "", {"content": content}
    raise FileNotFoundError(
        f"Override path not found: {override}. Searched: {search_paths}"
    )


def _get_resource_config(element: MacroElement) -> ResourceConfig:
    """Walk up the parent tree to find a ResourceConfig attached to a Figure.

    Resolution order:
    1. Figure._folium_resource_config (set by Map at construction)
    2. Global defaults via ResourceConfig.from_global()
    """
    root = element.get_root()
    cfg = getattr(root, "_folium_resource_config", None)
    if cfg is not None:
        return cfg
    return ResourceConfig.from_global()


class JSCSSMixin(MacroElement):
    """Render links to external Javascript and CSS resources.

    The resource loading strategy is resolved at render time by reading the
    ``_folium_resource_config`` attribute from the root Figure object.  This
    ensures that the Map and **all** its child plugins share the same
    ``resource_mode`` / ``local_path`` / overrides — there is no per-instance
    ``resource_mode`` on JSCSSMixin itself.

    To set the strategy for a map, pass ``resource_mode`` to
    :class:`folium.Map` or call :func:`folium.set_resource_mode` globally.
    """

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

        config = _get_resource_config(self)

        for name, url in self.default_js:
            link_cls, resolved_url, link_kwargs = _resolve_resource(
                name, url, config, "js"
            )
            js_link = link_cls(resolved_url, **link_kwargs)
            figure.header.add_child(js_link, name=name)

        for name, url in self.default_css:
            link_cls, resolved_url, link_kwargs = _resolve_resource(
                name, url, config, "css"
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
