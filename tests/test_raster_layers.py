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


def test_tile_layer_compatibility():
    """TileLayer 兼容性断言：逐项锁定 options/tiles/默认值/异常/渲染输出。"""
    tiles_url = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"

    layer = folium.raster_layers.TileLayer(
        tiles=tiles_url,
        name="test-tile",
        attr="Test Attribution",
        min_zoom=3,
        max_zoom=15,
        max_native_zoom=14,
        no_wrap=True,
        subdomains="123",
        detect_retina=True,
        tms=True,
        opacity=0.75,
        overlay=True,
        control=False,
        show=False,
        extra_option="value",
    )

    # layer_kwargs 传递给父类
    assert layer.tile_name == "test-tile"
    assert layer.layer_name == "test-tile"
    assert layer.overlay is True
    assert layer.control is False
    assert layer.show is False
    assert layer._name == "TileLayer"

    # tiles URL 透传
    assert layer.tiles == tiles_url

    # self.options 键名（snake_case，不 camelize）和值逐项锁定
    expected_options = {
        "min_zoom": 3,
        "max_zoom": 15,
        "max_native_zoom": 14,
        "no_wrap": True,
        "attribution": "Test Attribution",
        "subdomains": "123",
        "detect_retina": True,
        "tms": True,
        "opacity": 0.75,
        "extra_option": "value",
    }
    assert layer.options == expected_options

    # 缺省值锁定
    layer_defaults = folium.raster_layers.TileLayer(
        tiles=tiles_url, attr="DefaultAttr"
    )
    assert layer_defaults.options["min_zoom"] == 0
    assert layer_defaults.options["max_zoom"] == 18
    assert layer_defaults.options["max_native_zoom"] == 18
    assert layer_defaults.options["subdomains"] == "abc"
    assert layer_defaults.overlay is False
    assert layer_defaults.control is True
    assert layer_defaults.show is True

    # 异常信息锁定：自定义 tiles 必须有 attribution
    with pytest.raises(ValueError, match="Custom tiles must have an attribution."):
        folium.raster_layers.TileLayer(tiles=tiles_url)

    # 渲染 JS 输出锁定
    m = folium.Map()
    layer.add_to(m)
    html = m._parent.render()
    assert 'L.tileLayer(' in html
    assert '"https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"' in html
    # tojavascript 过滤器会自动 camelize：min_zoom → minZoom
    assert '"minZoom": 3' in html
    assert '"maxZoom": 15' in html
    assert '"attribution": "Test Attribution"' in html
    assert '"opacity": 0.75' in html
    assert '"extraOption": "value"' in html


def test_tile_layer_xyzservices_compatibility():
    """TileLayer xyzservices/provider 解析兼容性断言。"""
    provider = xyzservices.providers.CartoDB.DarkMatter
    layer = folium.raster_layers.TileLayer(tiles=provider)

    # provider 解析后生成的 URL
    expected_url = provider.build_url(fill_subdomain=False, scale_factor="{r}")
    assert layer.tiles == expected_url

    # provider 中的 attribution/min_zoom/max_zoom/subdomains 自动填充
    assert layer.options["attribution"] == provider.html_attribution
    assert layer.options["min_zoom"] == provider.get("min_zoom", 0)
    assert layer.options["max_zoom"] == provider.get("max_zoom", 18)
    assert layer.options["subdomains"] == provider.get("subdomains", "abc")

    # provider name 自动转为 tile_name
    expected_name = provider.name.replace(".", "").lower()
    assert layer.tile_name == expected_name
    assert layer.layer_name == expected_name

    # 用户显式传入的优先级更高（attr/min_zoom/max_zoom 是用户优先）
    # 注意：subdomains 是原代码的特殊情况，provider 值优先于用户传入
    layer2 = folium.raster_layers.TileLayer(
        tiles=provider,
        name="custom-name",
        attr="custom-attr",
        min_zoom=5,
        max_zoom=20,
        subdomains="xyz",
    )
    assert layer2.tile_name == "custom-name"
    assert layer2.options["attribution"] == "custom-attr"
    assert layer2.options["min_zoom"] == 5
    assert layer2.options["max_zoom"] == 20
    # subdomains 原代码行为：provider 值优先于用户传入
    assert layer2.options["subdomains"] == provider.get("subdomains", "xyz")

    # "OpenStreetMap" 字符串别名处理
    layer3 = folium.raster_layers.TileLayer(tiles="OpenStreetMap")
    assert "openstreetmap" in layer3.tile_name


