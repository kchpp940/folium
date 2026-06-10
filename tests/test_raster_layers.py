"""
Test raster_layers
------------------

"""

import pytest
import xyzservices

import folium
from folium.template import Template
from folium.utilities import normalize


def test_tile_layer():
    m = folium.Map([48.0, 5.0], zoom_start=6)
    layer = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"

    folium.raster_layers.TileLayer(
        tiles=layer, name="OpenStreetMap", attr="attribution"
    ).add_to(m)

    folium.raster_layers.TileLayer(
        tiles=layer, name="OpenStreetMap2", attr="attribution2", overlay=True
    ).add_to(m)

    folium.LayerControl().add_to(m)
    m._repr_html_()

    bounds = m.get_bounds()
    assert bounds == [[None, None], [None, None]], bounds


def _is_working_zoom_level(zoom, tiles, session):
    """Check if the zoom level works for the given tileset."""
    url = tiles.format(s="a", x=0, y=0, z=zoom)
    response = session.get(url, timeout=5)
    if response.status_code < 400:
        return True
    return False


def test_custom_tile_subdomains():
    """Test custom tile subdomains."""
    url = "http://{s}.custom_tiles.org/{z}/{x}/{y}.png"
    m = folium.Map()
    folium.TileLayer(
        tiles=url, name="subdomains2", attr="attribution", subdomains="mytilesubdomain"
    ).add_to(m)
    out = m._parent.render()
    assert "mytilesubdomain" in out


def test_wms():
    m = folium.Map([40, -100], zoom_start=4)
    url = "http://mesonet.agron.iastate.edu/cgi-bin/wms/nexrad/n0r.cgi"
    w = folium.raster_layers.WmsTileLayer(
        url=url,
        name="test",
        fmt="image/png",
        layers="nexrad-n0r-900913",
        attr="Weather data © 2012 IEM Nexrad",
        transparent=True,
        cql_filter="something",
    )
    w.add_to(m)
    html = m.get_root().render()

    # verify this special case wasn't converted to lowerCamelCase
    assert '"cql_filter": "something",' in html
    assert "cqlFilter" not in html

    bounds = m.get_bounds()
    assert bounds == [[None, None], [None, None]], bounds


def test_image_overlay():
    """Test image overlay."""
    data = [
        [[1, 0, 0, 1], [0, 0, 0, 0], [0, 0, 0, 0]],
        [[1, 1, 0, 0.5], [0, 0, 1, 1], [0, 0, 1, 1]],
    ]

    m = folium.Map()
    io = folium.raster_layers.ImageOverlay(
        data, [[0, -180], [90, 180]], mercator_project=True
    )
    io.add_to(m)
    m._repr_html_()

    out = m._parent.render()

    # Verify the URL generation.
    url = (
        "data:image/png;base64,"
        "iVBORw0KGgoAAAANSUhEUgAAAAMAAAACCAYAAACddGYaAAA"
        "AF0lEQVR42mP4z8AARFDw/z/DeiA5H4QBV60H6ABl9ZIAAAAASUVORK5CYII="
    )
    assert io.url == url

    # Verify the script part is okay.
    tmpl = Template("""
        var {{this.get_name()}} = L.imageOverlay(
            "{{ this.url }}",
            {{ this.bounds }},
            {{ this.options }}
        );
        {{ this.get_name() }}.addTo({{this._parent.get_name()}});
    """)
    assert normalize(tmpl.render(this=io)) in normalize(out)

    bounds = m.get_bounds()
    assert bounds == [[0, -180], [90, 180]], bounds


@pytest.mark.parametrize(
    "tiles", ["CartoDB DarkMatter", xyzservices.providers.CartoDB.DarkMatter]
)
def test_xyzservices(tiles):
    m = folium.Map([48.0, 5.0], tiles=tiles, zoom_start=6)

    folium.raster_layers.TileLayer(
        tiles=xyzservices.providers.CartoDB.Positron,
    ).add_to(m)
    folium.LayerControl().add_to(m)

    out = m._parent.render()
    assert (
        xyzservices.providers.CartoDB.DarkMatter.build_url(
            fill_subdomain=False, scale_factor="{r}"
        )
        in out
    )
    assert (
        xyzservices.providers.CartoDB.Positron.build_url(
            fill_subdomain=False, scale_factor="{r}"
        )
        in out
    )


_SVG_DATA = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
    '<circle cx="50" cy="50" r="40" fill="red"/></svg>'
)

_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
    "AAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)

_BOUNDS = [[0, -180], [90, 180]]


@pytest.mark.parametrize(
    "image,url_prefix",
    [
        ("https://example.com/img.png", "https://example.com/img.png"),
        (
            "data:image/png;base64,iVBORw0KGgo=",
            "data:image/png;base64,iVBORw0KGgo=",
        ),
        (_SVG_DATA, "data:image/svg+xml;base64,"),
        (_PNG_BASE64, "data:image/png;base64,"),
    ],
)
def test_image_overlay_input_types(image, url_prefix):
    """Test ImageOverlay accepts various image input types consistently."""
    io = folium.raster_layers.ImageOverlay(image, _BOUNDS)
    assert io.url.startswith(url_prefix), f"Expected prefix {url_prefix}, got {io.url[:60]}"


def test_image_overlay_mercator_project_non_array():
    """Test mercator_project is silently ignored for non-array inputs."""
    io = folium.raster_layers.ImageOverlay(
        "https://example.com/img.png", _BOUNDS, mercator_project=True
    )
    assert io.url == "https://example.com/img.png"


def test_image_overlay_colormap_non_array():
    """Test colormap is silently ignored for non-array inputs."""
    def dummy_cm(x):
        return (x, x, x, 1.0)

    io = folium.raster_layers.ImageOverlay(
        "https://example.com/img.png", _BOUNDS, colormap=dummy_cm
    )
    assert io.url == "https://example.com/img.png"


def test_image_overlay_pathlike(tmp_path):
    """Test ImageOverlay accepts PathLike objects."""
    from pathlib import Path

    f = tmp_path / "test.png"
    f.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    io = folium.raster_layers.ImageOverlay(Path(f), _BOUNDS)
    assert io.url.startswith("data:image/png;base64,")


def test_image_overlay_list_array():
    """Test ImageOverlay accepts Python lists as array-like input."""
    data = [[[1, 0, 0, 1], [0, 1, 0, 1]], [[0, 0, 1, 1], [1, 1, 0, 1]]]
    io = folium.raster_layers.ImageOverlay(data, _BOUNDS)
    assert io.url.startswith("data:image/png;base64,")


def test_float_image_consistency():
    """Test FloatImage produces consistent URLs for the same inputs as ImageOverlay."""
    from folium.plugins.float_image import FloatImage
    from folium.utilities import image_to_url

    inputs = [
        "https://example.com/img.png",
        "data:image/png;base64,iVBORw0KGgo=",
        _SVG_DATA,
        _PNG_BASE64,
    ]
    for img in inputs:
        fi = FloatImage(img)
        expected = image_to_url(img)
        assert fi.url == expected, f"Mismatch for input {type(img).__name__}: {fi.url} != {expected}"


def test_float_image_array():
    """Test FloatImage accepts array-like input."""
    from folium.plugins.float_image import FloatImage
    import numpy as np

    data = np.array([[[1, 0, 0, 1]], [[0, 1, 0, 1]]])
    fi = FloatImage(data)
    assert fi.url.startswith("data:image/png;base64,")
