"""Internal utilities for GeoJSON data normalization and identifier handling.

This module contains **pure data-processing functions** that do not depend on
Folium's class hierarchy. The public-facing classes in :mod:`folium.features`
are thin wrappers that delegate to these functions.

The processing pipeline is split into independent stages so callers can pick
exactly how much normalization they need:

1. ``ensure_properties`` — lightest touch, never changes the top-level type.
2. ``to_feature_collection`` — converts single Feature/Geometry to a
   FeatureCollection.  Automatically runs ``ensure_properties`` first.
3. ``resolve_feature_identifier`` — picks the best Javascript identifier
   expression.  Automatically runs ``to_feature_collection`` first, and may
   call ``assign_unique_ids`` as a fallback when no natural identifier exists.
"""

from __future__ import annotations

import json
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Stage 1 — properties normalization
# ---------------------------------------------------------------------------


def ensure_properties(data: dict) -> None:
    """Ensure every feature has a non-None ``properties`` dict.

    This is the lightest normalization step: it never changes the top-level
    data type, never converts geometries to features, and never assigns ids.

    Works on:
    * ``FeatureCollection`` — every feature is inspected.
    * Single ``Feature`` — its own properties are inspected.
    * Raw ``Geometry`` or ``GeometryCollection`` — left untouched.

    Operates **in place** on ``data``; callers are responsible for passing a
    deep copy when the original must be preserved.
    """
    data_type = data.get("type")

    if data_type == "FeatureCollection":
        for feat in data["features"]:
            if "properties" not in feat or feat["properties"] is None:
                feat["properties"] = {}
    elif data_type == "Feature":
        if "properties" not in data or data["properties"] is None:
            data["properties"] = {}


# ---------------------------------------------------------------------------
# Stage 2 — structure conversion (raw geometry / single Feature → FC)
# ---------------------------------------------------------------------------


def to_feature_collection(data: dict) -> dict:
    """Convert a single Feature or raw Geometry to a FeatureCollection.

    Runs ``ensure_properties`` automatically before converting so that any
    existing properties are normalized first.

    After this function returns, ``data`` is guaranteed to be a
    ``FeatureCollection`` with normalized properties on every feature.

    Returns the (possibly reassigned) ``data`` dict for convenience.
    """
    ensure_properties(data)

    data_type = data.get("type")
    if data_type == "FeatureCollection":
        return data

    if data_type == "Feature":
        feature = data.copy()
        feature.pop("features", None)
        data.clear()
        data["type"] = "FeatureCollection"
        data["features"] = [feature]
    else:
        geometry = data
        data.clear()
        data["type"] = "FeatureCollection"
        data["features"] = [
            {
                "type": "Feature",
                "geometry": geometry,
                "properties": {},
            }
        ]
    return data


# ---------------------------------------------------------------------------
# Stage 3 — synthetic id assignment
# ---------------------------------------------------------------------------


def assign_unique_ids(features: list[dict]) -> None:
    """Assign deterministic synthetic ids to every feature.

    When this function is called (because at least one feature lacks a valid
    unique id), **all** features receive a fresh synthetic id so the mapping
    is fully deterministic and stable.  Internal ids are stringified integers
    starting from ``"0"``.

    Operates **in place** on the ``features`` list.
    """
    if not features:
        return
    for idx, feat in enumerate(features):
        feat["id"] = str(idx)


# ---------------------------------------------------------------------------
# Stage 4 — identifier selection
# ---------------------------------------------------------------------------


def resolve_feature_identifier(data: dict) -> str:
    """Choose the most appropriate Javascript identifier expression.

    Returns, in priority order:

    1. ``"feature.id"`` — when the user supplied valid unique ids on every
       feature.
    2. ``"feature.properties.<key>"`` — when a single property key holds
       unique str/int values on every feature (preferred over generating
       synthetic ids because it preserves the user's natural identifier).
    3. ``"feature.id"`` — fallback: synthetic ids are assigned via
       :func:`assign_unique_ids` before returning.

    Automatically runs :func:`to_feature_collection` first so callers don't
    have to chain stages manually.
    """
    data = to_feature_collection(data)
    feats = data["features"]

    if not feats:
        return "feature.id"

    user_supplied_ids = [
        feat.get("id")
        for feat in feats
        if isinstance(feat.get("id"), (str, int))
    ]
    if len(user_supplied_ids) == len(feats) and len(set(user_supplied_ids)) == len(
        feats
    ):
        return "feature.id"

    first_props = feats[0].get("properties")
    if isinstance(first_props, dict) and first_props:
        for key in first_props:
            values: list = []
            all_valid = True
            for feat in feats:
                props = feat.get("properties")
                if not isinstance(props, dict):
                    all_valid = False
                    break
                val = props.get(key)
                if not isinstance(val, (str, int)):
                    all_valid = False
                    break
                values.append(val)
            if all_valid and len(set(values)) == len(feats):
                return f"feature.properties.{key}"

    assign_unique_ids(feats)
    return "feature.id"


