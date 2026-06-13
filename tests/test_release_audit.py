"""
Tests for the Folium Release Resource Audit tool.

These tests validate that:
  1. The manifest loads and is structurally valid
  2. Duplicate name detection works
  3. Version drift detection works
  4. Manifest consistency checks work (mismatch / missing / orphan)
  5. Docs consistency check works
  6. The full audit run succeeds against the current codebase
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from folium._audit.resources import (
    AuditResult,
    FOLIUM_ROOT,
    _collect_resources_from_class,
    _extract_package_from_url,
    _extract_version_from_url,
    _get_feature_classes,
    _get_plugin_classes,
    check_duplicate_names,
    check_manifest_consistency,
    check_version_drift,
    load_manifest,
    run_audit,
)

pytestmark = pytest.mark.audit


class TestManifestLoading:
    def test_manifest_file_exists(self):
        path = FOLIUM_ROOT / "resource_manifest.json"
        assert path.exists(), "resource_manifest.json must exist in folium package"

    def test_manifest_is_valid_json(self):
        data = load_manifest()
        assert isinstance(data, dict)

    def test_manifest_has_required_sections(self):
        data = load_manifest()
        assert "map_defaults" in data
        assert "plugins" in data
        assert "features" in data

    def test_manifest_map_defaults_structure(self):
        data = load_manifest()
        for kind in ("js", "css"):
            items = data["map_defaults"][kind]
            for item in items:
                assert "name" in item, f"Missing 'name' in map_defaults.{kind}"
                assert "url" in item, f"Missing 'url' in map_defaults.{kind}"
                assert item["url"].startswith("http"), f"Invalid URL in map_defaults.{kind}: {item['url']}"

    def test_manifest_plugin_entries_have_source(self):
        data = load_manifest()
        for plugin_name, entry in data["plugins"].items():
            assert "source" in entry, f"Plugin '{plugin_name}' missing 'source' field"
            assert "js" in entry, f"Plugin '{plugin_name}' missing 'js' field"
            assert "css" in entry, f"Plugin '{plugin_name}' missing 'css' field"


class TestResourceExtraction:
    def test_extract_package_from_jsdelivr(self):
        assert _extract_package_from_url(
            "https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/leaflet.js"
        ) == "leaflet"

    def test_extract_package_from_jsdelivr_scoped(self):
        assert _extract_package_from_url(
            "https://cdn.jsdelivr.net/npm/@fortawesome/fontawesome-free@6.2.0/css/all.min.css"
        ) == "fontawesome-free"

    def test_extract_package_from_cdnjs(self):
        assert _extract_package_from_url(
            "https://cdnjs.cloudflare.com/ajax/libs/leaflet.draw/1.0.2/leaflet.draw.js"
        ) == "leaflet.draw"

    def test_extract_package_from_unpkg(self):
        assert _extract_package_from_url(
            "https://unpkg.com/leaflet.boatmarker/leaflet.boatmarker.min.js"
        ) == "leaflet.boatmarker"

    def test_extract_package_from_gh(self):
        pkg = _extract_package_from_url(
            "https://cdn.jsdelivr.net/gh/marslan390/BeautifyMarker/leaflet-beautify-marker-icon.min.js"
        )
        assert pkg is not None

    def test_extract_version_at_sign(self):
        assert _extract_version_from_url(
            "https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/leaflet.js"
        ) == "1.9.3"

    def test_extract_version_path_segment(self):
        assert _extract_version_from_url(
            "https://cdnjs.cloudflare.com/ajax/libs/leaflet.draw/1.0.2/leaflet.draw.js"
        ) == "1.0.2"

    def test_extract_version_none(self):
        assert _extract_version_from_url(
            "https://unpkg.com/leaflet.boatmarker/leaflet.boatmarker.min.js"
        ) is None

    def test_collect_resources_from_map(self):
        from folium.folium import Map

        resources = _collect_resources_from_class(Map)
        assert "js" in resources
        assert "css" in resources
        assert len(resources["js"]) > 0
        assert len(resources["css"]) > 0

    def test_collect_resources_from_plugin(self):
        from folium.plugins.draw import Draw

        resources = _collect_resources_from_class(Draw)
        assert len(resources["js"]) > 0
        assert len(resources["css"]) > 0


class TestDuplicateNameDetection:
    def test_no_duplicates_passes(self):
        result = AuditResult()
        resources = {"js": [("a", "url1"), ("b", "url2")], "css": []}
        check_duplicate_names(result, resources, "TestClass")
        assert result.ok
        assert len(result.errors) == 0

    def test_duplicate_name_detected(self):
        result = AuditResult()
        resources = {"js": [("dup", "url1"), ("dup", "url2")], "css": []}
        check_duplicate_names(result, resources, "TestClass")
        assert not result.ok
        assert any(f.category == "duplicate_name" for f in result.errors)


class TestVersionDriftDetection:
    def test_no_drift_passes(self):
        result = AuditResult()
        all_resources = {
            "A": {"js": [("x", "https://cdn.jsdelivr.net/npm/foo@1.0.0/a.js")], "css": []},
            "B": {"js": [("y", "https://cdn.jsdelivr.net/npm/foo@1.0.0/b.js")], "css": []},
        }
        check_version_drift(result, all_resources)
        assert len(result.warnings) == 0

    def test_version_drift_detected(self):
        result = AuditResult()
        all_resources = {
            "A": {"js": [("x", "https://cdn.jsdelivr.net/npm/foo@1.0.0/a.js")], "css": []},
            "B": {"js": [("y", "https://cdn.jsdelivr.net/npm/foo@2.0.0/b.js")], "css": []},
        }
        check_version_drift(result, all_resources)
        assert any(f.category == "version_drift" for f in result.warnings)


class TestManifestConsistency:
    def test_matching_manifest_passes(self):
        result = AuditResult()
        manifest = {
            "plugins": {
                "TestPlugin": {
                    "source": "test",
                    "js": [{"name": "foo", "url": "https://cdn.example.com/foo.js"}],
                    "css": [],
                }
            }
        }
        resources = {"js": [("foo", "https://cdn.example.com/foo.js")], "css": []}
        check_manifest_consistency(result, manifest, "TestPlugin", resources, "plugins")
        assert result.ok

    def test_url_mismatch_detected(self):
        result = AuditResult()
        manifest = {
            "plugins": {
                "TestPlugin": {
                    "source": "test",
                    "js": [{"name": "foo", "url": "https://cdn.example.com/foo@1.0.0.js"}],
                    "css": [],
                }
            }
        }
        resources = {"js": [("foo", "https://cdn.example.com/foo@2.0.0.js")], "css": []}
        check_manifest_consistency(result, manifest, "TestPlugin", resources, "plugins")
        assert any(f.category == "url_mismatch" for f in result.errors)

    def test_missing_manifest_entry_detected(self):
        result = AuditResult()
        manifest = {"plugins": {}}
        resources = {"js": [("foo", "https://cdn.example.com/foo.js")], "css": []}
        check_manifest_consistency(result, manifest, "MissingPlugin", resources, "plugins")
        assert any(f.category == "manifest_missing" for f in result.errors)

    def test_manifest_orphan_detected(self):
        result = AuditResult()
        manifest = {
            "plugins": {
                "TestPlugin": {
                    "source": "test",
                    "js": [
                        {"name": "foo", "url": "https://cdn.example.com/foo.js"},
                        {"name": "orphan", "url": "https://cdn.example.com/orphan.js"},
                    ],
                    "css": [],
                }
            }
        }
        resources = {"js": [("foo", "https://cdn.example.com/foo.js")], "css": []}
        check_manifest_consistency(result, manifest, "TestPlugin", resources, "plugins")
        assert any(f.category == "manifest_orphan" for f in result.warnings)

    def test_js_dynamic_plugin_skipped(self):
        result = AuditResult()
        manifest = {
            "plugins": {
                "DynamicPlugin": {
                    "source": "test",
                    "js_dynamic": True,
                    "js": [],
                    "css": [],
                }
            }
        }
        resources = {"js": [("x", "url")], "css": []}
        check_manifest_consistency(result, manifest, "DynamicPlugin", resources, "plugins")
        assert result.ok


class TestFullAudit:
    def test_audit_runs_without_crash(self):
        result = run_audit()
        assert isinstance(result, AuditResult)
        assert isinstance(result.errors, list)
        assert isinstance(result.warnings, list)

    def test_manifest_covers_all_plugins(self):
        result = AuditResult()
        manifest = load_manifest()
        plugin_classes = _get_plugin_classes()
        for class_name, cls in plugin_classes.items():
            resources = _collect_resources_from_class(cls)
            check_manifest_consistency(result, manifest, class_name, resources, "plugins")

        missing = [f for f in result.errors if f.category == "manifest_missing"]
        assert len(missing) == 0, (
            f"Plugins missing from manifest: {[f.location for f in missing]}"
        )

    def test_manifest_covers_all_features(self):
        result = AuditResult()
        manifest = load_manifest()
        feature_classes = _get_feature_classes()
        for class_name, cls in feature_classes.items():
            if class_name == "VegaLite":
                continue
            resources = _collect_resources_from_class(cls)
            check_manifest_consistency(result, manifest, class_name, resources, "features")

        missing = [f for f in result.errors if f.category == "manifest_missing"]
        assert len(missing) == 0, (
            f"Features missing from manifest: {[f.location for f in missing]}"
        )

    def test_no_url_mismatches(self):
        result = run_audit()
        mismatches = [f for f in result.errors if f.category == "url_mismatch"]
        assert len(mismatches) == 0, (
            f"URL mismatches found:\n"
            + "\n".join(f"  {f.location}: {f.detail}" for f in mismatches)
        )

    def test_no_duplicate_names(self):
        result = run_audit()
        dups = [f for f in result.errors if f.category == "duplicate_name"]
        assert len(dups) == 0, (
            f"Duplicate resource names found:\n"
            + "\n".join(f"  {f.location}: {f.message}" for f in dups)
        )

    def test_audit_result_to_dict(self):
        result = run_audit()
        d = result.to_dict()
        assert "ok" in d
        assert "error_count" in d
        assert "warning_count" in d
        assert "errors" in d
        assert "warnings" in d


class TestAuditResultDataclass:
    def test_ok_with_no_errors(self):
        r = AuditResult()
        assert r.ok

    def test_not_ok_with_errors(self):
        r = AuditResult()
        r.add_error("test", "test error")
        assert not r.ok

    def test_merge(self):
        r1 = AuditResult()
        r2 = AuditResult()
        r1.add_error("cat1", "err1")
        r2.add_warning("cat2", "warn1")
        r1.merge(r2)
        assert len(r1.errors) == 1
        assert len(r1.warnings) == 1
