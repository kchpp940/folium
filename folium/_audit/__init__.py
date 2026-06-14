"""
Internal audit package for Folium.

This package contains:
  - resources.py:  CDN resource consistency audit (manifest vs source code)
  - api_audit.py:  Public API boundary audit (__all__ checks)
  - smoke.py:      Smoke test policy and marker metadata
  - diagnostics.py: Unified developer diagnostics (internal only)

All modules in this package are INTERNAL implementation details.
They are NOT part of the public API and may change without notice.
"""

from __future__ import annotations

__all__: list[str] = []