def test_wms_tile_layer_compatibility():
    """WmsTileLayer 兼容性断言：fmt→format/cql_filter/camelize/渲染输出。"""
    wms_url = "http://example.com/wms"
    layer = folium.raster_layers.WmsTileLayer(
        url=wms_url,
        layers="layer1,layer2",
        styles="style1,style2",
        fmt="image/png",
        transparent=True,
        version="1.3.0",
        attr="WMS Attribution",
        name="test-wms",
        overlay=False,
        control=False,
        show=False,
        cql_filter="id > 100",
        extra_param="value",
    )

    # 父类参数
    assert layer.layer_name == "test-wms"
    assert layer.overlay is False
    assert layer.control is False
    assert layer.show is False

    # URL 透传
    assert layer.url == wms_url

    # fmt→format 映射锁定
    # camelize：layers → layers（保持不变，因为 parse_options 只转换 snake_case）
    # transparent → transparent，version → version，attribution → attribution
    # extra_param → extraParam
    expected_options = {
        "layers": "layer1,layer2",
        "styles": "style1,style2",
        "transparent": True,
        "version": "1.3.0",
        "attribution": "WMS Attribution",
        "format": "image/png",
        "extraParam": "value",
        "cql_filter": "id > 100",  # 保留原名，不 camelize
    }
    assert layer.options == expected_options

    # 默认值锁定
    layer_defaults = folium.raster_layers.WmsTileLayer(
        url=wms_url, layers="test"
    )
    assert layer_defaults.options["format"] == "image/jpeg"
    assert layer_defaults.options["transparent"] is False
    assert layer_defaults.options["version"] == "1.1.1"
    assert layer_defaults.options["attribution"] == ""
    assert layer_defaults.overlay is True
    assert layer_defaults.control is True
    assert layer_defaults.show is True

    # 渲染 JS 输出锁定
    m = folium.Map()
    layer.add_to(m)
    html = m._parent.render()
    assert 'L.tileLayer.wms(' in html
    assert '"http://example.com/wms"' in html
    # WMS 用 tojson 不是 tojavascript，cql_filter 保留原名，但 > 会被转义
    assert '"cql_filter":' in html
    assert 'id \\u003e 100' in html  # > 被转义为 \u003e
    assert "cqlFilter" not in html
    assert '"extraParam": "value"' in html
    assert '"format": "image/png"' in html


def test_image_overlay_compatibility():
    """ImageOverlay 兼容性断言：options/bounds/url/渲染输出。"""
    data = [
        [[1, 0, 0, 1], [0, 0, 0, 0], [0, 0, 0, 0]],
        [[1, 1, 0, 0.5], [0, 0, 1, 1], [0, 0, 1, 1]],
    ]
    bounds = [[0, -180], [90, 180]]

    layer = folium.raster_layers.ImageOverlay(
        image=data,
        bounds=bounds,
        mercator_project=True,
        pixelated=False,
        name="test-image",
        overlay=False,
        control=False,
        show=False,
        opacity=0.8,
        alt="test alt",
        extra_option="value",
    )

    # 父类参数
    assert layer._name == "ImageOverlay"
    assert layer.layer_name == "test-image"
    assert layer.overlay is False
    assert layer.control is False
    assert layer.show is False

    # bounds 透传（保持原始输入格式）
    assert layer.bounds == bounds

    # 特有的非 options 属性
    assert layer.pixelated is False

    # self.options：不 camelize，只过滤 None
    expected_options = {
        "opacity": 0.8,
        "alt": "test alt",
        "extra_option": "value",
    }
    assert layer.options == expected_options

    # url 生成锁定（与原测试一致的 base64）
    expected_url = (
        "data:image/png;base64,"
        "iVBORw0KGgoAAAANSUhEUgAAAAMAAAACCAYAAACddGYaAAA"
        "AF0lEQVR42mP4z8AARFDw/z/DeiA5H4QBV60H6ABl9ZIAAAAASUVORK5CYII="
    )
    assert layer.url == expected_url

    # 默认值锁定
    layer_defaults = folium.raster_layers.ImageOverlay(
        image=data, bounds=bounds, mercator_project=True
    )
    assert layer_defaults.pixelated is True
    assert layer_defaults.overlay is True
    assert layer_defaults.control is True
    assert layer_defaults.show is True

    # bounds get_self_bounds 规范化
    normalized = layer._get_self_bounds()
    assert normalized == [[0.0, -180.0], [90.0, 180.0]]

    # 渲染 JS 输出锁定
    m = folium.Map()
    layer.add_to(m)
    html = m._parent.render()
    assert 'L.imageOverlay(' in html
    assert '[[0, -180], [90, 180]]' in html
    assert '"opacity": 0.8' in html
    assert '"alt": "test alt"' in html
    # tojavascript 过滤器会自动 camelize
    assert '"extraOption": "value"' in html


