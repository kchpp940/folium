"""
Regression tests: verify that rendered HTML resource link order
matches expected snapshots for multi-resource plugins.

These tests ensure the Resource → build_defaults → JSCSSMixin pipeline
produces the same <script>/<link> output as the old hand-written
default_js / default_css tuple lists.
"""

import re

import folium
from folium import plugins
from folium.utilities import normalize


def _extract_resource_tags(html: str) -> list[str]:
    """Extract all <script src=...> and <link rel="stylesheet" ...> tags in order."""
    pattern = re.compile(
        r'<script src="[^"]+"></script>'
        r'|<link rel="stylesheet" href="[^"]+"/?>'
    )
    return pattern.findall(html)


def _js_tag(url: str) -> str:
    return f'<script src="{url}"></script>'


def _css_tag(url: str) -> str:
    return f'<link rel="stylesheet" href="{url}"/>'


class TestFullscreenHtmlOrder:
    def test_js_css_order(self):
        m = folium.Map([47, 3], zoom_start=1)
        plugins.Fullscreen().add_to(m)
        out = normalize(m._parent.render())

        tags = _extract_resource_tags(out)
        expected = [
            _js_tag(
                "https://cdn.jsdelivr.net/npm/leaflet.fullscreen@3.0.0/"
                "Control.FullScreen.min.js"
            ),
            _css_tag(
                "https://cdn.jsdelivr.net/npm/leaflet.fullscreen@3.0.0/"
                "Control.FullScreen.css"
            ),
        ]
        for tag in expected:
            assert tag in tags, f"Missing resource tag: {tag}"

        js_idx = tags.index(expected[0])
        css_idx = tags.index(expected[1])
        assert js_idx < css_idx, "Fullscreen JS must load before its CSS"


class TestDrawHtmlOrder:
    def test_js_css_order(self):
        m = folium.Map([47, 3], zoom_start=1)
        plugins.Draw().add_to(m)
        out = normalize(m._parent.render())

        tags = _extract_resource_tags(out)
        expected = [
            _js_tag(
                "https://cdnjs.cloudflare.com/ajax/libs/leaflet.draw/1.0.2/"
                "leaflet.draw.js"
            ),
            _css_tag(
                "https://cdnjs.cloudflare.com/ajax/libs/leaflet.draw/1.0.2/"
                "leaflet.draw.css"
            ),
        ]
        for tag in expected:
            assert tag in tags, f"Missing resource tag: {tag}"

        js_idx = tags.index(expected[0])
        css_idx = tags.index(expected[1])
        assert js_idx < css_idx, "Draw JS must load before its CSS"


class TestMarkerClusterHtmlOrder:
    def test_js_css_order(self):
        m = folium.Map([45, 3], zoom_start=4)
        plugins.MarkerCluster([[45, 3]]).add_to(m)
        out = normalize(m._parent.render())

        tags = _extract_resource_tags(out)
        expected = [
            _js_tag(
                "https://cdnjs.cloudflare.com/ajax/libs/"
                "leaflet.markercluster/1.1.0/leaflet.markercluster.js"
            ),
            _css_tag(
                "https://cdnjs.cloudflare.com/ajax/libs/"
                "leaflet.markercluster/1.1.0/MarkerCluster.css"
            ),
            _css_tag(
                "https://cdnjs.cloudflare.com/ajax/libs/"
                "leaflet.markercluster/1.1.0/MarkerCluster.Default.css"
            ),
        ]
        for tag in expected:
            assert tag in tags, f"Missing resource tag: {tag}"

        js_idx = tags.index(expected[0])
        css1_idx = tags.index(expected[1])
        css2_idx = tags.index(expected[2])
        assert js_idx < css1_idx < css2_idx, (
            "MarkerCluster: JS → CSS1 → CSS2 load order violated"
        )


