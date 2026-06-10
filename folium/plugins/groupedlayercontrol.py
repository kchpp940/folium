from collections import OrderedDict

from branca.element import MacroElement

from folium.elements import JSCSSMixin
from folium.map import Layer, _collect_from_iterable
from folium.template import Template
from folium.utilities import remove_empty


class GroupedLayerControl(JSCSSMixin, MacroElement):
    """
    Create a Layer Control with groups of overlays.

    Uses the same control-boundary / dedup semantics as the regular
    LayerControl:
    - A ``Layer`` with ``control=True`` acts as a boundary: it is
      collected as a single entry and its children are NOT descended into.
    - A ``Layer`` with ``control=False`` (or any non-Layer element) is
      descended into so that nested ``control=True`` layers are discovered.
    - Duplicate Layer objects are deduplicated by identity within a group.
    - Layers sharing the same display ``layer_name`` are kept as separate
      entries thanks to the internal unique key (``get_name()``).

    Parameters
    ----------
    groups : dict
        A dictionary where the keys are group names and the values are lists
        of layer objects. For example::

            {
                "Group 1": [layer1, layer2],
                "Group 2": [layer3, layer4]
            }

    exclusive_groups : bool, default True
        Whether to use radio buttons (default) or checkboxes.
        If you want to use both, use two separate instances of this class.
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
                        {{ val.label|tojson }} : {{ val.layer_js }},
                        {%- endfor %}
                    },
                    {%- endfor %}
                },
                {{ this.options|tojavascript }},
            ).addTo({{this._parent.get_name()}});

            {%- for val in this.layers_untoggle %}
            {{ val }}.remove();
            {%- endfor %}

        {% endmacro %}
        """)

    def __init__(self, groups, exclusive_groups=True, **kwargs):
        super().__init__()
        self._name = "GroupedLayerControl"
        self.options = remove_empty(**kwargs)
        if exclusive_groups:
            self.options["exclusiveGroups"] = list(groups.keys())
        self._groups = groups
        self._exclusive_groups = exclusive_groups
        self.layers_untoggle = set()
        self.grouped_overlays: "OrderedDict[str, OrderedDict]" = OrderedDict()
        self._controlled_layers: list = []
        seen: set[int] = set()
        for sublist in self._groups.values():
            collected = _collect_from_iterable(sublist)
            for info in collected.values():
                layer = info["layer"]
                if id(layer) not in seen:
                    seen.add(id(layer))
                    self._controlled_layers.append(layer)
                    layer.control = False

    def render(self, **kwargs):
        """Renders the HTML representation of the element."""
        self.layers_untoggle = set()
        self.grouped_overlays = OrderedDict()
        for layer in self._controlled_layers:
            layer.control = True
        try:
            extra_layers = []
            for group_name, sublist in self._groups.items():
                self.grouped_overlays[group_name] = OrderedDict()
                for entry_idx, entry in enumerate(sublist):
                    collected = _collect_from_iterable([entry])
                    if not collected:
                        continue
                    entries = list(collected.values())
                    for info in entries:
                        layer = info["layer"]
                        if id(layer) not in {
                            id(l) for l in self._controlled_layers
                        }:
                            extra_layers.append(layer)
                        key = info["layer"].get_name()
                        self.grouped_overlays[group_name][key] = {
                            "label": info["label"],
                            "layer_js": info["layer_js"],
                        }
                        if not info["show"]:
                            self.layers_untoggle.add(info["layer_js"])
                        if self._exclusive_groups and entry_idx > 0:
                            self.layers_untoggle.add(info["layer_js"])
                if not self.grouped_overlays[group_name]:
                    del self.grouped_overlays[group_name]
        finally:
            for layer in self._controlled_layers:
                layer.control = False
            for layer in extra_layers:
                layer.control = False
        super().render()
