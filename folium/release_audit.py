"""
Release Resource Audit Tool for Folium (BACKWARD COMPATIBILITY SHIM).

Actual implementation has been moved to:
  - folium._audit.resources  (CDN resource consistency audit)
  - folium._audit.api_audit  (Public API boundary audit)

This module re-exports all public names for backward compatibility.
Existing code importing from folium.release_audit will continue to work.

Usage:
    python -m folium.release_audit              # run all checks, exit non-zero on error
    python -m folium.release_audit --json        # machine-readable output
    python -m folium.release_audit --strict      # treat warnings as errors
"""

from __future__ import annotations

import sys

from folium._audit.api_audit import (
    AUDITED_MODULES,
    check_all_defined,
    check_all_names_importable,
    check_all_sorted_and_unique,
    check_init_all_superset,
    check_internal_not_in_all,
    check_no_extra_public_names,
    check_top_level_modules,
    collect_api_summary,
    run_api_audit,
)
from folium._audit.resources import (
    CDN_PATTERN,
    FOLIUM_ROOT,
    PACKAGE_VERSION_PATTERN,
    AuditFinding,
    AuditResult,
    _collect_resources_from_class,
    _extract_package_from_url,
    _extract_version_from_url,
    _get_feature_classes,
    _get_plugin_classes,
    check_docs_consistency,
    check_duplicate_names,
    check_features_dynamic_urls,
    check_inline_cdn_urls,
    check_manifest_consistency,
    check_version_drift,
    load_manifest,
    run_audit,
)

__all__ = [
    "AUDITED_MODULES",
    "AuditFinding",
    "AuditResult",
    "CDN_PATTERN",
    "FOLIUM_ROOT",
    "PACKAGE_VERSION_PATTERN",
    "check_all_defined",
    "check_all_names_importable",
    "check_all_sorted_and_unique",
    "check_duplicate_names",
    "check_docs_consistency",
    "check_features_dynamic_urls",
    "check_inline_cdn_urls",
    "check_init_all_superset",
    "check_internal_not_in_all",
    "check_manifest_consistency",
    "check_no_extra_public_names",
    "check_top_level_modules",
    "check_version_drift",
    "collect_api_summary",
    "load_manifest",
    "run_api_audit",
    "run_audit",
    "_collect_resources_from_class",
    "_extract_package_from_url",
    "_extract_version_from_url",
    "_get_feature_classes",
    "_get_plugin_classes",
]


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
    import json

    parser = argparse.ArgumentParser(description="Folium Release Resource Audit")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    parser.add_argument("--strict", action="store_true", help="Treat warnings as errors")
    args = parser.parse_args()

    result = run_audit(strict=args.strict)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        output = format_findings(result.errors, "ERRORS")
        output += format_findings(result.warnings, "WARNINGS")
        if not result.errors and not result.warnings:
            output = "\n✓ All resource consistency checks passed."
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
