"""
Test caption registry
---------------------

Tests for the Map-level CaptionRegistry, CaptionControl, CaptionMixin,
and normalize_layer_metadata() utility.
"""

import re

import pytest

import folium
from folium.elements import (
    CaptionMixin,
    CaptionRegistry,
    LayerMetadata,
    LegendItem,
    normalize_layer_metadata,
)
from folium.raster_layers import ImageOverlay, TileLayer, VideoOverlay
from folium.plugins import FloatImage


# ── helpers ──────────────────────────────────────────────────────────────────

_RASTER_DATA = [
    [[1, 0, 0, 1], [0, 0, 0, 0], [0, 0, 0, 0]],
    [[1, 1, 0, 0.5], [0, 0, 1, 1], [0, 0, 1, 1]],
]


def _render(m):
    return m.get_root().render()


def _count_caption_controls(html):
    return len(re.findall(r"var \S+ = L\.control\.caption", html))


# ── normalize_layer_metadata ─────────────────────────────────────────────────


class TestNormalizeLayerMetadata:
    def test_none_returns_none(self):
        assert normalize_layer_metadata(None) is None

    def test_empty_dict_returns_defaults(self):
        result = normalize_layer_metadata({})
        assert result == {
            "position": "bottomright",
            "collapsible": True,
            "collapsed": False,
        }

    def test_filters_none_values(self):
        result = normalize_layer_metadata({"title": "A", "unit": None})
        assert "title" in result
        assert "unit" not in result

    def test_full_metadata(self):
        meta = {
            "title": "Temperature",
            "description": "Surface temp",
            "unit": "degC",
            "resolution": "1km",
            "source_url": "https://example.com",
            "source_text": "Example",
            "updated_time": "2024-01-15",
            "copyright": "(c) 2024",
            "legend": [{"label": "Low", "color": "#0000ff"}],
            "collapsible": False,
            "collapsed": True,
            "position": "topleft",
        }
        result = normalize_layer_metadata(meta)
        assert result["title"] == "Temperature"
        assert result["position"] == "topleft"
        assert result["collapsible"] is False
        assert result["collapsed"] is True
        assert len(result["legend"]) == 1
        assert result["legend"][0]["label"] == "Low"

    def test_legend_validation_missing_keys(self):
        with pytest.raises(ValueError, match="must contain 'label' and 'color'"):
            normalize_layer_metadata({"legend": [{"label": "X"}]})

    def test_legend_validation_not_dict(self):
        with pytest.raises(ValueError, match="must contain 'label' and 'color'"):
            normalize_layer_metadata({"legend": ["not-a-dict"]})

    def test_legend_validation_not_list(self):
        with pytest.raises(TypeError, match="must be a list"):
            normalize_layer_metadata({"legend": "bad"})

    def test_legend_strips_extra_keys(self):
        result = normalize_layer_metadata(
            {"legend": [{"label": "A", "color": "#fff", "extra": 1}]}
        )
        assert result["legend"] == [{"label": "A", "color": "#fff"}]

    def test_legend_empty_list_dropped(self):
        result = normalize_layer_metadata({"legend": []})
        assert "legend" not in result

    def test_position_invalid(self):
        with pytest.raises(ValueError, match="must be one of"):
            normalize_layer_metadata({"position": "middle"})

    def test_position_valid_all(self):
        for pos in ("topleft", "topright", "bottomleft", "bottomright"):
            result = normalize_layer_metadata({"position": pos})
            assert result["position"] == pos

    def test_typed_dict_accepted(self):
        meta = LayerMetadata(title="T", unit="m")
        result = normalize_layer_metadata(meta)
        assert result["title"] == "T"
        assert result["unit"] == "m"

    def test_collapsible_truthy_coercion(self):
        result = normalize_layer_metadata({"collapsible": 1, "collapsed": 0})
        assert result["collapsible"] is True
        assert result["collapsed"] is False


# ── single layer, no caption (backward compatibility) ────────────────────────


class TestBackwardCompatibility:
    def test_no_caption_no_control(self):
        m = folium.Map()
        ImageOverlay(_RASTER_DATA, [[0, -180], [90, 180]], mercator_project=True).add_to(m)
        html = _render(m)
        assert "leaflet-control-caption" not in html

    def test_existing_params_preserved(self):
        m = folium.Map()
        io = ImageOverlay(
            _RASTER_DATA,
            [[0, -180], [90, 180]],
            opacity=0.7,
            alt="test",
            cross_origin="anonymous",
            mercator_project=True,
        )
        io.add_to(m)
        _render(m)
        assert io.bounds == [[0, -180], [90, 180]]
        assert io.options.get("opacity") == 0.7
        assert io.options.get("alt") == "test"
        assert io.options.get("cross_origin") == "anonymous"
        assert io.pixelated is True

    def test_no_caption_no_registry_on_map(self):
        m = folium.Map()
        ImageOverlay(_RASTER_DATA, [[0, -180], [90, 180]], mercator_project=True).add_to(m)
        _render(m)
        assert not hasattr(m, "_caption_registry")


