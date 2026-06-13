"""
Folium Public API Boundary Audit.

Validates that the public API export boundary is properly maintained
according to the rules declared in :mod:`folium._audit.api_policy`.

This module contains ONLY audit logic. All policy decisions (which
modules to audit, which names are internal, which require re-export)
are defined in :mod:`folium._audit.api_policy`.

Checks performed:
  1. Every audited module defines ``__all__``
  2. All names in ``__all__`` are actually importable from the module
  3. Public names (classes and functions defined in the module) that
     are not in ``__all__`` are flagged as potential API leaks
  4. Names declared as internal in ``api_policy.INTERNAL_NAMES`` must
     not appear in any module's ``__all__``
  5. Modules declared in ``api_policy.INIT_REEXPORT_MODULES`` must have
     their public names re-exported through ``folium.__init__``
  6. ``__all__`` lists contain no duplicates
  7. No forbidden top-level modules exist under ``folium/`` that are
     not prefixed with an underscore

Usage:
    python -m folium.api_audit              # backward-compat shim
    python -m folium._audit.api_audit       # direct internal use
"""

from __future__ import annotations

import importlib
import inspect
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from folium._audit.api_policy import (
    AUDITED_MODULES,
    COMPAT_ALIASES,
    EXPERIMENTAL_NAMES,
    FORBIDDEN_TOPLEVEL_MODULES,
    INIT_REEXPORT_MODULES,
    INTERNAL_NAMES,
)


_NAMES_ALLOWED_IN_MODULE_NS_WITHOUT_ALL: set[str] = {
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
    "Final",
}

__all__: list[str] = []

FOLIUM_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class AuditFinding:
    severity: str
    category: str
    message: str
    location: str = ""
    detail: str = ""


@dataclass
class AuditResult:
    errors: list[AuditFinding] = field(default_factory=list)
    warnings: list[AuditFinding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0

    def add_error(self, category: str, message: str, location: str = "", detail: str = ""):
        self.errors.append(AuditFinding("error", category, message, location, detail))

    def add_warning(self, category: str, message: str, location: str = "", detail: str = ""):
        self.warnings.append(AuditFinding("warning", category, message, location, detail))

    def merge(self, other: AuditResult):
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "errors": [
                {
                    "severity": f.severity,
                    "category": f.category,
                    "message": f.message,
                    "location": f.location,
                    "detail": f.detail,
                }
                for f in self.errors
            ],
            "warnings": [
                {
                    "severity": f.severity,
                    "category": f.category,
                    "message": f.message,
                    "location": f.location,
                    "detail": f.detail,
                }
                for f in self.warnings
            ],
        }


def _is_module_defined(mod_name: str, obj) -> bool:
    obj_module = getattr(obj, "__module__", None)
    if obj_module is None:
        return False
    return obj_module == mod_name or obj_module.startswith(mod_name + ".")


def check_all_defined(result: AuditResult):
    for module_name in AUDITED_MODULES:
        mod = importlib.import_module(module_name)
        if not hasattr(mod, "__all__"):
            result.add_error(
                "missing_all",
                f"Module {module_name} does not define __all__",
                location=module_name,
            )


def check_all_names_importable(result: AuditResult):
    for module_name in AUDITED_MODULES:
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
    for module_name in AUDITED_MODULES:
        mod = importlib.import_module(module_name)
        all_names = set(getattr(mod, "__all__", []))
        internal_names = INTERNAL_NAMES.get(module_name, set())
        candidates: set[str] = set()
        for name in dir(mod):
            if name.startswith("_"):
                continue
            if name in _NAMES_ALLOWED_IN_MODULE_NS_WITHOUT_ALL:
                continue
            if name in internal_names:
                continue
            try:
                obj = getattr(mod, name)
            except Exception:
                continue
            if inspect.ismodule(obj):
                continue
            if not _is_module_defined(module_name, obj):
                continue
            if isinstance(obj, type) and not issubclass(obj, BaseException):
                candidates.add(name)
            elif callable(obj):
                candidates.add(name)
        extra = candidates - all_names
        if extra:
            result.add_warning(
                "name_not_in_all",
                f"Public names in {module_name} not in __all__",
                location=module_name,
                detail=", ".join(sorted(extra)),
            )


