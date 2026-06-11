"""
Folium map Tests
----------------

"""

import warnings

import numpy as np
import pytest

from folium import GeoJson, Map, TileLayer
from folium.map import Class, CustomPane, Icon, LayerControl, Marker, Popup
from folium.utilities import JsCode, normalize

tmpl = """
        <div id="{id}"
                style="width: {width}; height: {height};">
                {text}</div>
""".format


def test_layer_control_initialization():
    layer_control = LayerControl()
    assert layer_control._name == "LayerControl"
    assert layer_control.options["position"] == "topright"
    assert layer_control.options["collapsed"] is True
    assert layer_control.options["autoZIndex"] is True
    assert layer_control.draggable is False
    assert layer_control.base_layers == {}
    assert layer_control.overlays == {}


def test_layer_control_reset():
    layer_control = LayerControl()
    layer_control.base_layers = {"Layer1": "layer1"}
    layer_control.overlays = {"Layer2": "layer2"}
    layer_control.reset()
    assert layer_control.base_layers == {}
    assert layer_control.overlays == {}


def test_layer_control_render():
    m = Map(tiles=None)
    layer1 = TileLayer().add_to(m)
    layer2 = Marker([0, 0]).add_to(m)
    layer3 = GeoJson({}).add_to(m)
    layer1.control = True
    layer2.control = False
    layer3.control = True
    layer1.layer_name = "Layer1"
    layer2.layer_name = "Layer2"
    layer3.layer_name = "Layer3"
    layer1.get_name = lambda: "layer1"
    layer2.get_name = lambda: "layer2"
    layer3.get_name = lambda: "layer3"

    layer_control = LayerControl().add_to(m)
    layer_control.render()

    assert layer_control.base_layers == {"Layer1": "layer1"}
    assert layer_control.overlays == {"Layer3": "layer3"}


def test_layer_control_draggable():
    m = Map(tiles=None)
    layer_control = LayerControl(draggable=True).add_to(m)
    expected = f"new L.Draggable({ layer_control.get_name() }.getContainer()).enable();"
    rendered = m.get_root().render()
    assert normalize(expected) in normalize(rendered)


def test_popup_ascii():
    popup = Popup("Some text.")
    _id = list(popup.html._children.keys())[0]
    kw = {
        "id": _id,
        "width": "100.0%",
        "height": "100.0%",
        "text": "Some text.",
    }
    assert "".join(popup.html.render().split()) == "".join(tmpl(**kw).split())


def test_popup_quotes():
    popup = Popup("Let's try quotes", parse_html=True)
    _id = list(popup.html._children.keys())[0]
    kw = {
        "id": _id,
        "width": "100.0%",
        "height": "100.0%",
        "text": "Let&#39;s try quotes",
    }
    assert "".join(popup.html.render().split()) == "".join(tmpl(**kw).split())


def test_popup_unicode():
    popup = Popup("Ça c'est chouette", parse_html=True)
    _id = list(popup.html._children.keys())[0]
    kw = {
        "id": _id,
        "width": "100.0%",
        "height": "100.0%",
        "text": "Ça c&#39;est chouette",
    }
    assert "".join(popup.html.render().split()) == "".join(tmpl(**kw).split())


def test_popup_sticky():
    m = Map()
    popup = Popup("Some text.", sticky=True).add_to(m)
    rendered = popup._template.render(this=popup, kwargs={})
    expected = """
    var {popup_name} = L.popup({{
        "maxWidth": "100%",
        "autoClose": false,
        "closeOnClick": false,
    }});

    var {html_name} = $(`<div id="{html_name}" style="width: 100.0%; height: 100.0%;">Some text.</div>`)[0];
    {popup_name}.setContent({html_name});
    {map_name}.bindPopup({popup_name});
    """.format(
        popup_name=popup.get_name(),
        html_name=list(popup.html._children.keys())[0],
        map_name=m.get_name(),
    )
    assert normalize(rendered) == normalize(expected)


def test_popup_show():
    m = Map()
    popup = Popup("Some text.", show=True).add_to(m)
    rendered = popup._template.render(this=popup, kwargs={})
    expected = """
    var {popup_name} = L.popup({{
        "maxWidth": "100%","autoClose": false,
    }});
    var {html_name} = $(`<div id="{html_name}" style="width: 100.0%; height: 100.0%;">Some text.</div>`)[0];
    {popup_name}.setContent({html_name});
    {map_name}.bindPopup({popup_name}).openPopup();
    """.format(
        popup_name=popup.get_name(),
        html_name=list(popup.html._children.keys())[0],
        map_name=m.get_name(),
    )
    # assert compare_rendered(rendered, expected)
    assert normalize(rendered) == normalize(expected)


