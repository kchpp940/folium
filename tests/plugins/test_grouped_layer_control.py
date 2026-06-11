import folium
from folium.plugins import groupedlayercontrol
from folium.utilities import normalize


def test_grouped_layer_control():
    m = folium.Map([40.0, 70.0], zoom_start=6)
    fg1 = folium.FeatureGroup(name="g1")
    fg2 = folium.FeatureGroup(name="g2")
    fg3 = folium.FeatureGroup(name="g3")
    folium.Marker([40, 74]).add_to(fg1)
    folium.Marker([38, 72]).add_to(fg2)
    folium.Marker([40, 72]).add_to(fg3)
    m.add_child(fg1)
    m.add_child(fg2)
    m.add_child(fg3)
    lc = groupedlayercontrol.GroupedLayerControl(groups={"groups1": [fg1, fg2]})
    lc.add_to(m)
    out = m._parent.render()
    out = normalize(out)

    assert (
        "https://cdnjs.cloudflare.com/ajax/libs/leaflet-groupedlayercontrol/0.6.1/leaflet.groupedlayercontrol.min.js"
        in out
    )

    expected = normalize(f"""
        L.control.groupedLayers(
            null,
            {{
                "groups1" : {{
                    "g1" : {fg1.get_name()},
                    "g2" : {fg2.get_name()},
                }},
            }},
            {{"sortLayers": false,"exclusiveGroups": ["groups1",],}},
         ).addTo({m.get_name()});
         {fg2.get_name()}.remove();
    """)
    assert expected in out


def test_grouped_layer_control_disabled_uses_layers_index():
    """GroupedLayerControl must use _layers array indexing + _folium meta
    (no text-based querySelector matching) for control_disabled."""
    m = folium.Map(tiles=None)
    folium.TileLayer(name="OSM", tiles="OpenStreetMap",
                     overlay=False, attr="© OSM").add_to(m)
    fg_a = folium.FeatureGroup(name="Markers", control_disabled=True).add_to(m)
    fg_b = folium.FeatureGroup(name="Boundaries").add_to(m)
    folium.Marker([0, 0]).add_to(fg_b)

    lc = groupedlayercontrol.GroupedLayerControl(groups={
        "Overlays": [fg_a, fg_b],
    }).add_to(m)
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


def test_grouped_layer_control_collapsed_groups():
    """control_collapsed on a layer in GroupedLayerControl must cause the
    enclosing group to be rendered in the collapsed state by default, and
    groupCollapsing must be auto-enabled."""
    m = folium.Map(tiles=None)
    folium.TileLayer(name="OSM", tiles="OpenStreetMap",
                     overlay=False, attr="© OSM").add_to(m)
    fg_a = folium.FeatureGroup(name="Markers",
                               control_group=["Pois", "Europe"],
                               control_collapsed=True).add_to(m)
    fg_b = folium.FeatureGroup(name="Boundaries",
                               control_group=["Pois", "Europe"]).add_to(m)
    fg_c = folium.FeatureGroup(name="Other",
                               control_group=["Misc"]).add_to(m)

    lc = groupedlayercontrol.GroupedLayerControl().add_to(m)
    # Do NOT call lc.render() manually — the control has side effects on
    # layer.control that would break the subsequent full map render.
    out = m._parent.render()

    # groupCollapsing must be enabled automatically
    assert "groupCollapsing" in out
    assert 'groupCollapsing": true' in out or "groupCollapsing: true" in out

    # Post-processing JS that clicks on collapsed group names present.
    # The template renders: <idx_list>.forEach(function (idx) { ... nameEl.click() })
    # (the list is the _collapsed_groups value serialised via |tojson, so
    # the literal text "_collapsed_groups" does not appear in the output).
    assert ".forEach(function (idx)" in out
    assert "leaflet-control-layers-group-name" in out
    assert "nameEl" in out and ("click()" in out or ".click(" in out)
    # We know group 0 (Pois) is the collapsed one: the index list starts with 0
    assert "[0]" in out or "0].forEach" in out or "0. forEach" in out

    # At minimum the rendering path must be exercised: options include groupCollapsing
    assert lc.options.get("groupCollapsing") is True
