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


def test_module_exports():
    """模块公开接口检查：__all__ 必须只导出四个公共类，不能泄露内部实现。"""
    import folium.raster_layers as rl

    # __all__ 必须存在且只包含四个公共类
    assert hasattr(rl, "__all__")
    assert set(rl.__all__) == {"TileLayer", "WmsTileLayer", "ImageOverlay", "VideoOverlay"}

    # _RasterLayerConfig 必须存在（单下划线，非公开）
    assert hasattr(rl, "_RasterLayerConfig")

    # 模块 dir 列表不应以公共方式暴露 _RasterLayerConfig（不会出现在 from * 导入中）
    module_dir_names = [n for n in dir(rl) if not n.startswith("_")]
    assert "TileLayer" in module_dir_names
    assert "WmsTileLayer" in module_dir_names
    assert "ImageOverlay" in module_dir_names
    assert "VideoOverlay" in module_dir_names
    # _RasterLayerConfig 不以非下划线形式存在
    assert "RasterLayerConfig" not in module_dir_names


def test_tile_layer_signature():
    """TileLayer.__init__ 参数顺序和默认值必须精确锁定。"""
    import inspect

    sig = inspect.signature(folium.raster_layers.TileLayer.__init__)
    params = list(sig.parameters.keys())

    # 排除 self，检查参数顺序（独立预期值）
    EXPECTED_PARAMS = [
        "tiles",
        "min_zoom",
        "max_zoom",
        "max_native_zoom",
        "attr",
        "detect_retina",
        "name",
        "overlay",
        "control",
        "show",
        "no_wrap",
        "subdomains",
        "tms",
        "opacity",
        "kwargs",
    ]
    assert params[1:] == EXPECTED_PARAMS

    # 检查每个参数的默认值（独立预期值）
    EXPECTED_DEFAULTS = {
        "tiles": "OpenStreetMap",
        "min_zoom": None,
        "max_zoom": None,
        "max_native_zoom": None,
        "attr": None,
        "detect_retina": False,
        "name": None,
        "overlay": False,
        "control": True,
        "show": True,
        "no_wrap": False,
        "subdomains": "abc",
        "tms": False,
        "opacity": 1,
    }
    for param_name, expected_default in EXPECTED_DEFAULTS.items():
        param = sig.parameters[param_name]
        assert param.default == expected_default, (
            f"TileLayer.{param_name} 默认值不匹配: "
            f"期望 {expected_default}, 实际 {param.default}"
        )

    # kwargs 必须是 VAR_KEYWORD（**kwargs）
    assert sig.parameters["kwargs"].kind == inspect.Parameter.VAR_KEYWORD

    # kwargs 必须能正确吸收未知参数并进入 self.options
    tiles_url = "https://example.com/{z}/{x}/{y}.png"
    layer = folium.raster_layers.TileLayer(
        tiles=tiles_url,
        attr="attr",
        unknown_option_a="value_a",
        unknown_option_b=42,
    )
    # kwargs 吸收的参数进入 self.options，不被 camelize（TileLayer 用 remove_empty）
    assert "unknown_option_a" in layer.options
    assert layer.options["unknown_option_a"] == "value_a"
    assert "unknown_option_b" in layer.options
    assert layer.options["unknown_option_b"] == 42
    # 未被吸收的参数（已定义的参数）不应作为 kwargs
    assert "tiles" not in layer.options
    assert "attr" not in layer.options  # attr → attribution 后进入 options


def test_wms_tile_layer_signature():
    """WmsTileLayer.__init__ 参数顺序和默认值必须精确锁定。"""
    import inspect

    sig = inspect.signature(folium.raster_layers.WmsTileLayer.__init__)
    params = list(sig.parameters.keys())

    EXPECTED_PARAMS = [
        "url",
        "layers",
        "styles",
        "fmt",
        "transparent",
        "version",
        "attr",
        "name",
        "overlay",
        "control",
        "show",
        "kwargs",
    ]
    assert params[1:] == EXPECTED_PARAMS

    EXPECTED_DEFAULTS = {
        "styles": "",
        "fmt": "image/jpeg",
        "transparent": False,
        "version": "1.1.1",
        "attr": "",
        "name": None,
        "overlay": True,
        "control": True,
        "show": True,
    }
    for param_name, expected_default in EXPECTED_DEFAULTS.items():
        param = sig.parameters[param_name]
        assert param.default == expected_default, (
            f"WmsTileLayer.{param_name} 默认值不匹配: "
            f"期望 {expected_default}, 实际 {param.default}"
        )

    # url 和 layers 必须没有默认值（POSITIONAL_OR_KEYWORD）
    assert sig.parameters["url"].default == inspect.Parameter.empty
    assert sig.parameters["layers"].default == inspect.Parameter.empty

    # kwargs 必须是 VAR_KEYWORD
    assert sig.parameters["kwargs"].kind == inspect.Parameter.VAR_KEYWORD

    # kwargs 吸收的参数被 camelize（WMS 用 parse_options）并进入 self.options
    wms_url = "http://example.com/wms"
    layer = folium.raster_layers.WmsTileLayer(
        url=wms_url,
        layers="test",
        my_custom_option="value",
        another_param=123,
    )
    # camelize: my_custom_option → myCustomOption
    assert "myCustomOption" in layer.options
    assert layer.options["myCustomOption"] == "value"
    assert "anotherParam" in layer.options
    assert layer.options["anotherParam"] == 123


