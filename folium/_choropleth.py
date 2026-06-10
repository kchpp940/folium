"""
Internal Choropleth color mapping logic.

Combines the data binding layer (_data_binding) with GeoJSON key resolution
(_geojson_utils) and branca colormaps to produce a complete feature → color
pipeline. This module encapsulates all coloring decisions so that Choropleth
(features.py) only deals with layer assembly.

This is a private internal module - the public API is exposed through the
Choropleth class in folium.features.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from branca.colormap import StepColormap
from branca.utilities import color_brewer

from folium._data_binding import ChoroplethDataBinder
from folium._geojson_utils import resolve_dotted_key


class ChoroplethColorMapper:
    """Complete feature → color/style mapping for Choropleth maps.

    Encapsulates the full coloring pipeline:
      feature dict
        -> key_on path resolution (resolve_dotted_key)
        -> data binder value lookup (get_value_for_coloring)
        -> bin index (np.digitize)
        -> (fill_color, fill_opacity)

    Three states are handled uniformly:
      - No data at all      -> constant fill_color / fill_opacity
      - All values invalid  -> constant nan_fill_color / nan_fill_opacity
      - Valid values exist  -> StepColormap + nan fallback

    The ``color_scale`` property exposes the legend colormap (or None).
    """

    def __init__(
        self,
        data_binder: ChoroplethDataBinder,
        key_on: str | None,
        *,
        fill_color: str,
        nan_fill_color: str,
        fill_opacity: float,
        nan_fill_opacity: float,
        bins: int | Sequence[float],
        use_jenks: bool = False,
        legend_name: str = "",
    ):
        self._data_binder = data_binder
        self._key_on = self._normalize_key_on(key_on)
        self._fill_color = fill_color
        self._nan_fill_color = nan_fill_color
        self._fill_opacity = fill_opacity
        self._nan_fill_opacity = nan_fill_opacity
        self._bins = bins
        self._use_jenks = use_jenks
        self._legend_name = legend_name

        self._color_scale: StepColormap | None = None
        self._color_range: list[str] | None = None
        self._bin_edges: np.ndarray | None = None
        self._mode: str = "empty"

        self._build()

    @staticmethod
    def _normalize_key_on(key_on: str | None) -> str | None:
        """Strip leading "feature." prefix from key_on paths.

        Choropleth users pass paths like "feature.properties.id" where
        "feature" is a placeholder referring to the current GeoJSON
        feature dict. We strip it so that resolve_dotted_key works
        directly on the feature dict.
        """
        if key_on is None:
            return None
        if key_on.startswith("feature."):
            return key_on[8:]
        return key_on

    def _build(self) -> None:
        has_data = self._data_binder.has_data()
        has_key = self._key_on is not None

        if not has_data or not has_key:
            self._mode = "no_data"
            return

        real_values = self._data_binder.get_valid_numeric_values()

        if len(real_values) == 0:
            self._mode = "all_invalid"
            return

        bin_edges = self._data_binder.compute_bins(self._bins, self._use_jenks)
        self._bin_edges = bin_edges

        bins_min, bins_max = float(min(bin_edges)), float(max(bin_edges))

        nb_bins = len(bin_edges) - 1
        color_range = color_brewer(self._fill_color, n=nb_bins)
        self._color_range = color_range

        self._color_scale = StepColormap(
            color_range,
            index=list(bin_edges),
            vmin=bins_min,
            vmax=bins_max,
            caption=self._legend_name,
        )

        increasing = bin_edges[0] <= bin_edges[-1]
        bin_edges_float = bin_edges.astype(float)
        bin_edges_float[-1] = np.nextafter(
            bin_edges_float[-1], (1 if increasing else -1) * np.inf
        )
        self._bin_edges = bin_edges_float

        self._mode = "active"

    @property
    def color_scale(self) -> StepColormap | None:
        """The StepColormap for the legend, or None if not applicable."""
        return self._color_scale

    def get_fill_color_and_opacity(self, feature: dict) -> tuple[str, float]:
        """Return (fill_color, fill_opacity) for a single GeoJSON feature.

        This is the single authoritative entry point for coloring.
        All style_function variants should go through here.
        """
        if self._mode == "no_data":
            return self._fill_color, self._fill_opacity

        if self._mode == "all_invalid":
            return self._nan_fill_color, self._nan_fill_opacity

        assert self._key_on is not None
        assert self._bin_edges is not None
        assert self._color_range is not None

        key_of_x = resolve_dotted_key(feature, self._key_on)
        if key_of_x is None:
            raise ValueError(
                f"key_on {self._key_on!r} not found in GeoJSON."
            )

        value_float = self._data_binder.get_value_for_coloring(key_of_x)
        if value_float is None:
            return self._nan_fill_color, self._nan_fill_opacity

        color_idx = np.digitize(value_float, self._bin_edges, right=False) - 1
        return self._color_range[color_idx], self._fill_opacity
