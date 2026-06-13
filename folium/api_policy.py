"""
Backward-compatibility shim.

The real implementation lives in :mod:`folium._audit.api_policy`.
This module is kept solely so that ``python -m folium.api_policy``
and ``from folium.api_policy import ...`` continue to work during a
transition period. Do not add new logic here.
"""

from __future__ import annotations

from folium._audit.api_policy import *  # noqa: F401,F403
from folium._audit.api_policy import (
    AUDITED_MODULES,
    COMPAT_ALIASES,
    EXPERIMENTAL_NAMES,
    FORBIDDEN_TOPLEVEL_MODULES,
    INIT_REEXPORT_MODULES,
    INTERNAL_NAMES,
)

__all__: list[str] = []
