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

    - A ``Layer`` with ``control=True`` acts as a boundary: it is collected
      as a single entry and its children are NOT descended into.
    - A ``Layer`` with ``control=False`` (or any non-Layer element) is
      descended into so that nested ``control=True`` layers are discovered.
    - Duplicate Layer objects are deduplicated by identity within a group.
    - Layers sharing the same display ``layer_name`` are kept as separate
      entries thanks to the internal unique key (``get_name()``).

    During ``__init__``, the groups dict is scanned using the normal
    control semantics to determine which layers this control will manage.
    No layer attributes are modified, so the order in which a regular
    ``LayerControl`` and any number of ``GroupedLayerControl`` instances
    are created / added does not affect the final output.  At render
    time the regular ``LayerControl`` consults every
    ``GroupedLayerControl`` on the same map and excludes the layers they
    manage from its own collection.

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
                self._controlled_layer_ids.add(id(info["layer"]))

    def get_controlled_layer_ids(self):
        """
        Return the set of ``id()`` values of every Layer managed by this
        control.  The regular ``LayerControl`` calls this at render time
        so that layers belonging to a grouped control don't also appear
        in the default layer tree.

        Delayed additions (layers added to a ``control=False`` container
        after ``__init__`` but before ``render``) are included.
        """
        return set(self._controlled_layer_ids)

    def refresh_controlled_layer_ids(self):
        """
        Re-scan the groups dict and update the set of managed layer ids,
        picking up any layers that were added to ``control=False``
        containers after ``__init__``.  Called automatically by
        :class:`LayerControl` before it collects its own layers.
        """
        for sublist in self._groups.values():
            collected = _collect_from_iterable(sublist)
            for info in collected.values():
                self._controlled_layer_ids.add(id(info["layer"]))

    def render(self, **kwargs):
        """Renders the HTML representation of the element."""
        self.layers_untoggle = set()
        self.grouped_overlays = OrderedDict()
        for group_name, sublist in self._groups.items():
            self.grouped_overlays[group_name] = OrderedDict()
            for entry_idx, entry in enumerate(sublist):
                collected = _collect_from_iterable([entry])
                if not collected:
                    continue
                entries = list(collected.values())
                for info in entries:
                    layer = info["layer"]
                    self._controlled_layer_ids.add(id(layer))
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
        super().render()
