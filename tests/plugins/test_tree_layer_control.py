"""Tests for TreeLayerControl unified disabled/collapsed/order semantics."""

import re

import folium
from folium import FeatureGroup
from folium.plugins import TreeLayerControl


def test_tree_layer_control_disabled_uses_data_attribute():
    """TreeLayerControl must encode disabled state as a data-folium-disabled
    HTML attribute embedded in the label string, and use a CSS selector to
    disable the DOM entry — no text-based querySelector matching."""
    m = folium.Map()
    FeatureGroup(name='Paris',
                 control_group=['POIs', 'Europe'],
                 control_disabled=True,
                 control_order=10).add_to(m)
    FeatureGroup(name='London',
                 control_group=['POIs', 'Europe'],
                 control_order=20).add_to(m)
    FeatureGroup(name='NYC',
                 control_group=['POIs', 'Americas'],
                 control_disabled=True).add_to(m)

    TreeLayerControl().add_to(m)
    out = m._parent.render()

    # data-folium-disabled attribute present in label HTML
    assert 'data-folium-disabled' in out, \
        'data-folium-disabled attribute not found in tree labels'

    # Exactly two disabled labels (Paris + NYC), encoded in JSON with
    # escaped quotes: data-folium-disabled=\"true\"
    label_disabled_count = out.count('data-folium-disabled=\\"true\\"')
    assert label_disabled_count == 2, \
        f'Expected 2 disabled labels, got {label_disabled_count}'

    # Old text-matching approach gone
    assert 'disabled.indexOf(' not in out, 'Old text-matching still present!'
    assert '.innerText' not in out and '.textContent' not in out, \
        'Old text-based matching still present'

    # New CSS-selector-based approach present
    assert 'querySelectorAll' in out and 'data-folium-disabled' in out, \
        'CSS-selector disabled handler not present'


def test_tree_layer_control_same_label_at_different_levels():
    """Two layers with the same label living at different tree depths must
    not collapse into a single node, and each may be independently disabled."""
    m = folium.Map()
    # Same name but at different levels and different control_group
    FeatureGroup(name='Duplicate',
                 control_group=['Top'],
                 control_disabled=True).add_to(m)
    FeatureGroup(name='Duplicate',
                 control_group=['Bottom', 'Deep']).add_to(m)

    TreeLayerControl().add_to(m)
    out = m._parent.render()

    # The string "Duplicate" should appear exactly twice in label context
    # (once as a leaf node at each depth).  We count JSON-serialised label:
    # keys containing the name.
    dup_count = len(re.findall(r'"label":\s*"Duplicate"', out))
    # The label wrapped in data-folium-disabled span also contains the word
    dup_count += len(re.findall(r'Duplicate.*data-folium-disabled', out))
    # At minimum the name is present more than once
    assert out.count('Duplicate') >= 2, 'Duplicate names were collapsed!'

    # And one (and only one) is disabled
    disabled_count = out.count('data-folium-disabled=\\"true\\"')
    assert disabled_count == 1, \
        f'Expected exactly 1 disabled node, got {disabled_count}'


def test_tree_layer_control_multi_leaves_per_group():
    """A control_group path with multiple layers inside it must render each
    layer as a distinct leaf (not overwrite earlier layers)."""
    m = folium.Map()
    FeatureGroup(name='Layer 1',
                 control_group=['Only Group'],
                 control_order=1).add_to(m)
    FeatureGroup(name='Layer 2',
                 control_group=['Only Group'],
                 control_order=2).add_to(m)
    FeatureGroup(name='Layer 3',
                 control_group=['Only Group'],
                 control_order=3,
                 control_disabled=True).add_to(m)

    TreeLayerControl().add_to(m)
    out = m._parent.render()

    # All three layer names must be present
    assert '"Layer 1"' in out or '>Layer 1<' in out
    assert '"Layer 2"' in out or '>Layer 2<' in out
    # Layer 3 is disabled so it's wrapped in the span
    assert 'Layer 3' in out
    # Exactly 1 disabled (Layer 3)
    disabled_count = out.count('data-folium-disabled=\\"true\\"')
    assert disabled_count == 1, \
        f'Expected exactly 1 disabled node (Layer 3), got {disabled_count}'


def test_tree_layer_control_panel_collapsed_priority():
    """Panel-level collapsed priority: explicit TreeLayerControl(collapsed=...)
    argument always wins over layer-level control_collapsed hints for the
    overall control panel.  (Per-node collapsed inside the tree is
    unaffected by this flag.)"""
    # 1. Explicit collapsed=False, layer has control_collapsed -> still False
    m1 = folium.Map(tiles=None)
    folium.TileLayer(name="OSM", tiles="OpenStreetMap",
                     overlay=False, attr="© OSM").add_to(m1)
    FeatureGroup(name='A', control_collapsed=True).add_to(m1)
    lc1 = TreeLayerControl(collapsed=False).add_to(m1)
    lc1.render()
    assert lc1.options["collapsed"] is False
    assert lc1._collapsed_explicit is True

    # 2. Default (no explicit) + layer has control_collapsed -> True
    m2 = folium.Map(tiles=None)
    folium.TileLayer(name="OSM", tiles="OpenStreetMap",
                     overlay=False, attr="© OSM").add_to(m2)
    FeatureGroup(name='B', control_collapsed=True).add_to(m2)
    lc2 = TreeLayerControl().add_to(m2)
    lc2.render()
    assert lc2.options["collapsed"] is True
    assert lc2._collapsed_explicit is False

    # 3. Default (no explicit) + no collapsed layers -> default True
    m3 = folium.Map(tiles=None)
    folium.TileLayer(name="OSM", tiles="OpenStreetMap",
                     overlay=False, attr="© OSM").add_to(m3)
    FeatureGroup(name='C').add_to(m3)
    lc3 = TreeLayerControl().add_to(m3)
    lc3.render()
    assert lc3.options["collapsed"] is True
    assert lc3._collapsed_explicit is False


def test_tree_layer_control_node_collapsed_explicit_priority():
    """Within the tree itself: an explicit collapsed attribute on an
    overlay_tree / base_tree LEAF node overrides the layer's own
    control_collapsed hint when the two refer to the same leaf."""
    m = folium.Map()
    fg = FeatureGroup(name='Paris',
                      control_group=['POIs', 'Europe'],
                      control_collapsed=True).add_to(m)

    # The explicit tree sets the Paris *leaf* node to collapsed=False,
    # overriding the layer-level control_collapsed=True.
    explicit = {
        'label': 'POIs',
        'children': [
            {
                'label': 'Europe',
                'children': [
                    {
                        'label': 'Paris',
                        'layer': fg,
                        'collapsed': False,  # explicit override of layer hint
                    }
                ]
            }
        ]
    }
    TreeLayerControl(overlay_tree=explicit).add_to(m)
    out = m._parent.render()

    # In the final JSON the Paris leaf should NOT have "collapsed": true,
    # because the explicit tree said False (and False is the default,
    # so it may be omitted entirely).
    # Look specifically for the Paris leaf entry:
    import re
    # Find the "Paris" label block and check it doesn't contain collapsed: true
    paris_match = re.search(
        r'"label":\s*"Paris".*?}', out, re.DOTALL,
    )
    assert paris_match, "Paris node not found in output"
    paris_block = paris_match.group()
    assert '"collapsed": true' not in paris_block and \
        'collapsed: true' not in paris_block, \
        f"Paris leaf should not be collapsed (explicit=False wins): {paris_block}"

    # The layer should still be attached to the node
    assert fg.get_name() in paris_block
