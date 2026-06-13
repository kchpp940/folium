"""
Backward-compatibility shim.

The real implementation lives in :mod:`folium._audit.resources`.
This module is kept solely so that ``python -m folium.release_audit``
and ``from folium.release_audit import ...`` continue to work during a
transition period. Do not add new logic here.
"""

from __future__ import annotations

from folium._audit.resources import *  # noqa: F401,F403
from folium._audit.resources import (
    AuditFinding,
    AuditResult,
    FOLIUM_ROOT,
    check_duplicate_names,
    check_inline_cdn_urls,
    check_manifest_consistency,
    check_version_drift,
    format_findings,
    load_manifest,
    main,
    run_audit,
    _collect_resources_from_class,
    _extract_package_from_url,
    _extract_version_from_url,
    _get_feature_classes,
    _get_plugin_classes,
)

__all__: list[str] = []


if __name__ == "__main__":
    main()
