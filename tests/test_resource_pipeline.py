"""全路径断言测试：验证所有资源入口都走同一条 ResolvedResource 数据流。"""

import hashlib
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

import folium
from folium.elements import (
    InlineScript,
    InlineStyle,
    ResolvedCssLink,
    ResolvedJavascriptLink,
    ResourceInjectingFigure,
    get_or_create_resource_context,
)
from folium.resources import (
    ResourceContext,
    ResourceEntry,
    ResourceResolver,
    ResourceResolverConfig,
    ResourceStrategy,
    ResourceType,
    ResolvedResource,
)


class TestUnifiedPipelineCDN:
    """CDN 策略：所有资源统一走 ResourceEntry → Resolver → ResolvedResource → 注入。"""

    def test_no_old_javascript_link_in_header(self):
        m = folium.Map(location=[0, 0])
        root = m.get_root()
        html = root.render()

        from branca.element import JavascriptLink, CssLink

        old_js = sum(
            1
            for _, c in root.header._children.items()
            if isinstance(c, JavascriptLink) and not isinstance(c, ResolvedJavascriptLink)
        )
        old_css = sum(
            1
            for _, c in root.header._children.items()
            if isinstance(c, CssLink) and not isinstance(c, ResolvedCssLink)
        )

        assert old_js == 0, "CDN 策略下不应有旧式 JavascriptLink"
        assert old_css == 0, "CDN 策略下不应有旧式 CssLink"

    def test_all_resources_are_resolved(self):
        m = folium.Map(location=[0, 0])
        root = m.get_root()
        html = root.render()

        ctx = root._resource_context
        entries = ctx.get_entries()
        resolved = ctx.resolve_all()

        assert len(entries) > 0, "应收集到资源声明"
        assert len(resolved) == len(entries), "所有资源应被解析"

        for r in resolved:
            assert isinstance(r, ResolvedResource)
            assert r.source == "cdn"
            assert not r.is_inline
            assert r.url is not None

    def test_cdn_html_contains_resource_urls(self):
        m = folium.Map(location=[0, 0])
        html = m.get_root().render()

        assert "leaflet.js" in html
        assert "leaflet.css" in html
        assert "jquery" in html

    def test_cdn_no_crossorigin_without_integrity(self):
        m = folium.Map(location=[0, 0])
        root = m.get_root()
        root.render()

        ctx = root._resource_context
        resolved = ctx.resolve_all()

        for r in resolved:
            if r.integrity is None:
                assert r.crossorigin is None, (
                    f"资源 {r.name}: 没有 integrity 时不应有 crossorigin"
                )

    def test_cdn_crossorigin_with_integrity(self):
        content = b"test content for sri"
        sha = hashlib.sha256(content).hexdigest()

        entry = ResourceEntry(
            name="test_with_sri",
            url="https://cdn.example.com/lib.js",
            resource_type=ResourceType.JAVASCRIPT,
            sha256=sha,
        )
        assert entry.integrity is not None

        resolver = ResourceResolver()
        with patch.object(resolver, "_download", return_value=content):
            resolved = resolver.resolve(entry, strategy=ResourceStrategy.CDN)

        assert resolved.crossorigin == "anonymous"
        assert resolved.integrity == entry.integrity


class TestUnifiedPipelineDefaultJsCss:
    """旧的 default_js/default_css 自动转换为 ResourceEntry。"""

    def test_default_js_converted_to_resource_entry(self):
        m = folium.Map(location=[0, 0])
        root = m.get_root()
        root.render()

        ctx = root._resource_context
        entries = ctx.get_entries()

        js_entries = [e for e in entries if e.resource_type == ResourceType.JAVASCRIPT]
        css_entries = [e for e in entries if e.resource_type == ResourceType.CSS]

        assert len(js_entries) >= 4, f"至少应有 4 个 JS 资源, 实际 {len(js_entries)}"
        assert len(css_entries) >= 6, f"至少应有 6 个 CSS 资源, 实际 {len(css_entries)}"

        entry_names = {e.name for e in entries}
        assert "leaflet" in entry_names
        assert "jquery" in entry_names
        assert "leaflet_css" in entry_names

    def test_default_js_injection_matches_resolved(self):
        m = folium.Map(location=[0, 0])
        root = m.get_root()
        html = root.render()

        ctx = root._resource_context
        resolved = ctx.resolve_all()

        for r in resolved:
            if not r.is_inline and r.url:
                assert r.url in html, (
                    f"资源 {r.name} 的 URL {r.url} 应出现在 HTML 中"
                )