# ── single layer with caption ────────────────────────────────────────────────


class TestSingleLayerCaption:
    def test_caption_content_in_html(self):
        m = folium.Map()
        ImageOverlay(
            _RASTER_DATA,
            [[0, -180], [90, 180]],
            caption={"title": "Temp", "unit": "degC"},
            mercator_project=True,
        ).add_to(m)
        html = _render(m)
        assert "Temp" in html
        assert "degC" in html

    def test_single_caption_control(self):
        m = folium.Map()
        ImageOverlay(
            _RASTER_DATA,
            [[0, -180], [90, 180]],
            caption={"title": "A"},
            mercator_project=True,
        ).add_to(m)
        html = _render(m)
        assert _count_caption_controls(html) == 1

    def test_registry_created_on_map(self):
        m = folium.Map()
        ImageOverlay(
            _RASTER_DATA,
            [[0, -180], [90, 180]],
            caption={"title": "X"},
            mercator_project=True,
        ).add_to(m)
        _render(m)
        assert hasattr(m, "_caption_registry")
        assert isinstance(m._caption_registry, CaptionRegistry)


# ── multiple layers ──────────────────────────────────────────────────────────


class TestMultipleLayers:
    def test_one_control_for_multiple_layers(self):
        m = folium.Map()
        ImageOverlay(
            _RASTER_DATA, [[0, -180], [45, 180]],
            caption={"title": "L1"}, mercator_project=True, name="L1",
        ).add_to(m)
        ImageOverlay(
            _RASTER_DATA, [[45, -180], [90, 180]],
            caption={"title": "L2"}, mercator_project=True, name="L2",
        ).add_to(m)
        html = _render(m)
        assert _count_caption_controls(html) == 1
        assert "L1" in html
        assert "L2" in html

    def test_mixed_layer_types(self):
        m = folium.Map()
        TileLayer(
            "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
            attr="OSM",
            caption={"title": "Base Map"},
        ).add_to(m)
        ImageOverlay(
            _RASTER_DATA, [[0, -180], [90, 180]],
            caption={"title": "Overlay"}, mercator_project=True, name="Overlay",
        ).add_to(m)
        FloatImage(
            "https://example.com/img.png",
            caption={"title": "Legend"},
        ).add_to(m)
        html = _render(m)
        assert _count_caption_controls(html) == 1
        assert "Base Map" in html
        assert "Overlay" in html
        assert "Legend" in html

    def test_sections_with_separators(self):
        m = folium.Map()
        ImageOverlay(
            _RASTER_DATA, [[0, -180], [45, 180]],
            caption={"title": "L1"}, mercator_project=True, name="L1",
        ).add_to(m)
        ImageOverlay(
            _RASTER_DATA, [[45, -180], [90, 180]],
            caption={"title": "L2"}, mercator_project=True, name="L2",
        ).add_to(m)
        html = _render(m)
        assert "caption-section" in html
        assert "caption-section:last-child" in html


# ── show=False ───────────────────────────────────────────────────────────────


class TestShowFalse:
    def test_show_false_still_registers(self):
        m = folium.Map()
        ImageOverlay(
            _RASTER_DATA, [[0, -180], [90, 180]],
            caption={"title": "Hidden"}, show=False, mercator_project=True,
        ).add_to(m)
        html = _render(m)
        assert "Hidden" in html
        assert "setInitialVisible" in html

    def test_show_false_initial_visible_false(self):
        m = folium.Map()
        ImageOverlay(
            _RASTER_DATA, [[0, -180], [90, 180]],
            caption={"title": "Hidden"}, show=False, mercator_project=True,
        ).add_to(m)
        html = _render(m)
        matches = re.findall(
            r'setInitialVisible\([^,]+,\s*(true|false)', html
        )
        assert "false" in matches

    def test_show_true_initial_visible_true(self):
        m = folium.Map()
        ImageOverlay(
            _RASTER_DATA, [[0, -180], [90, 180]],
            caption={"title": "Visible"}, show=True, mercator_project=True,
        ).add_to(m)
        html = _render(m)
        matches = re.findall(
            r'setInitialVisible\([^,]+,\s*(true|false)', html
        )
        assert "true" in matches


# ── add_child path ───────────────────────────────────────────────────────────


