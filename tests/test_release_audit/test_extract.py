"""
Tests for folium.release_audit._extract module.

Responsibility coverage:
  - Data classes: ResourceEntry, ClassResources, AuditFinding, AuditResult
  - URL parsing: extract_package_from_url, extract_version_from_url, cdn_host
  - Resource ID hashing: resource_id
  - Source extraction: collect_resources_from_class
  - Class discovery: get_plugin_classes, get_feature_classes, get_map_class
  - Full collection: collect_all_resources
"""

import pytest

from folium.release_audit import (
    AuditResult,
    ClassResources,
    FOLIUM_ROOT,
    ResourceEntry,
    cdn_host,
    collect_all_resources,
    collect_resources_from_class,
    extract_package_from_url,
    extract_version_from_url,
    get_feature_classes,
    get_map_class,
    get_plugin_classes,
    resource_id,
)

pytestmark = pytest.mark.audit


class TestResourceEntry:
    def test_resource_entry_construction(self):
        re = ResourceEntry(name="leaflet", url="https://example.com/leaflet.js")
        assert re.name == "leaflet"
        assert re.url == "https://example.com/leaflet.js"


class TestClassResources:
    def test_class_resources_construction(self):
        cr = ClassResources(
            class_name="Foo",
            module="test.foo",
            js=[ResourceEntry("a", "url_a")],
            css=[ResourceEntry("b", "url_b")],
            declared_on_class=True,
            is_jscssmixin_subclass=True,
            inherited_from=None,
        )
        assert cr.class_name == "Foo"
        assert len(cr.js) == 1
        assert len(cr.css) == 1


class TestAuditResult:
    def test_ok_no_errors(self):
        r = AuditResult()
        assert r.ok is True

    def test_not_ok_with_errors(self):
        r = AuditResult()
        r.add_error("test", "boom")
        assert r.ok is False

    def test_to_dict_structure(self):
        r = AuditResult()
        r.add_error("err_cat", "error message", location="here", detail="oops")
        r.add_warning("warn_cat", "warning message")
        d = r.to_dict()
        assert d["ok"] is False
        assert d["error_count"] == 1
        assert d["warning_count"] == 1
        assert len(d["errors"]) == 1
        assert d["errors"][0]["category"] == "err_cat"
        assert d["warnings"][0]["category"] == "warn_cat"

    def test_merge(self):
        r1 = AuditResult()
        r1.add_error("a", "e1")
        r2 = AuditResult()
        r2.add_warning("b", "w1")
        r1.merge(r2)
        assert len(r1.errors) == 1
        assert len(r1.warnings) == 1


class TestResourceId:
    def test_resource_id_stable(self):
        url1 = "https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/leaflet.js"
        url2 = "https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/leaflet.js"
        assert resource_id(url1) == resource_id(url2)
        assert len(resource_id(url1)) == 12

    def test_resource_id_different_urls(self):
        assert resource_id("http://a") != resource_id("http://b")


class TestPackageExtraction:
    def test_jsdelivr_npm(self):
        assert extract_package_from_url(
            "https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/leaflet.js"
        ) == "leaflet"

    def test_jsdelivr_scoped(self):
        assert extract_package_from_url(
            "https://cdn.jsdelivr.net/npm/@fortawesome/fontawesome-free@6.2.0/css/all.min.css"
        ) == "fontawesome-free"

    def test_cdnjs(self):
        assert extract_package_from_url(
            "https://cdnjs.cloudflare.com/ajax/libs/leaflet.draw/1.0.2/leaflet.draw.js"
        ) == "leaflet.draw"

    def test_unpkg(self):
        assert extract_package_from_url(
            "https://unpkg.com/leaflet.boatmarker/leaflet.boatmarker.min.js"
        ) == "leaflet.boatmarker"


class TestVersionExtraction:
    def test_at_sign_version(self):
        assert extract_version_from_url(
            "https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/leaflet.js"
        ) == "1.9.3"

    def test_path_segment_version(self):
        assert extract_version_from_url(
            "https://cdnjs.cloudflare.com/ajax/libs/leaflet.draw/1.0.2/leaflet.draw.js"
        ) == "1.0.2"

    def test_no_version(self):
        assert extract_version_from_url(
            "https://unpkg.com/leaflet.boatmarker/leaflet.boatmarker.min.js"
        ) is None


class TestCdnHost:
    def test_all_hosts(self):
        assert cdn_host("https://cdn.jsdelivr.net/npm/foo/a.js") == "jsdelivr"
        assert cdn_host("https://cdnjs.cloudflare.com/ajax/libs/foo/1/a.js") == "cdnjs"
        assert cdn_host("https://unpkg.com/foo/a.js") == "unpkg"
        assert cdn_host("https://code.jquery.com/jquery-3.js") == "jquery"
        assert cdn_host("https://netdna.bootstrapcdn.com/bootstrap/3/css/b.min.css") == "bootstrapcdn"
        assert cdn_host("https://www.webglearth.com/v2/api.js") == "webglearth"
        assert cdn_host("https://teastman.github.io/Leaflet.pattern/leaflet.pattern.js") == "github_pages"


class TestResourceExtractionFromClasses:
    def test_map_class_extraction(self):
        Map = get_map_class()
        resources = collect_resources_from_class(Map)
        assert isinstance(resources, ClassResources)
        assert resources.class_name == "Map"
        assert len(resources.js) > 0
        assert len(resources.css) > 0
        assert resources.is_jscssmixin_subclass is True
        assert resources.declared_on_class is True

    def test_plugin_with_resources(self):
        plugins = get_plugin_classes()
        Draw = plugins["Draw"]
        resources = collect_resources_from_class(Draw)
        assert len(resources.js) > 0
        assert len(resources.css) > 0

    def test_inheritance_tracking(self):
        plugins = get_plugin_classes()
        FMC = plugins.get("FastMarkerCluster")
        if FMC is not None:
            resources = collect_resources_from_class(FMC)
            assert resources.inherited_from is not None
            assert resources.inherited_from == "MarkerCluster"
            assert resources.declared_on_class is False
            assert len(resources.js) > 0

    def test_all_plugins_collected(self):
        plugin_classes = get_plugin_classes()
        assert len(plugin_classes) > 30
        assert "MarkerCluster" in plugin_classes
        assert "Draw" in plugin_classes

    def test_all_features_collected(self):
        feature_classes = get_feature_classes()
        assert len(feature_classes) >= 4


class TestCollectAllResources:
    def test_collect_returns_dict(self):
        all_res = collect_all_resources()
        assert isinstance(all_res, dict)
        assert "Map" in all_res

    def test_contains_expected_classes(self):
        all_res = collect_all_resources()
        for name in ["Map", "MarkerCluster", "FastMarkerCluster", "Draw"]:
            assert name in all_res, f"Expected class {name} in collected resources"
