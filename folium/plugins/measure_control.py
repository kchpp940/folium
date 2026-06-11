from branca.element import MacroElement

from folium.elements import JSCSSMixin
from folium.plugins._resources import Resource, build_defaults
from folium.template import Template
from folium.utilities import remove_empty


class MeasureControl(JSCSSMixin, MacroElement):
    """Add a measurement widget on the map.

    Parameters
    ----------
    position: str, default 'topright'
        Location of the widget.
    primary_length_unit: str, default 'meters'
    secondary_length_unit: str, default 'miles'
    primary_area_unit: str, default 'sqmeters'
    secondary_area_unit: str, default 'acres'

    See https://github.com/ljagis/leaflet-measure for more information.

    """

    _template = Template("""
        {% macro script(this, kwargs) %}
            var {{ this.get_name() }} = new L.Control.Measure(
                {{ this.options|tojavascript }});
            {{this._parent.get_name()}}.addControl({{this.get_name()}});

            // Workaround for using this plugin with Leaflet>=1.8.0
            // https://github.com/ljagis/leaflet-measure/issues/171
            L.Control.Measure.include({
                _setCaptureMarkerIcon: function () {
                    // disable autopan
                    this._captureMarker.options.autoPanOnFocus = false;
                    // default function
                    this._captureMarker.setIcon(
                        L.divIcon({
                            iconSize: this._map.getSize().multiplyBy(2)
                        })
                    );
                },
            });

        {% endmacro %}
        """)  # noqa

    resources = [
        Resource(
            name="leaflet_measure_js",
            url="https://cdn.jsdelivr.net/gh/ljagis/leaflet-measure@2.1.7/dist/leaflet-measure.min.js",
            type="js",
            plugin="MeasureControl",
            package="leaflet-measure",
            version="2.1.7",
            kind="plugin",
        ),
        Resource(
            name="leaflet_measure_css",
            url="https://cdn.jsdelivr.net/gh/ljagis/leaflet-measure@2.1.7/dist/leaflet-measure.min.css",
            type="css",
            plugin="MeasureControl",
            package="leaflet-measure",
            version="2.1.7",
            kind="plugin",
        ),
    ]
    default_js, default_css = build_defaults(resources)

    def __init__(
        self,
        position="topright",
        primary_length_unit="meters",
        secondary_length_unit="miles",
        primary_area_unit="sqmeters",
        secondary_area_unit="acres",
        **kwargs,
    ):
        super().__init__()
        self._name = "MeasureControl"

        self.options = remove_empty(
            position=position,
            primary_length_unit=primary_length_unit,
            secondary_length_unit=secondary_length_unit,
            primary_area_unit=primary_area_unit,
            secondary_area_unit=secondary_area_unit,
            **kwargs,
        )
