from collections import OrderedDict

from branca.element import MacroElement

from folium.elements import JSCSSMixin
from folium.template import Template
from folium.utilities import remove_empty


class GroupedLayerControl(JSCSSMixin, MacroElement):
    """
    Create a Layer Control with groups of overlays.

    Besides the explicit ``groups`` dict, every overlay layer added to the
    map with a ``control_group`` attribute will be automatically placed in
    that group (single-level only – the first path element is used for
    multi-level ``control_group`` values).

    Parameters
    ----------
    groups : dict, optional
        A dictionary where the keys are group names and the values are lists
        of layer objects. For example::

            {
                "Group 1": [layer1, layer2],
                "Group 2": [layer3, layer4]
            }

        Layers with their own ``control_group`` are merged into matching
        groups declared here.  If ``None``/``{}``, groups are derived
        entirely from the layers' ``control_group`` attributes.
    exclusive_groups : bool, default True
        Whether to use radio buttons (default) or checkboxes.
        If you want to use both, use two separate instances of this class.
    sort_groups : bool, default True
        Sort groups using each group's minimum ``control_order`` (tie-broken
        by first insertion).  If False, the order of ``groups`` is preserved
        first, then auto-discovered groups follow in insertion order.
    sort_layers : bool, default True
        Sort layers inside each group by ``control_order``.
    group_collapsing : bool, optional
        Whether individual overlay groups can be collapsed by clicking their
        name.  If omitted (``None``, the default), it is automatically
        enabled whenever any layer declares ``control_collapsed=True``; the
        corresponding groups start folded.  If set *explicitly* to True or
        False the control-level setting always wins — passing False here
        keeps every group expanded regardless of layer-level hints.
    **kwargs
        Additional (possibly inherited) options. See
        https://leafletjs.com/reference.html#control-layers
    """

    default_js = [
        (
            "leaflet.groupedlayercontrol.min.js",
            "https://cdnjs.cloudflare.com/ajax/libs/leaflet-groupedlayercontrol/0.6.1/leaflet.groupedlayercontrol.min.js",  # noqa
        ),
    ]
    default_css = [
        (
            "leaflet.groupedlayercontrol.min.css",
            "https://cdnjs.cloudflare.com/ajax/libs/leaflet-groupedlayercontrol/0.6.1/leaflet.groupedlayercontrol.min.css",  # noqa
        )
    ]

    _template = Template("""
        {% macro script(this,kwargs) %}

            {%- for layer in this._all_layer_objs %}
            {{ layer.get_name() }}._folium = {
                controlDisabled: {{ 'true' if layer.control_disabled else 'false' }},
                controlCollapsed: {{ 'true' if layer.control_collapsed else 'false' }}
            };
            {%- endfor %}

            var {{ this.get_name() }} = L.control.groupedLayers(
                null,
                {
                    {%- for group_name, overlays in this.grouped_overlays.items() %}
                    {{ group_name|tojson }} : {
                        {%- for overlaykey, val in overlays.items() %}
                        {{ overlaykey|tojson }} : {{val}},
                        {%- endfor %}
                    },
                    {%- endfor %}
                },
                {{ this.options|tojavascript }},
            ).addTo({{this._parent.get_name()}});

            {%- for val in this.layers_untoggle %}
            {{ val }}.remove();
            {%- endfor %}

            {%- if this._has_disabled %}
            (function (ctl) {
                var container = ctl.getContainer();
                var inputs = container.querySelectorAll(
                    '.leaflet-control-layers-overlays input');
                var overlayIdx = 0;
                ctl._layers.forEach(function (entry) {
                    if (!entry.overlay) return;
                    if (entry.layer._folium && entry.layer._folium.controlDisabled) {
                        if (inputs[overlayIdx]) {
                            inputs[overlayIdx].disabled = true;
                            var label = inputs[overlayIdx].closest('label')
                                      || inputs[overlayIdx].parentElement;
                            if (label) label.style.opacity = '0.5';
                        }
                    }
                    overlayIdx++;
                });
            })({{ this.get_name() }});
            {%- endif %}

            {%- if this._collapsed_groups %}
            (function (ctl) {
                var container = ctl.getContainer();
                var groups = container.querySelectorAll(
                    '.leaflet-control-layers-group');
                {{ this._collapsed_groups|tojson }}.forEach(function (idx) {
                    if (groups[idx]) {
                        var nameEl = groups[idx].querySelector(
                            '.leaflet-control-layers-group-name');
                        if (nameEl) nameEl.click();
                    }
                });
            })({{ this.get_name() }});
            {%- endif %}

        {% endmacro %}
        """)

    def __init__(
        self,
        groups=None,
        exclusive_groups=True,
        sort_groups=True,
        sort_layers=True,
        group_collapsing=None,
        **kwargs,
    ):
        super().__init__()
        self._name = "GroupedLayerControl"
        self.options = remove_empty(**kwargs)
        # Sorting is done entirely on the Python side; the plugin's
        # native sortLayers would just alphabetise again.
        self.options["sortLayers"] = False
        self._explicit_groups = groups or {}
        self._exclusive = exclusive_groups
        self._sort_groups = sort_groups
        self._sort_layers = sort_layers
        self._group_collapsing = group_collapsing
        self.layers_untoggle: set[str] = set()
        self.grouped_overlays: "OrderedDict[str, OrderedDict[str, str]]" = OrderedDict()
        self._all_layer_objs: list = []
        self._has_disabled: bool = False
        self._collapsed_groups: list[int] = []
        # Pre-register the explicit group order in exclusiveGroups.
        if exclusive_groups and self._explicit_groups:
            self.options["exclusiveGroups"] = list(self._explicit_groups.keys())

    def render(self, **kwargs):
        from folium.layer_control_utils import (
            build_grouped_overlays,
            collect_layers,
            sort_layers as _sort,
            deduplicate_layer_names,
        )

        # 1. Collect overlay layers from the parent map.
        layers = collect_layers(self._parent, include_ungrouped=True, only_overlay=True)

        # 2. Explicit groups: also register their layers for ordering by
        #    attaching an insertion index.  (They may or may not already be
        #    map children.)
        explicit_flat = []
        for group_name, sublist in self._explicit_groups.items():
            for element in sublist:
                if not hasattr(element, "_lc_insertion_idx"):
                    element._lc_insertion_idx = len(layers) + len(explicit_flat)
                    explicit_flat.append(element)

        all_layers = layers + explicit_flat
        if self._sort_layers:
            all_layers = _sort(all_layers)

        # 3. Build the grouped structure.
        structured = build_grouped_overlays(
            all_layers, explicit_groups=self._explicit_groups or None,
        )

        # 4. Apply per-group sorting option.
        if not self._sort_groups and self._explicit_groups:
            # Keep explicit order first; append auto-discovered in original
            # structured order.
            ordered: "OrderedDict[str, OrderedDict[str, object]]" = OrderedDict()
            for g in self._explicit_groups.keys():
                if g in structured:
                    ordered[g] = structured[g]
            for g, v in structured.items():
                if g not in ordered:
                    ordered[g] = v
            structured = ordered

        # 5. Convert layer objects → JS names; dedupe; record untoggles.
        self.grouped_overlays = OrderedDict()
        self.layers_untoggle = set()
        self._all_layer_objs = []
        self._has_disabled = False
        self._collapsed_groups = []

        all_names_seen: dict[str, int] = {}

        def unique_name(preferred: str) -> str:
            if preferred in all_names_seen:
                all_names_seen[preferred] += 1
                return f"{preferred} ({all_names_seen[preferred]})"
            all_names_seen[preferred] = 1
            return preferred

        exclusive_seen_first: dict[str, bool] = {}
        group_has_collapsed: dict[str, bool] = {}

        for group_name, inner in structured.items():
            self.grouped_overlays[group_name] = OrderedDict()
            group_has_collapsed[group_name] = False
            for layer_label, layer in inner.items():
                # make sure the elements used in GroupedLayerControl
                # don't show up in the regular LayerControl.
                layer.control = False

                final_label = unique_name(layer_label)
                self.grouped_overlays[group_name][final_label] = layer.get_name()
                self._all_layer_objs.append(layer)

                if layer.control_disabled:
                    self._has_disabled = True
                if layer.control_collapsed:
                    group_has_collapsed[group_name] = True

                is_first_in_exclusive = self._exclusive and not exclusive_seen_first.get(
                    group_name, False
                )

                if not layer.show:
                    self.layers_untoggle.add(layer.get_name())
                if self._exclusive:
                    exclusive_seen_first[group_name] = True
                    if not is_first_in_exclusive:
                        # Only enable the first radio button; others must be off.
                        self.layers_untoggle.add(layer.get_name())

        # Determine which group indices should be collapsed by default.
        for idx, group_name in enumerate(self.grouped_overlays.keys()):
            if group_has_collapsed.get(group_name, False):
                self._collapsed_groups.append(idx)

        # Priority rule: an explicit control-level ``group_collapsing``
        # argument always wins.  If the user disabled it explicitly we must
        # not auto-collapse any groups either (otherwise the click()
        # post-processing would still trigger on non-collapsible groups).
        # If left at the default (None) we honour the layer-level
        # ``control_collapsed`` hints: enable groupCollapsing and fold the
        # groups whose layers requested collapsing.
        if self._group_collapsing is not None:
            self.options["groupCollapsing"] = bool(self._group_collapsing)
            if not self._group_collapsing:
                self._collapsed_groups = []
        elif self._collapsed_groups:
            self.options["groupCollapsing"] = True

        if self._exclusive:
            self.options["exclusiveGroups"] = list(self.grouped_overlays.keys())

        super().render()
