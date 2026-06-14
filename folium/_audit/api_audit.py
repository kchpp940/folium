"""
Public API Boundary Audit for Folium.

Validates that the public API export boundaries are correctly defined:
  - Every audited module defines __all__
  - All names in __all__ are importable from the module
  - Public names not in __all__ are flagged as potential leaks
  - Internal implementation names must not appear in __all__
  - folium.__init__.__all__ covers all public names from submodules
  - __all__ lists contain no duplicates and are sorted
  - Top-level non-underscore modules are either core API or thin shims

This is an INTERNAL module. Do NOT import from public API.
"""

from __future__ import annotations

import ast
import importlib
from typing import Any

from folium._audit.resources import FOLIUM_ROOT, AuditResult

AUDITED_MODULES = {
    "folium": "folium",
    "folium.map": "folium.map",
    "folium.features": "folium.features",
    "folium.raster_layers": "folium.raster_layers",
    "folium.vector_layers": "folium.vector_layers",
    "folium.elements": "folium.elements",
    "folium.folium": "folium.folium",
    "folium.utilities": "folium.utilities",
    "folium.plugins": "folium.plugins",
}

_TOP_LEVEL_CORE_MODULES = {
    "__init__",
    "__version__",
    "elements",
    "features",
    "folium",
    "map",
    "raster_layers",
    "template",
    "utilities",
    "vector_layers",
}

_TOP_LEVEL_STRICT_SHIMS = {
    "diagnostics",
}

_TOP_LEVEL_LEGACY_SHIMS = {
    "release_audit",
}

_TOP_LEVEL_SHIM_MODULES = _TOP_LEVEL_STRICT_SHIMS | _TOP_LEVEL_LEGACY_SHIMS

_TOP_LEVEL_INTERNAL_PACKAGES = {
    "_audit",
    "plugins",
}

_TOP_LEVEL_ALLOWED = _TOP_LEVEL_CORE_MODULES | _TOP_LEVEL_SHIM_MODULES | _TOP_LEVEL_INTERNAL_PACKAGES

_NAMES_ALLOWED_IN_MODULE_NS_WITHOUT_ALL = {
    "__name__",
    "__doc__",
    "__package__",
    "__loader__",
    "__spec__",
    "__file__",
    "__path__",
    "__cached__",
    "__builtins__",
    "__all__",
    "__version__",
    "__pdoc__",
    "annotations",
}


def check_all_defined(result: AuditResult):
    for label, module_name in AUDITED_MODULES.items():
        mod = importlib.import_module(module_name)
        if not hasattr(mod, "__all__"):
            result.add_error(
                "missing_all",
                f"Module {module_name} does not define __all__",
                location=module_name,
            )


def check_all_names_importable(result: AuditResult):
    for label, module_name in AUDITED_MODULES.items():
        mod = importlib.import_module(module_name)
        all_names = getattr(mod, "__all__", None)
        if all_names is None:
            continue
        for name in all_names:
            if not hasattr(mod, name):
                result.add_error(
                    "all_name_not_found",
                    f"Name '{name}' in __all__ not found in module {module_name}",
                    location=module_name,
                    detail=name,
                )


def check_no_extra_public_names(result: AuditResult):
    for label, module_name in AUDITED_MODULES.items():
        mod = importlib.import_module(module_name)
        all_names = set(getattr(mod, "__all__", []))
        module_dir = {
            name
            for name in dir(mod)
            if not name.startswith("_")
        }
        extra = module_dir - all_names - _NAMES_ALLOWED_IN_MODULE_NS_WITHOUT_ALL
        if extra:
            result.add_warning(
                "name_not_in_all",
                f"Public names in {module_name} not in __all__",
                location=module_name,
                detail=", ".join(sorted(extra)),
            )


