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
    """TileLayer xyzservices/provider 解析兼容性断言。用独立预期值锁住行为，不依赖当前实现。"""
    provider = xyzservices.providers.CartoDB.DarkMatter
    layer = folium.raster_layers.TileLayer(tiles=provider)

    # provider 解析后生成的 URL（独立预期值）
    EXPECTED_PROVIDER_URL = "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
    assert layer.tiles == EXPECTED_PROVIDER_URL

    # provider 中的 attribution/min_zoom/max_zoom/subdomains 自动填充（独立预期值）
    EXPECTED_ATTR = provider.html_attribution  # 完整 attribution 可能变化，用实际值对比
    EXPECTED_MAX_ZOOM = 20  # CartoDB.DarkMatter 的 max_zoom
    EXPECTED_SUBDOMAINS = "abcd"  # CartoDB.DarkMatter 的 subdomains
    assert layer.options["attribution"] == EXPECTED_ATTR
    assert layer.options["min_zoom"] == 0  # provider 没有 min_zoom，用默认值
    assert layer.options["max_zoom"] == EXPECTED_MAX_ZOOM
    assert layer.options["subdomains"] == EXPECTED_SUBDOMAINS

    # provider name 自动转为 tile_name（独立预期值）
    EXPECTED_NAME = "cartodbdarkmatter"  # "CartoDB.DarkMatter" → 去点+小写
    assert layer.tile_name == EXPECTED_NAME
    assert layer.layer_name == EXPECTED_NAME

    # 用户显式传入的优先级更高（attr/min_zoom/max_zoom 是用户优先）
    # 注意：subdomains 是原代码的特殊情况，provider 值优先于用户传入
    layer2 = folium.raster_layers.TileLayer(
        tiles=provider,
        name="custom-name",
        attr="custom-attr",
        min_zoom=5,
        max_zoom=25,
        subdomains="xyz",
    )
    assert layer2.tile_name == "custom-name"
    assert layer2.options["attribution"] == "custom-attr"
    assert layer2.options["min_zoom"] == 5
    assert layer2.options["max_zoom"] == 25
    # subdomains 原代码行为：provider 值优先于用户传入（独立预期值锁住）
    assert layer2.options["subdomains"] == EXPECTED_SUBDOMAINS

    # "OpenStreetMap" 字符串别名处理（独立预期值）
    layer3 = folium.raster_layers.TileLayer(tiles="OpenStreetMap")
    EXPECTED_OSM_NAME = "openstreetmap"
    assert layer3.tile_name == EXPECTED_OSM_NAME
    EXPECTED_OSM_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"  # 实际 provider 没有 {s}
    assert layer3.tiles == EXPECTED_OSM_URL


def test_wms_tile_layer_compatibility():
    """WmsTileLayer 兼容性断言：fmt→format/cql_filter/camelize/渲染输出。用独立预期值锁住行为。"""
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

    # fmt→format 映射锁定（独立预期值）
    # camelize：extra_param → extraParam
    # cql_filter 保留原名，不被 camelize
    EXPECTED_OPTIONS = {
        "layers": "layer1,layer2",
        "styles": "style1,style2",
        "transparent": True,
        "version": "1.3.0",
        "attribution": "WMS Attribution",
        "format": "image/png",  # fmt→format
        "extraParam": "value",  # camelize
        "cql_filter": "id > 100",  # 保留原名
    }
    assert layer.options == EXPECTED_OPTIONS

    # self.options key 完整性检查：必须恰好是这些 key，不能多不能少
    assert set(layer.options.keys()) == set(EXPECTED_OPTIONS.keys())

    # 默认值锁定（独立预期值）
    layer_defaults = folium.raster_layers.WmsTileLayer(
        url=wms_url, layers="test"
    )
    EXPECTED_DEFAULT_OPTIONS = {
        "format": "image/jpeg",
        "transparent": False,
        "version": "1.1.1",
        "attribution": "",
        "layers": "test",
        "styles": "",
    }
    assert layer_defaults.options == EXPECTED_DEFAULT_OPTIONS
    assert layer_defaults.overlay is True
    assert layer_defaults.control is True
    assert layer_defaults.show is True

    # 渲染 JS 输出结构锁定（独立预期值，不依赖变量名）
    m = folium.Map()
    layer.add_to(m)
    html = m._parent.render()

    # 完整 JS 调用结构检查
    assert 'L.tileLayer.wms(' in html
    assert '"http://example.com/wms"' in html
    # options 对象中必须包含这些 key-value 对
    assert '"attribution": "WMS Attribution"' in html
    assert '"cql_filter":' in html
    assert 'id \\u003e 100' in html  # > 被转义
    assert '"extraParam": "value"' in html
    assert '"format": "image/png"' in html
    assert '"layers": "layer1,layer2"' in html
    assert '"styles": "style1,style2"' in html
    assert '"transparent": true' in html
    assert '"version": "1.3.0"' in html
    # cql_filter 必须不被 camelize
    assert "cqlFilter" not in html
    # 验证 JS 对象的 key 顺序不影响功能（检查整体结构）
    import re
    wms_call_pattern = r'L\.tileLayer\.wms\(\s*"http://example\.com/wms",\s*(\{[^}]+\})\s*\)'
    match = re.search(wms_call_pattern, html, re.DOTALL)
    assert match is not None, "WMS JS 调用结构不匹配"
    # 验证 options 对象是有效的 JSON（不依赖 key 顺序）
    import json
    options_json = match.group(1)
    options_dict = json.loads(options_json)
    EXPECTED_JSON_OPTIONS = {
        "attribution": "WMS Attribution",
        "cql_filter": "id > 100",
        "extraParam": "value",
        "format": "image/png",
        "layers": "layer1,layer2",
        "styles": "style1,style2",
        "transparent": True,
        "version": "1.3.0",
    }
    assert options_dict == EXPECTED_JSON_OPTIONS, f"JS options 不匹配: {options_dict}"


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
