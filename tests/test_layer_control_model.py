import folium
from folium.map import FeatureGroup, LayerControl
from folium.layer_control_model import LayerControlModel, collect_excluded_layers
from folium.plugins import GroupedLayerControl, TreeLayerControl


def _find_leaf_labels(node, acc=None):
    if acc is None:
        acc = []
    if isinstance(node, list):
        for n in node:
            _find_leaf_labels(n, acc)
    elif isinstance(node, dict):
        if "children" in node:
            _find_leaf_labels(node["children"], acc)
        else:
            acc.append(node.get("label"))
    return acc


def test_grouped_no_control_mutation():
    m = folium.Map()
    fg1 = FeatureGroup(name="fg1", control=True, show=True, overlay=True)
    fg2 = FeatureGroup(name="fg2", control=True, show=True, overlay=True)
    fg1.add_to(m)
    fg2.add_to(m)

    assert fg1.control is True
    assert fg2.control is True

    GroupedLayerControl(groups={"MyGroup": [fg1, fg2]}).add_to(m)
    m._repr_html_()

    assert fg1.control is True
    assert fg2.control is True


def test_grouped_auto_grouped_via_control_group():
    m = folium.Map()
    fg_auto = FeatureGroup(
        name="auto_grp",
        control=True,
        show=True,
        overlay=True,
        control_group="AutoGroup",
    )
    fg_explicit = FeatureGroup(
        name="explicit_grp", control=True, show=True, overlay=True
    )
    fg_no_group = FeatureGroup(
        name="no_group", control=True, show=True, overlay=True
    )
    fg_auto.add_to(m)
    fg_explicit.add_to(m)
    fg_no_group.add_to(m)

    ctrl = GroupedLayerControl(
        groups={"ExplicitGroup": [fg_explicit]}
    ).add_to(m)
    m._repr_html_()

    go = ctrl.grouped_overlays
    assert "AutoGroup" in go
    assert "ExplicitGroup" in go
    assert fg_auto.layer_name in go["AutoGroup"]
    assert fg_explicit.layer_name in go["ExplicitGroup"]
    assert "no_group" not in str(go)


def test_tree_auto_builds_from_control_group():
    m = folium.Map()
    fg_fr = FeatureGroup(
        name="France",
        control=True,
        show=True,
        overlay=True,
        control_group="POI/Europe/France",
    )
    fg_de = FeatureGroup(
        name="Germany",
        control=True,
        show=True,
        overlay=True,
        control_group="POI/Europe/Germany",
    )
    fg_uk = FeatureGroup(
        name="UK",
        control=True,
        show=True,
        overlay=True,
        control_group="POI/UK",
    )
    fg_fr.add_to(m)
    fg_de.add_to(m)
    fg_uk.add_to(m)

    ctrl = TreeLayerControl().add_to(m)
    m._repr_html_()

    ot = ctrl.overlay_tree
    labels = _find_leaf_labels(ot)
    assert "France" in labels
    assert "Germany" in labels
    assert "UK" in labels


def test_tree_override_merges_with_auto():
    m = folium.Map()
    fg_spain = FeatureGroup(
        name="Spain",
        control=True,
        show=True,
        overlay=True,
        control_group="POI/Europe/Spain",
    )
    fg_portugal = FeatureGroup(
        name="Portugal", control=True, show=True, overlay=True
    )
    fg_spain.add_to(m)
    fg_portugal.add_to(m)

    override_tree = {
        "label": "POI",
        "children": [
            {
                "label": "Europe",
                "children": [
                    {
                        "label": "Iberia",
                        "children": [{"label": "Portugal", "layer": fg_portugal}],
                    }
                ],
            }
        ],
    }

    ctrl = TreeLayerControl(overlay_tree=override_tree).add_to(m)
    m._repr_html_()

    labels = _find_leaf_labels(ctrl.overlay_tree)
    assert "Spain" in labels
    assert "Portugal" in labels


def test_control_disabled_untoggle():
    m = folium.Map()
    fg = FeatureGroup(
        name="hidden_fg",
        control=True,
        show=True,
        overlay=True,
        control_group="Grp",
        control_disabled=True,
    )
    fg.add_to(m)

    ctrl = GroupedLayerControl(groups={}).add_to(m)
    m._repr_html_()

    assert fg.get_name() in ctrl.layers_untoggle


def test_control_collapsed_in_tree():
    m = folium.Map()
    fg = FeatureGroup(
        name="collapsed_fg",
        control=True,
        show=True,
        overlay=True,
        control_group="A/B/C",
        control_collapsed=True,
    )
    fg.add_to(m)

    ctrl = TreeLayerControl().add_to(m)
    m._repr_html_()

    labels = _find_leaf_labels(ctrl.overlay_tree)
    assert "collapsed_fg" in labels


def test_layer_control_excludes_grouped_explicit():
    m = folium.Map()
    fg1 = FeatureGroup(name="fg1", control=True, show=True, overlay=True)
    fg2 = FeatureGroup(name="fg2", control=True, show=True, overlay=True)
    fg3 = FeatureGroup(name="fg3", control=True, show=True, overlay=True)
    fg1.add_to(m)
    fg2.add_to(m)
    fg3.add_to(m)

    GroupedLayerControl(groups={"G": [fg1, fg2]}).add_to(m)
    lc = LayerControl().add_to(m)
    m._repr_html_()

    assert fg1.layer_name not in lc.overlays
    assert fg2.layer_name not in lc.overlays
    assert fg3.layer_name in lc.overlays