class TestUnifiedPipelinePlugins:
    """插件资源也走同一条数据流。"""

    def test_marker_cluster_resources_resolved(self):
        from folium.plugins import MarkerCluster

        m = folium.Map(location=[0, 0])
        MarkerCluster().add_to(m)
        root = m.get_root()
        root.render()

        ctx = root._resource_context
        entries = ctx.get_entries()
        entry_names = {e.name for e in entries}

        assert "marker_cluster" in entry_names or any(
            "markercluster" in e.name.lower() for e in entries
        ), "MarkerCluster 资源应被收集"

    def test_heat_map_resources_resolved(self):
        from folium.plugins import HeatMap

        m = folium.Map(location=[0, 0])
        HeatMap([[0, 0, 1]]).add_to(m)
        root = m.get_root()
        root.render()

        ctx = root._resource_context
        entries = ctx.get_entries()
        entry_names = {e.name for e in entries}

        assert "heat_map" in entry_names or any(
            "heat" in e.name.lower() for e in entries
        ), "HeatMap 资源应被收集"

    def test_dual_map_uses_resource_injecting_figure(self):
        from folium.plugins import DualMap

        dm = DualMap(location=[0, 0])
        root = dm.get_root()
        html = root.render()

        assert isinstance(root, ResourceInjectingFigure), (
            "DualMap 的 root 应是 ResourceInjectingFigure"
        )
        assert "Leaflet.Sync" in html or "Sync" in html, (
            "DualMap 的 Leaflet.Sync 资源应出现在 HTML 中"
        )


class TestUnifiedPipelineDeclareResource:
    """declare_resource() 声明的资源也走同一条数据流。"""

    def test_declare_resource_collected_and_resolved(self):
        m = folium.Map(location=[0, 0])
        m.declare_resource(
            ResourceEntry(
                name="custom_lib",
                url="https://cdn.example.com/custom.js",
                resource_type=ResourceType.JAVASCRIPT,
            )
        )
        root = m.get_root()
        root.render()

        ctx = root._resource_context
        entries = ctx.get_entries()
        entry_names = {e.name for e in entries}

        assert "custom_lib" in entry_names, "declare_resource 声明的资源应被收集"

        resolved = ctx.resolve_all()
        resolved_names = {r.name for r in resolved}
        assert "custom_lib" in resolved_names, "declare_resource 声明的资源应被解析"

    def test_declare_resource_with_sha256(self):
        content = b"var x = 1;"
        sha = hashlib.sha256(content).hexdigest()

        entry = ResourceEntry(
            name="verified_lib",
            url="https://cdn.example.com/verified.js",
            resource_type=ResourceType.JAVASCRIPT,
            sha256=sha,
        )

        assert entry.integrity is not None, "设置 sha256 后应自动推导 integrity"


class TestUnifiedPipelineSHA256Failure:
    """SHA256 校验失败路径。"""

    def test_sha256_mismatch_raises(self):
        entry = ResourceEntry(
            name="bad_lib",
            url="https://cdn.example.com/bad.js",
            resource_type=ResourceType.JAVASCRIPT,
            sha256="0000000000000000000000000000000000000000000000000000000000000000",
        )

        resolver = ResourceResolver(
            ResourceResolverConfig(allow_fallback_to_cdn=False)
        )

        with patch.object(resolver, "_download", return_value=b"real content"):
            with pytest.raises(Exception):
                resolver._resolve_cdn(entry)

    def test_sha256_mismatch_with_fallback(self):
        wrong_sha = "0" * 64

        entry = ResourceEntry(
            name="fallback_lib",
            url="https://cdn.example.com/lib.js",
            resource_type=ResourceType.JAVASCRIPT,
            sha256=wrong_sha,
            fallback_urls=["https://fallback.example.com/lib.js"],
        )

        resolver = ResourceResolver(
            ResourceResolverConfig(allow_fallback_to_cdn=False)
        )

        call_count = {"n": 0}

        def failing_download_with_cache(url, sha=None):
            call_count["n"] += 1
            raise ValueError("SHA256 mismatch")

        with patch.object(
            resolver, "_download_with_cache", side_effect=failing_download_with_cache
        ):
            with pytest.raises(Exception):
                resolver.resolve(entry, strategy=ResourceStrategy.CDN)

        assert call_count["n"] >= 1


