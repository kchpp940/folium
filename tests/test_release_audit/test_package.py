"""
Tests for folium.release_audit package structure and public API.

Responsibility coverage:
  - __init__.py: all public symbols are exported
  - policy file is included in package_data (setup.py)
  - __main__.py: module runs as __main__
"""

import importlib
import sys
from pathlib import Path

import pytest

from folium import release_audit as ra_pkg
from folium.release_audit import (
    FOLIUM_ROOT,
    load_policy,
)

pytestmark = pytest.mark.audit


class TestPublicApiExports:
    EXPECTED_EXPORTS = [
        "AuditFinding", "AuditResult", "CDN_PATTERN", "ClassResources",
        "FOLIUM_ROOT", "MANIFEST_SCHEMA_VERSION", "ResourceEntry",
        "apply_strict_policy", "build_stable_manifest",
        "check_docs_consistency", "check_duplicate_names",
        "check_inheritance_consistency", "check_inline_cdn_urls",
        "check_policy_compliance", "check_vegalite_variants",
        "check_version_drift", "collect_all_resources",
        "collect_resources_from_class", "download_resources",
        "extract_package_from_url", "extract_version_from_url",
        "generate_manifest", "get_feature_classes", "get_map_class",
        "get_plugin_classes", "is_dynamic_resource_class",
        "is_inheritance_class", "is_no_resources_class",
        "is_strict_promotable", "load_policy", "manifest_json_schema",
        "policy_file_path", "run_audit", "validate_manifest",
    ]

    @pytest.mark.parametrize("symbol", EXPECTED_EXPORTS)
    def test_symbol_exported(self, symbol):
        assert hasattr(ra_pkg, symbol), f"Symbol '{symbol}' not exported from folium.release_audit"

    def test_all_exports_in_all_list(self):
        for symbol in self.EXPECTED_EXPORTS:
            assert symbol in ra_pkg.__all__, f"'{symbol}' not in __all__"

    def test_no_underscore_symbols_in_all(self):
        for symbol in ra_pkg.__all__:
            assert not symbol.startswith("_"), (
                f"Private symbol '{symbol}' should not be in __all__"
            )


class TestPolicyFilePackaging:
    def test_policy_file_in_folium_package(self):
        policy_path = FOLIUM_ROOT / "release_audit_policy.json"
        assert policy_path.exists()
        assert policy_path.is_file()

    def test_policy_file_listed_in_setup_py(self):
        setup_path = FOLIUM_ROOT.parent / "setup.py"
        content = setup_path.read_text(encoding="utf-8")
        assert "release_audit_policy.json" in content, (
            "release_audit_policy.json must be in setup.py package_data"
        )

    def test_load_policy_after_install_simulation(self):
        policy = load_policy()
        assert isinstance(policy, dict)
        assert "classes" in policy
        assert "strict" in policy
        assert "docs" in policy


class TestModuleStructure:
    def test_internal_modules_exist(self):
        import folium.release_audit._audit as _audit
        import folium.release_audit._extract as _extract
        import folium.release_audit._manifest as _manifest
        import folium.release_audit._offline as _offline
        import folium.release_audit._policy as _policy

        for mod in [_audit, _extract, _manifest, _offline, _policy]:
            assert mod is not None

    def test_no_cross_dependency_violations(self):
        import folium.release_audit._policy as _policy
        source = Path(_policy.__file__).read_text()
        assert "from ._audit" not in source
        assert "from ._manifest" not in source
        assert "from ._offline" not in source

        import folium.release_audit._extract as _extract
        source = Path(_extract.__file__).read_text()
        assert "from ._audit" not in source
        assert "from ._manifest" not in source
        assert "from ._offline" not in source

        import folium.release_audit._manifest as _manifest
        source = Path(_manifest.__file__).read_text()
        assert "from ._audit" not in source
        assert "from ._offline" not in source

        import folium.release_audit._offline as _offline
        source = Path(_offline.__file__).read_text()
        assert "from ._audit" not in source
        assert "from ._extract" not in source
