"""
Folium Release Resource Audit Package.

Public API surface — all imports from `folium.release_audit` go through here.
Internal modules are prefixed with `_` (e.g., `_audit`, `_manifest`).

Module responsibilities:
  _extract   — shared data classes + source code resource extraction + URL parsing
  _policy    — policy file loading + policy helper functions
  _audit     — all audit rule checks (duplicate names, version drift, etc.)
  _manifest  — stable manifest schema + generation + validation
  _offline   — offline CDN resource download + caching

CLI entry point: __main__.py (python -m folium.release_audit)
"""

from __future__ import annotations

from ._audit import (
    apply_strict_policy,
    check_docs_consistency,
    check_duplicate_names,
    check_inheritance_consistency,
    check_inline_cdn_urls,
    check_policy_compliance,
    check_vegalite_variants,
    check_version_drift,
    run_audit,
)
from ._extract import (
    CDN_PATTERN,
    AuditFinding,
    AuditResult,
    ClassResources,
    FOLIUM_ROOT,
    ResourceEntry,
    cdn_host,
    collect_all_resources,
    collect_resources_from_class,
    extract_package_from_url,
    extract_version_from_url,
    get_feature_classes,
    get_map_class,
    get_plugin_classes,
    resource_id,
)
from ._manifest import (
    MANIFEST_SCHEMA_VERSION,
    build_stable_manifest,
    generate_manifest,
    manifest_json_schema,
    validate_manifest,
)
from ._offline import download_resources
from ._policy import (
    is_dynamic_resource_class,
    is_inheritance_class,
    is_no_resources_class,
    is_strict_promotable,
    load_policy,
    policy_file_path,
)

__all__ = [
    "AuditFinding",
    "AuditResult",
    "CDN_PATTERN",
    "ClassResources",
    "FOLIUM_ROOT",
    "MANIFEST_SCHEMA_VERSION",
    "ResourceEntry",
    "apply_strict_policy",
    "build_stable_manifest",
    "check_docs_consistency",
    "check_duplicate_names",
    "check_inheritance_consistency",
    "check_inline_cdn_urls",
    "check_policy_compliance",
    "check_vegalite_variants",
    "check_version_drift",
    "collect_all_resources",
    "collect_resources_from_class",
    "download_resources",
    "extract_package_from_url",
    "extract_version_from_url",
    "generate_manifest",
    "get_feature_classes",
    "get_map_class",
    "get_plugin_classes",
    "is_dynamic_resource_class",
    "is_inheritance_class",
    "is_no_resources_class",
    "is_strict_promotable",
    "load_policy",
    "manifest_json_schema",
    "policy_file_path",
    "run_audit",
    "validate_manifest",
]