def test_include():
    create_tile = """
        function(coords, done) {
            const url = this.getTileUrl(coords);
            const img = document.createElement('img');
            fetch(url, {
              headers: {
                "Authorization": "Bearer <Token>"
              },
            })
            .then((response) => {
                img.src = URL.createObjectURL(response.body);
                done(null, img);
            })
            return img;
        }
    """
    TileLayer.include(create_tile=JsCode(create_tile))
    tiles = TileLayer(
        tiles="OpenStreetMap",
    )
    m = Map(
        tiles=tiles,
    )
    rendered = m.get_root().render()
    Class._includes.clear()
    expected = """
    L.TileLayer.include({
      "createTile":
        function(coords, done) {
            const url = this.getTileUrl(coords);
            const img = document.createElement('img');
            fetch(url, {
              headers: {
                "Authorization": "Bearer <Token>"
              },
            })
            .then((response) => {
                img.src = URL.createObjectURL(response.body);
                done(null, img);
            })
            return img;
        },
    })
    """
    assert normalize(expected) in normalize(rendered)


def test_include_once():
    abc = "MY BEAUTIFUL SENTINEL"
    TileLayer.include(abc=abc)
    tiles = TileLayer(
        tiles="OpenStreetMap",
    )
    m = Map(
        tiles=tiles,
    )
    TileLayer(
        tiles="OpenStreetMap",
    ).add_to(m)

    rendered = m.get_root().render()
    Class._includes.clear()

    assert rendered.count(abc) == 1, "Includes should happen only once per class"


def test_popup_backticks():
    m = Map()
    popup = Popup("back`tick`tick").add_to(m)
    rendered = popup._template.render(this=popup, kwargs={})
    expected = """
    var {popup_name} = L.popup({{
        "maxWidth": "100%",
    }});
    var {html_name} = $(`<div id="{html_name}" style="width: 100.0%; height: 100.0%;">back\\`tick\\`tick</div>`)[0];
    {popup_name}.setContent({html_name});
    {map_name}.bindPopup({popup_name});
    """.format(
        popup_name=popup.get_name(),
        html_name=list(popup.html._children.keys())[0],
        map_name=m.get_name(),
    )
    assert normalize(rendered) == normalize(expected)


def test_popup_backticks_already_escaped():
    m = Map()
    popup = Popup("back\\`tick").add_to(m)
    rendered = popup._template.render(this=popup, kwargs={})
    expected = """
    var {popup_name} = L.popup({{
        "maxWidth": "100%",
    }});
    var {html_name} = $(`<div id="{html_name}" style="width: 100.0%; height: 100.0%;">back\\`tick</div>`)[0];
    {popup_name}.setContent({html_name});
    {map_name}.bindPopup({popup_name});
    """.format(
        popup_name=popup.get_name(),
        html_name=list(popup.html._children.keys())[0],
        map_name=m.get_name(),
    )
    assert normalize(rendered) == normalize(expected)


def test_icon_valid_marker_colors():
    assert len(Icon.color_options) == 19
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        for color in Icon.color_options:
            Icon(color=color)


def test_custom_pane_show():
    m = Map()
    pane = CustomPane("test-name", z_index=625, pointer_events=False).add_to(m)
    rendered = pane._template.module.script(this=pane, kwargs={})
    expected = f"""
    var {pane.get_name()} = {m.get_name()}.createPane("test-name");
    {pane.get_name()}.style.zIndex = 625;
    {pane.get_name()}.style.pointerEvents = 'none';
    """
    assert normalize(rendered) == normalize(expected)


def test_marker_valid_location():
    m = Map()
    marker = Marker()
    marker.add_to(m)
    with pytest.raises(ValueError):
        m.render()


def test_marker_numpy_array_as_location():
    Marker(np.array([0, 0]))


@pytest.mark.filterwarnings("ignore::UserWarning")
def test_icon_invalid_marker_colors():
    pytest.warns(UserWarning, Icon, color="lila")
    pytest.warns(UserWarning, Icon, color=42)
    pytest.warns(UserWarning, Icon, color=None)


# --- Layer control semantics (disabled / collapsed / ordering) ---