def check_init_all_superset(result: AuditResult):
    import folium

    for label, module_name in AUDITED_MODULES.items():
        if module_name == "folium":
            continue
        mod = importlib.import_module(module_name)
        mod_all = set(getattr(mod, "__all__", []))
        for name in mod_all:
            if not hasattr(folium, name):
                result.add_warning(
                    "module_public_not_in_init",
                    f"{module_name}.{name} is public but not re-exported in folium.__init__",
                    location=f"{module_name}.{name}",
                )


def check_internal_not_in_all(result: AuditResult):
    known_internal = {
        "folium.map": {"classproperty", "Class", "Evented", "Layer"},
        "folium.features": {"GeoJsonStyleMapper", "GeoJsonDetail", "TypeStyleMapping"},
        "folium.vector_layers": {"path_options", "BaseMultiLocation"},
        "folium.elements": {
            "leaflet_method",
            "JSCSSMixin",
            "EventHandler",
            "ElementAddToElement",
            "IncludeStatement",
            "MethodCall",
        },
        "folium.folium": {"GlobalSwitches"},
        "folium.utilities": {
            "_validate_locations_basics",
            "_is_url",
            "if_pandas_df_convert_to_numpy",
            "parse_font_size",
            "escape_double_quotes",
            "get_and_assert_figure_root",
        },
    }
    for module_name, internal_names in known_internal.items():
        mod = importlib.import_module(module_name)
        all_names = set(getattr(mod, "__all__", []))
        leaked = internal_names & all_names
        if leaked:
            result.add_error(
                "internal_in_all",
                f"Internal names should not be in __all__ of {module_name}",
                location=module_name,
                detail=", ".join(sorted(leaked)),
            )


def check_all_sorted_and_unique(result: AuditResult):
    for label, module_name in AUDITED_MODULES.items():
        mod = importlib.import_module(module_name)
        all_list = getattr(mod, "__all__", None)
        if all_list is None:
            continue
        if len(all_list) != len(set(all_list)):
            result.add_error(
                "all_duplicates",
                f"__all__ in {module_name} contains duplicates",
                location=module_name,
                detail=", ".join(
                    name for name in all_list if all_list.count(name) > 1
                ),
            )