class TestHeatMapWithTimeHtmlOrder:
    def test_dependency_before_plugin(self):
        import numpy as np
        np.random.seed(42)
        data = np.random.normal(size=(10, 2)).tolist()
        data = [data]

        m = folium.Map([48, 5], zoom_start=6)
        plugins.HeatMapWithTime(data).add_to(m)
        out = normalize(m._parent.render())

        tags = _extract_resource_tags(out)
        expected_js = [
            _js_tag(
                "https://cdn.jsdelivr.net/npm/iso8601-js-period@0.2.1/"
                "iso8601.min.js"
            ),
            _js_tag(
                "https://cdn.jsdelivr.net/npm/leaflet-timedimension@1.1.1/"
                "dist/leaflet.timedimension.min.js"
            ),
            _js_tag(
                "https://cdn.jsdelivr.net/gh/python-visualization/folium/"
                "folium/templates/pa7_hm.min.js"
            ),
            _js_tag(
                "https://cdn.jsdelivr.net/gh/python-visualization/folium/"
                "folium/templates/pa7_leaflet_hm.min.js"
            ),
        ]
        expected_css = [
            _css_tag(
                "https://cdn.jsdelivr.net/npm/leaflet-timedimension@1.1.1/"
                "dist/leaflet.timedimension.control.css"
            ),
        ]

        all_expected = expected_js + expected_css
        for tag in all_expected:
            assert tag in tags, f"Missing resource tag: {tag}"

        indices = [tags.index(t) for t in expected_js]
        assert indices == sorted(indices), (
            f"HeatMapWithTime JS resources not in declaration order: {indices}"
        )

        for js_tag_item in expected_js:
            for css_tag_item in expected_css:
                assert tags.index(js_tag_item) < tags.index(css_tag_item), (
                    "HeatMapWithTime: all JS must load before CSS"
                )


class TestTimestampedGeoJsonHtmlOrder:
    def test_full_resource_chain(self):
        import numpy as np

        data = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [0, 0]},
                    "properties": {"times": [1435708800000]},
                }
            ],
        }
        m = folium.Map([47, 3], zoom_start=1)
        plugins.TimestampedGeoJson(data).add_to(m)
        out = normalize(m._parent.render())

        tags = _extract_resource_tags(out)

        expected_js = [
            _js_tag(
                "https://cdnjs.cloudflare.com/ajax/libs/jquery/3.7.1/"
                "jquery.min.js"
            ),
            _js_tag(
                "https://cdnjs.cloudflare.com/ajax/libs/jqueryui/1.10.2/"
                "jquery-ui.min.js"
            ),
            _js_tag(
                "https://cdn.jsdelivr.net/npm/iso8601-js-period@0.2.1/"
                "iso8601.min.js"
            ),
            _js_tag(
                "https://cdn.jsdelivr.net/npm/leaflet-timedimension@1.1.1/"
                "dist/leaflet.timedimension.min.js"
            ),
            _js_tag(
                "https://cdnjs.cloudflare.com/ajax/libs/moment.js/2.18.1/"
                "moment.min.js"
            ),
        ]
        expected_css = [
            _css_tag(
                "https://cdnjs.cloudflare.com/ajax/libs/highlight.js/8.4/"
                "styles/default.min.css"
            ),
            _css_tag(
                "https://cdn.jsdelivr.net/npm/leaflet-timedimension@1.1.1/"
                "dist/leaflet.timedimension.control.css"
            ),
        ]

        all_expected = expected_js + expected_css
        for tag in all_expected:
            assert tag in tags, f"Missing resource tag: {tag}"

        js_indices = [tags.index(t) for t in expected_js]
        assert js_indices == sorted(js_indices), (
            f"TimestampedGeoJson JS not in declaration order: {js_indices}"
        )

        for js_tag_item in expected_js:
            for css_tag_item in expected_css:
                assert tags.index(js_tag_item) < tags.index(css_tag_item), (
                    "TimestampedGeoJson: all JS must load before CSS"
                )


class TestDrawResourceMetadata:
    def test_resource_fields_populated(self):
        res = plugins.Draw.resources
        assert len(res) == 2
        for r in res:
            assert r.plugin == "Draw"
            assert r.package == "leaflet.draw"
            assert r.version == "1.0.2"
            assert r.kind == "plugin"


class TestMarkerClusterResourceMetadata:
    def test_resource_fields_populated(self):
        res = plugins.MarkerCluster.resources
        assert len(res) == 3
        for r in res:
            assert r.plugin == "MarkerCluster"
            assert r.package == "leaflet.markercluster"
            assert r.version == "1.1.0"
            assert r.kind == "plugin"


class TestHeatMapWithTimeResourceMetadata:
    def test_dependency_vs_plugin_kind(self):
        res = plugins.HeatMapWithTime.resources
        plugin_resources = [r for r in res if r.kind == "plugin"]
        dep_resources = [r for r in res if r.kind == "dependency"]
        assert len(plugin_resources) >= 1, "Expected at least one plugin-kind resource"
        assert len(dep_resources) >= 1, "Expected at least one dependency-kind resource"

        for r in res:
            assert r.plugin == "HeatMapWithTime"


class TestTimestampedGeoJsonResourceMetadata:
    def test_dependency_vs_plugin_kind(self):
        res = plugins.TimestampedGeoJson.resources
        plugin_resources = [r for r in res if r.kind == "plugin"]
        dep_resources = [r for r in res if r.kind == "dependency"]
        assert len(plugin_resources) >= 1
        assert len(dep_resources) >= 1

        for r in res:
            assert r.plugin == "TimestampedGeoJson"
