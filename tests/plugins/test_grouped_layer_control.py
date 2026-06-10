import folium
from folium.plugins import FeatureGroupSubGroup, MarkerCluster, groupedlayercontrol
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
    print(out)
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
            {{"exclusiveGroups": ["groups1",],}},
         ).addTo({m.get_name()});
         {fg2.get_name()}.remove();
    """)
    assert expected in out


def test_grouped_layer_control_same_name_preserves_both():
    m = folium.Map([40.0, 70.0], zoom_start=6)
    fg_a = folium.FeatureGroup(name="Duplicate")
    fg_b = folium.FeatureGroup(name="Duplicate")
    folium.Marker([40, 74]).add_to(fg_a)
    folium.Marker([38, 72]).add_to(fg_b)
    m.add_child(fg_a)
    m.add_child(fg_b)
    lc = groupedlayercontrol.GroupedLayerControl(
        groups={"g1": [fg_a, fg_b]}, exclusive_groups=False
    )
    lc.add_to(m)
    lc.render()
    group_entries = lc.grouped_overlays["g1"]
    labels = [v["label"] for v in group_entries.values()]
    assert labels.count("Duplicate") == 2
    assert len(group_entries) == 2


def test_grouped_layer_control_dedup_same_object_in_group():
    m = folium.Map([40.0, 70.0], zoom_start=6)
    fg = folium.FeatureGroup(name="Once")
    folium.Marker([40, 74]).add_to(fg)
    m.add_child(fg)
    lc = groupedlayercontrol.GroupedLayerControl(
        groups={"g1": [fg, fg]}, exclusive_groups=False
    )
    lc.add_to(m)
    lc.render()
    group_entries = lc.grouped_overlays["g1"]
    assert len(group_entries) == 1
    labels = [v["label"] for v in group_entries.values()]
    assert labels.count("Once") == 1


def test_grouped_layer_control_control_false_container_expands():
    m = folium.Map([40.0, 70.0], zoom_start=6)
    outer = folium.FeatureGroup(name="Wrapper", control=False)
    inner_a = folium.FeatureGroup(name="InnerA")
    inner_b = folium.FeatureGroup(name="InnerB")
    outer.add_child(inner_a)
    outer.add_child(inner_b)
    m.add_child(outer)
    lc = groupedlayercontrol.GroupedLayerControl(
        groups={"g": [outer]}, exclusive_groups=False
    )
    lc.add_to(m)
    lc.render()
    group_entries = lc.grouped_overlays["g"]
    labels = [v["label"] for v in group_entries.values()]
    assert "Wrapper" not in labels
    assert "InnerA" in labels
    assert "InnerB" in labels
    assert len(group_entries) == 2


def test_grouped_layer_control_control_true_is_boundary():
    m = folium.Map([40.0, 70.0], zoom_start=6)
    outer = folium.FeatureGroup(name="Outer", control=True)
    inner = folium.FeatureGroup(name="Inner", control=True)
    outer.add_child(inner)
    m.add_child(outer)
    lc = groupedlayercontrol.GroupedLayerControl(
        groups={"g": [outer]}, exclusive_groups=False
    )
    lc.add_to(m)
    lc.render()
    group_entries = lc.grouped_overlays["g"]
    labels = [v["label"] for v in group_entries.values()]
    assert "Outer" in labels
    assert "Inner" not in labels
    assert len(group_entries) == 1


def test_grouped_layer_control_late_addition_inside_control_false_container():
    m = folium.Map([40.0, 70.0], zoom_start=6)
    outer = folium.FeatureGroup(name="Wrapper", control=False)
    early = folium.FeatureGroup(name="Early")
    outer.add_child(early)
    m.add_child(outer)
    lc = groupedlayercontrol.GroupedLayerControl(
        groups={"g": [outer]}, exclusive_groups=False
    )
    lc.add_to(m)
    late = folium.FeatureGroup(name="Late")
    outer.add_child(late)
    lc.render()
    group_entries = lc.grouped_overlays["g"]
    labels = [v["label"] for v in group_entries.values()]
    assert "Wrapper" not in labels
    assert "Early" in labels
    assert "Late" in labels
    assert len(group_entries) == 2


def test_grouped_layer_control_with_marker_cluster_and_subgroups():
    m = folium.Map([40.0, 70.0], zoom_start=6)
    mcg = MarkerCluster(control=False)
    m.add_child(mcg)
    sg_a = FeatureGroupSubGroup(mcg, "Subgroup A")
    sg_b = FeatureGroupSubGroup(mcg, "Subgroup B")
    sg_a.add_child(folium.Marker([40, 74]))
    sg_b.add_child(folium.Marker([38, 72]))
    m.add_child(sg_a)
    m.add_child(sg_b)
    lc = groupedlayercontrol.GroupedLayerControl(
        groups={"Points": [sg_a, sg_b]}, exclusive_groups=True
    )
    lc.add_to(m)
    lc.render()
    group_entries = lc.grouped_overlays["Points"]
    labels = [v["label"] for v in group_entries.values()]
    assert "Subgroup A" in labels
    assert "Subgroup B" in labels
    assert len(group_entries) == 2
    js_names = [v["layer_js"] for v in group_entries.values()]
    assert sg_a.get_name() in js_names
    assert sg_b.get_name() in js_names
    assert sg_a.get_name() not in lc.layers_untoggle
    assert sg_b.get_name() in lc.layers_untoggle


def test_grouped_layer_control_control_false_cluster_expands():
    m = folium.Map([40.0, 70.0], zoom_start=6)
    mcg = MarkerCluster(control=False)
    sg_a = FeatureGroupSubGroup(mcg, "Subgroup A")
    sg_b = FeatureGroupSubGroup(mcg, "Subgroup B")
    sg_a.add_child(folium.Marker([40, 74]))
    sg_b.add_child(folium.Marker([38, 72]))
    mcg.add_child(sg_a)
    mcg.add_child(sg_b)
    m.add_child(mcg)
    lc = groupedlayercontrol.GroupedLayerControl(
        groups={"Points": [mcg]}, exclusive_groups=False
    )
    lc.add_to(m)
    lc.render()
    group_entries = lc.grouped_overlays["Points"]
    labels = [v["label"] for v in group_entries.values()]
    assert "Subgroup A" in labels
    assert "Subgroup B" in labels
    assert len(group_entries) == 2

