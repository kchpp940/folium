from typing import Union

from branca.element import MacroElement

from folium.elements import JSCSSMixin
from folium.template import Template
from folium.utilities import remove_empty


class TreeLayerControl(JSCSSMixin, MacroElement):
    """
    Create a Layer Control allowing a tree structure for the layers.
    See https://github.com/jjimenezshaw/Leaflet.Control.Layers.Tree for more
    information.

    Besides passing explicit ``base_tree`` and ``overlay_tree`` dicts (the
    traditional API), you can instead (or in addition) rely on each layer's
    ``control_group`` attribute.  Pass a list, e.g.
    ``["Europe", "France", "Paris"]``, and the control will automatically
    construct the matching branches.  Explicit trees are merged on top.

    Parameters
    ----------
    base_tree : dict or list, optional
        A dictionary defining the base layers, OR a skeleton onto which
        layers declaring ``control_group`` are merged.
        Valid elements are

        children: list
            Array of child nodes for this node. Each node is a dict that
            has the same valid elements as base_tree.
        label: str
            Text displayed in the tree for this node. It may contain HTML
            code.
        layer: Layer
            The layer itself. This needs to be added to the map.
        name: str
            Text displayed in the toggle when control is minimized.
            If not present, label is used. It makes sense only when
            namedToggle is true, and with base layers.
        radioGroup: str, default ''
            Text to identify different radio button groups.
            It is used in the name attribute in the radio button.
            It is used only in the overlays layers (ignored in the base
            layers), allowing you to have radio buttons instead of checkboxes.
            See that radio groups cannot be unselected, so create a 'fake'
            layer (like L.layersGroup([])) if you want to disable it.
            Default '' (that means checkbox).
        collapsed: bool, default False
            Indicate whether this tree node should be collapsed initially,
            useful for opening large trees partially based on user input or
            context.  Can also be set per-layer with the ``control_collapsed``
            attribute on any :class:`~folium.map.Layer`.
        selectAllCheckbox: bool or str
            Displays a checkbox to select/unselect all overlays in the
            sub-tree. In case of being a <str>, that text will be the title
            (tooltip). When any overlay in the sub-tree is clicked, the
            checkbox goes into indeterminate state (a dash in the box).
    overlay_tree : dict or list, optional
        Similar to baseTree, but for overlays.  If omitted entirely, a tree
        is built automatically from every overlay layer's ``control_group``.
    closed_symbol : str, default '+',
        Symbol displayed on a closed node (that you can click to open).
    opened_symbol : str, default '-',
        Symbol displayed on an opened node (that you can click to close).
    space_symbol : str, default ' ',
        Symbol between the closed or opened symbol, and the text.
    selector_back : bool, default False,
        Flag to indicate if the selector (+ or −) is after the text.
    named_toggle : bool, default False,
        Flag to replace the toggle image (box with the layers image) with the
        'name' of the selected base layer. If the name field is not present in
        the tree for this layer, label is used. See that you can show a
        different name when control is collapsed than the one that appears
        in the tree when it is expanded.
    collapse_all : str, default '',
        Text for an entry in control that collapses the tree (baselayers or
        overlays). If empty, no entry is created.
    expand_all : str, default '',
        Text for an entry in control that expands the tree. If empty, no entry
        is created
    label_is_selector : str, default 'both',
        Controls if a label or only the checkbox/radiobutton can toggle layers.
        If set to `both`, `overlay` or `base` those labels can be clicked
        on to toggle the layer.
    auto_build : bool, default True
        If True and only a skeleton (or None) is given for base/overlay
        trees, automatically populate them from the map's layer children
        using each layer's ``control_group`` attribute.
    **kwargs
        Additional (possibly inherited) options. See
        https://leafletjs.com/reference.html#control-layers

    Examples
    --------
    >>> import folium
    >>> from folium.plugins.treelayercontrol import TreeLayerControl
    >>> from folium.features import Marker

    >>> m = folium.Map(location=[46.603354, 1.8883335], zoom_start=5)

    >>> marker = Marker(
    ...     [48.8582441, 2.2944775],
    ...     name="Tour Eiffel",
    ...     control_group=["Points of Interest", "Europe", "France"],
    ...     control_order=1,
    ... ).add_to(m)

    >>> control = TreeLayerControl().add_to(m)
    """

    default_js = [
        (
            "L.Control.Layers.Tree.min.js",
            "https://cdn.jsdelivr.net/npm/leaflet.control.layers.tree@1.1.0/L.Control.Layers.Tree.min.js",  # noqa
        ),
    ]
    default_css = [
        (
            "L.Control.Layers.Tree.min.css",
            "https://cdn.jsdelivr.net/npm/leaflet.control.layers.tree@1.1.0/L.Control.Layers.Tree.min.css",  # noqa
        )
    ]

    _template = Template("""
        {% macro script(this,kwargs) %}
            L.control.layers.tree(
                {{this.base_tree|tojavascript}},
                {{this.overlay_tree|tojavascript}},
                {{this.options|tojavascript}}
            ).addTo({{this._parent.get_name()}});

            {%- if this.disabled_layers %}
            (function () {
                var sel = '.leaflet-control-layers-list label';
                var disabled = {{ this.disabled_layers|tojson }};
                document.querySelectorAll(sel).forEach(function (lbl) {
                    var txt = (lbl.innerText || lbl.textContent || '').trim();
                    if (disabled.indexOf(txt) !== -1) {
                        var inp = lbl.querySelector('input');
                        if (inp) inp.disabled = true;
                        lbl.style.opacity = '0.5';
                    }
                });
            })();
            {%- endif %}
        {% endmacro %}
        """)

    def __init__(
        self,
        base_tree: Union[dict, list, None] = None,
        overlay_tree: Union[dict, list, None] = None,
        closed_symbol: str = "+",
        opened_symbol: str = "-",
        space_symbol: str = "&nbsp;",
        selector_back: bool = False,
        named_toggle: bool = False,
        collapse_all: str = "",
        expand_all: str = "",
        label_is_selector: str = "both",
        auto_build: bool = True,
        **kwargs,
    ):
        super().__init__()
        self._name = "TreeLayerControl"
        kwargs["closed_symbol"] = closed_symbol
        kwargs["opened_symbol"] = opened_symbol
        kwargs["space_symbol"] = space_symbol
        kwargs["selector_back"] = selector_back
        kwargs["named_toggle"] = named_toggle
        kwargs["collapse_all"] = collapse_all
        kwargs["expand_all"] = expand_all
        kwargs["label_is_selector"] = label_is_selector
        self.options = remove_empty(**kwargs)
        self._base_skeleton = base_tree
        self._overlay_skeleton = overlay_tree
        self._auto_build = auto_build
        self.base_tree = base_tree
        self.overlay_tree = overlay_tree
        self.disabled_layers: list[str] = []

    def render(self, **kwargs):
        from folium.layer_control_utils import (
            build_tree,
            collect_layers,
            deduplicate_layer_names,
            sort_layers,
            strip_tree_plugin_flags,
        )

        self.disabled_layers = []

        if self._auto_build:
            # Collect base / overlay layers from the parent map.
            base_layers = collect_layers(self._parent, only_overlay=False)
            overlay_layers = collect_layers(self._parent, only_overlay=True)

            # Sort the flat lists so insertion order ties are consistent.
            base_layers = sort_layers(base_layers)
            overlay_layers = sort_layers(overlay_layers)

            # Record disabled labels for post-processing in JS.
            def collect_disabled(layers):
                disabled = []
                for layer in layers:
                    if layer.control_disabled:
                        disabled.append(layer.layer_name)
                return disabled

            self.disabled_layers.extend(collect_disabled(base_layers))
            self.disabled_layers.extend(collect_disabled(overlay_layers))

            # Build trees.
            built_base = build_tree(base_layers, explicit_tree=self._base_skeleton)
            built_overlay = build_tree(
                overlay_layers, explicit_tree=self._overlay_skeleton
            )

            # If the user gave None AND there are no layers to show,
            # keep None so the plugin receives null (the Leaflet plugin
            # expects either null/undefined or a tree object/list).
            def finalize(skeleton, built):
                if skeleton is None and built in (None, [], {}):
                    return None
                if built == []:
                    return skeleton if skeleton is not None else None
                return built

            self.base_tree = strip_tree_plugin_flags(
                finalize(self._base_skeleton, built_base)
            )
            self.overlay_tree = strip_tree_plugin_flags(
                finalize(self._overlay_skeleton, built_overlay)
            )
        else:
            self.base_tree = self._base_skeleton
            self.overlay_tree = self._overlay_skeleton

        super().render()
