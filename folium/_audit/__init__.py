"""
Internal audit utilities for Folium.

This package contains engineering tools for CI and release validation.
It is NOT part of the public API — the underscore prefix signals that
downstream code should not import from here.

Submodules:
    api_policy   — pure data: public API boundary rules
    api_audit    — logic:  public API boundary checks
    resources    — logic:  CDN resource consistency checks
"""

from __future__ import annotations

__all__: list[str] = []