def check_init_all_superset(result: AuditResult):
    import folium

    for module_name in AUDITED_MODULES:
        if module_name == "folium":
            continue
        if module_name not in INIT_REEXPORT_MODULES:
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
    for module_name, internal_names in INTERNAL_NAMES.items():
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
    for module_name in AUDITED_MODULES:
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


def check_compat_aliases_exist(result: AuditResult):
    for module_name, aliases in COMPAT_ALIASES.items():
        mod = importlib.import_module(module_name)
        all_names = set(getattr(mod, "__all__", []))
        for alias_name, target_name in aliases.items():
            if alias_name not in all_names:
                result.add_warning(
                    "compat_alias_missing",
                    f"Compatibility alias '{alias_name}' not in __all__ of {module_name}",
                    location=module_name,
                )
            if not hasattr(mod, alias_name):
                result.add_error(
                    "compat_alias_not_found",
                    f"Compatibility alias '{alias_name}' not defined in {module_name}",
                    location=f"{module_name}.{alias_name}",
                    detail=f"should point to {target_name}",
                )


def check_experimental_names_tracked(result: AuditResult):
    for module_name, exp_names in EXPERIMENTAL_NAMES.items():
        mod = importlib.import_module(module_name)
        all_names = set(getattr(mod, "__all__", []))
        for name in exp_names:
            if name not in all_names:
                result.add_warning(
                    "experimental_not_in_all",
                    f"Experimental name '{name}' not in __all__ of {module_name}",
                    location=module_name,
                )


def check_no_forbidden_toplevel_modules(result: AuditResult):
    for name in FORBIDDEN_TOPLEVEL_MODULES:
        module_path = FOLIUM_ROOT / f"{name}.py"
        if not module_path.exists():
            continue
        content = module_path.read_text(encoding="utf-8", errors="ignore")
        import_target = f"folium._audit.{name}"
        if name == "release_audit":
            import_target = "folium._audit.resources"
        has_reexport = f"from {import_target}" in content or f"import {import_target}" in content
        if not has_reexport:
            result.add_error(
                "forbidden_toplevel_module",
                f"folium/{name}.py exists at top level but is not a shim re-exporting "
                f"from {import_target}. Non-underscore audit modules must be "
                f"shims only. New tooling belongs in folium/_audit/.",
                location=f"folium/{name}.py",
            )


def run_api_audit(strict: bool = False) -> AuditResult:
    result = AuditResult()

    check_all_defined(result)
    check_all_names_importable(result)
    check_no_extra_public_names(result)
    check_init_all_superset(result)
    check_internal_not_in_all(result)
    check_all_sorted_and_unique(result)
    check_compat_aliases_exist(result)
    check_experimental_names_tracked(result)
    check_no_forbidden_toplevel_modules(result)

    if strict:
        for w in result.warnings:
            result.errors.append(w)
        result.warnings.clear()

    return result


def format_findings(findings: list[AuditFinding], label: str) -> str:
    if not findings:
        return ""
    lines = [f"\n{'='*60}", f"  {label} ({len(findings)})", f"{'='*60}"]
    for f in findings:
        lines.append(f"\n  [{f.severity.upper()}] {f.category}")
        lines.append(f"  {f.message}")
        if f.location:
            lines.append(f"  Location: {f.location}")
        if f.detail:
            lines.append(f"  Detail: {f.detail}")
    return "\n".join(lines)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Folium Public API Boundary Audit")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    parser.add_argument("--strict", action="store_true", help="Treat warnings as errors")
    args = parser.parse_args()

    result = run_api_audit(strict=args.strict)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        output = format_findings(result.errors, "ERRORS")
        output += format_findings(result.warnings, "WARNINGS")
        if not result.errors and not result.warnings:
            output = "\n✓ All public API boundary checks passed."
        else:
            summary = f"\n\nSummary: {len(result.errors)} error(s), {len(result.warnings)} warning(s)"
            if result.ok:
                summary += "\nNo blocking errors found."
            else:
                summary += "\n❌ Blocking errors found — fix before release."
            output += summary
        print(output)

    sys.exit(0 if result.ok else 1)


if __name__ == "__main__":
    main()
