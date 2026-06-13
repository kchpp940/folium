"""
Tests for the Folium Public API Boundary Audit.

These tests validate that:
  1. Every audited module defines __all__
  2. All names in __all__ are importable from the module
  3. Public names (classes / functions defined in the module) that are
     not in __all__ are flagged as potential API leaks
  4. Names declared internal in api_policy.INTERNAL_NAMES must not
     appear in any module's __all__
  5. Modules in api_policy.INIT_REEXPORT_MODULES must have their
     public names re-exported through folium.__init__
  6. __all__ lists contain no duplicates
  7. The policy file (api_policy) and audit implementation (api_audit)
     are decoupled — policy contains only data, audit contains only logic
  8. Specific boundary assertions (e.g. folium.map does not export
     Evented / Layer; new ImageOverlay / VideoOverlay / CustomPane
     are importable from top-level folium)
"""

from __future__ import annotations

import pytest

from folium.api_audit import (
    AuditResult,
    check_all_defined,
    check_all_names_importable,
    check_all_sorted_and_unique,
    check_compat_aliases_exist,
    check_experimental_names_tracked,
    check_init_all_superset,
    check_internal_not_in_all,
    check_no_extra_public_names,
    run_api_audit,
)
from folium.api_policy import (
    AUDITED_MODULES,
    COMPAT_ALIASES,
    EXPERIMENTAL_NAMES,
    INIT_REEXPORT_MODULES,
    INTERNAL_NAMES,
)


pytestmark = pytest.mark.audit


class TestApiPolicyStructure:
    def test_policy_contains_only_data(self):
        import types

        import folium.api_policy as policy

        for name in dir(policy):
            if name.startswith("_"):
                continue
            obj = getattr(policy, name)
            assert not isinstance(obj, types.FunctionType), (
                f"api_policy should be data-only, found function: {name}"
            )
            assert not isinstance(obj, type), (
                f"api_policy should be data-only, found class: {name}"
            )

    def test_policy_sections_are_sets_or_dicts(self):
        assert isinstance(AUDITED_MODULES, set)
        assert isinstance(INIT_REEXPORT_MODULES, set)
        assert isinstance(INTERNAL_NAMES, dict)
        assert isinstance(COMPAT_ALIASES, dict)
        assert isinstance(EXPERIMENTAL_NAMES, dict)

    def test_init_reexport_is_subset_of_audited(self):
        assert INIT_REEXPORT_MODULES <= AUDITED_MODULES

    def test_internal_names_keys_are_in_audited(self):
        for mod_name in INTERNAL_NAMES:
            assert mod_name in AUDITED_MODULES, (
                f"INTERNAL_NAMES key '{mod_name}' not in AUDITED_MODULES"
            )

    def test_compat_aliases_keys_are_in_audited(self):
        for mod_name in COMPAT_ALIASES:
            assert mod_name in AUDITED_MODULES, (
                f"COMPAT_ALIASES key '{mod_name}' not in AUDITED_MODULES"
            )

    def test_experimental_names_keys_are_in_audited(self):
        for mod_name in EXPERIMENTAL_NAMES:
            assert mod_name in AUDITED_MODULES, (
                f"EXPERIMENTAL_NAMES key '{mod_name}' not in AUDITED_MODULES"
            )

    def test_audited_modules_covers_key_modules(self):
        assert "folium" in AUDITED_MODULES
        assert "folium.map" in AUDITED_MODULES
        assert "folium.features" in AUDITED_MODULES
        assert "folium.raster_layers" in AUDITED_MODULES
        assert "folium.vector_layers" in AUDITED_MODULES
        assert "folium.plugins" in AUDITED_MODULES


class TestApiAuditAllDefined:
    def test_all_audited_modules_have_all(self):
        result = AuditResult()
        check_all_defined(result)
        assert result.ok, (
            "Modules missing __all__:\n"
            + "\n".join(f"  {f.location}: {f.message}" for f in result.errors)
        )


class TestApiAuditAllImportable:
    def test_all_names_are_importable(self):
        result = AuditResult()
        check_all_names_importable(result)
        assert result.ok, (
            "Names in __all__ not found in module:\n"
            + "\n".join(f"  {f.location}: {f.detail}" for f in result.errors)
        )


