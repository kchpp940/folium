"""Add Locate control to folium Map.

Based on leaflet plugin: https://github.com/domoritz/leaflet-locatecontrol
"""

from branca.element import MacroElement

from folium.elements import JSCSSMixin
from folium.plugins._resources import Resource, build_defaults
from folium.template import Template
from folium.utilities import remove_empty


class LocateControl(JSCSSMixin, MacroElement):
    """Control plugin to geolocate the user.

    This plugins adds a button to the map, and when it's clicked shows the current
    user device location.

    To work properly in production, the connection needs to be encrypted, otherwise browser will not
    allow users to share their location.

    Parameters
    ----------
    auto-start : bool, default False
        When set to True, plugin will be activated on map loading and search for user position.
        Once user location is founded, the map will automatically centered in using user coordinates.
    **kwargs
        For possible options, see https://github.com/domoritz/leaflet-locatecontrol

    Examples
    --------
    >>> m = folium.Map()
    # With default settings
    >>> LocateControl().add_to(m)

    # With some custom options
    >>> LocateControl(
    ...     position="bottomright",
    ...     strings={"title": "See you current location", "popup": "Your position"},
    ... ).add_to(m)

    For more info check:
    https://github.com/domoritz/leaflet-locatecontrol

    """

    _template = Template("""
        {% macro script(this, kwargs) %}
            var {{this.get_name()}} = L.control.locate(
                {{this.options | tojson}}
            ).addTo({{this._parent.get_name()}});
            {% if this.auto_start %}
                {{this.get_name()}}.start();
            {% endif %}
        {% endmacro %}
        """)

    resources = [
        Resource(
            name="Control_locate_min_js",
            url="https://cdnjs.cloudflare.com/ajax/libs/leaflet-locatecontrol/0.66.2/L.Control.Locate.min.js",
            type="js",
            plugin="LocateControl",
            package="leaflet-locatecontrol",
            version="0.66.2",
            kind="plugin",
        ),
        Resource(
            name="Control_locate_min_css",
            url="https://cdnjs.cloudflare.com/ajax/libs/leaflet-locatecontrol/0.66.2/L.Control.Locate.min.css",
            type="css",
            plugin="LocateControl",
            package="leaflet-locatecontrol",
            version="0.66.2",
            kind="plugin",
        ),
    ]
    default_js, default_css = build_defaults(resources)

    def __init__(self, auto_start=False, **kwargs):
        super().__init__()
        self._name = "LocateControl"
        self.auto_start = auto_start
        self.options = remove_empty(**kwargs)
