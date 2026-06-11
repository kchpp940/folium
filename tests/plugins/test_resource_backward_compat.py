"""
Strict backward-compatibility assertions for the Resource migration.

For every plugin converted from the legacy (default_js, default_css)
tuple-list format to Resource descriptors, this test hard-codes the
*original* tuple lists as they were before the migration and asserts
that ``build_defaults(Plugin.resources)`` reproduces them exactly.

This guards against three types of regression that simple import/count
checks miss:

* ``name``s that drift (e.g. a typo introduced while adding metadata).
* ``url``s that drift (e.g. a CDN host or version number accidentally
  changed while filling in ``package`` / ``version``).
* Order changes that break load-order contracts between inter-dependent
  libraries such as ``jquery < jquery-ui < leaflet-timedimension``.

When a plugin's default_js / default_css *intentionally* changes, this
is the single file that must be updated alongside the plugin module.
"""

from __future__ import annotations

from typing import Type

import pytest

from folium.elements import JSCSSMixin
from folium.plugins import (
    AntPath,
    BeautifyIcon,
    BoatMarker,
    CirclePattern,
    Draw,
    DualMap,
    FeatureGroupSubGroup,
    Fullscreen,
    Geocoder,
    GeoMan,
    GroupedLayerControl,
    HeatMap,
    HeatMapWithTime,
    LocateControl,
    MarkerCluster,
    MeasureControl,
    MiniMap,
    MousePosition,
    OverlappingMarkerSpiderfier,
    PolyLineFromEncoded,
    PolyLineOffset,
    PolyLineTextPath,
    PolygonFromEncoded,
    Realtime,
    Search,
    SemiCircle,
    SideBySideLayers,
    StripePattern,
    TagFilterButton,
    Terminator,
    TimeSliderChoropleth,
    Timeline,
    TimelineSlider,
    TimestampedGeoJson,
    TimestampedWmsTileLayers,
    TreeLayerControl,
    VectorGridProtobuf,
    WebGLEarth,
)


# ---------------------------------------------------------------------------
# Mapping: plugin class -> (original_default_js, original_default_css)
#
# These values were copied verbatim from the codebase BEFORE the
# Resource descriptor migration was introduced.  Do NOT derive them
# from the Resource descriptors – that would defeat the point of the
# test.
# ---------------------------------------------------------------------------

