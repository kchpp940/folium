from functools import wraps
from typing import TYPE_CHECKING, Optional

from branca.element import (
    CssLink,
    Element,  # NoQA: F401  needed as a reexport
    Figure,
    JavascriptLink,
    MacroElement,
)

from folium.resources import (
    ResolvedResource,
    ResourceContext,
    ResourceEntry,
    ResourceStrategy,
    ResourceType,
)
from folium.template import Template
from folium.utilities import JsCode, camelize

if TYPE_CHECKING:
    from collections.abc import Sequence


def leaflet_method(fn):
    @wraps(fn)
    def inner(self, *args, **kwargs):
        self.add_child(MethodCall(self, fn.__name__, *args, **kwargs))

    return inner


def get_or_create_resource_context(
    figure: Figure,
    strategy: ResourceStrategy = ResourceStrategy.CDN,
) -> ResourceContext:
    """从 Figure 获取或创建 ResourceContext。

    这是连接 branca.Figure 和 folium 资源管理系统的桥梁。
    ResourceContext 附加到 Figure 的 _resource_context 属性上。
    """
    ctx = getattr(figure, "_resource_context", None)
    if ctx is None:
        ctx = ResourceContext(strategy=strategy)
        figure._resource_context = ctx
    return ctx


class InlineScript(MacroElement):
    """内联 JavaScript 脚本元素。

    用于渲染 ResolvedResource 的内联内容。
    渲染层只消费 ResolvedResource，不涉及策略决策。
    """

    _template = Template("""
        {% macro html(this, kwargs) %}
            <script>{{ this.content }}</script>
        {% endmacro %}
    """)

    def __init__(self, content: str):
        super().__init__()
        self._name = "InlineScript"
        self.content = content


class InlineStyle(MacroElement):
    """内联 CSS 样式元素。

    用于渲染 ResolvedResource 的内联内容。
    渲染层只消费 ResolvedResource，不涉及策略决策。
    """

    _template = Template("""
        {% macro html(this, kwargs) %}
            <style>{{ this.content }}</style>
        {% endmacro %}
    """)

    def __init__(self, content: str):
        super().__init__()
        self._name = "InlineStyle"
        self.content = content


class ResolvedJavascriptLink(JavascriptLink):
    """带 SRI 支持的 JavaScript 链接元素。

    从 ResolvedResource 创建，渲染层只消费已解析数据。
    """

    _template = Template("""
        {% macro html(this, kwargs) %}
            <script src="{{ this.url }}"
                {%- if this.integrity %} integrity="{{ this.integrity }}"{% endif %}
                {%- if this.crossorigin %} crossorigin="{{ this.crossorigin }}"{% endif %}>
            </script>
        {% endmacro %}
    """)

    def __init__(
        self,
        url: str,
        integrity: Optional[str] = None,
        crossorigin: Optional[str] = None,
    ):
        super().__init__(url)
        self.integrity = integrity
        self.crossorigin = crossorigin


class ResolvedCssLink(CssLink):
    """带 SRI 支持的 CSS 链接元素。

    从 ResolvedResource 创建，渲染层只消费已解析数据。
    """

    _template = Template("""
        {% macro html(this, kwargs) %}
            <link rel="stylesheet" href="{{ this.url }}"
                {%- if this.integrity %} integrity="{{ this.integrity }}"{% endif %}
                {%- if this.crossorigin %} crossorigin="{{ this.crossorigin }}"{% endif %}>
        {% endmacro %}
    """)

    def __init__(
        self,
        url: str,
        integrity: Optional[str] = None,
        crossorigin: Optional[str] = None,
    ):
        super().__init__(url)
        self.integrity = integrity
        self.crossorigin = crossorigin


def inject_resolved_resource(
    figure: Figure,
    resource: ResolvedResource,
) -> None:
    """将已解析的资源注入到 Figure 的 header 中。

    渲染层只消费 ResolvedResource，不涉及任何策略决策或网络操作。

    根据资源类型和是否内联，创建相应的元素：
    - 内联 JS: InlineScript
    - 外链 JS: ResolvedJavascriptLink (带 SRI)
    - 内联 CSS: InlineStyle
    - 外链 CSS: ResolvedCssLink (带 SRI)
    """
    if resource.resource_type == ResourceType.JAVASCRIPT:
        if resource.is_inline and resource.content is not None:
            element: Element = InlineScript(resource.content)
        elif resource.url is not None:
            element = ResolvedJavascriptLink(
                url=resource.url,
                integrity=resource.integrity,
                crossorigin=resource.crossorigin,
            )
        else:
            raise ValueError(
                f"Resolved JavaScript resource '{resource.name}' has "
                f"neither content nor URL."
            )
    else:
        if resource.is_inline and resource.content is not None:
            element = InlineStyle(resource.content)
        elif resource.url is not None:
            element = ResolvedCssLink(
                url=resource.url,
                integrity=resource.integrity,
                crossorigin=resource.crossorigin,
            )
        else:
            raise ValueError(
                f"Resolved CSS resource '{resource.name}' has "
                f"neither content nor URL."
            )

    figure.header.add_child(element, name=resource.name)


def inject_all_resolved_resources(figure: Figure) -> None:
    """解析并注入 Figure 的 ResourceContext 中的所有资源。

    这是渲染前的最后一步，确保所有资源都已解析并注入。
    应该在 Figure.render() 之前调用。
    """
    ctx = getattr(figure, "_resource_context", None)
    if ctx is None:
        return

    for resource in ctx.resolve_all():
        inject_resolved_resource(figure, resource)


