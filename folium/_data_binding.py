"""
Internal data binding utilities for Choropleth and data-driven map layers.

This module provides unified data processing for converting pandas DataFrames,
pandas Series, and plain dicts into normalized color mapping inputs, handling
missing values (None, pd.NA, np.nan), infinite values (inf/-inf), nullable
dtypes (Int64, etc.), and str/int key normalization.

This is a private internal module - the public API is exposed through the
Choropleth class in folium.features.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

try:
    import pandas as pd
except ImportError:
    pd = None


def _is_missing_value(value: Any) -> bool:
    """Check if a value is missing (None, np.nan, pd.NA, etc.).

    Uses numpy first (faster, always available), then pandas as fallback
    for nullable dtypes (pd.NA, Int64, etc.).
    """
    if value is None:
        return True
    try:
        if np.isnan(value):
            return True
    except (TypeError, ValueError):
        pass
    if pd is not None:
        try:
            if pd.isna(value):
                return True
        except (TypeError, ValueError):
            pass
    return False


def is_invalid_value(value: Any) -> bool:
    """Check if a value is invalid for color mapping.

    A value is invalid if it is missing (None, np.nan, pd.NA) or if it
    is infinite (np.inf, -np.inf).
    """
    if _is_missing_value(value):
        return True
    try:
        if np.isinf(value):
            return True
    except (TypeError, ValueError):
        pass
    return False


def _is_dataframe(data: Any) -> bool:
    """Duck-type check for pandas DataFrame.

    We avoid isinstance checks to keep pandas an optional dependency and
    to support DataFrame-like objects that implement the same interface.
    """
    return hasattr(data, "set_index") and hasattr(data, "to_dict")


def _is_series(data: Any) -> bool:
    """Duck-type check for pandas Series.

    Distinguishes Series from DataFrames by the absence of set_index.
    """
    return hasattr(data, "to_dict") and not hasattr(data, "set_index")


def normalize_key_lookup(color_data: dict, key: Any) -> Any:
    """Look up a value in color_data with automatic str/int key matching.

    GeoJSON ids are often strings, while data indices may be integers,
    or vice versa. This function bridges that gap by trying both forms.

    Raises KeyError if the key (and its str/int variants) is not found.
    """
    if key in color_data:
        return color_data[key]

    if isinstance(key, int):
        str_key = str(key)
        if str_key in color_data:
            return color_data[str_key]

    if isinstance(key, str):
        try:
            int_key = int(key)
            if int_key in color_data:
                return color_data[int_key]
        except (ValueError, TypeError):
            pass

    raise KeyError(key)


def build_color_data(
    data: Any,
    columns: Sequence[Any] | None = None,
) -> dict | None:
    """Convert supported data inputs into a plain {key: value} dict.

    Supported inputs:
      - pandas DataFrame (requires columns=[key_col, value_col])
      - pandas Series (uses index as keys)
      - dict-like (copied via dict())
      - None or empty -> returns None

    This is a pure conversion, no value filtering is applied.
    """
    if data is None:
        return None

    if _is_dataframe(data) and columns is not None:
        return data.set_index(columns[0])[columns[1]].to_dict()
    elif _is_series(data):
        return data.to_dict()
    elif data:
        return dict(data)
    else:
        return None


def extract_valid_numeric_values(color_data: dict) -> np.ndarray:
    """Extract valid numeric values from a color_data dict.

    Filters out missing values, infinite values, and values that cannot
    be coerced to float. Returns a flat numpy float64 array suitable
    for histogram/bin calculations.

    Returns an empty array if no valid values are found.
    """
    values: list[float] = []
    for v in color_data.values():
        if not is_invalid_value(v):
            try:
                values.append(float(v))
            except (TypeError, ValueError):
                pass
    return np.array(values, dtype=float)


def compute_bin_edges(
    valid_values: np.ndarray,
    bins: int | Sequence[float],
    use_jenks: bool = False,
) -> np.ndarray:
    """Compute bin edges from valid numeric values.

    Supports standard numpy histogram binning (int or sequence of edges)
    as well as Jenks natural breaks optimization via the `jenkspy` package.

    Validates that all values fall within the computed or provided bins.
    Raises ValueError if valid_values is empty, if jenks parameters are
    invalid, or if any value falls outside the bin range.
    """
    if len(valid_values) == 0:
        raise ValueError("No valid numeric values available for binning.")

    if use_jenks:
        from jenkspy import jenks_breaks

        if not isinstance(bins, int):
            raise ValueError(
                f"bins value must be an integer when using Jenks."
                f' Invalid value "{bins}" received.'
            )
        bin_edges = np.array(
            jenks_breaks(valid_values, bins), dtype=float
        )
    else:
        _, bin_edges = np.histogram(valid_values, bins=bins)

    bins_min, bins_max = min(bin_edges), max(bin_edges)
    if np.any((valid_values < bins_min) | (valid_values > bins_max)):
        raise ValueError(
            "All values are expected to fall into one of the provided "
            "bins (or to be Nan). Please check the `bins` parameter "
            "and/or your data."
        )

    return bin_edges


def resolve_value_for_coloring(
    color_data: dict,
    key: Any,
) -> float | None:
    """Full resolution pipeline for coloring a single GeoJSON feature.

    Given a color_data dict and a GeoJSON key:
      1. Look up the raw value with str/int key normalization
      2. Check for missing / infinite / non-numeric values
      3. Coerce to float if valid

    Returns a float ready for np.digitize(), or None if the value should
    be rendered with nan_fill_color.

    This is the single authoritative path that style_function uses -
    no other code path should perform key lookup or value validation.
    """
    try:
        raw_value = normalize_key_lookup(color_data, key)
    except KeyError:
        return None

    if is_invalid_value(raw_value):
        return None

    try:
        return float(raw_value)
    except (TypeError, ValueError):
        return None


class ChoroplethDataBinder:
    """Unified data binding layer for Choropleth maps.

    Encapsulates the full pipeline:
      data (DataFrame/Series/dict)
        -> color_data dict (build_color_data)
        -> valid_values array (extract_valid_numeric_values, cached)
        -> bin_edges (compute_bin_edges)
        -> per-feature value resolution (resolve_value_for_coloring)

    Choropleth only deals with this class - no direct data processing
    logic should live in the rendering class.
    """

    def __init__(
        self,
        data: Any,
        columns: Sequence[Any] | None = None,
    ):
        self._color_data: dict | None = build_color_data(data, columns)
        self._valid_values: np.ndarray | None = None

    def has_data(self) -> bool:
        """Return True if color_data was successfully built."""
        return self._color_data is not None

    def get_color_data(self) -> dict | None:
        """Access the raw {key: value} dict (for debugging/inspection)."""
        return self._color_data

    def get_valid_numeric_values(self) -> np.ndarray:
        """Extract and cache valid numeric values for binning."""
        if self._valid_values is not None:
            return self._valid_values

        if self._color_data is None:
            self._valid_values = np.array([], dtype=float)
            return self._valid_values

        self._valid_values = extract_valid_numeric_values(self._color_data)
        return self._valid_values

    def compute_bins(
        self,
        bins: int | Sequence[float],
        use_jenks: bool = False,
    ) -> np.ndarray:
        """Compute bin edges for color scale.

        Thin wrapper around compute_bin_edges that uses the cached
        valid values from this binder instance.
        """
        return compute_bin_edges(
            self.get_valid_numeric_values(), bins, use_jenks
        )

    def lookup_value(self, key: Any) -> Any:
        """Raw key lookup with str/int normalization.

        Prefer get_value_for_coloring() for rendering - this method
        is exposed for cases where you need the unfiltered raw value.
        """
        if self._color_data is None:
            raise KeyError(key)
        return normalize_key_lookup(self._color_data, key)

    def get_value_for_coloring(self, key: Any) -> float | None:
        """Single-authority path for resolving a feature's color value.

        Returns None if the feature should use nan_fill_color.
        """
        if self._color_data is None:
            return None
        return resolve_value_for_coloring(self._color_data, key)