ORIGINAL_RESOURCES: dict[Type[JSCSSMixin], tuple[list[tuple[str, str]], list[tuple[str, str]]]] = {

    # ------------------------------------------------------------------
    # Single JS resource plugins
    # ------------------------------------------------------------------

    AntPath: (
        [("antpath", "https://cdn.jsdelivr.net/npm/leaflet-ant-path@1.1.2/dist/leaflet-ant-path.min.js")],
        [],
    ),

    BoatMarker: (
        [("markerclusterjs", "https://unpkg.com/leaflet.boatmarker/leaflet.boatmarker.min.js")],
        [],
    ),

    DualMap: (
        [("Leaflet.Sync", "https://cdn.jsdelivr.net/gh/jieter/Leaflet.Sync/L.Map.Sync.min.js")],
        [],
    ),

    # _BaseFromEncoded → both PolyLineFromEncoded / PolygonFromEncoded share it
    PolyLineFromEncoded: (
        [("polyline-encoded", "https://cdn.jsdelivr.net/npm/polyline-encoded@0.0.9/Polyline.encoded.js")],
        [],
    ),
    PolygonFromEncoded: (
        [("polyline-encoded", "https://cdn.jsdelivr.net/npm/polyline-encoded@0.0.9/Polyline.encoded.js")],
        [],
    ),

    FeatureGroupSubGroup: (
        [("featuregroupsubgroupjs", "https://unpkg.com/leaflet.featuregroup.subgroup@1.0.2/dist/leaflet.featuregroup.subgroup.js")],
        [],
    ),

    OverlappingMarkerSpiderfier: (
        [("overlappingmarkerjs", "https://cdnjs.cloudflare.com/ajax/libs/OverlappingMarkerSpiderfier-Leaflet/0.2.6/oms.min.js")],
        [],
    ),

    # StripePattern / CirclePattern both had identical single-JS resource
    StripePattern: (
        [("pattern", "https://teastman.github.io/Leaflet.pattern/leaflet.pattern.js")],
        [],
    ),
    CirclePattern: (
        [("pattern", "https://teastman.github.io/Leaflet.pattern/leaflet.pattern.js")],
        [],
    ),

    PolyLineOffset: (
        [("polylineoffset", "https://cdn.jsdelivr.net/npm/leaflet-polylineoffset@1.1.1/leaflet.polylineoffset.min.js")],
        [],
    ),

    PolyLineTextPath: (
        [("polylinetextpath", "https://cdn.jsdelivr.net/npm/leaflet-textpath@1.2.3/leaflet.textpath.min.js")],
        [],
    ),

    Realtime: (
        [("Leaflet_Realtime_js", "https://cdnjs.cloudflare.com/ajax/libs/leaflet-realtime/2.2.0/leaflet-realtime.js")],
        [],
    ),

    SemiCircle: (
        [("semicirclejs", "https://cdn.jsdelivr.net/npm/leaflet-semicircle@2.0.4/Semicircle.min.js")],
        [],
    ),

    SideBySideLayers: (
        [("leaflet.sidebyside", "https://cdn.jsdelivr.net/gh/digidem/leaflet-side-by-side@2.0.0/leaflet-side-by-side.min.js")],
        [],
    ),

    Terminator: (
        [("terminator", "https://unpkg.com/@joergdietrich/leaflet.terminator")],
        [],
    ),

    VectorGridProtobuf: (
        [("vectorGrid", "https://unpkg.com/leaflet.vectorgrid@latest/dist/Leaflet.VectorGrid.bundled.js")],
        [],
    ),

    WebGLEarth: (
        [("webglearth_v2_js", "https://www.webglearth.com/v2/api.js")],
        [],
    ),

    # ------------------------------------------------------------------
    # JS + CSS (1 each) – standard plugins
    # ------------------------------------------------------------------

    BeautifyIcon: (
        [("beautify_icon_js", "https://cdn.jsdelivr.net/gh/marslan390/BeautifyMarker/leaflet-beautify-marker-icon.min.js")],
        [("beautify_icon_css", "https://cdn.jsdelivr.net/gh/marslan390/BeautifyMarker/leaflet-beautify-marker-icon.min.css")],
    ),

    Draw: (
        [("leaflet_draw_js", "https://cdnjs.cloudflare.com/ajax/libs/leaflet.draw/1.0.2/leaflet.draw.js")],
        [("leaflet_draw_css", "https://cdnjs.cloudflare.com/ajax/libs/leaflet.draw/1.0.2/leaflet.draw.css")],
    ),

    Fullscreen: (
        [("Control.Fullscreen.js", "https://cdn.jsdelivr.net/npm/leaflet.fullscreen@3.0.0/Control.FullScreen.min.js")],
        [("Control.FullScreen.css", "https://cdn.jsdelivr.net/npm/leaflet.fullscreen@3.0.0/Control.FullScreen.css")],
    ),

    Geocoder: (
        [("Control.Geocoder.js", "https://unpkg.com/leaflet-control-geocoder/dist/Control.Geocoder.js")],
        [("Control.Geocoder.css", "https://unpkg.com/leaflet-control-geocoder/dist/Control.Geocoder.css")],
    ),

    GeoMan: (
        [("leaflet_geoman_js", "https://unpkg.com/@geoman-io/leaflet-geoman-free@latest/dist/leaflet-geoman.js")],
        [("leaflet_geoman_css", "https://unpkg.com/@geoman-io/leaflet-geoman-free@latest/dist/leaflet-geoman.css")],
    ),

    GroupedLayerControl: (
        [("leaflet.groupedlayercontrol.min.js", "https://cdnjs.cloudflare.com/ajax/libs/leaflet-groupedlayercontrol/0.6.1/leaflet.groupedlayercontrol.min.js")],
        [("leaflet.groupedlayercontrol.min.css", "https://cdnjs.cloudflare.com/ajax/libs/leaflet-groupedlayercontrol/0.6.1/leaflet.groupedlayercontrol.min.css")],
    ),

    LocateControl: (
        [("Control_locate_min_js", "https://cdnjs.cloudflare.com/ajax/libs/leaflet-locatecontrol/0.66.2/L.Control.Locate.min.js")],
        [("Control_locate_min_css", "https://cdnjs.cloudflare.com/ajax/libs/leaflet-locatecontrol/0.66.2/L.Control.Locate.min.css")],
    ),

    MeasureControl: (
        [("leaflet_measure_js", "https://cdn.jsdelivr.net/gh/ljagis/leaflet-measure@2.1.7/dist/leaflet-measure.min.js")],
        [("leaflet_measure_css", "https://cdn.jsdelivr.net/gh/ljagis/leaflet-measure@2.1.7/dist/leaflet-measure.min.css")],
    ),

    MiniMap: (
        [("Control_MiniMap_js", "https://cdnjs.cloudflare.com/ajax/libs/leaflet-minimap/3.6.1/Control.MiniMap.js")],
        [("Control_MiniMap_css", "https://cdnjs.cloudflare.com/ajax/libs/leaflet-minimap/3.6.1/Control.MiniMap.css")],
    ),

    MousePosition: (
        [("Control_MousePosition_js", "https://cdn.jsdelivr.net/gh/ardhi/Leaflet.MousePosition/src/L.Control.MousePosition.min.js")],
        [("Control_MousePosition_css", "https://cdn.jsdelivr.net/gh/ardhi/Leaflet.MousePosition/src/L.Control.MousePosition.min.css")],
    ),

    Search: (
        [("Leaflet.Search.js", "https://cdn.jsdelivr.net/npm/leaflet-search@2.9.7/dist/leaflet-search.min.js")],
        [("Leaflet.Search.css", "https://cdn.jsdelivr.net/npm/leaflet-search@2.9.7/dist/leaflet-search.min.css")],
    ),

    TreeLayerControl: (
        [("L.Control.Layers.Tree.min.js", "https://cdn.jsdelivr.net/npm/leaflet.control.layers.tree@1.1.0/L.Control.Layers.Tree.min.js")],
        [("L.Control.Layers.Tree.min.css", "https://cdn.jsdelivr.net/npm/leaflet.control.layers.tree@1.1.0/L.Control.Layers.Tree.min.css")],
    ),

    # ------------------------------------------------------------------
    # Multi-JS / multi-CSS plugins
    # ------------------------------------------------------------------

    HeatMap: (
        [("leaflet-heat.js", "https://cdn.jsdelivr.net/gh/python-visualization/folium@main/folium/templates/leaflet_heat.min.js")],
        [],
    ),

    MarkerCluster: (
        [("markerclusterjs", "https://cdnjs.cloudflare.com/ajax/libs/leaflet.markercluster/1.1.0/leaflet.markercluster.js")],
        [
            ("markerclustercss", "https://cdnjs.cloudflare.com/ajax/libs/leaflet.markercluster/1.1.0/MarkerCluster.css"),
            ("markerclusterdefaultcss", "https://cdnjs.cloudflare.com/ajax/libs/leaflet.markercluster/1.1.0/MarkerCluster.Default.css"),
        ],
    ),

    HeatMapWithTime: (
        [
            ("iso8601", "https://cdn.jsdelivr.net/npm/iso8601-js-period@0.2.1/iso8601.min.js"),
            ("leaflet.timedimension.min.js", "https://cdn.jsdelivr.net/npm/leaflet-timedimension@1.1.1/dist/leaflet.timedimension.min.js"),
            ("heatmap.min.js", "https://cdn.jsdelivr.net/gh/python-visualization/folium/folium/templates/pa7_hm.min.js"),
            ("leaflet-heatmap.js", "https://cdn.jsdelivr.net/gh/python-visualization/folium/folium/templates/pa7_leaflet_hm.min.js"),
        ],
        [
            ("leaflet.timedimension.control.min.css", "https://cdn.jsdelivr.net/npm/leaflet-timedimension@1.1.1/dist/leaflet.timedimension.control.css"),
        ],
    ),

    TagFilterButton: (
        [
            ("tag-filter-button.js", "https://cdn.jsdelivr.net/npm/leaflet-tag-filter-button/src/leaflet-tag-filter-button.js"),
            ("easy-button.js", "https://cdn.jsdelivr.net/npm/leaflet-easybutton@2/src/easy-button.js"),
        ],
        [
            ("tag-filter-button.css", "https://cdn.jsdelivr.net/npm/leaflet-tag-filter-button/src/leaflet-tag-filter-button.css"),
            ("easy-button.css", "https://cdn.jsdelivr.net/npm/leaflet-easybutton@2/src/easy-button.css"),
            ("ripples.min.css", "https://cdn.jsdelivr.net/npm/css-ripple-effect@1.0.5/dist/ripple.min.css"),
        ],
    ),

    TimeSliderChoropleth: (
        [
            ("d3v4", "https://d3js.org/d3.v4.min.js"),
            ("moment", "https://cdnjs.cloudflare.com/ajax/libs/moment.js/2.18.1/moment.min.js"),
        ],
        [],
    ),

    Timeline: (
        [
            ("timeline", "https://cdn.jsdelivr.net/npm/leaflet.timeline@1.6.0/dist/leaflet.timeline.min.js"),
            ("moment", "https://cdnjs.cloudflare.com/ajax/libs/moment.js/2.18.1/moment.min.js"),
        ],
        [],
    ),
    TimelineSlider: (
        [
            ("timeline", "https://cdn.jsdelivr.net/npm/leaflet.timeline@1.6.0/dist/leaflet.timeline.min.js"),
            ("moment", "https://cdnjs.cloudflare.com/ajax/libs/moment.js/2.18.1/moment.min.js"),
        ],
        [],
    ),

    TimestampedGeoJson: (
        [
            ("jquery3.7.1", "https://cdnjs.cloudflare.com/ajax/libs/jquery/3.7.1/jquery.min.js"),
            ("jqueryui1.10.2", "https://cdnjs.cloudflare.com/ajax/libs/jqueryui/1.10.2/jquery-ui.min.js"),
            ("iso8601", "https://cdn.jsdelivr.net/npm/iso8601-js-period@0.2.1/iso8601.min.js"),
            ("leaflet.timedimension", "https://cdn.jsdelivr.net/npm/leaflet-timedimension@1.1.1/dist/leaflet.timedimension.min.js"),
            ("moment", "https://cdnjs.cloudflare.com/ajax/libs/moment.js/2.18.1/moment.min.js"),
        ],
        [
            ("highlight.js_css", "https://cdnjs.cloudflare.com/ajax/libs/highlight.js/8.4/styles/default.min.css"),
            ("leaflet.timedimension_css", "https://cdn.jsdelivr.net/npm/leaflet-timedimension@1.1.1/dist/leaflet.timedimension.control.css"),
        ],
    ),

    TimestampedWmsTileLayers: (
        [
            ("jquery3.7.1", "https://cdnjs.cloudflare.com/ajax/libs/jquery/3.7.1/jquery.min.js"),
            ("jqueryui1.10.2", "https://cdnjs.cloudflare.com/ajax/libs/jqueryui/1.10.2/jquery-ui.min.js"),
            ("iso8601", "https://cdn.jsdelivr.net/npm/iso8601-js-period@0.2.1/iso8601.min.js"),
            ("leaflet.timedimension", "https://cdn.jsdelivr.net/npm/leaflet-timedimension@1.1.1/dist/leaflet.timedimension.min.js"),
        ],
        [
            ("highlight.js_css", "https://cdnjs.cloudflare.com/ajax/libs/highlight.js/8.4/styles/default.min.css"),
            ("leaflet.timedimension_css", "https://cdn.jsdelivr.net/npm/leaflet-timedimension@1.1.1/dist/leaflet.timedimension.control.css"),
        ],
    ),
}