class TestAddChildPath:
    def test_add_child_registers_caption(self):
        m = folium.Map()
        io = ImageOverlay(
            _RASTER_DATA, [[0, -180], [90, 180]],
            caption={"title": "Child Added"}, mercator_project=True,
        )
        m.add_child(io)
        html = _render(m)
        assert "Child Added" in html

    def test_add_child_single_control(self):
        m = folium.Map()
        io1 = ImageOverlay(
            _RASTER_DATA, [[0, -180], [90, 180]],
            caption={"title": "A"}, mercator_project=True,
        )
        io1.add_to(m)
        io2 = ImageOverlay(
            _RASTER_DATA, [[0, -180], [90, 180]],
            caption={"title": "B"}, mercator_project=True,
        )
        m.add_child(io2)
        html = _render(m)
        assert _count_caption_controls(html) == 1
        assert "A" in html
        assert "B" in html


# ── layer add/remove events ─────────────────────────────────────────────────


class TestLayerControlEvents:
    def test_add_remove_listeners_present(self):
        m = folium.Map()
        ImageOverlay(
            _RASTER_DATA, [[0, -180], [90, 180]],
            caption={"title": "L"}, mercator_project=True,
        ).add_to(m)
        html = _render(m)
        assert "layerVar.on('add'" in html
        assert "layerVar.on('remove'" in html

    def test_registry_update_logic(self):
        m = folium.Map()
        ImageOverlay(
            _RASTER_DATA, [[0, -180], [90, 180]],
            caption={"title": "L"}, mercator_project=True,
        ).add_to(m)
        html = _render(m)
        assert "_update" in html
        assert "setVisibleLayers" in html
        assert "visibleOrder" in html


# ── TileLayer with caption ───────────────────────────────────────────────────


class TestTileLayerCaption:
    def test_tile_layer_caption(self):
        m = folium.Map()
        TileLayer(
            "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
            attr="OSM",
            caption={"title": "Base", "unit": "N/A"},
        ).add_to(m)
        html = _render(m)
        assert "Base" in html
        assert "L.tileLayer" in html


# ── VideoOverlay with caption ────────────────────────────────────────────────


class TestVideoOverlayCaption:
    def test_video_overlay_caption(self):
        m = folium.Map()
        VideoOverlay(
            "https://example.com/video.mp4",
            [[0, 0], [1, 1]],
            caption={"title": "Video", "description": "Test video"},
        ).add_to(m)
        html = _render(m)
        assert "Video" in html
        assert "L.videoOverlay" in html


# ── FloatImage with caption ──────────────────────────────────────────────────


class TestFloatImageCaption:
    def test_float_image_caption(self):
        m = folium.Map([45.0, 3.0], zoom_start=4)
        FloatImage(
            "https://example.com/img.png",
            bottom=60, left=70, width="20%",
            caption={"title": "Compass Rose"},
        ).add_to(m)
        html = _render(m)
        assert "Compass Rose" in html
        assert "float_image" in html


# ── TypedDict vs dict parity ─────────────────────────────────────────────────


class TestTypedDictParity:
    def test_typed_dict_same_as_dict(self):
        dict_result = normalize_layer_metadata({"title": "T", "unit": "m"})
        td_result = normalize_layer_metadata(LayerMetadata(title="T", unit="m"))
        assert dict_result == td_result

    def test_image_overlay_with_layer_metadata(self):
        m = folium.Map()
        meta = LayerMetadata(title="Typed", unit="degC")
        ImageOverlay(
            _RASTER_DATA, [[0, -180], [90, 180]],
            caption=meta, mercator_project=True,
        ).add_to(m)
        html = _render(m)
        assert "Typed" in html


# ── empty state ──────────────────────────────────────────────────────────────


class TestEmptyState:
    def test_empty_state_message(self):
        m = folium.Map()
        ImageOverlay(
            _RASTER_DATA, [[0, -180], [90, 180]],
            caption={"title": "L"}, mercator_project=True, show=False,
        ).add_to(m)
        html = _render(m)
        assert "No active layer metadata" in html
        assert "caption-empty" in html


# ── collapsed / collapsible ──────────────────────────────────────────────────


class TestCollapsibleCollapsed:
    def test_collapsed_class(self):
        m = folium.Map()
        ImageOverlay(
            _RASTER_DATA, [[0, -180], [90, 180]],
            caption={"title": "C", "collapsed": True},
            mercator_project=True,
        ).add_to(m)
        html = _render(m)
        assert "caption-collapsed" in html

    def test_toggle_present_when_collapsible(self):
        m = folium.Map()
        ImageOverlay(
            _RASTER_DATA, [[0, -180], [90, 180]],
            caption={"title": "C", "collapsible": True},
            mercator_project=True,
        ).add_to(m)
        html = _render(m)
        assert "caption-toggle" in html