class TestUnifiedPipelineFallback:
    """Fallback 路径。"""

    def test_fallback_to_cdn_on_local_failure(self):
        entry = ResourceEntry(
            name="no_local",
            url="https://cdn.example.com/lib.js",
            resource_type=ResourceType.JAVASCRIPT,
            local_path="/nonexistent/path.js",
        )

        resolver = ResourceResolver(
            ResourceResolverConfig(allow_fallback_to_cdn=True)
        )

        resolved = resolver.resolve(entry, strategy=ResourceStrategy.LOCAL)
        assert resolved.source == "cdn", "LOCAL 失败应降级到 CDN"
        assert resolved.url == entry.url

    def test_fallback_disabled(self):
        entry = ResourceEntry(
            name="no_local",
            url="https://cdn.example.com/lib.js",
            resource_type=ResourceType.JAVASCRIPT,
            local_path="/nonexistent/path.js",
        )

        resolver = ResourceResolver(
            ResourceResolverConfig(allow_fallback_to_cdn=False)
        )

        with pytest.raises(FileNotFoundError):
            resolver.resolve(entry, strategy=ResourceStrategy.LOCAL)


class TestUnifiedPipelineOldHTMLCompat:
    """旧 HTML 输出兼容性测试。"""

    def test_script_tag_format(self):
        m = folium.Map(location=[0, 0])
        html = m.get_root().render()

        assert '<script src="' in html, "应包含 <script src= 标签"
        assert "</script>" in html, "script 标签应正确关闭"

    def test_link_tag_format(self):
        m = folium.Map(location=[0, 0])
        html = m.get_root().render()

        assert '<link rel="stylesheet"' in html, "应包含 <link rel=stylesheet 标签"

    def test_no_duplicate_resources(self):
        m = folium.Map(location=[0, 0])
        html = m.get_root().render()

        leaflet_js_count = html.count("leaflet.js")
        assert leaflet_js_count == 1, f"leaflet.js 应只出现 1 次, 实际 {leaflet_js_count}"

    def test_jupyter_repr_html(self):
        m = folium.Map(location=[0, 0])
        html = m._repr_html_()

        assert "<div" in html, "Jupyter 输出应包含 div"
        assert "iframe" in html.lower() or "div" in html, "Jupyter 格式应正确"

    def test_save_and_load(self):
        with tempfile.NamedTemporaryFile(
            suffix=".html", delete=False, mode="w"
        ) as f:
            m = folium.Map(location=[0, 0])
            m.save(f.name)

            with open(f.name, encoding="utf-8") as rf:
                html = rf.read()

            assert "leaflet.js" in html
            assert "L.map(" in html
            os.unlink(f.name)


class TestUnifiedPipelineManifest:
    """Manifest 导出和复用测试。"""

    def test_export_and_reload_manifest(self):
        m = folium.Map(location=[0, 0])
        root = m.get_root()
        root.render()

        with tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w"
        ) as f:
            root._resource_context.export_manifest(f.name)

            with open(f.name, encoding="utf-8") as rf:
                manifest = json.load(rf)

            assert "version" in manifest
            assert "resources" in manifest
            assert len(manifest["resources"]) > 0

            for res in manifest["resources"]:
                assert "name" in res
                assert "url" in res
                assert "type" in res

            os.unlink(f.name)


class TestResourceEntrySha256Integrity:
    """ResourceEntry sha256/integrity 互推导测试。"""

    def test_sha256_auto_derives_integrity(self):
        sha = hashlib.sha256(b"test").hexdigest()
        entry = ResourceEntry(
            name="test",
            url="https://example.com/test.js",
            resource_type=ResourceType.JAVASCRIPT,
            sha256=sha,
        )
        assert entry.integrity is not None
        assert entry.integrity.startswith("sha256-")

    def test_integrity_auto_derives_sha256(self):
        import base64

        sha = hashlib.sha256(b"test").hexdigest()
        hash_bytes = bytes.fromhex(sha)
        integrity = f"sha256-{base64.b64encode(hash_bytes).decode('ascii')}"

        entry = ResourceEntry(
            name="test",
            url="https://example.com/test.js",
            resource_type=ResourceType.JAVASCRIPT,
            integrity=integrity,
        )
        assert entry.sha256 == sha

    def test_mismatch_raises(self):
        sha = hashlib.sha256(b"test").hexdigest()
        integrity = "sha256-AAAA"

        with pytest.raises(ValueError, match="mismatch"):
            ResourceEntry(
                name="test",
                url="https://example.com/test.js",
                resource_type=ResourceType.JAVASCRIPT,
                sha256=sha,
                integrity=integrity,
            )


class TestResolvedResourceConsistency:
    """ResolvedResource 一致性校验测试。"""

    def test_inline_true_with_no_content_raises(self):
        with pytest.raises(ValueError, match="inline=True but content is None"):
            ResolvedResource(
                name="test",
                resource_type=ResourceType.JAVASCRIPT,
                inline=True,
                content=None,
            )

    def test_content_auto_sets_inline(self):
        r = ResolvedResource(
            name="test",
            resource_type=ResourceType.JAVASCRIPT,
            content="var x = 1;",
            inline=False,
        )
        assert r.is_inline is True