def test_layer_control_excludes_grouped_auto():
    m = folium.Map()
    fg_auto = FeatureGroup(
        name="auto_fg",
        control=True,
        show=True,
        overlay=True,
        control_group="AutoGrp",
    )
    fg_plain = FeatureGroup(
        name="plain_fg", control=True, show=True, overlay=True
    )
    fg_auto.add_to(m)
    fg_plain.add_to(m)

    GroupedLayerControl(groups={}).add_to(m)
    lc = LayerControl().add_to(m)
    m._repr_html_()

    assert fg_auto.layer_name not in lc.overlays
    assert fg_plain.layer_name in lc.overlays


def test_layer_control_excludes_tree_explicit():
    m = folium.Map()
    fg_tree = FeatureGroup(
        name="tree_fg", control=True, show=True, overlay=True
    )
    fg_plain = FeatureGroup(
        name="plain_fg", control=True, show=True, overlay=True
    )
    fg_tree.add_to(m)
    fg_plain.add_to(m)

    overlay_tree = {
        "label": "Root",
        "children": [{"label": "TreeLayer", "layer": fg_tree}],
    }
    TreeLayerControl(overlay_tree=overlay_tree).add_to(m)
    lc = LayerControl().add_to(m)
    m._repr_html_()

    assert fg_tree.layer_name not in lc.overlays
    assert fg_plain.layer_name in lc.overlays


def test_layer_control_excludes_tree_auto():
    m = folium.Map()
    fg_auto = FeatureGroup(
        name="auto_tree_fg",
        control=True,
        show=True,
        overlay=True,
        control_group="Grp/Sub",
    )
    fg_plain = FeatureGroup(
        name="plain_fg2", control=True, show=True, overlay=True
    )
    fg_auto.add_to(m)
    fg_plain.add_to(m)

    TreeLayerControl().add_to(m)
    lc = LayerControl().add_to(m)
    m._repr_html_()

    assert fg_auto.layer_name not in lc.overlays
    assert fg_plain.layer_name in lc.overlays


def test_no_grouped_or_tree_no_exclusion():
    m = folium.Map()
    fg = FeatureGroup(
        name="fg_with_group",
        control=True,
        show=True,
        overlay=True,
        control_group="SomeGroup",
    )
    fg.add_to(m)

    lc = LayerControl().add_to(m)
    m._repr_html_()

    assert fg.layer_name in lc.overlays


def test_collect_excluded_layers_function():
    m = folium.Map()
    fg1 = FeatureGroup(name="fg1", control=True, show=True, overlay=True)
    fg2 = FeatureGroup(
        name="fg2",
        control=True,
        show=True,
        overlay=True,
        control_group="G",
    )
    fg1.add_to(m)
    fg2.add_to(m)

    excluded = collect_excluded_layers(m)
    assert len(excluded) == 0

    GroupedLayerControl(groups={"G": [fg1]}).add_to(m)
    excluded = collect_excluded_layers(m)
    assert fg1 in excluded
    assert fg2 in excluded


def test_grouped_order_explicit_then_auto():
    m = folium.Map()
    fg_explicit = FeatureGroup(
        name="explicit_fg", control=True, show=True, overlay=True
    )
    fg_auto = FeatureGroup(
        name="auto_fg",
        control=True,
        show=True,
        overlay=True,
        control_group="AutoGrp",
    )
    fg_explicit.add_to(m)
    fg_auto.add_to(m)

    ctrl = GroupedLayerControl(
        groups={"ExplicitGrp": [fg_explicit]}
    ).add_to(m)
    m._repr_html_()

    keys = list(ctrl.grouped_overlays.keys())
    assert keys.index("ExplicitGrp") < keys.index("AutoGrp")


def test_tree_control_group_deep_path():
    m = folium.Map()
    fg1 = FeatureGroup(
        name="leaf1",
        control=True,
        show=True,
        overlay=True,
        control_group="A/B/C/D",
    )
    fg2 = FeatureGroup(
        name="leaf2",
        control=True,
        show=True,
        overlay=True,
        control_group="A/B/E",
    )
    fg1.add_to(m)
    fg2.add_to(m)

    ctrl = TreeLayerControl().add_to(m)
    m._repr_html_()

    labels = _find_leaf_labels(ctrl.overlay_tree)
    assert "leaf1" in labels
    assert "leaf2" in labels


def test_model_exclude_parameter():
    m = folium.Map()
    fg1 = FeatureGroup(name="kept", control=True, show=True, overlay=True)
    fg2 = FeatureGroup(name="excluded", control=True, show=True, overlay=True)
    fg1.add_to(m)
    fg2.add_to(m)

    model = LayerControlModel.from_map_children(m, exclude={fg2})
    assert model.find_entry(fg1) is not None
    assert model.find_entry(fg2) is None