def test_image_overlay_signature():
    """ImageOverlay.__init__ 参数顺序和默认值必须精确锁定。"""
    import inspect

    sig = inspect.signature(folium.raster_layers.ImageOverlay.__init__)
    params = list(sig.parameters.keys())

    EXPECTED_PARAMS = [
        "image",
        "bounds",
        "origin",
        "colormap",
        "mercator_project",
        "pixelated",
        "name",
        "overlay",
        "control",
        "show",
        "kwargs",
    ]
    assert params[1:] == EXPECTED_PARAMS

    EXPECTED_DEFAULTS = {
        "origin": "upper",
        "colormap": None,
        "mercator_project": False,
        "pixelated": True,
        "name": None,
        "overlay": True,
        "control": True,
        "show": True,
    }
    for param_name, expected_default in EXPECTED_DEFAULTS.items():
        param = sig.parameters[param_name]
        assert param.default == expected_default, (
            f"ImageOverlay.{param_name} 默认值不匹配: "
            f"期望 {expected_default}, 实际 {param.default}"
        )

    # image 和 bounds 必须没有默认值
    assert sig.parameters["image"].default == inspect.Parameter.empty
    assert sig.parameters["bounds"].default == inspect.Parameter.empty

    # kwargs 必须是 VAR_KEYWORD
    assert sig.parameters["kwargs"].kind == inspect.Parameter.VAR_KEYWORD

    # kwargs 吸收的参数进入 self.options，不被 camelize
    data = [
        [[1, 0, 0, 1], [0, 0, 0, 0], [0, 0, 0, 0]],
        [[1, 1, 0, 0.5], [0, 0, 1, 1], [0, 0, 1, 1]],
    ]
    bounds = [[0, -180], [90, 180]]
    layer = folium.raster_layers.ImageOverlay(
        image=data,
        bounds=bounds,
        mercator_project=True,
        extra_img_option="my_value",
        zoom_level=10,
    )
    # 不 camelize
    assert "extra_img_option" in layer.options
    assert layer.options["extra_img_option"] == "my_value"
    assert "zoom_level" in layer.options
    assert layer.options["zoom_level"] == 10


def test_video_overlay_signature():
    """VideoOverlay.__init__ 参数顺序和默认值必须精确锁定。"""
    import inspect

    sig = inspect.signature(folium.raster_layers.VideoOverlay.__init__)
    params = list(sig.parameters.keys())

    EXPECTED_PARAMS = [
        "video_url",
        "bounds",
        "autoplay",
        "loop",
        "name",
        "overlay",
        "control",
        "show",
        "kwargs",
    ]
    assert params[1:] == EXPECTED_PARAMS

    EXPECTED_DEFAULTS = {
        "autoplay": True,
        "loop": True,
        "name": None,
        "overlay": True,
        "control": True,
        "show": True,
    }
    for param_name, expected_default in EXPECTED_DEFAULTS.items():
        param = sig.parameters[param_name]
        assert param.default == expected_default, (
            f"VideoOverlay.{param_name} 默认值不匹配: "
            f"期望 {expected_default}, 实际 {param.default}"
        )

    # video_url 和 bounds 必须没有默认值
    assert sig.parameters["video_url"].default == inspect.Parameter.empty
    assert sig.parameters["bounds"].default == inspect.Parameter.empty

    # kwargs 必须是 VAR_KEYWORD
    assert sig.parameters["kwargs"].kind == inspect.Parameter.VAR_KEYWORD

    # kwargs 吸收的参数进入 self.options，不被 camelize
    video_url = "https://example.com/video.mp4"
    bounds = [[-45, -90], [45, 90]]
    layer = folium.raster_layers.VideoOverlay(
        video_url=video_url,
        bounds=bounds,
        extra_video_opt="opt_value",
        play_back_rate=1.5,
    )
    # 不 camelize
    assert "extra_video_opt" in layer.options
    assert layer.options["extra_video_opt"] == "opt_value"
    assert "play_back_rate" in layer.options
    assert layer.options["play_back_rate"] == 1.5
    # autoplay 和 loop 进入 self.options（非 kwargs）
    assert "autoplay" in layer.options
    assert "loop" in layer.options


def test_layer_control_params_passthrough():
    """父类 Layer 控制参数（name/overlay/control/show）透传行为断言。"""
    tiles_url = "https://example.com/{z}/{x}/{y}.png"
    wms_url = "http://example.com/wms"
    data = [
        [[1, 0, 0, 1], [0, 0, 0, 0]],
        [[1, 1, 0, 0.5], [0, 0, 1, 1]],
    ]
    img_bounds = [[0, -180], [90, 180]]
    video_url = "https://example.com/video.mp4"
    video_bounds = [[-45, -90], [45, 90]]

    TEST_PARAMS = {
        "name": "custom-layer",
        "overlay": True,
        "control": False,
        "show": False,
    }

    # TileLayer
    tl = folium.raster_layers.TileLayer(
        tiles=tiles_url, attr="attr", **TEST_PARAMS
    )
    assert tl.layer_name == "custom-layer"
    assert tl.overlay is True
    assert tl.control is False
    assert tl.show is False

    # WmsTileLayer
    wms = folium.raster_layers.WmsTileLayer(
        url=wms_url, layers="test", **TEST_PARAMS
    )
    assert wms.layer_name == "custom-layer"
    assert wms.overlay is True
    assert wms.control is False
    assert wms.show is False

    # ImageOverlay
    img = folium.raster_layers.ImageOverlay(
        image=data, bounds=img_bounds, mercator_project=True, **TEST_PARAMS
    )
    assert img.layer_name == "custom-layer"
    assert img.overlay is True
    assert img.control is False
    assert img.show is False

    # VideoOverlay
    vid = folium.raster_layers.VideoOverlay(
        video_url=video_url, bounds=video_bounds, **TEST_PARAMS
    )
    assert vid.layer_name == "custom-layer"
    assert vid.overlay is True
    assert vid.control is False
    assert vid.show is False
