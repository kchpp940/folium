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
# Stage 3 — synthetic id generation (does NOT write into features)
# ---------------------------------------------------------------------------


def generate_synthetic_ids(n: int) -> list[str]:
    """Return a list of deterministic synthetic ids of length *n*.

    The ids are stringified integers ``["0", "1", …]``.  They are **not**
    written into any feature dict — they exist only as a private mapping
    that the rendering pipeline uses on the JS side.
    """
    return [str(i) for i in range(n)]


# ---------------------------------------------------------------------------
# Stage 4 — identifier selection
# ---------------------------------------------------------------------------


def resolve_feature_identifier(data: dict) -> tuple[str, list[str | int] | None]:
    """Choose the most appropriate Javascript identifier expression.

    Returns a ``(identifier_expr, feature_id_map)`` tuple:

    * ``("feature.id", None)`` — when the user supplied valid unique ids
      on every feature.
    * ``("feature.properties.<key>", None)`` — when a single property key
      holds unique str/int values on every feature.
    * ``("feature._folium_id", ["0", "1", ...])`` — fallback: no natural
      identifier exists, so synthetic ids are generated and returned as a
      private mapping.  The mapping is **never** written into the GeoJSON
      data; the JS template injects ``feature._folium_id`` at render time.

    Automatically runs :func:`to_feature_collection` first so callers don't
    have to chain stages manually.
    """
    data = to_feature_collection(data)
    feats = data["features"]

    if not feats:
        return ("feature.id", None)

    user_supplied_ids = [
        feat.get("id")
        for feat in feats
        if isinstance(feat.get("id"), (str, int))
    ]
    if len(user_supplied_ids) == len(feats) and len(set(user_supplied_ids)) == len(
        feats
    ):
        return ("feature.id", None)

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
                return (f"feature.properties.{key}", None)

    id_map = generate_synthetic_ids(len(feats))
    return ("feature._folium_id", id_map)


# ---------------------------------------------------------------------------
# Identifier resolution (Python side, mirror of the JS expression)
# ---------------------------------------------------------------------------


def get_feature_id(
    feature: dict,
    identifier: str = "feature.id",
    feature_id_map: list[str | int] | None = None,
    feature_index: int | None = None,
) -> str | int:
    """Return the unique identifier value for a feature.

    When *feature_id_map* is provided (synthetic-id case), the id is
    looked up by *feature_index* instead of walking the feature dict.
    This keeps synthetic ids out of the GeoJSON payload entirely.

    Parameters
    ----------
    feature: dict
        A GeoJSON Feature dictionary.
    identifier: str
        A dotted path such as ``"feature.id"`` or
        ``"feature.properties.name"``.
    feature_id_map: list or None
        Private mapping from feature index to synthetic id, as returned
        by :func:`resolve_feature_identifier`.
    feature_index: int or None
        Index of the feature within the FeatureCollection's features
        list.  Required when *feature_id_map* is not None.

    Returns
    -------
    str or int
        The feature's unique identifier.
    """
    if feature_id_map is not None:
        assert feature_index is not None
        return feature_id_map[feature_index]

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
    feature_id_map: list[str | int] | None = None,
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
    feature_id_map:
        Optional private mapping from feature index to synthetic id.
        When provided, ids are looked up by index instead of walking
        the feature dict, keeping synthetic ids out of the GeoJSON
        payload.

    Returns
    -------
    dict
        A mapping suitable for direct use as ``GeoJson.style_map`` or
        ``GeoJson.highlight_map``.
    """
    mapping: TypeStyleMapping = {}
    for idx, feature in enumerate(features):
        content = style_function(feature)
        if macro_element_parent is not None:
            for key, value in content.items():
                if _is_macro_element(value):
                    if value._parent is None:
                        value._parent = macro_element_parent
                        value.render()
                    content[key] = "{{'" + value.get_name() + "'}}"
        key = _style_to_key(content)
        feature_id = get_feature_id(
            feature, identifier, feature_id_map=feature_id_map, feature_index=idx
        )
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
