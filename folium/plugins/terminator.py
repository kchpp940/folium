from branca.element import MacroElement

from folium.elements import JSCSSMixin
from folium.plugins._resources import Resource, build_defaults
from folium.template import Template


class Terminator(JSCSSMixin, MacroElement):
    """
    Leaflet.Terminator is a simple plug-in to the Leaflet library to
    overlay day and night regions on maps.

    """

    _template = Template("""
        {% macro script(this, kwargs) %}
            L.terminator().addTo({{this._parent.get_name()}});
        {% endmacro %}
        """)

    resources = [
        Resource(
            name="terminator",
            url="https://unpkg.com/@joergdietrich/leaflet.terminator",
            type="js",
            plugin="Terminator",
            package="@joergdietrich/leaflet.terminator",
            version=None,
            kind="plugin",
        ),
    ]
    default_js, default_css = build_defaults(resources)

    def __init__(self):
        super().__init__()
        self._name = "Terminator"
