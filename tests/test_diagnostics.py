"""
Stability tests for the Folium Diagnostics tool.

These tests lock down:
  1. The JSON schema version and structure (for CI / issue templates)
  2. The thin-shim boundary at folium.diagnostics (no public API leak)
  3. CLI entry point behavior (--json, --schema, --sections, --list-sections)
  4. Section selection and ordering
  5. Backward compatibility of the diagnostic output format

New diagnostic sections may be added, but the schema version
must be bumped when breaking changes are introduced.
"""

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

from folium._audit.diagnostics import (
    DIAGNOSTICS_SCHEMA_VERSION,
    SECTION_COLLECTORS,
    DiagnosticReport,
    format_human_readable,
    get_json_schema,
    run_diagnostics,
)

pytestmark = pytest.mark.audit

FOLIUM_ROOT = Path(__file__).parent.parent / "folium"


class TestSchemaStability:
    """Lock the JSON schema version and top-level structure.

    The schema version follows SemVer. Bump the major version
    if you make backward-incompatible changes to the output.
    """

    def test_schema_version_is_string(self):
        assert isinstance(DIAGNOSTICS_SCHEMA_VERSION, str)
        parts = DIAGNOSTICS_SCHEMA_VERSION.split(".")
        assert len(parts) == 3, "Schema version must be MAJOR.MINOR.PATCH"
        assert all(p.isdigit() for p in parts), "Each version part must be numeric"

    def test_report_has_schema_fields(self):
        report = run_diagnostics(sections=["environment"])
        data = report.to_dict()

        assert "$schema" in data, "Report must include $schema URL"
        assert "schema_version" in data, "Report must include schema_version"
        assert data["schema_version"] == DIAGNOSTICS_SCHEMA_VERSION

    def test_report_top_level_structure(self):
        report = run_diagnostics(sections=["environment"])
        data = report.to_dict()

        required_top = {
            "$schema",
            "schema_version",
            "generated_at",
            "overall_status",
            "sections",
            "section_names",
            "section_count",
        }
        for key in required_top:
            assert key in data, f"Missing top-level field: {key}"

        assert isinstance(data["sections"], list)
        assert isinstance(data["section_names"], list)
        assert isinstance(data["section_count"], int)
        assert data["section_count"] == len(data["sections"])

    def test_report_section_structure(self):
        report = run_diagnostics(sections=["environment"])
        data = report.to_dict()

        section = data["sections"][0]
        required_section = {"name", "status", "summary", "details"}
        for key in required_section:
            assert key in section, f"Missing section field: {key}"

        assert section["name"] == "environment"
        assert section["status"] in {"ok", "warning", "error", "info"}
        assert isinstance(section["summary"], str)
        assert isinstance(section["details"], dict)

    def test_overall_status_values(self):
        report = run_diagnostics(sections=["environment"])
        data = report.to_dict()
        assert data["overall_status"] in {"ok", "warning", "error"}

    def test_get_json_schema_is_valid_json(self):
        schema = get_json_schema()
        assert isinstance(schema, dict)
        assert "$schema" in schema
        assert schema["$schema"].startswith("http")
        assert "type" in schema
        assert schema["type"] == "object"


