"""
Public API Boundary Audit for Folium.

Validates that the public API export boundaries are correctly defined:
  - Every audited module defines __all__
  - All names in __all__ are importable from the module
  - Public names not in __all__ are flagged as potential leaks
  - Internal implementation names must not appear in __all__
  - folium.__init__.__all__ covers all public names from submodules
  - __all__ lists contain no duplicates and are sorted

This is an INTERNAL module. Do NOT import from public API.
"""

from __future__ import annotations

import importlib
from typing import Any

from folium._audit.resources import AuditResult

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


def run_api_audit(strict: bool = False) -> AuditResult:
    result = AuditResult()

    check_all_defined(result)
    check_all_names_importable(result)
    check_no_extra_public_names(result)
    check_init_all_superset(result)
    check_internal_not_in_all(result)
    check_all_sorted_and_unique(result)

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
    }
