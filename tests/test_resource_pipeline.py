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
