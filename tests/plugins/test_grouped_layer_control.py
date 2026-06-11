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
    """Default behaviour: when a layer declares control_collapsed=True and
    the user did NOT pass an explicit group_collapsing argument, the
    enclosing group is rendered collapsed by default and groupCollapsing
    is auto-enabled."""
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
    out = m._parent.render()

    # groupCollapsing must be enabled automatically
    assert "groupCollapsing" in out
    assert 'groupCollapsing": true' in out or "groupCollapsing: true" in out

    # Post-processing JS that clicks on collapsed group names present.
    assert ".forEach(function (idx)" in out
    assert "leaflet-control-layers-group-name" in out
    assert "nameEl" in out and ("click()" in out or ".click(" in out)
    # Group 0 (Pois) is the collapsed one
    assert "[0]" in out or "0].forEach" in out or "0. forEach" in out

    assert lc.options.get("groupCollapsing") is True
    assert lc._group_collapsing is None  # not explicitly set
    assert len(lc._collapsed_groups) >= 1


def test_grouped_layer_control_group_collapsing_explicit_disable():
    """Explicit priority rule: passing group_collapsing=False disables all
    auto-collapsing even when layers declare control_collapsed=True."""
    m = folium.Map(tiles=None)
    folium.TileLayer(name="OSM", tiles="OpenStreetMap",
                     overlay=False, attr="© OSM").add_to(m)
    fg_a = folium.FeatureGroup(name="Markers",
                               control_group=["Pois"],
                               control_collapsed=True).add_to(m)

    lc = groupedlayercontrol.GroupedLayerControl(
        group_collapsing=False,
    ).add_to(m)
    out = m._parent.render()

    # groupCollapsing should be explicitly false in the output
    assert 'groupCollapsing": false' in out or "groupCollapsing: false" in out
    # And the collapsed-groups list MUST be empty — no auto-clicking happens
    assert len(lc._collapsed_groups) == 0, \
        "Explicit group_collapsing=False must empty _collapsed_groups"
    # No post-processing click loop when nothing is collapsed
    # (the {% if %} block in the template guards against it)
    assert ".forEach(function (idx)" not in out or \
        "[].forEach" in out  # if for some reason an empty list still triggers


def test_grouped_layer_control_group_collapsing_explicit_enable():
    """Explicit group_collapsing=True enables collapsing even when no layer
    declares control_collapsed=True (but no group is auto-folded)."""
    m = folium.Map(tiles=None)
    folium.TileLayer(name="OSM", tiles="OpenStreetMap",
                     overlay=False, attr="© OSM").add_to(m)
    folium.FeatureGroup(name="Markers",
                        control_group=["Pois"]).add_to(m)

    lc = groupedlayercontrol.GroupedLayerControl(
        group_collapsing=True,
    ).add_to(m)
    out = m._parent.render()

    # groupCollapsing should be true
    assert 'groupCollapsing": true' in out or "groupCollapsing: true" in out
    # But no group is auto-collapsed (no layers requested it)
    assert len(lc._collapsed_groups) == 0
