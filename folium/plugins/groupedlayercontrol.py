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

            L.control.groupedLayers(
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

            {%- if this.disabled_layers %}
            (function () {
                var sel = 'input[name^="leaflet-base-layers"], ' +
                          'input[name^="leaflet-overlay-layers"]';
                document.querySelectorAll(sel).forEach(function (inp) {
                    var label = inp.parentElement;
                    if (!label) return;
                    var txt = (label.innerText || label.textContent || '').trim();
                    if ({{ this.disabled_layers|tojson }}.indexOf(txt) !== -1) {
                        inp.disabled = true;
                        label.style.opacity = '0.5';
                    }
                });
            })();
            {%- endif %}

        {% endmacro %}
        """)

    def __init__(
        self,
        groups=None,
        exclusive_groups=True,
        sort_groups=True,
        sort_layers=True,
        **kwargs,
    ):
        super().__init__()
        self._name = "GroupedLayerControl"
        self.options = remove_empty(**kwargs)
        self._explicit_groups = groups or {}
        self._exclusive = exclusive_groups
        self._sort_groups = sort_groups
        self._sort_layers = sort_layers
        self.layers_untoggle: set[str] = set()
        self.grouped_overlays: "OrderedDict[str, OrderedDict[str, str]]" = OrderedDict()
        self.disabled_layers: list[str] = []
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
        self.disabled_layers = []

        all_names_seen: dict[str, int] = {}

        def unique_name(preferred: str) -> str:
            if preferred in all_names_seen:
                all_names_seen[preferred] += 1
                return f"{preferred} ({all_names_seen[preferred]})"
            all_names_seen[preferred] = 1
            return preferred

        exclusive_seen_first: dict[str, bool] = {}

        for group_name, inner in structured.items():
            self.grouped_overlays[group_name] = OrderedDict()
            for layer_label, layer in inner.items():
                # make sure the elements used in GroupedLayerControl
                # don't show up in the regular LayerControl.
                layer.control = False

                final_label = unique_name(layer_label)
                self.grouped_overlays[group_name][final_label] = layer.get_name()

                if layer.control_disabled:
                    self.disabled_layers.append(final_label)

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

        if self._exclusive:
            self.options["exclusiveGroups"] = list(self.grouped_overlays.keys())

        super().render()
