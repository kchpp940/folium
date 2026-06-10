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


def test_layer_control_excludes_grouped_managed_layers():
    m = folium.Map([40.0, 70.0], zoom_start=6, tiles=None)
    fg1 = folium.FeatureGroup(name="Managed1")
    fg2 = folium.FeatureGroup(name="Managed2")
    fg3 = folium.FeatureGroup(name="Standalone")
    m.add_child(fg1)
    m.add_child(fg2)
    m.add_child(fg3)
    glc = groupedlayercontrol.GroupedLayerControl(
        groups={"G": [fg1, fg2]}, exclusive_groups=False
    )
    glc.add_to(m)
    lc = folium.LayerControl().add_to(m)
    lc.render()
    overlay_labels = [v["label"] for v in lc.overlays.values()]
    assert "Managed1" not in overlay_labels
    assert "Managed2" not in overlay_labels
    assert "Standalone" in overlay_labels
    assert len(lc.overlays) == 1


def test_layer_control_excludes_grouped_regardless_of_add_order():
    m = folium.Map([40.0, 70.0], zoom_start=6, tiles=None)
    fg1 = folium.FeatureGroup(name="Managed")
    fg2 = folium.FeatureGroup(name="Standalone")
    m.add_child(fg1)
    m.add_child(fg2)
    lc = folium.LayerControl().add_to(m)
    glc = groupedlayercontrol.GroupedLayerControl(
        groups={"G": [fg1]}, exclusive_groups=False
    )
    glc.add_to(m)
    lc.render()
    overlay_labels = [v["label"] for v in lc.overlays.values()]
    assert "Managed" not in overlay_labels
    assert "Standalone" in overlay_labels
    assert len(lc.overlays) == 1


def test_multiple_grouped_controls_do_not_interfere():
    m = folium.Map([40.0, 70.0], zoom_start=6, tiles=None)
    fg_a1 = folium.FeatureGroup(name="G1-A")
    fg_a2 = folium.FeatureGroup(name="G1-B")
    fg_b1 = folium.FeatureGroup(name="G2-A")
    fg_b2 = folium.FeatureGroup(name="G2-B")
    m.add_child(fg_a1)
    m.add_child(fg_a2)
    m.add_child(fg_b1)
    m.add_child(fg_b2)
    glc1 = groupedlayercontrol.GroupedLayerControl(
        groups={"Group1": [fg_a1, fg_a2]}, exclusive_groups=False
    )
    glc2 = groupedlayercontrol.GroupedLayerControl(
        groups={"Group2": [fg_b1, fg_b2]}, exclusive_groups=False
    )
    glc1.add_to(m)
    glc2.add_to(m)
    glc1.render()
    glc2.render()
    g1_labels = [v["label"] for v in glc1.grouped_overlays["Group1"].values()]
    g2_labels = [v["label"] for v in glc2.grouped_overlays["Group2"].values()]
    assert "G1-A" in g1_labels and "G1-B" in g1_labels
    assert "G2-A" in g2_labels and "G2-B" in g2_labels
    assert len(glc1.grouped_overlays["Group1"]) == 2
    assert len(glc2.grouped_overlays["Group2"]) == 2
    lc = folium.LayerControl().add_to(m)
    lc.render()
    overlay_labels = [v["label"] for v in lc.overlays.values()]
    for name in ("G1-A", "G1-B", "G2-A", "G2-B"):
        assert name not in overlay_labels
    assert len(lc.overlays) == 0


def test_layer_control_preserves_original_control_attribute():
    m = folium.Map([40.0, 70.0], zoom_start=6, tiles=None)
    fg = folium.FeatureGroup(name="Managed")
    m.add_child(fg)
    assert fg.control is True
    glc = groupedlayercontrol.GroupedLayerControl(
        groups={"G": [fg]}, exclusive_groups=False
    )
    glc.add_to(m)
    assert fg.control is True, "GroupedLayerControl.__init__ must not mutate control"
    lc = folium.LayerControl().add_to(m)
    lc.render()
    glc.render()
    assert fg.control is True, "Render must not mutate control"