class TestApiAuditNoExtraPublicNames:
    def test_no_unlisted_public_names(self):
        result = AuditResult()
        check_no_extra_public_names(result)
        for f in result.warnings:
            if f.category == "name_not_in_all":
                pytest.fail(
                    f"Public name(s) not in __all__ in {f.location}: {f.detail}"
                )


class TestApiAuditInitSuperset:
    def test_init_all_covers_submodule_public_names(self):
        result = AuditResult()
        check_init_all_superset(result)
        uncovered = [
            f for f in result.warnings if f.category == "module_public_not_in_init"
        ]
        assert len(uncovered) == 0, (
            "Public submodule names not in folium.__init__:\n"
            + "\n".join(f"  {f.location}" for f in uncovered)
        )


class TestApiAuditInternalNotInAll:
    def test_internal_names_not_in_all(self):
        result = AuditResult()
        check_internal_not_in_all(result)
        assert result.ok, (
            "Internal names leaked into __all__:\n"
            + "\n".join(f"  {f.location}: {f.detail}" for f in result.errors)
        )


class TestApiAuditNoDuplicates:
    def test_all_lists_have_no_duplicates(self):
        result = AuditResult()
        check_all_sorted_and_unique(result)
        assert result.ok, (
            "__all__ contains duplicates:\n"
            + "\n".join(f"  {f.location}: {f.detail}" for f in result.errors)
        )


class TestApiAuditCompatAliases:
    def test_compat_aliases_are_tracked(self):
        result = AuditResult()
        check_compat_aliases_exist(result)
        assert result.ok, (
            "Compatibility alias issues:\n"
            + "\n".join(f"  {f.location}: {f.message}" for f in result.errors)
        )


class TestApiAuditExperimental:
    def test_experimental_names_are_tracked(self):
        result = AuditResult()
        check_experimental_names_tracked(result)
        assert result.ok, (
            "Experimental name issues:\n"
            + "\n".join(f"  {f.location}: {f.message}" for f in result.errors)
        )


class TestApiAuditFullRun:
    def test_api_audit_runs_without_crash(self):
        result = run_api_audit()
        assert isinstance(result, AuditResult)

    def test_api_audit_no_errors(self):
        result = run_api_audit()
        assert result.ok, (
            "API audit found errors:\n"
            + "\n".join(
                f"  [{f.severity}] {f.category}: {f.message} ({f.location})"
                for f in result.errors
            )
        )

    def test_audit_result_to_dict(self):
        result = run_api_audit()
        d = result.to_dict()
        assert "ok" in d
        assert "error_count" in d
        assert "warning_count" in d
        assert "errors" in d
        assert "warnings" in d


class TestApiBoundarySpecific:
    def test_features_excludes_internal(self):
        import folium.features as features

        assert "GeoJsonStyleMapper" not in features.__all__
        assert "GeoJsonDetail" not in features.__all__

    def test_map_excludes_internal(self):
        import folium.map as map_mod

        assert "classproperty" not in map_mod.__all__
        assert "Class" not in map_mod.__all__
        assert "Evented" not in map_mod.__all__
        assert "Layer" not in map_mod.__all__

    def test_vector_layers_excludes_internal(self):
        import folium.vector_layers as vl

        assert "path_options" not in vl.__all__
        assert "BaseMultiLocation" not in vl.__all__

    def test_elements_has_empty_all(self):
        import folium.elements as elements

        assert elements.__all__ == []

    def test_folium_init_includes_new_exports(self):
        import folium

        assert "ImageOverlay" in folium.__all__
        assert "VideoOverlay" in folium.__all__
        assert "CustomPane" in folium.__all__

    def test_folium_init_new_exports_importable(self):
        from folium import CustomPane, ImageOverlay, VideoOverlay

        assert CustomPane is not None
        assert ImageOverlay is not None
        assert VideoOverlay is not None

    def test_api_policy_not_in_folium_init(self):
        import folium

        assert not hasattr(folium, "api_policy") or "api_policy" not in folium.__all__

    def test_api_audit_not_in_folium_init(self):
        import folium

        assert not hasattr(folium, "api_audit") or "api_audit" not in folium.__all__


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