@pytest.mark.parametrize(
    "plugin_cls",
    list(ORIGINAL_RESOURCES.keys()),
    ids=[cls.__name__ for cls in ORIGINAL_RESOURCES.keys()],
)
def test_defaults_match_original_tuples(plugin_cls):
    """Each migrated plugin's defaults must reproduce its legacy tuple lists."""

    expected_js, expected_css = ORIGINAL_RESOURCES[plugin_cls]

    assert hasattr(plugin_cls, "resources"), (
        f"{plugin_cls.__name__} does not declare a 'resources' class attribute; "
        f"it is either not yet migrated or is a subclass that should inherit."
    )

    assert hasattr(plugin_cls, "default_js")
    assert hasattr(plugin_cls, "default_css")

    actual_js = list(plugin_cls.default_js)
    actual_css = list(plugin_cls.default_css)

    assert actual_js == expected_js, (
        f"{plugin_cls.__name__}.default_js does not match the legacy tuple list.\n"
        f"  Expected: {expected_js}\n"
        f"  Got:      {actual_js}"
    )
    assert actual_css == expected_css, (
        f"{plugin_cls.__name__}.default_css does not match the legacy tuple list.\n"
        f"  Expected: {expected_css}\n"
        f"  Got:      {actual_css}"
    )


def test_all_jscss_covered():
    """Every exported JSCSSMixin subclass that declares its own 'resources'
    must appear in ORIGINAL_RESOURCES.

    This guards against adding a new Resource-based plugin and forgetting
    to register its legacy tuple list here.

    Subclasses that merely *inherit* resources from a parent (without
    overriding) are checked implicitly when the parent entry is verified,
    but entries in ORIGINAL_RESOURCES are intentionally allowed to include
    them – some tests do want to assert inherited resources are identical.
    """

    import folium.plugins as pkg

    covered = {cls.__name__ for cls in ORIGINAL_RESOURCES}
    exported_own_resources = set()

    for attr_name in dir(pkg):
        if attr_name.startswith("_"):
            continue
        obj = getattr(pkg, attr_name)
        if not isinstance(obj, type):
            continue
        if not issubclass(obj, JSCSSMixin):
            continue
        res = getattr(obj, "resources", None)
        if res is None:
            continue
        if "resources" in obj.__dict__:
            exported_own_resources.add(obj.__name__)

    missing = exported_own_resources - covered
    assert not missing, (
        f"These plugins declare their own 'resources' class attribute but "
        f"are missing from ORIGINAL_RESOURCES: {sorted(missing)}.  Please "
        f"add an entry for each to test_resource_backward_compat.py."
    )


