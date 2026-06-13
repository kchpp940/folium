"""
Tests for the Folium Release Resource Audit tool (Policy-Driven Architecture).

Source of truth: plugin/feature Python source code (default_js/default_css).
Rules: release_audit_policy.json.

These tests validate that:
  1. Policy file loads and is structurally valid
  2. Resources are extracted correctly from source code
  3. Package name / version extraction works
  4. Duplicate name detection works
  5. Version drift detection works
  6. Policy compliance checks work (no_resources, inheritance)
  7. Inheritance consistency checks work
  8. VegaLite dynamic variant checks work
  9. Inline CDN URL detection works
  10. Manifest generation from source works
  11. Full audit run succeeds against current codebase
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from folium.release_audit import (
    AuditResult,
    ClassResources,
    FOLIUM_ROOT,
    ResourceEntry,
    _collect_resources_from_class,
    _extract_package_from_url,
    _extract_version_from_url,
    _get_feature_classes,
    _get_plugin_classes,
    _is_no_resources_class,
    _is_inheritance_class,
    _is_dynamic_resource_class,
    _is_strict_promotable,
    check_duplicate_names,
    check_inheritance_consistency,
    check_policy_compliance,
    check_version_drift,
    collect_all_resources,
    generate_manifest,
    load_policy,
    run_audit,
)

pytestmark = pytest.mark.audit


class TestPolicyLoading:
    def test_policy_file_exists(self):
        path = FOLIUM_ROOT / "release_audit_policy.json"
        assert path.exists(), "release_audit_policy.json must exist in folium package"

    def test_policy_is_valid_json(self):
        data = load_policy()
        assert isinstance(data, dict)

    def test_policy_has_required_sections(self):
        data = load_policy()
        assert "classes" in data
        assert "docs" in data
        assert "strict" in data
        assert "version_drift" in data

    def test_policy_classes_structure(self):
        data = load_policy()
        classes = data["classes"]
        for key in ["no_resources_expected", "inherit_resources_from", "dynamic_resource_classes", "ignore_inline_cdn_locations"]:
            assert key in classes, f"Policy missing 'classes.{key}'"
            assert isinstance(classes[key], list)

    def test_policy_no_resources_entries_have_reason(self):
        data = load_policy()
        for entry in data["classes"]["no_resources_expected"]:
            assert "class_name" in entry
            assert "reason" in entry

    def test_policy_inheritance_entries_have_parent(self):
        data = load_policy()
        for entry in data["classes"]["inherit_resources_from"]:
            assert "class_name" in entry
            assert "parent_class" in entry

    def test_policy_strict_structure(self):
        data = load_policy()
        strict = data["strict"]
        assert "promote_warnings_to_errors" in strict
        assert "never_promote" in strict

    def test_policy_docs_structure(self):
        data = load_policy()
        docs = data["docs"]
        assert "check_docs" in docs
        assert "allowed_extra_url_patterns" in docs


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
        assert isinstance(resources, ClassResources)
        assert resources.class_name == "Map"
        assert len(resources.js) > 0
        assert len(resources.css) > 0
        assert resources.is_jscssmixin_subclass is True
        assert resources.declared_on_class is True

    def test_collect_resources_from_plugin(self):
        from folium.plugins.draw import Draw

        resources = _collect_resources_from_class(Draw)
        assert len(resources.js) > 0
        assert len(resources.css) > 0
        assert all(isinstance(r, ResourceEntry) for r in resources.js)
        assert all(isinstance(r, ResourceEntry) for r in resources.css)

    def test_collect_resources_tracks_inheritance(self):
        from folium.plugins.fast_marker_cluster import FastMarkerCluster

        resources = _collect_resources_from_class(FastMarkerCluster)
        assert resources.inherited_from is not None
        assert resources.inherited_from == "MarkerCluster"
        assert resources.declared_on_class is False
        assert len(resources.js) > 0

    def test_collect_all_resources_returns_expected_classes(self):
        all_res = collect_all_resources()
        assert "Map" in all_res
        assert "MarkerCluster" in all_res
        assert "FastMarkerCluster" in all_res
        assert len(all_res) > 30

    def test_all_plugin_classes_are_collected(self):
        all_res = collect_all_resources()
        plugin_classes = _get_plugin_classes()
        for name in plugin_classes:
            assert name in all_res, f"Plugin {name} not collected"

    def test_all_feature_classes_are_collected(self):
        all_res = collect_all_resources()
        feature_classes = _get_feature_classes()
        for name in feature_classes:
            assert name in all_res, f"Feature {name} not collected"

    def test_no_resources_classes_flagged_correctly(self):
        policy = load_policy()
        for entry in policy["classes"]["no_resources_expected"]:
            class_name = entry["class_name"]
            is_no_res, _ = _is_no_resources_class(policy, class_name)
            assert is_no_res, f"{class_name} should be marked as no_resources_expected"

    def test_inheritance_classes_flagged_correctly(self):
        policy = load_policy()
        for entry in policy["classes"]["inherit_resources_from"]:
            class_name = entry["class_name"]
            is_inherit, inherit_entry = _is_inheritance_class(policy, class_name)
            assert is_inherit, f"{class_name} should be marked as inheritance class"
            assert inherit_entry["parent_class"] == entry["parent_class"]

    def test_dynamic_classes_flagged_correctly(self):
        policy = load_policy()
        is_dynamic, cfg = _is_dynamic_resource_class(policy, "VegaLite")
        assert is_dynamic
        assert cfg["method_prefix"] == "_embed_vegalite_v"

    def test_strict_promotable_rules(self):
        policy = load_policy()
        for category in policy["strict"]["promote_warnings_to_errors"]:
            assert _is_strict_promotable(policy, category) is True
        for category in policy["strict"]["never_promote"]:
            assert _is_strict_promotable(policy, category) is False
        assert _is_strict_promotable(policy, "duplicate_name") is False


class TestDuplicateNameDetection:
    def test_no_duplicates_passes(self):
        result = AuditResult()
        resources = ClassResources(
            class_name="Test",
            module="test",
            js=[ResourceEntry("a", "url1"), ResourceEntry("b", "url2")],
            css=[],
            declared_on_class=True,
            is_jscssmixin_subclass=True,
        )
        check_duplicate_names(result, resources)
        assert result.ok
        assert len(result.errors) == 0

    def test_duplicate_name_detected(self):
        result = AuditResult()
        resources = ClassResources(
            class_name="Test",
            module="test",
            js=[ResourceEntry("dup", "url1"), ResourceEntry("dup", "url2")],
            css=[],
            declared_on_class=True,
            is_jscssmixin_subclass=True,
        )
        check_duplicate_names(result, resources)
        assert not result.ok
        assert any(f.category == "duplicate_name" for f in result.errors)

    def test_no_duplicates_in_current_codebase(self):
        result = run_audit()
        dups = [f for f in result.errors if f.category == "duplicate_name"]
        assert len(dups) == 0, (
            f"Duplicate resource names found:\n"
            + "\n".join(f"  {f.location}: {f.detail}" for f in dups)
        )


class TestVersionDriftDetection:
    def test_no_drift_passes(self):
        result = AuditResult()
        policy = {
            "version_drift": {
                "enabled": True,
                "allowed_multi_version_packages": [],
                "allow_unversioned_packages": True,
                "unversioned_warning": True,
            }
        }
        all_res = {
            "A": ClassResources(
                class_name="A", module="a",
                js=[ResourceEntry("x", "https://cdn.jsdelivr.net/npm/foo@1.0.0/a.js")],
                css=[], declared_on_class=True, is_jscssmixin_subclass=True,
            ),
            "B": ClassResources(
                class_name="B", module="b",
                js=[ResourceEntry("y", "https://cdn.jsdelivr.net/npm/foo@1.0.0/b.js")],
                css=[], declared_on_class=True, is_jscssmixin_subclass=True,
            ),
        }
        check_version_drift(result, all_res, policy)
        assert len(result.warnings) == 0

    def test_version_drift_detected(self):
        result = AuditResult()
        policy = {
            "version_drift": {
                "enabled": True,
                "allowed_multi_version_packages": [],
                "allow_unversioned_packages": True,
                "unversioned_warning": True,
            }
        }
        all_res = {
            "A": ClassResources(
                class_name="A", module="a",
                js=[ResourceEntry("x", "https://cdn.jsdelivr.net/npm/foo@1.0.0/a.js")],
                css=[], declared_on_class=True, is_jscssmixin_subclass=True,
            ),
            "B": ClassResources(
                class_name="B", module="b",
                js=[ResourceEntry("y", "https://cdn.jsdelivr.net/npm/foo@2.0.0/b.js")],
                css=[], declared_on_class=True, is_jscssmixin_subclass=True,
            ),
        }
        check_version_drift(result, all_res, policy)
        assert any(f.category == "version_drift" for f in result.warnings)

    def test_allowed_multi_version_skipped(self):
        result = AuditResult()
        policy = {
            "version_drift": {
                "enabled": True,
                "allowed_multi_version_packages": ["foo"],
                "allow_unversioned_packages": True,
                "unversioned_warning": True,
            }
        }
        all_res = {
            "A": ClassResources(
                class_name="A", module="a",
                js=[ResourceEntry("x", "https://cdn.jsdelivr.net/npm/foo@1.0.0/a.js")],
                css=[], declared_on_class=True, is_jscssmixin_subclass=True,
            ),
            "B": ClassResources(
                class_name="B", module="b",
                js=[ResourceEntry("y", "https://cdn.jsdelivr.net/npm/foo@2.0.0/b.js")],
                css=[], declared_on_class=True, is_jscssmixin_subclass=True,
            ),
        }
        check_version_drift(result, all_res, policy)
        assert len(result.warnings) == 0

    def test_version_drift_disabled(self):
        result = AuditResult()
        policy = {"version_drift": {"enabled": False}}
        all_res = {
            "A": ClassResources(
                class_name="A", module="a",
                js=[ResourceEntry("x", "https://cdn.jsdelivr.net/npm/foo@1.0.0/a.js")],
                css=[], declared_on_class=True, is_jscssmixin_subclass=True,
            ),
        }
        check_version_drift(result, all_res, policy)
        assert len(result.warnings) == 0
        assert len(result.errors) == 0


class TestPolicyCompliance:
    def test_no_resources_class_with_resources_flagged(self):
        result = AuditResult()
        policy = {
            "classes": {
                "no_resources_expected": [
                    {"class_name": "EmptyClass", "reason": "test"}
                ],
                "inherit_resources_from": [],
                "dynamic_resource_classes": [],
                "ignore_inline_cdn_locations": [],
            }
        }
        all_res = {
            "EmptyClass": ClassResources(
                class_name="EmptyClass", module="test",
                js=[ResourceEntry("x", "url")], css=[],
                declared_on_class=True, is_jscssmixin_subclass=True,
            ),
        }
        check_policy_compliance(result, all_res, policy)
        assert any(f.category == "policy_violation" for f in result.warnings)

    def test_jscssmixin_without_resources_not_in_policy_flagged(self):
        result = AuditResult()
        policy = {
            "classes": {
                "no_resources_expected": [],
                "inherit_resources_from": [],
                "dynamic_resource_classes": [],
                "ignore_inline_cdn_locations": [],
            }
        }
        all_res = {
            "NeedsPolicy": ClassResources(
                class_name="NeedsPolicy", module="test",
                js=[], css=[],
                declared_on_class=False, is_jscssmixin_subclass=True,
            ),
        }
        check_policy_compliance(result, all_res, policy)
        assert any(f.category == "policy_violation" for f in result.warnings)

    def test_inheritance_mismatch_flagged(self):
        result = AuditResult()
        policy = {
            "classes": {
                "no_resources_expected": [],
                "inherit_resources_from": [
                    {"class_name": "Child", "parent_class": "ExpectedParent", "reason": "test"}
                ],
                "dynamic_resource_classes": [],
                "ignore_inline_cdn_locations": [],
            }
        }
        all_res = {
            "Child": ClassResources(
                class_name="Child", module="test",
                js=[], css=[],
                declared_on_class=False, is_jscssmixin_subclass=True,
                inherited_from="ActualParent",
            ),
            "ExpectedParent": ClassResources(
                class_name="ExpectedParent", module="test",
                js=[], css=[],
                declared_on_class=False, is_jscssmixin_subclass=True,
            ),
            "ActualParent": ClassResources(
                class_name="ActualParent", module="test",
                js=[], css=[],
                declared_on_class=False, is_jscssmixin_subclass=True,
            ),
        }
        check_policy_compliance(result, all_res, policy)
        assert any(f.category == "inheritance_mismatch" for f in result.warnings)

    def test_current_codebase_policy_compliance(self):
        result = run_audit()
        violations = [f for f in result.warnings if f.category == "policy_violation"]
        assert len(violations) == 0, (
            f"Policy violations found:\n"
            + "\n".join(f"  {f.location}: {f.message}" for f in violations)
        )


class TestInheritanceConsistency:
    def test_child_with_matching_resources_passes(self):
        result = AuditResult()
        policy = {
            "classes": {
                "no_resources_expected": [],
                "inherit_resources_from": [
                    {"class_name": "Child", "parent_class": "Parent", "reason": "test"}
                ],
                "dynamic_resource_classes": [],
                "ignore_inline_cdn_locations": [],
            }
        }
        all_res = {
            "Parent": ClassResources(
                class_name="Parent", module="test",
                js=[ResourceEntry("x", "https://cdn.jsdelivr.net/npm/foo@1.0.0/a.js")],
                css=[ResourceEntry("y", "https://cdn.jsdelivr.net/npm/foo@1.0.0/a.css")],
                declared_on_class=True, is_jscssmixin_subclass=True,
            ),
            "Child": ClassResources(
                class_name="Child", module="test",
                js=[ResourceEntry("x", "https://cdn.jsdelivr.net/npm/foo@1.0.0/a.js")],
                css=[ResourceEntry("y", "https://cdn.jsdelivr.net/npm/foo@1.0.0/a.css")],
                declared_on_class=True, is_jscssmixin_subclass=True,
            ),
        }
        check_inheritance_consistency(result, all_res, policy)
        assert len(result.warnings) == 0

    def test_child_with_different_resources_flagged(self):
        result = AuditResult()
        policy = {
            "classes": {
                "no_resources_expected": [],
                "inherit_resources_from": [
                    {"class_name": "Child", "parent_class": "Parent", "reason": "test"}
                ],
                "dynamic_resource_classes": [],
                "ignore_inline_cdn_locations": [],
            }
        }
        all_res = {
            "Parent": ClassResources(
                class_name="Parent", module="test",
                js=[ResourceEntry("x", "https://cdn.jsdelivr.net/npm/foo@1.0.0/a.js")],
                css=[],
                declared_on_class=True, is_jscssmixin_subclass=True,
            ),
            "Child": ClassResources(
                class_name="Child", module="test",
                js=[ResourceEntry("x", "https://cdn.jsdelivr.net/npm/foo@2.0.0/a.js")],
                css=[],
                declared_on_class=True, is_jscssmixin_subclass=True,
            ),
        }
        check_inheritance_consistency(result, all_res, policy)
        assert any(f.category == "inheritance_resource_mismatch" for f in result.warnings)

    def test_current_codebase_inheritance_consistency(self):
        result = run_audit()
        mismatches = [f for f in result.warnings if f.category == "inheritance_resource_mismatch"]
        assert len(mismatches) == 0, (
            f"Inheritance resource mismatches found:\n"
            + "\n".join(f"  {f.location}: {f.detail}" for f in mismatches)
        )


class TestManifestGeneration:
    def test_generate_manifest_returns_json(self):
        all_res = collect_all_resources()
        manifest_str = generate_manifest(all_res, pretty=False)
        data = json.loads(manifest_str)
        assert "_generated" in data
        assert "_generated_at" in data
        assert "map_defaults" in data
        assert "features" in data
        assert "plugins" in data

    def test_generate_manifest_includes_map_defaults(self):
        all_res = collect_all_resources()
        manifest_str = generate_manifest(all_res, pretty=False)
        data = json.loads(manifest_str)
        assert "js" in data["map_defaults"]
        assert "css" in data["map_defaults"]
        assert len(data["map_defaults"]["js"]) > 0

    def test_generate_manifest_includes_plugins(self):
        all_res = collect_all_resources()
        manifest_str = generate_manifest(all_res, pretty=False)
        data = json.loads(manifest_str)
        assert len(data["plugins"]) > 30
        assert "MarkerCluster" in data["plugins"]
        assert "Draw" in data["plugins"]

    def test_generate_manifest_marks_inherited_resources(self):
        all_res = collect_all_resources()
        manifest_str = generate_manifest(all_res, pretty=False)
        data = json.loads(manifest_str)
        assert data["plugins"]["FastMarkerCluster"].get("inherited") is True
        assert data["plugins"]["FastMarkerCluster"].get("inherited_from") == "MarkerCluster"

    def test_generate_manifest_pretty_format(self):
        all_res = collect_all_resources()
        pretty_str = generate_manifest(all_res, pretty=True)
        assert "\n" in pretty_str
        assert "  " in pretty_str


class TestFullAudit:
    def test_audit_runs_without_crash(self):
        result = run_audit()
        assert isinstance(result, AuditResult)
        assert isinstance(result.errors, list)
        assert isinstance(result.warnings, list)

    def test_audit_result_to_dict(self):
        result = run_audit()
        d = result.to_dict()
        assert "ok" in d
        assert "error_count" in d
        assert "warning_count" in d
        assert "errors" in d
        assert "warnings" in d

    def test_no_blocking_errors_in_current_codebase(self):
        result = run_audit()
        assert result.ok, (
            f"Blocking errors found:\n"
            + "\n".join(f"  [{f.category}] {f.location}: {f.message}" for f in result.errors)
        )

    def test_vegalite_variants_all_present(self):
        result = run_audit()
        missing = [f for f in result.errors if f.category == "vegalite_variant_missing"]
        assert len(missing) == 0, (
            f"Missing VegaLite variants:\n"
            + "\n".join(f"  {f.location}" for f in missing)
        )

    def test_strict_mode_promotes_warnings(self):
        policy = load_policy()
        result_normal = run_audit(strict=False)
        result_strict = run_audit(strict=True)

        promotable_cats = set(policy["strict"]["promote_warnings_to_errors"])
        never_cats = set(policy["strict"]["never_promote"])

        for f in result_normal.warnings:
            if f.category in promotable_cats and f.category not in never_cats:
                promoted = any(
                    e.category == f.category and e.message == f.message
                    for e in result_strict.errors
                )
                assert promoted, f"Warning '{f.category}' should be promoted in strict mode"