# ---------------------------------------------------------------------------
# Identifier resolution (Python side, mirror of the JS expression)
# ---------------------------------------------------------------------------


def get_feature_id(
    feature: dict, identifier: str = "feature.id"
) -> str | int:
    """Return the unique identifier value for a feature.

    The identifier is resolved using the same field-path logic that the
    rendered Javascript uses, so the Python and JS sides always agree on
    how to identify a feature.

    Parameters
    ----------
    feature: dict
        A GeoJSON Feature dictionary.
    identifier: str
        A dotted path such as ``"feature.id"`` or
        ``"feature.properties.name"``.

    Returns
    -------
    str or int
        The feature's unique identifier.

    Raises
    ------
    AssertionError
        If the resolved value is not a scalar (str/int), which indicates
        the data was not properly normalized before calling this function.
    """
    fields = identifier.split(".")[1:]
    value: Any = feature
    for field in fields:
        if isinstance(value, dict):
            value = value.get(field)
        else:
            value = None
            break
    assert isinstance(value, (str, int)), (
        f"Resolved identifier {identifier!r} to non-scalar value {value!r} "
        "on feature. This indicates that the data was not properly "
        "normalized before rendering."
    )
    return value


# ---------------------------------------------------------------------------
# Style / highlight mapping
# ---------------------------------------------------------------------------


TypeStyleMapping = dict[str, str | list[str | int]]


def _style_to_key(d: dict) -> str:
    """Convert a style dict to a string key, enabling Jinja2 template syntax."""
    as_str = json.dumps(d, sort_keys=True)
    return as_str.replace('"{{', "{{").replace('}}"', "}}")


def _set_default_key(mapping: TypeStyleMapping) -> None:
    """Replace the bucket with the most features with a ``'default'`` key."""
    key_longest = max(mapping, key=mapping.get)  # type: ignore
    mapping["default"] = key_longest
    del mapping[key_longest]


def build_style_mapping(
    features: list[dict],
    identifier: str,
    style_function: Callable[[dict], dict],
    macro_element_parent: Any | None = None,
) -> TypeStyleMapping:
    """Build the mapping from serialized style → list of feature ids.

    Parameters
    ----------
    features:
        The normalized ``FeatureCollection["features"]`` list.
    identifier:
        The dotted identifier string produced by
        :func:`resolve_feature_identifier`.
    style_function:
        User-supplied callable mapping a feature dict to a style dict.
    macro_element_parent:
        Optional Folium element used as parent for any ``MacroElement``
        values found inside style dicts (e.g. ``Icon`` references).

    Returns
    -------
    dict
        A mapping suitable for direct use as ``GeoJson.style_map`` or
        ``GeoJson.highlight_map``.
    """
    mapping: TypeStyleMapping = {}
    for feature in features:
        content = style_function(feature)
        if macro_element_parent is not None:
            for key, value in content.items():
                if _is_macro_element(value):
                    if value._parent is None:
                        value._parent = macro_element_parent
                        value.render()
                    content[key] = "{{'" + value.get_name() + "'}}"
        key = _style_to_key(content)
        feature_id = get_feature_id(feature, identifier)
        mapping.setdefault(key, []).append(feature_id)  # type: ignore
    _set_default_key(mapping)
    return mapping


def _is_macro_element(value: Any) -> bool:
    """Return True if *value* is a branca MacroElement.

    Imported lazily to avoid a circular dependency at module load time.
    """
    from branca.element import MacroElement  # noqa: PLC0415

    return isinstance(value, MacroElement)


# ---------------------------------------------------------------------------
# Choropleth helpers
# ---------------------------------------------------------------------------


def get_by_key(obj: dict | list, key: str) -> float | str | None:
    """Walk a dotted ``key`` path through a nested dict/list structure.

    Numeric path segments (e.g. ``"0"``) are interpreted as list indices.
    Missing dict keys return ``None`` rather than raising; list index
    errors propagate as ``IndexError`` to match original Choropleth
    behaviour.

    Used by :class:`folium.features.Choropleth` to resolve
    ``key_on`` references such as ``"properties.statename"``.
    """
    key_parts = key.split(".")
    first_key_part = key_parts[0]
    if first_key_part.isdigit():
        value = obj[int(first_key_part)]  # type: ignore
    else:
        try:
            value = obj.get(first_key_part, None)  # type: ignore
        except AttributeError:
            return None
    if len(key_parts) > 1:
        new_key = ".".join(key_parts[1:])
        return get_by_key(value, new_key)
    return value