def test_add_js_link_still_mutates_default_js():
    """JSCSSMixin mutates default_js via add_js_link – contract must survive.

    NOTE: add_js_link mutates the *class attribute* list in-place on
    JSCSSMixin's side, so we must save and restore the class-level list
    to avoid polluting other tests.
    """
    original_class_js = list(MarkerCluster.default_js)
    try:
        m = MarkerCluster()
        m.add_js_link("markerclusterjs", "https://override.example.com/new.js")

        assert MarkerCluster.default_js == [
            ("markerclusterjs", "https://override.example.com/new.js")
        ], "add_js_link did not override the existing entry in default_js."
        assert list(m.default_css) == list(MarkerCluster.default_css), (
            "default_css should be unchanged by add_js_link."
        )
    finally:
        MarkerCluster.default_js[:] = original_class_js


def test_add_css_link_still_mutates_default_css():
    """JSCSSMixin mutates default_css via add_css_link – contract must survive."""
    original_class_css = list(MiniMap.default_css)
    try:
        m = MiniMap()
        m.add_css_link("Control_MiniMap_css", "https://override.example.com/new.css")

        assert MiniMap.default_css == [
            ("Control_MiniMap_css", "https://override.example.com/new.css")
        ], "add_css_link did not override the existing entry in default_css."
    finally:
        MiniMap.default_css[:] = original_class_css


def test_add_js_link_appends_new_name():
    """add_js_link with a previously-unseen name appends (legacy contract)."""
    original_class_js = list(Fullscreen.default_js)
    try:
        m = Fullscreen()
        count_before = len(Fullscreen.default_js)
        m.add_js_link("new_extra", "https://extra.example.com/script.js")
        count_after = len(Fullscreen.default_js)
        assert count_after == count_before + 1, (
            "add_js_link with a new name should append a tuple to default_js."
        )
        assert Fullscreen.default_js[-1] == (
            "new_extra", "https://extra.example.com/script.js"
        )
    finally:
        Fullscreen.default_js[:] = original_class_js
