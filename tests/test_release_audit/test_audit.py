"""
Tests for folium.release_audit._audit module.

Responsibility coverage:
  - check_duplicate_names
  - check_version_drift
  - check_policy_compliance
  - check_inheritance_consistency
  - check_vegalite_variants
  - check_docs_consistency
  - check_inline_cdn_urls
  - apply_strict_policy
  - run_audit (integration)
"""

import pytest

from folium.release_audit import (
    AuditResult,
    ClassResources,
    ResourceEntry,
    check_duplicate_names,
    check_inheritance_consistency,
    check_policy_compliance,
    check_version_drift,
    load_policy,
    run_audit,
)

pytestmark = pytest.mark.audit


class TestDuplicateNameCheck:
    def test_no_duplicates_passes(self):
        result = AuditResult()
        resources = ClassResources(
            class_name="Test", module="test",
            js=[ResourceEntry("a", "url1"), ResourceEntry("b", "url2")],
            css=[], declared_on_class=True, is_jscssmixin_subclass=True,
        )
        check_duplicate_names(result, resources)
        assert result.ok
        assert len(result.errors) == 0

    def test_duplicate_name_detected_as_error(self):
        result = AuditResult()
        resources = ClassResources(
            class_name="Test", module="test",
            js=[ResourceEntry("dup", "url1"), ResourceEntry("dup", "url2")],
            css=[], declared_on_class=True, is_jscssmixin_subclass=True,
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


class TestVersionDriftCheck:
    def test_no_drift_passes(self):
        result = AuditResult()
        policy = {
            "version_drift": {
                "enabled": True, "allowed_multi_version_packages": [],
                "allow_unversioned_packages": True, "unversioned_warning": True,
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

    def test_version_drift_detected_as_warning(self):
        result = AuditResult()
        policy = {
            "version_drift": {
                "enabled": True, "allowed_multi_version_packages": [],
                "allow_unversioned_packages": True, "unversioned_warning": True,
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
                "enabled": True, "allowed_multi_version_packages": ["foo"],
                "allow_unversioned_packages": True, "unversioned_warning": True,
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

    def test_current_codebase_no_policy_violations(self):
        result = run_audit()
        violations = [f for f in result.warnings if f.category == "policy_violation"]
        assert len(violations) == 0, (
            f"Policy violations found:\n"
            + "\n".join(f"  {f.location}: {f.message}" for f in violations)
        )


class TestInheritanceConsistency:
    def test_child_matching_parent_passes(self):
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

    def test_child_different_resources_flagged(self):
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
                css=[], declared_on_class=True, is_jscssmixin_subclass=True,
            ),
            "Child": ClassResources(
                class_name="Child", module="test",
                js=[ResourceEntry("x", "https://cdn.jsdelivr.net/npm/foo@2.0.0/a.js")],
                css=[], declared_on_class=True, is_jscssmixin_subclass=True,
            ),
        }
        check_inheritance_consistency(result, all_res, policy)
        assert any(f.category == "inheritance_resource_mismatch" for f in result.warnings)

    def test_current_codebase_inheritance_ok(self):
        result = run_audit()
        mismatches = [f for f in result.warnings if f.category == "inheritance_resource_mismatch"]
        assert len(mismatches) == 0


class TestFullAuditIntegration:
    def test_audit_runs_without_crash(self):
        result = run_audit()
        assert isinstance(result, AuditResult)
        assert isinstance(result.errors, list)
        assert isinstance(result.warnings, list)

    def test_audit_result_to_dict(self):
        result = run_audit()
        d = result.to_dict()
        assert "ok" in d and "error_count" in d and "warning_count" in d

    def test_no_blocking_errors_in_current_codebase(self):
        result = run_audit()
        assert result.ok, (
            f"Blocking errors found:\n"
            + "\n".join(f"  [{f.category}] {f.location}: {f.message}" for f in result.errors)
        )

    def test_vegalite_variants_present(self):
        result = run_audit()
        missing = [f for f in result.errors if f.category == "vegalite_variant_missing"]
        assert len(missing) == 0

    def test_strict_mode_promotes_warnings(self):
        from folium.release_audit._audit import apply_strict_policy
        policy = load_policy()
        result_normal = run_audit(strict=False)
        result_strict = run_audit(strict=True)

        from folium.release_audit import is_strict_promotable
        for f in result_normal.warnings:
            if is_strict_promotable(policy, f.category):
                promoted = any(
                    e.category == f.category and e.message == f.message
                    for e in result_strict.errors
                )
                assert promoted, f"Warning '{f.category}' should be promoted in strict mode"