class ResourceInjectingFigure(Figure):
    """扩展 branca.Figure，自动注入已解析的资源。

    这是推荐使用的 Figure 类，它在 render() 时自动：
    1. 解析 ResourceContext 中的所有资源
    2. 将 ResolvedResource 注入到 header

    向后兼容：如果不需要资源管理功能，可以继续使用 branca.Figure。
    """

    def __init__(
        self,
        *args,
        resource_strategy: ResourceStrategy = ResourceStrategy.CDN,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self._resource_context = ResourceContext(strategy=resource_strategy)

    @property
    def resource_context(self) -> ResourceContext:
        """获取资源上下文。"""
        return self._resource_context

    def _prepare_render(self, **kwargs) -> None:
        """准备渲染：收集资源声明并注入已解析资源。

        流程：
        1. 渲染所有子元素，触发 JSCSSMixin 收集资源声明
           - CDN 策略：JSCSSMixin 直接注入资源到 header（向后兼容）
           - 非 CDN 策略：JSCSSMixin 只收集到 ResourceContext，不注入
        2. 对于非 CDN 策略，解析资源并注入到 header
        """
        # 第一步：渲染所有子元素，收集资源声明
        for name, child in self._children.items():
            child.render(**kwargs)

        # 第二步：对于非 CDN 策略，解析并注入资源
        if self._resource_context.strategy != ResourceStrategy.CDN:
            self._inject_resolved_resources()

    def render(self, **kwargs) -> str:
        """渲染前先解析并注入所有资源。

        避免了两次调用 super().render() 可能导致的副作用。
        """
        self._prepare_render(**kwargs)
        return self._template.render(this=self, kwargs=kwargs)

    def _repr_html_(self, **kwargs) -> str:
        """Jupyter 显示前先解析并注入所有资源。"""
        self._prepare_render(**kwargs)
        return super()._repr_html_(**kwargs)

    def _inject_resolved_resources(self) -> None:
        """解析并注入所有资源到 header。

        对于 INLINE/LOCAL/MIRROR 策略，JSCSSMixin 只收集资源声明
        不直接注入，由此方法统一解析并注入。
        """
        for resource in self._resource_context.resolve_all():
            inject_resolved_resource(self, resource)


class JSCSSMixin(MacroElement):
    """Render links to external Javascript and CSS resources.

    使用新的 ResourceContext 架构：
    - 组件声明其依赖的资源（通过 default_js/default_css 或 add_js_link/add_css_link）
    - 渲染时将资源声明收集到 Figure 的 ResourceContext
    - 最终由 ResourceInjectingFigure 统一解析和注入

    完全向后兼容：
    - 保留 default_js/default_css 类属性
    - 保留 add_js_link/add_css_link 方法
    - 旧代码无需修改即可使用新架构
    """

    default_js: list[tuple[str, str]] = []
    default_css: list[tuple[str, str]] = []

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

    def declare_resource(self, entry: ResourceEntry) -> None:
        """声明一个资源（新 API，支持完整元数据）。

        相比于 add_js_link/add_css_link，此方法支持：
        - SHA256 完整性校验
        - Fallback URL
        - 本地文件路径
        - SRI integrity 属性
        """
        # 同步更新 default_js/default_css 以保持向后兼容
        if entry.resource_type == ResourceType.JAVASCRIPT:
            self.add_js_link(entry.name, entry.url)
        else:
            self.add_css_link(entry.name, entry.url)

        # 将完整元数据存储到实例属性
        if not hasattr(self, "_resource_entries"):
            self._resource_entries = {}
        self._resource_entries[entry.name] = entry

    def render(self, **kwargs):
        figure = self.get_root()
        assert isinstance(
            figure, Figure
        ), "You cannot render this Element if it is not in a Figure."

        ctx = get_or_create_resource_context(figure)

        # 获取资源策略，决定是否直接注入资源
        # CDN 策略：直接注入（向后兼容）
        # 非 CDN 策略：只收集到 ResourceContext，由 ResourceInjectingFigure 统一注入
        strategy = getattr(ctx, "strategy", ResourceStrategy.CDN)
        should_inject_directly = (strategy == ResourceStrategy.CDN)

        # 优先使用完整的 ResourceEntry（通过 declare_resource 声明的）
        if hasattr(self, "_resource_entries"):
            for entry in self._resource_entries.values():
                ctx.add_resource(entry)
                if should_inject_directly:
                    if entry.resource_type == ResourceType.JAVASCRIPT:
                        figure.header.add_child(
                            ResolvedJavascriptLink(
                                url=entry.url,
                                integrity=entry.integrity,
                                crossorigin=entry.crossorigin,
                            ),
                            name=entry.name,
                        )
                    else:
                        figure.header.add_child(
                            ResolvedCssLink(
                                url=entry.url,
                                integrity=entry.integrity,
                                crossorigin=entry.crossorigin,
                            ),
                            name=entry.name,
                        )

        # 同时处理 default_js/default_css，确保向后兼容
        for name, url in self.default_js:
            if hasattr(self, "_resource_entries") and name in self._resource_entries:
                continue
            ctx.add_resource(
                ResourceEntry(
                    name=name,
                    url=url,
                    resource_type=ResourceType.JAVASCRIPT,
                )
            )
            if should_inject_directly:
                figure.header.add_child(JavascriptLink(url), name=name)

        for name, url in self.default_css:
            if hasattr(self, "_resource_entries") and name in self._resource_entries:
                continue
            ctx.add_resource(
                ResourceEntry(
                    name=name,
                    url=url,
                    resource_type=ResourceType.CSS,
                )
            )
            if should_inject_directly:
                figure.header.add_child(CssLink(url), name=name)

        super().render(**kwargs)


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
