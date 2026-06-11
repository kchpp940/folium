from collections import OrderedDict

from branca.element import MacroElement

from folium.elements import JSCSSMixin
from folium.layer_control_model import LayerControlModel
from folium.template import Template
from folium.utilities import remove_empty


class GroupedLayerControl(JSCSSMixin, MacroElement):
    """
    Create a Layer Control with groups of overlays.

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
        self.grouped_overlays: OrderedDict[str, OrderedDict[str, str]] = (
            OrderedDict()
        )
        self.layers_untoggle: set = set()
        for sublist in groups.values():
            for element in sublist:
                element.control = False

    def render(self, **kwargs):
        model = LayerControlModel.from_map_children(self._parent)

        for sublist in self._groups.values():
            for element in sublist:
                model.ensure_layer(element)

        model.apply_group_overrides(self._groups)
        model.deduplicate()
        model.sort_by_weight()

        self.grouped_overlays = model.as_grouped_dicts()

        self.layers_untoggle = set()
        for entry in model.entries:
            if not entry.is_visible or entry.is_disabled:
                self.layers_untoggle.add(entry.js_name)

        if self._exclusive_groups:
            for sublist in self._groups.values():
                for element in sublist[1:]:
                    self.layers_untoggle.add(element.get_name())

        super().render()