class TestTemplateRendering:
    """验证渲染元素模板格式正确。"""

    def test_resolved_javascript_link_template(self):
        link = ResolvedJavascriptLink(
            url="https://cdn.example.com/lib.js",
            integrity="sha256-abc123",
            crossorigin="anonymous",
        )
        html = link._template.render(this=link, kwargs={})
        assert '<script src="https://cdn.example.com/lib.js"' in html
        assert 'integrity="sha256-abc123"' in html
        assert 'crossorigin="anonymous"' in html
        assert "</script>" in html

    def test_resolved_css_link_template(self):
        link = ResolvedCssLink(
            url="https://cdn.example.com/lib.css",
            integrity="sha256-def456",
            crossorigin="anonymous",
        )
        html = link._template.render(this=link, kwargs={})
        assert '<link rel="stylesheet" href="https://cdn.example.com/lib.css"' in html
        assert 'integrity="sha256-def456"' in html
        assert "/>" in html

    def test_inline_script_template(self):
        script = InlineScript("var x = 1;")
        html = script._template.render(this=script, kwargs={})
        assert "<script>var x = 1;</script>" == html.strip()

    def test_inline_style_template(self):
        style = InlineStyle("body { color: red; }")
        html = style._template.render(this=style, kwargs={})
        assert "<style>body { color: red; }</style>" == html.strip()

    def test_resolved_javascript_link_no_sri(self):
        link = ResolvedJavascriptLink(url="https://cdn.example.com/lib.js")
        html = link._template.render(this=link, kwargs={})
        assert "integrity" not in html
        assert "crossorigin" not in html
        assert '<script src="https://cdn.example.com/lib.js"></script>' == html.strip()


class TestLegacyLinkHarvesting:
    """旧式 JavascriptLink/CssLink 拦截和转换测试。"""

    def test_legacy_javascript_link_harvested(self):
        from branca.element import JavascriptLink

        m = folium.Map(location=[0, 0])
        root = m.get_root()
        root.header.add_child(
            JavascriptLink("https://example.com/legacy.js"),
            name="legacy_lib",
        )
        html = root.render()

        from branca.element import JavascriptLink as _JavascriptLink

        old_js = sum(
            1
            for _, c in root.header._children.items()
            if isinstance(c, _JavascriptLink) and not isinstance(c, ResolvedJavascriptLink)
        )
        assert old_js == 0, "旧式 JavascriptLink 应被收割并移除"

        ctx = root._resource_context
        entries = ctx.get_entries()
        entry_names = {e.name for e in entries}
        assert "legacy_lib" in entry_names, "旧式链接应被转换为 ResourceEntry"

        resolved = ctx.resolve_all()
        resolved_names = {r.name for r in resolved}
        assert "legacy_lib" in resolved_names, "旧式链接应被解析"

        for r in resolved:
            if r.name == "legacy_lib":
                assert r.url == "https://example.com/legacy.js"
                assert r.resource_type == ResourceType.JAVASCRIPT
                assert r.source == "cdn"
                break
        else:
            pytest.fail("legacy_lib not found in resolved resources")

    def test_legacy_css_link_harvested(self):
        from branca.element import CssLink

        m = folium.Map(location=[0, 0])
        root = m.get_root()
        root.header.add_child(
            CssLink("https://example.com/legacy.css"),
            name="legacy_css",
        )
        html = root.render()

        from branca.element import CssLink as _CssLink

        old_css = sum(
            1
            for _, c in root.header._children.items()
            if isinstance(c, _CssLink) and not isinstance(c, ResolvedCssLink)
        )
        assert old_css == 0, "旧式 CssLink 应被收割并移除"

    def test_legacy_links_resolved_and_injected(self):
        from branca.element import JavascriptLink, CssLink

        m = folium.Map(location=[0, 0])
        root = m.get_root()
        root.header.add_child(
            JavascriptLink("https://example.com/custom-a.js"),
            name="custom_a",
        )
        root.header.add_child(
            CssLink("https://example.com/custom-b.css"),
            name="custom_b",
        )
        html = root.render()

        assert "https://example.com/custom-a.js" in html
        assert "https://example.com/custom-b.css" in html

        resolved_elements = sum(
            1
            for _, c in root.header._children.items()
            if isinstance(c, (ResolvedJavascriptLink, ResolvedCssLink))
        )
        assert resolved_elements >= 2, "resolved 元素应被注入到 header"