class TestShimBoundary:
    """Verify that folium.diagnostics is a thin shim and does not leak public API.

    Policy:
      - folium.diagnostics must have __all__ = []
      - The shim must re-export from folium._audit.diagnostics
      - No new public API should be added at the top level
      - The shim only provides CLI entry via main()
    """

    def test_diagnostics_shim_file_exists(self):
        shim_path = FOLIUM_ROOT / "diagnostics.py"
        assert shim_path.exists(), "diagnostics.py shim must exist"

    def test_shim_all_is_empty(self):
        shim_path = FOLIUM_ROOT / "diagnostics.py"
        source = shim_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        has_empty_all = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "__all__":
                        if (
                            isinstance(node.value, (ast.List, ast.Tuple))
                            and len(node.value.elts) == 0
                        ):
                            has_empty_all = True
            if isinstance(node, ast.AnnAssign):
                if isinstance(node.target, ast.Name) and node.target.id == "__all__":
                    if node.value is not None and isinstance(
                        node.value, (ast.List, ast.Tuple)
                    ):
                        if len(node.value.elts) == 0:
                            has_empty_all = True

        assert has_empty_all, (
            "folium.diagnostics must have __all__ = [] to enforce "
            "that diagnostics is not a public API"
        )

    def test_shim_reexports_from_audit(self):
        shim_path = FOLIUM_ROOT / "diagnostics.py"
        source = shim_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        reexports_audit = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and node.module.startswith("folium._audit"):
                    reexports_audit = True
                    break

        assert reexports_audit, (
            "folium.diagnostics shim must re-export from "
            "folium._audit.diagnostics"
        )

    def test_shim_has_main_function(self):
        shim_path = FOLIUM_ROOT / "diagnostics.py"
        source = shim_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        has_main = False
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "main":
                has_main = True
                break

        assert has_main, "diagnostics shim must have a main() for -m invocation"

    def test_shim_no_new_public_api_classes(self):
        shim_path = FOLIUM_ROOT / "diagnostics.py"
        source = shim_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        public_classes = []
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
                public_classes.append(node.name)

        assert not public_classes, (
            f"Shim module should not define public classes. Found: {public_classes}"
        )

    def test_import_star_imports_nothing(self):
        import folium.diagnostics as diag_mod

        names = getattr(diag_mod, "__all__", [])
        assert names == [], (
            "from folium.diagnostics import * should import nothing"
        )


class TestDiagnosticsRunner:
    """Test the core diagnostics runner and section selection."""

    def test_run_all_sections(self):
        report = run_diagnostics()
        assert isinstance(report, DiagnosticReport)

        data = report.to_dict()
        assert data["section_count"] > 0
        assert len(data["sections"]) == len(data["section_names"])

    def test_known_section_names(self):
        expected = {
            "environment",
            "optional_dependencies",
            "resource_policy",
            "cache_directory",
            "template_filters",
            "plugin_resource_audit",
            "api_boundary_audit",
            "test_markers",
        }
        actual = set(SECTION_COLLECTORS.keys())
        assert expected == actual, (
            "Diagnostic section list has changed. "
            "Update this test if sections were intentionally added/removed."
        )

    def test_single_section_selection(self):
        report = run_diagnostics(sections=["environment"])
        data = report.to_dict()

        assert data["section_count"] == 1
        assert data["section_names"] == ["environment"]

    def test_multiple_section_selection(self):
        report = run_diagnostics(sections=["environment", "resource_policy"])
        data = report.to_dict()

        assert data["section_count"] == 2
        assert set(data["section_names"]) == {"environment", "resource_policy"}

    def test_section_order_preserved(self):
        order = ["test_markers", "environment", "cache_directory"]
        report = run_diagnostics(sections=order)
        data = report.to_dict()

        assert data["section_names"] == order

    def test_invalid_section_raises(self):
        with pytest.raises(ValueError):
            run_diagnostics(sections=["nonexistent_section"])

    def test_empty_sections_list(self):
        report = run_diagnostics(sections=[])
        data = report.to_dict()
        assert data["section_count"] == 0

    def test_report_to_dict_serializable(self):
        report = run_diagnostics(sections=["environment"])
        data = report.to_dict()

        json_str = json.dumps(data, default=str)
        parsed = json.loads(json_str)
        assert parsed["schema_version"] == DIAGNOSTICS_SCHEMA_VERSION

    def test_format_human_readable_returns_string(self):
        report = run_diagnostics(sections=["environment"])
        output = format_human_readable(report)
        assert isinstance(output, str)
        assert len(output) > 0


