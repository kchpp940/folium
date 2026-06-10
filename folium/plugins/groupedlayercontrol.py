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
    LayerControl, but with a *force-collect* mechanism instead of
    temporarily flipping ``control`` flags:

    - During ``__init__``, all Layer objects reachable through the groups
      dict are collected using normal control semantics (``control=True``
      → boundary, ``control=False`` → descend).  Their ``control`` flag
      is then set to False so they won't also appear in a regular
      ``LayerControl``.
    - During ``render``, the same layers are re-collected using
      ``force_collect_ids`` — a set of object ids that are treated as
      if they had ``control=True`` — so no temporary flag flipping is
      needed.  Layers added after ``__init__`` (inside ``control=False``
      containers) are also picked up naturally.

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
        self._controlled_layer_ids: set[int] = set()
        for sublist in self._groups.values():
            collected = _collect_from_iterable(sublist)
            for info in collected.values():
                layer = info["layer"]
                obj_id = id(layer)
                if obj_id not in self._controlled_layer_ids:
                    self._controlled_layer_ids.add(obj_id)
                    layer.control = False

    def render(self, **kwargs):
        """Renders the HTML representation of the element."""
        self.layers_untoggle = set()
        self.grouped_overlays = OrderedDict()
        new_layers: list = []
        for group_name, sublist in self._groups.items():
            self.grouped_overlays[group_name] = OrderedDict()
            for entry_idx, entry in enumerate(sublist):
                collected = _collect_from_iterable(
                    [entry], force_collect_ids=self._controlled_layer_ids
                )
                if not collected:
                    continue
                entries = list(collected.values())
                for info in entries:
                    layer = info["layer"]
                    if id(layer) not in self._controlled_layer_ids:
                        new_layers.append(layer)
                    key = layer.get_name()
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
        for layer in new_layers:
            self._controlled_layer_ids.add(id(layer))
            layer.control = False
        super().render()