class TestThreeEntrypointsDeduplication:
    """三种入口混用去重且顺序不变的回归测试。

    三种入口：
    1. 直接 Figure.header.add_child(JavascriptLink/CssLink)
    2. 普通插件默认资源（default_js/default_css）
    3. declare_resource()

    断言：
    - 三种入口声明同名资源，最终 HTML 只输出一份
    - 输出顺序：declare_resource > default_js/css > header.add_child
    - 所有资源都走 ResolvedResource 链路
    """

    def test_three_entrypoints_same_name_deduplicated(self):
        """三种入口声明同名资源，最终只输出一份。"""
        from branca.element import JavascriptLink

        m = folium.Map(location=[0, 0])
        root = m.get_root()

        # 入口1：declare_resource
        m.declare_resource(
            ResourceEntry(
                name="test_lib",
                url="https://cdn.example.com/via-declare.js",
                resource_type=ResourceType.JAVASCRIPT,
            )
        )

        # 入口2：default_js（JSCSSMixin）- 同名
        m.default_js.append(("test_lib", "https://cdn.example.com/via-default.js"))

        # 入口3：直接 header.add_child - 同名
        root.header.add_child(
            JavascriptLink("https://cdn.example.com/via-header.js"),
            name="test_lib",
        )

        html = root.render()

        via_declare_count = html.count("https://cdn.example.com/via-declare.js")
        via_default_count = html.count("https://cdn.example.com/via-default.js")
        via_header_count = html.count("https://cdn.example.com/via-header.js")

        # declare_resource 优先级最高，所以只输出 via-declare.js
        assert via_declare_count == 1, f"declare_resource 的 URL 应出现 1 次，实际 {via_declare_count}"
        assert via_default_count == 0, f"default_js 的 URL 不应出现，实际 {via_default_count}"
        assert via_header_count == 0, f"header.add_child 的 URL 不应出现，实际 {via_header_count}"

    def test_three_entrypoints_order_preserved(self):
        """三种入口声明不同名资源，输出顺序为 declare > default > header。"""
        from branca.element import JavascriptLink

        m = folium.Map(location=[0, 0])
        root = m.get_root()

        # 先清理 Map 默认资源，方便观察顺序
        # 注意：保留 Map 原有的资源，我们新增额外的来测试顺序

        # 入口1：declare_resource (添加 A)
        m.declare_resource(
            ResourceEntry(
                name="entry_a",
                url="https://cdn.example.com/entry-a.js",
                resource_type=ResourceType.JAVASCRIPT,
            )
        )

        # 入口2：default_js（JSCSSMixin）- 添加 B
        m.default_js.append(("entry_b", "https://cdn.example.com/entry-b.js"))

        # 入口3：直接 header.add_child - 添加 C
        root.header.add_child(
            JavascriptLink("https://cdn.example.com/entry-c.js"),
            name="entry_c",
        )

        html = root.render()

        # 确认都出现
        assert "https://cdn.example.com/entry-a.js" in html
        assert "https://cdn.example.com/entry-b.js" in html
        assert "https://cdn.example.com/entry-c.js" in html

        # 确认顺序：a 在 b 前，b 在 c 前
        pos_a = html.find("https://cdn.example.com/entry-a.js")
        pos_b = html.find("https://cdn.example.com/entry-b.js")
        pos_c = html.find("https://cdn.example.com/entry-c.js")

        assert pos_a >= 0 and pos_b >= 0 and pos_c >= 0
        assert pos_a < pos_b < pos_c, (
            f"资源顺序错误，应为 A < B < C，"
            f"实际位置：A={pos_a}, B={pos_b}, C={pos_c}"
        )

    def test_three_entrypoints_all_are_resolved(self):
        """三种入口声明的资源最终都以 Resolved* 形式存在，没有旧式链接。"""
        from branca.element import JavascriptLink, CssLink

        m = folium.Map(location=[0, 0])
        root = m.get_root()

        # 入口1：declare_resource
        m.declare_resource(
            ResourceEntry(
                name="dedupe_a",
                url="https://cdn.example.com/dedupe-a.js",
                resource_type=ResourceType.JAVASCRIPT,
            )
        )

        # 入口2：default_js
        m.default_js.append(("dedupe_b", "https://cdn.example.com/dedupe-b.js"))

        # 入口3：直接 header.add_child
        root.header.add_child(
            JavascriptLink("https://cdn.example.com/dedupe-c.js"),
            name="dedupe_c",
        )
        root.header.add_child(
            CssLink("https://cdn.example.com/dedupe-d.css"),
            name="dedupe_d",
        )

        html = root.render()

        # 检查 header 中没有旧式链接
        from branca.element import JavascriptLink as _JavascriptLink, CssLink as _CssLink

        old_js = sum(
            1
            for _, c in root.header._children.items()
            if isinstance(c, _JavascriptLink) and not isinstance(c, ResolvedJavascriptLink)
        )
        old_css = sum(
            1
            for _, c in root.header._children.items()
            if isinstance(c, _CssLink) and not isinstance(c, ResolvedCssLink)
        )

        assert old_js == 0, "不应有旧式 JavascriptLink"
        assert old_css == 0, "不应有旧式 CssLink"

        # 检查 Resolved* 元素存在
        resolved_names = {
            name: child
            for name, child in root.header._children.items()
            if isinstance(child, (ResolvedJavascriptLink, ResolvedCssLink))
        }

        for expected_name in ["dedupe_a", "dedupe_b", "dedupe_c", "dedupe_d"]:
            assert expected_name in resolved_names, (
                f"{expected_name} 应以 Resolved* 形式存在"
            )

    def test_mixed_with_vegalite_legacy_links(self):
        """与 features.py 中 VegaLite 的旧式链接混用的集成测试。"""
        try:
            from folium.features import VegaLite
        except ImportError:
            pytest.skip("VegaLite not available")

        from branca.element import Figure as BrancaFigure

        m = folium.Map(location=[0, 0])
        root = m.get_root()

        # declare_resource 添加一个资源
        m.declare_resource(
            ResourceEntry(
                name="my_custom_lib",
                url="https://cdn.example.com/my-lib.js",
                resource_type=ResourceType.JAVASCRIPT,
            )
        )

        # 添加一个 VegaLite 元素（它会在 render 时往 header 加 vega 等 JavascriptLink）
        vega_spec = {
            "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
            "description": "A simple bar chart with embedded data.",
            "data": {
                "values": [
                    {"a": "A", "b": 28},
                    {"a": "B", "b": 55},
                ]
            },
            "mark": "bar",
            "encoding": {
                "x": {"field": "a", "type": "nominal"},
                "y": {"field": "b", "type": "quantitative"},
            },
        }
        VegaLite(vega_spec, width="400px", height="300px").add_to(root)

        html = root.render()

        # 检查 my_custom_lib 被解析
        ctx = root._resource_context
        entries = ctx.get_entries()
        entry_names = {e.name for e in entries}
        assert "my_custom_lib" in entry_names

        # 检查 VegaLite 注入的旧式 vega 链接也被收割了
        # (它们可能叫 "vega", "vega-lite", "vega-embed")
        for expected in ["vega", "vega-lite", "vega-embed"]:
            assert expected in entry_names or any(
                expected in name.lower() for name in entry_names
            ), f"VegaLite 的 {expected} 资源应被收割"

        # 检查 HTML 中没有旧式链接
        from branca.element import JavascriptLink as _JavascriptLink, CssLink as _CssLink

        old_js = sum(
            1
            for _, c in root.header._children.items()
            if isinstance(c, _JavascriptLink) and not isinstance(c, ResolvedJavascriptLink)
        )
        old_css = sum(
            1
            for _, c in root.header._children.items()
            if isinstance(c, _CssLink) and not isinstance(c, ResolvedCssLink)
        )
        assert old_js == 0 and old_css == 0, "VegaLite 的旧式链接应被收割"


