from branca.element import MacroElement

from folium.elements import JSCSSMixin
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
        self.grouped_overlays = {}
        for element in self._iter_all_layers():
            element.control = False

    def _iter_all_layers(self):
        seen = set()
        for sublist in self._groups.values():
            for element in sublist:
                if id(element) not in seen:
                    seen.add(id(element))
                    yield element

    def render(self, **kwargs):
        """Renders the HTML representation of the element."""
        self.layers_untoggle = set()
        self.grouped_overlays = {}
        for group_name, sublist in self._groups.items():
            self.grouped_overlays[group_name] = {}
            group_seen_ids = set()
            for idx, element in enumerate(sublist):
                obj_id = id(element)
                if obj_id in group_seen_ids:
                    continue
                group_seen_ids.add(obj_id)
                key = element.get_name()
                self.grouped_overlays[group_name][key] = {
                    "label": element.layer_name,
                    "layer_js": element.get_name(),
                }
                if not element.show:
                    self.layers_untoggle.add(element.get_name())
                if self._exclusive_groups and idx > 0:
                    self.layers_untoggle.add(element.get_name())
        super().render()