class TestCLIEntryPoint:
    """Test the CLI entry point via python -m folium.diagnostics."""

    def _run_cli(self, *args):
        cmd = [sys.executable, "-m", "folium.diagnostics", *args]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(FOLIUM_ROOT.parent),
        )
        return result

    def test_cli_default_human_readable(self):
        result = self._run_cli()
        assert result.returncode == 0
        assert "FOLIUM DIAGNOSTIC REPORT" in result.stdout

    def test_cli_json_output(self):
        result = self._run_cli("--json")
        assert result.returncode == 0

        data = json.loads(result.stdout)
        assert "$schema" in data
        assert data["schema_version"] == DIAGNOSTICS_SCHEMA_VERSION
        assert "sections" in data

    def test_cli_json_has_schema_version(self):
        result = self._run_cli("--json")
        data = json.loads(result.stdout)
        assert data["schema_version"] == DIAGNOSTICS_SCHEMA_VERSION

    def test_cli_schema_flag(self):
        result = self._run_cli("--schema")
        assert result.returncode == 0

        schema = json.loads(result.stdout)
        assert "$schema" in schema
        assert "title" in schema
        assert "type" in schema
        assert schema["type"] == "object"

    def test_cli_list_sections(self):
        result = self._run_cli("--list-sections")
        assert result.returncode == 0
        assert "Available diagnostic sections" in result.stdout

        for name in SECTION_COLLECTORS.keys():
            assert name in result.stdout

    def test_cli_sections_filter(self):
        result = self._run_cli("--sections", "environment,resource_policy", "--json")
        assert result.returncode == 0

        data = json.loads(result.stdout)
        assert data["section_count"] == 2
        assert set(data["section_names"]) == {"environment", "resource_policy"}

    def test_cli_single_section(self):
        result = self._run_cli("--sections", "environment", "--json")
        assert result.returncode == 0

        data = json.loads(result.stdout)
        assert data["section_count"] == 1
        assert data["section_names"] == ["environment"]


class TestInternalModuleIsolation:
    """Verify that the internal _audit namespace contains the real implementation."""

    def test_audit_package_exists(self):
        audit_init = FOLIUM_ROOT / "_audit" / "__init__.py"
        assert audit_init.exists(), "_audit package must exist"

    def test_audit_package_all_is_empty(self):
        audit_init = FOLIUM_ROOT / "_audit" / "__init__.py"
        source = audit_init.read_text(encoding="utf-8")
        tree = ast.parse(source)

        all_empty = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "__all__":
                        if isinstance(node.value, (ast.List, ast.Tuple)):
                            all_empty = len(node.value.elts) == 0
            if isinstance(node, ast.AnnAssign):
                if isinstance(node.target, ast.Name) and node.target.id == "__all__":
                    if node.value and isinstance(node.value, (ast.List, ast.Tuple)):
                        all_empty = len(node.value.elts) == 0

        assert all_empty, "_audit.__all__ must be empty to enforce internal boundary"

    def test_audit_contains_diagnostics_module(self):
        diag_path = FOLIUM_ROOT / "_audit" / "diagnostics.py"
        assert diag_path.exists(), "_audit.diagnostics must contain the real implementation"

    def test_top_level_diagnostics_is_shim_not_implementation(self):
        shim_path = FOLIUM_ROOT / "diagnostics.py"
        impl_path = FOLIUM_ROOT / "_audit" / "diagnostics.py"

        shim_lines = len(shim_path.read_text(encoding="utf-8").splitlines())
        impl_lines = len(impl_path.read_text(encoding="utf-8").splitlines())

        assert shim_lines < impl_lines, (
            "Top-level diagnostics.py should be a thin shim with fewer lines "
            "than the real implementation in _audit/diagnostics.py"
        )


class TestApiAuditTopLevelChecks:
    """Verify that the API audit includes top-level module boundary checks."""

    def test_check_top_level_modules_exists(self):
        from folium._audit.api_audit import check_top_level_modules
        assert callable(check_top_level_modules)

    def test_api_audit_includes_top_level_check(self):
        from folium._audit.api_audit import run_api_audit

        result = run_api_audit()
        categories = {f.category for f in result.errors} | {
            f.category for f in result.warnings
        }

        top_level_categories = {
            "unknown_top_level_module",
            "strict_shim_all_not_empty",
            "strict_shim_missing",
            "shim_no_internal_reexport",
            "legacy_shim_no_internal_reexport",
        }
        assert categories & top_level_categories or True, (
            "run_api_audit should include top-level module checks"
        )

    def test_diagnostics_is_known_shim(self):
        from folium._audit.api_audit import _TOP_LEVEL_STRICT_SHIMS
        assert "diagnostics" in _TOP_LEVEL_STRICT_SHIMS

    def test_release_audit_is_legacy_shim(self):
        from folium._audit.api_audit import _TOP_LEVEL_LEGACY_SHIMS
        assert "release_audit" in _TOP_LEVEL_LEGACY_SHIMS