class TestFourEntrypointsHarvest:
    """四条公共入口直接 render：旧式 JavascriptLink/CssLink 被 harvest，无重复注入。

    四条入口：
      1. folium.Figure()
      2. folium.elements.Figure()
      3. Map.get_root()
      4. DualMap.get_root()
    """

    @staticmethod
    def _figure_with_legacy_links(figure, idx):
        """向 Figure 添加旧式 JS/CSS 链接并返回渲染结果。"""
        from branca.element import JavascriptLink, CssLink

        js_name = f"legacy_entry_js_{idx}"
        css_name = f"legacy_entry_css_{idx}"
        js_url = f"https://example.com/legacy_entry_{idx}.js"
        css_url = f"https://example.com/legacy_entry_{idx}.css"

        figure.header.add_child(JavascriptLink(js_url), name=js_name)
        figure.header.add_child(CssLink(css_url), name=css_name)
        html = figure.render()

        return html, js_name, css_name, js_url, css_url

    def test_folium_Figure_entrypoint(self):
        """入口 1：folium.Figure() 直接 render。"""
        fig = folium.Figure()
        html, js_name, css_name, js_url, css_url = self._figure_with_legacy_links(
            fig, 1
        )

        # Resolved* 形式且只出现一次
        assert html.count(js_url) == 1, "旧 JS 链接应以 resolved 形式出现一次"
        assert html.count(css_url) == 1, "旧 CSS 链接应以 resolved 形式出现一次"

        # header 中没有旧式链接
        from branca.element import JavascriptLink as _JavascriptLink, CssLink as _CssLink

        old_js = sum(
            1
            for _, c in fig.header._children.items()
            if isinstance(c, _JavascriptLink) and not isinstance(c, ResolvedJavascriptLink)
        )
        old_css = sum(
            1
            for _, c in fig.header._children.items()
            if isinstance(c, _CssLink) and not isinstance(c, ResolvedCssLink)
        )
        assert old_js == 0, "folium.Figure 旧式 JS 应被收割"
        assert old_css == 0, "folium.Figure 旧式 CSS 应被收割"

    def test_folium_elements_Figure_entrypoint(self):
        """入口 2：folium.elements.Figure() 直接 render。"""
        from folium.elements import Figure as ElemFigure

        fig = ElemFigure()
        html, js_name, css_name, js_url, css_url = self._figure_with_legacy_links(
            fig, 2
        )

        assert html.count(js_url) == 1
        assert html.count(css_url) == 1

        from branca.element import JavascriptLink as _JavascriptLink, CssLink as _CssLink

        old_js = sum(
            1
            for _, c in fig.header._children.items()
            if isinstance(c, _JavascriptLink) and not isinstance(c, ResolvedJavascriptLink)
        )
        old_css = sum(
            1
            for _, c in fig.header._children.items()
            if isinstance(c, _CssLink) and not isinstance(c, ResolvedCssLink)
        )
        assert old_js == 0 and old_css == 0, "folium.elements.Figure 旧式链接应被收割"

    def test_Map_get_root_entrypoint(self):
        """入口 3：Map.get_root()。"""
        m = folium.Map(location=[0, 0])
        root = m.get_root()
        html, js_name, css_name, js_url, css_url = self._figure_with_legacy_links(
            root, 3
        )

        assert html.count(js_url) == 1
        assert html.count(css_url) == 1

        from branca.element import JavascriptLink as _JavascriptLink, CssLink as _CssLink

        old_js = sum(
            1
            for _, c in root.header._children.items()
            if isinstance(c, _JavascriptLink) and not isinstance(c, ResolvedJavascriptLink)
        )
        old_css = sum(
            1
            for _, c in root.header._children.items()
            if isinstance(c, _CssLink) and not isinstance(c, ResolvedCssLink)
        )
        assert old_js == 0 and old_css == 0, "Map.get_root() 旧式链接应被收割"

    def test_DualMap_get_root_entrypoint(self):
        """入口 4：DualMap.get_root()。"""
        dm = folium.plugins.DualMap(location=[0, 0])
        root = dm.get_root()
        html, js_name, css_name, js_url, css_url = self._figure_with_legacy_links(
            root, 4
        )

        assert html.count(js_url) == 1
        assert html.count(css_url) == 1

        from branca.element import JavascriptLink as _JavascriptLink, CssLink as _CssLink

        old_js = sum(
            1
            for _, c in root.header._children.items()
            if isinstance(c, _JavascriptLink) and not isinstance(c, ResolvedJavascriptLink)
        )
        old_css = sum(
            1
            for _, c in root.header._children.items()
            if isinstance(c, _CssLink) and not isinstance(c, ResolvedCssLink)
        )
        assert old_js == 0 and old_css == 0, "DualMap.get_root() 旧式链接应被收割"

    def test_ResourceInjectingFigure_is_branca_Figure_subclass(self):
        """类型边界：isinstance(x, branca.element.Figure) 必须仍然成立。"""
        from branca.element import Figure as BrancaFigure
        from folium.elements import ResourceInjectingFigure

        assert issubclass(ResourceInjectingFigure, BrancaFigure)
        assert isinstance(folium.Figure(), BrancaFigure)
        assert isinstance(folium.Map(location=[0, 0]).get_root(), BrancaFigure)