def test_layer_control_disabled_uses_layers_index():
    """LayerControl should use _layers array indexing + _folium meta, not
    querySelector text matching, to disable entries."""
    m = Map(tiles=None)
    TileLayer(name="OpenStreetMap", tiles="OpenStreetMap",
              overlay=False, attr="© OpenStreetMap").add_to(m)
    fg_a = GeoJson({}, name="Markers",
                   control_disabled=True).add_to(m)
    fg_b = GeoJson({}, name="Boundaries").add_to(m)

    LayerControl().add_to(m)
    out = m._parent.render()

    # New _layers-based approach present
    assert "ctl._layers.forEach" in out
    # _folium meta attribute injected
    assert fg_a.get_name() + "._folium" in out
    # Old text-matching approach must be gone
    assert "disabled.indexOf(" not in out
    assert ".innerText" not in out
    # sortLayers disabled in JS
    assert '"sortLayers": false' in out or "sortLayers: false" in out


def test_layer_control_collapsed_overrides_option():
    """Priority rule: an explicit ``collapsed`` argument on the control
    always wins, regardless of layer-level ``control_collapsed`` hints.
    Layer hints only take effect when the user left the control argument
    at its default (i.e. did not pass it explicitly)."""
    # 1. Explicit collapsed=False, no collapsed layers -> stays False
    m1 = Map(tiles=None)
    TileLayer(name="OSM", tiles="OpenStreetMap",
              overlay=False, attr="© OSM").add_to(m1)
    GeoJson({}, name="A").add_to(m1)
    lc1 = LayerControl(collapsed=False).add_to(m1)
    lc1.render()
    assert lc1.options["collapsed"] is False
    assert lc1._collapsed_explicit is True

    # 2. Explicit collapsed=False BUT a layer has control_collapsed=True
    #    -> STILL False (control-level explicit setting wins)
    m2 = Map(tiles=None)
    TileLayer(name="OSM", tiles="OpenStreetMap",
              overlay=False, attr="© OSM").add_to(m2)
    GeoJson({}, name="A", control_collapsed=True).add_to(m2)
    lc2 = LayerControl(collapsed=False).add_to(m2)
    lc2.render()
    assert lc2.options["collapsed"] is False, \
        "Explicit control-level collapsed=False must win over layer hints"
    assert lc2._collapsed_explicit is True
    out2 = m2._parent.render()
    assert '"collapsed": false' in out2 or "collapsed: false" in out2

    # 3. Default (no explicit collapsed) + no collapsed layers -> default True
    m3 = Map(tiles=None)
    TileLayer(name="OSM", tiles="OpenStreetMap",
              overlay=False, attr="© OSM").add_to(m3)
    GeoJson({}, name="B").add_to(m3)
    lc3 = LayerControl().add_to(m3)
    lc3.render()
    assert lc3.options["collapsed"] is True
    assert lc3._collapsed_explicit is False

    # 4. Default (no explicit collapsed) + layer has control_collapsed
    #    -> True (layer hint kicks in)
    m4 = Map(tiles=None)
    TileLayer(name="OSM", tiles="OpenStreetMap",
              overlay=False, attr="© OSM").add_to(m4)
    GeoJson({}, name="C", control_collapsed=True).add_to(m4)
    lc4 = LayerControl().add_to(m4)
    lc4.render()
    assert lc4.options["collapsed"] is True, \
        "Layer-level control_collapsed must force panel collapse when " \
        "control-level argument is left at default"
    assert lc4._collapsed_explicit is False

    # 5. Explicit collapsed=True + no layer hints -> stays True
    m5 = Map(tiles=None)
    TileLayer(name="OSM", tiles="OpenStreetMap",
              overlay=False, attr="© OSM").add_to(m5)
    GeoJson({}, name="D").add_to(m5)
    lc5 = LayerControl(collapsed=True).add_to(m5)
    lc5.render()
    assert lc5.options["collapsed"] is True
    assert lc5._collapsed_explicit is True


def test_layer_control_same_label_base_overlay_no_confusion():
    """A base layer and an overlay sharing the same label must not be
    accidentally cross-disabled by the text-matching-less implementation."""
    m = Map(tiles=None)
    # Base layer called "World" (NOT disabled)
    TileLayer(name="World", tiles="OpenStreetMap",
              overlay=False, attr="© OSM").add_to(m)
    # Overlay called "World" (disabled)
    GeoJson({}, name="World", overlay=True,
            control_disabled=True).add_to(m)

    LayerControl().add_to(m)
    out = m._parent.render()

    # The overlay (second entry in the overall _layers list) must have
    # controlDisabled=true; the base must not.
    assert "controlDisabled: true" in out
    assert "controlDisabled: false" in out
    # Two distinct _folium blocks for the two layers
    assert out.count("_folium = {") >= 2
