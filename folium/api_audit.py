"""
Backward-compatibility shim.

The real implementation lives in :mod:`folium._audit.api_audit`.
This module is kept solely so that ``python -m folium.api_audit``
and ``from folium.api_audit import ...`` continue to work during a
transition period. Do not add new logic here.
"""

from __future__ import annotations

from folium._audit.api_audit import *  # noqa: F401,F403
from folium._audit.api_audit import (
    AuditFinding,
    AuditResult,
    check_all_defined,
    check_all_names_importable,
    check_all_sorted_and_unique,
    check_compat_aliases_exist,
    check_experimental_names_tracked,
    check_init_all_superset,
    check_internal_not_in_all,
    check_no_extra_public_names,
    check_no_forbidden_toplevel_modules,
    format_findings,
    main,
    run_api_audit,
)

__all__: list[str] = []


if __name__ == "__main__":
    main()