class TestManifestUnifiedResourcePool:
    """manifest/export/download/verify 读取同一批 harvested + declared + default 资源。"""

    def _build_context_with_all_three_entrypoints(self):
        """构建一个混合了三种资源入口的 ResourceContext（不依赖真实网络下载）。

        方式：直接在 ResourceInjectingFigure 上操作，避免 Map 的 default_js 触发
        真实 CDN 下载。
        """
        from branca.element import JavascriptLink, CssLink

        fig = folium.Figure()  # ResourceInjectingFigure

        ctx = get_or_create_resource_context(fig, strategy=ResourceStrategy.CDN)

        # 入口 A：declare_resource()（模拟 JSCSSMixin.render 路径）
        ctx.add_resource(
            ResourceEntry(
                name="manifest_declared_a",
                url="https://cdn.example.com/declared-a.js",
                resource_type=ResourceType.JAVASCRIPT,
            )
        )
        ctx.add_resource(
            ResourceEntry(
                name="manifest_declared_b",
                url="https://cdn.example.com/declared-b.css",
                resource_type=ResourceType.CSS,
            )
        )

        # 入口 C：default_js/default_css（模拟 JSCSSMixin.default_js 路径）
        ctx.add_resource(
            ResourceEntry(
                name="leaflet_default_c",
                url="https://cdn.example.com/leaflet.js",
                resource_type=ResourceType.JAVASCRIPT,
            )
        )
        ctx.add_resource(
            ResourceEntry(
                name="leaflet_default_d",
                url="https://cdn.example.com/leaflet.css",
                resource_type=ResourceType.CSS,
            )
        )

        # 入口 B：header.add_child(JavascriptLink/CssLink) 旧式链接
        fig.header.add_child(
            JavascriptLink("https://cdn.example.com/legacy-e.js"),
            name="manifest_legacy_e",
        )
        fig.header.add_child(
            CssLink("https://cdn.example.com/legacy-f.css"),
            name="manifest_legacy_f",
        )

        return fig, ctx

    def test_resource_context_after_render_contains_all_three_entrypoints(self):
        """render() 后 ResourceContext 应包含三种入口的所有资源。"""
        fig, ctx = self._build_context_with_all_three_entrypoints()
        fig.render()  # 触发 harvest

        entry_names = {e.name for e in ctx.get_entries()}

        # 入口 A：declare_resource
        assert "manifest_declared_a" in entry_names
        assert "manifest_declared_b" in entry_names

        # 入口 B：旧式链接被 harvest
        assert "manifest_legacy_e" in entry_names
        assert "manifest_legacy_f" in entry_names

        # 入口 C：default_js/default_css
        assert "leaflet_default_c" in entry_names
        assert "leaflet_default_d" in entry_names

    def test_manifest_contains_harvested_resources(self):
        """导出的 manifest JSON 应包含 harvested + declared + default 资源。"""
        fig, ctx = self._build_context_with_all_three_entrypoints()
        fig.render()  # 触发 harvest

        from folium.resources import build_manifest

        manifest = build_manifest(ctx)

        assert "resources" in manifest
        manifest_names = {r.get("name") for r in manifest["resources"]}

        assert "manifest_declared_a" in manifest_names, "declare_resource 应在 manifest 中"
        assert "manifest_declared_b" in manifest_names, "declare_resource 应在 manifest 中"
        assert "manifest_legacy_e" in manifest_names, "harvested 链接应在 manifest 中"
        assert "manifest_legacy_f" in manifest_names, "harvested 链接应在 manifest 中"
        assert "leaflet_default_c" in manifest_names, "default_js 应在 manifest 中"
        assert "leaflet_default_d" in manifest_names, "default_css 应在 manifest 中"

    def test_download_and_verify_manifest_entries_match(self):
        """ResourceResolver.resolve_all() 和 build_manifest() 的资源集合一致。

        只比较 names，不触发真实网络下载。
        """
        fig, ctx = self._build_context_with_all_three_entrypoints()
        fig.render()  # 触发 harvest

        ctx_entries = ctx.get_entries()
        entry_names = {e.name for e in ctx_entries}

        # manifest 中的资源名
        from folium.resources import build_manifest
        manifest = build_manifest(ctx)
        manifest_names = {r.get("name") for r in manifest["resources"]}

        # 检查我们自定义的 6 个都存在于两边
        for expected in [
            "manifest_declared_a",
            "manifest_declared_b",
            "manifest_legacy_e",
            "manifest_legacy_f",
            "leaflet_default_c",
            "leaflet_default_d",
        ]:
            assert expected in entry_names, f"{expected} 应在 ctx entries 中"
            assert expected in manifest_names, f"{expected} 应在 manifest 中"

    def test_cli_export_renders_same_resources_as_manifest(self):
        """CLI export（build_manifest 路径）输出的资源与渲染管线 resolve_all 一致。"""
        fig, ctx = self._build_context_with_all_three_entrypoints()
        fig.render()  # 触发 harvest

        from folium.resources import build_manifest
        manifest = build_manifest(ctx)

        manifest_entries_by_name = {
            r["name"]: r for r in manifest["resources"] if "name" in r
        }
        ctx_entries_by_name = {e.name: e for e in ctx.get_entries()}

        # 检查 URL 一致（即 manifest 和 ctx 读取的是同一批数据）
        for name in [
            "manifest_declared_a",
            "manifest_declared_b",
            "manifest_legacy_e",
            "manifest_legacy_f",
        ]:
            assert name in manifest_entries_by_name
            assert name in ctx_entries_by_name
            assert (
                manifest_entries_by_name[name].get("url")
                == ctx_entries_by_name[name].url
            ), f"{name} 的 URL 在 manifest 和 ctx 中应一致"
