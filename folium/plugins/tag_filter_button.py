from branca.element import MacroElement

from folium.elements import JSCSSMixin
from folium.plugins._resources import Resource, build_defaults
from folium.template import Template
from folium.utilities import remove_empty


class TagFilterButton(JSCSSMixin, MacroElement):
    """
    Creates a Tag Filter Button to filter elements based on criteria
    (https://github.com/maydemirx/leaflet-tag-filter-button)

    This plugin works for multiple element types like Marker, GeoJson
    and vector layers like PolyLine.

    Parameters
    ----------
    data: list, of strings.
        The tags to filter for this filter button.
    icon: string, default 'fa-filter'
        The icon for the filter button
    clear_text: string, default 'clear'
        Text of the clear button
    filter_on_every_click: bool, default True
        if True, the plugin will filter on every click event on checkbox.
    open_popup_on_hover: bool, default False
        if True, popup that contains tags will be open at mouse hover time

    """

    _template = Template("""
        {% macro header(this,kwargs) %}
            <style>
                .easy-button-button {
                  display: block !important;
                }

                .tag-filter-tags-container {
                  left: 30px;
                }
            </style>
        {% endmacro %}

        {% macro script(this, kwargs) %}
            var {{ this.get_name() }} = L.control.tagFilterButton(
                {{ this.options|tojavascript }}
            ).addTo({{ this._parent.get_name() }});
        {% endmacro %}
        """)

    resources = [
        Resource(
            name="tag-filter-button.js",
            url="https://cdn.jsdelivr.net/npm/leaflet-tag-filter-button/src/leaflet-tag-filter-button.js",
            type="js",
            plugin="TagFilterButton",
            package="leaflet-tag-filter-button",
            version=None,
            kind="plugin",
        ),
        Resource(
            name="easy-button.js",
            url="https://cdn.jsdelivr.net/npm/leaflet-easybutton@2/src/easy-button.js",
            type="js",
            plugin="TagFilterButton",
            package="leaflet-easybutton",
            version="2",
            kind="dependency",
        ),
        Resource(
            name="tag-filter-button.css",
            url="https://cdn.jsdelivr.net/npm/leaflet-tag-filter-button/src/leaflet-tag-filter-button.css",
            type="css",
            plugin="TagFilterButton",
            package="leaflet-tag-filter-button",
            version=None,
            kind="plugin",
        ),
        Resource(
            name="easy-button.css",
            url="https://cdn.jsdelivr.net/npm/leaflet-easybutton@2/src/easy-button.css",
            type="css",
            plugin="TagFilterButton",
            package="leaflet-easybutton",
            version="2",
            kind="dependency",
        ),
        Resource(
            name="ripples.min.css",
            url="https://cdn.jsdelivr.net/npm/css-ripple-effect@1.0.5/dist/ripple.min.css",
            type="css",
            plugin="TagFilterButton",
            package="css-ripple-effect",
            version="1.0.5",
            kind="dependency",
        ),
    ]
    default_js, default_css = build_defaults(resources)

    def __init__(
        self,
        data,
        icon="fa-filter",
        clear_text="clear",
        filter_on_every_click=True,
        open_popup_on_hover=False,
        **kwargs,
    ):
        super().__init__()
        self._name = "TagFilterButton"
        self.options = remove_empty(
            data=data,
            icon=icon,
            clear_text=clear_text,
            filter_on_every_click=filter_on_every_click,
            open_popup_on_hover=open_popup_on_hover,
            **kwargs,
        )
