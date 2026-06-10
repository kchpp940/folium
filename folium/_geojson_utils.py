"""
Internal GeoJSON utility functions.

Provides unified dotted-key path resolution for both GeoJSON features and
GeoJSON style mappings. Supports dict key access (strings) and list index
access (integers). The field path uses dot-separated components, e.g.
"properties.id" or "features.0.properties.name".

This is a private internal module - the public API is exposed through
Choropleth and GeoJson in folium.features.
"""

from __future__ import annotations

import functools
import operator
from typing import Any, cast


def parse_key_on_path(key_on: str) -> list[str]:
    """Split a dotted key_on path into its components.

    Both Choropleth and GeoJsonStyleMapper use the same "fields.id"
    convention. This is the single authoritative parser.
    """
    return key_on.split(".")


def resolve_dotted_key(
    obj: dict | list,
    key: str,
    *,
    default_missing: Any = None,
) -> Any:
    """Look up a value in a nested dict/list structure via dotted key.

    This is the unified replacement for:
      - Choropleth._get_by_key (recursive dict/list traversal)
      - GeoJsonStyleMapper.get_feature_id (functools.reduce)

    Numeric path components are interpreted as list indices; non-numeric
    components as dict keys. Missing dict keys return ``default_missing``.

    Examples
    --------
    >>> resolve_dotted_key({"a": {"b": 42}}, "a.b")
    42
    >>> resolve_dotted_key({"features": [{"id": "NY"}]}, "features.0.id")
    'NY'
    >>> resolve_dotted_key({"a": {}}, "a.missing") is None
    True
    """
    parts = parse_key_on_path(key)
    current: Any = obj

    for part in parts:
        if isinstance(current, list):
            try:
                current = current[int(part)]
            except (IndexError, ValueError):
                return default_missing
        elif isinstance(current, dict):
            current = current.get(part, default_missing)
            if current is default_missing:
                return default_missing
        else:
            return default_missing

    return current


def get_feature_id(
    feature: dict,
    feature_identifier: str,
) -> str | int:
    """Extract the identifier value from a single GeoJSON feature.

    The feature_identifier is a dotted path like "properties.id".
    The first component is ignored by convention (callers pass
    "feature.properties.id" where "feature" is the leading placeholder).

    Returns the raw id value - expected to be str or int for dict keys.
    """
    fields = parse_key_on_path(feature_identifier)[1:]
    value = functools.reduce(operator.getitem, fields, feature)
    return cast(str | int, value)