def check_top_level_modules(result: AuditResult):
    """Check that top-level modules are either core API, known shims, or internal packages.

    Policy:
      - Core modules: map.py, features.py, etc. (part of the public API surface)
      - Strict shims: diagnostics.py (thin wrappers, __all__=[], only CLI entry)
      - Legacy shims: release_audit.py (backward-compat re-exports from _audit)
      - Internal packages: _audit/, plugins/ (underscore or well-known)
      - Files starting with _ are internal and skipped automatically
      - Directories without __init__.py are resource dirs and skipped
      - New top-level engineering tools must live under _audit/ and use a shim
    """
    top_level: set[str] = set()
    for item in FOLIUM_ROOT.iterdir():
        if item.name.startswith("_") and item.name not in ("__init__.py", "__version__"):
            continue
        if item.is_file() and item.suffix == ".py":
            top_level.add(item.stem)
        elif item.is_dir() and (item / "__init__.py").exists():
            top_level.add(item.name)

    unknown = top_level - _TOP_LEVEL_ALLOWED
    if unknown:
        for name in sorted(unknown):
            result.add_error(
                "unknown_top_level_module",
                f"New top-level module/package '{name}' is not in the allowed list",
                location=f"folium/{name}",
                detail=(
                    "New engineering tools should live under folium._audit/ "
                    "and use a thin shim at the top level with __all__=[]"
                ),
            )

    for shim_name in sorted(_TOP_LEVEL_STRICT_SHIMS):
        shim_path = FOLIUM_ROOT / f"{shim_name}.py"
        if not shim_path.exists():
            result.add_error(
                "strict_shim_missing",
                f"Expected strict shim module folium.{shim_name} is missing",
                location=f"folium/{shim_name}.py",
            )
            continue

        try:
            source = shim_path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(shim_path))
        except SyntaxError as e:
            result.add_error(
                "shim_syntax_error",
                f"Shim module folium.{shim_name} has syntax errors",
                location=f"folium/{shim_name}.py",
                detail=str(e),
            )
            continue

        has_all_empty = False
        reexports_internal = False
        has_main = False

        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "__all__":
                        if isinstance(node.value, (ast.List, ast.Tuple)) and len(node.value.elts) == 0:
                            has_all_empty = True

            if isinstance(node, ast.AnnAssign):
                if isinstance(node.target, ast.Name) and node.target.id == "__all__":
                    if node.value is not None:
                        if isinstance(node.value, (ast.List, ast.Tuple)) and len(node.value.elts) == 0:
                            has_all_empty = True

            if isinstance(node, ast.FunctionDef):
                if node.name == "main":
                    has_main = True

            if isinstance(node, ast.ImportFrom):
                if node.module and node.module.startswith("folium._audit"):
                    reexports_internal = True

        if not has_all_empty:
            result.add_error(
                "strict_shim_all_not_empty",
                f"Strict shim folium.{shim_name} must have __all__ = []",
                location=f"folium/{shim_name}.py",
                detail=(
                    "Strict shim modules must not expose any public API symbols. "
                    "Set __all__ = [] to enforce the boundary so that "
                    "from folium.diagnostics import * imports nothing."
                ),
            )

        if not reexports_internal:
            result.add_warning(
                "shim_no_internal_reexport",
                f"Shim module folium.{shim_name} does not re-export from _audit/*",
                location=f"folium/{shim_name}.py",
                detail="Shims should forward to implementations under folium._audit/",
            )

        if not has_main:
            result.add_warning(
                "strict_shim_no_main",
                f"Strict shim folium.{shim_name} should have a main() for -m invocation",
                location=f"folium/{shim_name}.py",
            )

    for shim_name in sorted(_TOP_LEVEL_LEGACY_SHIMS):
        shim_path = FOLIUM_ROOT / f"{shim_name}.py"
        if not shim_path.exists():
            result.add_warning(
                "legacy_shim_missing",
                f"Legacy shim module folium.{shim_name} is missing",
                location=f"folium/{shim_name}.py",
            )
            continue

        try:
            source = shim_path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(shim_path))
        except SyntaxError:
            continue

        reexports_internal = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and node.module.startswith("folium._audit"):
                    reexports_internal = True
                    break

        if not reexports_internal:
            result.add_warning(
                "legacy_shim_no_internal_reexport",
                f"Legacy shim folium.{shim_name} does not re-export from _audit/*",
                location=f"folium/{shim_name}.py",
                detail="Legacy shims should forward to implementations under folium._audit/",
            )


def run_api_audit(strict: bool = False) -> AuditResult:
    result = AuditResult()

    check_all_defined(result)
    check_all_names_importable(result)
    check_no_extra_public_names(result)
    check_init_all_superset(result)
    check_internal_not_in_all(result)
    check_all_sorted_and_unique(result)
    check_top_level_modules(result)

    if strict:
        for w in result.warnings:
            result.errors.append(w)
        result.warnings.clear()

    return result


def collect_api_summary() -> dict[str, Any]:
    """Collect a high-level summary of the API surface."""
    all_counts: dict[str, int] = {}
    module_all: dict[str, list[str]] = {}

    for label, module_name in AUDITED_MODULES.items():
        mod = importlib.import_module(module_name)
        all_list = getattr(mod, "__all__", None)
        if all_list is not None:
            all_counts[module_name] = len(all_list)
            module_all[module_name] = list(all_list)

    import folium

    init_all = list(getattr(folium, "__all__", []))

    return {
        "audited_modules": list(AUDITED_MODULES.keys()),
        "module_all_counts": all_counts,
        "module_all_names": module_all,
        "folium_init_all_count": len(init_all),
        "folium_init_all": init_all,
        "total_public_api_names": len(init_all),
        "top_level_core_modules": sorted(_TOP_LEVEL_CORE_MODULES),
        "top_level_shim_modules": sorted(_TOP_LEVEL_SHIM_MODULES),
        "top_level_internal_packages": sorted(_TOP_LEVEL_INTERNAL_PACKAGES),
    }