def test_video_overlay_compatibility():
    """VideoOverlay 兼容性断言：options/bounds/video_url/渲染输出。"""
    video_url = "https://example.com/video.mp4"
    bounds = [[-45, -90], [45, 90]]

    layer = folium.raster_layers.VideoOverlay(
        video_url=video_url,
        bounds=bounds,
        autoplay=False,
        loop=False,
        name="test-video",
        overlay=False,
        control=False,
        show=False,
        muted=True,
        playsinline=True,
        extra_option="value",
    )

    # 父类参数
    assert layer._name == "VideoOverlay"
    assert layer.layer_name == "test-video"
    assert layer.overlay is False
    assert layer.control is False
    assert layer.show is False

    # video_url 透传
    assert layer.video_url == video_url

    # bounds 透传
    assert layer.bounds == bounds

    # self.options：不 camelize，autoplay/loop 作为 layer_options 传入
    expected_options = {
        "autoplay": False,
        "loop": False,
        "muted": True,
        "playsinline": True,
        "extra_option": "value",
    }
    assert layer.options == expected_options

    # 默认值锁定
    layer_defaults = folium.raster_layers.VideoOverlay(
        video_url=video_url, bounds=bounds
    )
    assert layer_defaults.options["autoplay"] is True
    assert layer_defaults.options["loop"] is True
    assert layer_defaults.overlay is True
    assert layer_defaults.control is True
    assert layer_defaults.show is True

    # bounds get_self_bounds 规范化
    normalized = layer._get_self_bounds()
    assert normalized == [[-45.0, -90.0], [45.0, 90.0]]

    # 渲染 JS 输出锁定
    m = folium.Map()
    layer.add_to(m)
    html = m._parent.render()
    assert 'L.videoOverlay(' in html
    assert '"https://example.com/video.mp4"' in html
    assert '[[-45, -90], [45, 90]]' in html
    assert '"autoplay": false' in html
    assert '"loop": false' in html
    # tojavascript 过滤器会自动 camelize
    assert '"extraOption": "value"' in html


def test_raster_layer_config_public_api():
    """RasterLayerConfig 公开接口检查：不得引入新的公开属性或改变行为。"""
    from folium.raster_layers import RasterLayerConfig

    # 公开属性只能是这四个
    public_properties = [
        "layer_kwargs",
        "options",
        "bounds",
        "attribution",
    ]
    for prop in public_properties:
        assert hasattr(RasterLayerConfig, prop) or prop in dir(
            RasterLayerConfig
        ), f"Missing public property: {prop}"

    # 公开工厂方法
    assert callable(RasterLayerConfig.for_tile_layer)
    assert callable(RasterLayerConfig.for_wms_tile_layer)
    assert callable(RasterLayerConfig.for_image_overlay)
    assert callable(RasterLayerConfig.for_video_overlay)

    # 不得有额外的公开属性（下划线开头视为私有）
    config = RasterLayerConfig()
    all_attrs = [
        attr for attr in dir(config)
        if not attr.startswith("_") and not attr.startswith("for_")
        and attr not in public_properties
        and not callable(getattr(config, attr, None))
    ]
    # 允许 __slots__、__module__、__doc__ 等特殊属性
    public_attrs = [attr for attr in all_attrs if not attr.startswith("__")]
    assert len(public_attrs) == 0, (
        f"RasterLayerConfig 不应引入新的公开属性，发现: {public_attrs}"
    )

    # _build_options 必须是静态私有方法，外部不得直接依赖
    assert hasattr(RasterLayerConfig, "_build_options")
    assert RasterLayerConfig._build_options.__name__ == "_build_options"

    # for_tile_layer 必须抛出正确的异常
    with pytest.raises(ValueError, match="Custom tiles must have an attribution."):
        RasterLayerConfig.for_tile_layer(tiles="https://example.com/{z}/{x}/{y}.png")
