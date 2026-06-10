"""
Test TimestampedGeoJson
-----------------------

"""

import numpy as np

import folium
from folium import plugins
from folium.template import Template
from folium.utilities import normalize


def test_timestamped_geo_json():
    coordinates = [
        [
            [
                [lon - 8 * np.sin(theta), -47 + 6 * np.cos(theta)]
                for theta in np.linspace(0, 2 * np.pi, 25)
            ],
            [
                [lon - 4 * np.sin(theta), -47 + 3 * np.cos(theta)]
                for theta in np.linspace(0, 2 * np.pi, 25)
            ],
        ]
        for lon in np.linspace(-150, 150, 7)
    ]
    data = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [0, 0],
                },
                "properties": {"times": [1435708800000 + 12 * 86400000]},
            },
            {
                "type": "Feature",
                "geometry": {
                    "type": "MultiPoint",
                    "coordinates": [[lon, -25] for lon in np.linspace(-150, 150, 49)],
                },
                "properties": {
                    "times": [
                        1435708800000 + i * 86400000 for i in np.linspace(0, 25, 49)
                    ]
                },
            },
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[lon, 25] for lon in np.linspace(-150, 150, 25)],
                },
                "properties": {
                    "times": [
                        1435708800000 + i * 86400000 for i in np.linspace(0, 25, 25)
                    ],
                    "style": {"color": "red"},
                },
            },
            {
                "type": "Feature",
                "geometry": {
                    "type": "MultiLineString",
                    "coordinates": [
                        [
                            [lon - 4 * np.sin(theta), 47 + 3 * np.cos(theta)]
                            for theta in np.linspace(0, 2 * np.pi, 25)
                        ]
                        for lon in np.linspace(-150, 150, 13)
                    ],
                },
                "properties": {
                    "times": [
                        1435708800000 + i * 86400000 for i in np.linspace(0, 25, 13)
                    ]
                },
            },
            {
                "type": "Feature",
                "geometry": {
                    "type": "MultiPolygon",
                    "coordinates": coordinates,
                },
                "properties": {
                    "times": [
                        1435708800000 + i * 86400000 for i in np.linspace(0, 25, 7)
                    ]
                },
            },
        ],
    }

    m = folium.Map([47, 3], zoom_start=1)
    tgj = plugins.TimestampedGeoJson(data).add_to(m)

    out = normalize(m._parent.render())

    # Verify the imports.
    assert (
        '<script src="https://cdnjs.cloudflare.com/ajax/libs/jquery/3.7.1/jquery.min.js"></script>'
        in out
    )
    assert (
        '<script src="https://cdnjs.cloudflare.com/ajax/libs/jqueryui/1.10.2/jquery-ui.min.js"></script>'
        in out
    )
    assert (
        '<script src="https://cdn.jsdelivr.net/npm/iso8601-js-period@0.2.1/iso8601.min.js"></script>'
        in out
    )
    assert (
        '<script src="https://cdn.jsdelivr.net/npm/leaflet-timedimension@1.1.1/dist/leaflet.timedimension.min.js"></script>'  # noqa
        in out
    )  # noqa
    assert (
        '<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/8.4/styles/default.min.css"/>'
        in out
    )  # noqa
    assert (
        '<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/leaflet-timedimension@1.1.1/dist/leaflet.timedimension.control.css"/>'  # noqa
        in out
    )  # noqa
    assert (
        '<script src="https://cdnjs.cloudflare.com/ajax/libs/moment.js/2.18.1/moment.min.js"></script>'
        in out
    )

    # Verify that the script is okay.
    tmpl = Template("""
        if (typeof L.Control.TimeDimensionShared === 'undefined') {
            L.Control.TimeDimensionShared = L.Control.TimeDimension.extend({
                initialize: function(options) {
                    var playerOptions = {
                        buffer: 1,
                        minBufferReady: -1
                    };
                    options.playerOptions = $.extend({}, playerOptions, options.playerOptions || {});
                    L.Control.TimeDimension.prototype.initialize.call(this, options);
                    this._formatStrategy = options.formatStrategy || 'moment';
                    this._formatOptions = options.formatOptions || {};
                    this._index = options.index || null;
                },
                _getDisplayDateFormat: function(date) {
                    if (this._formatStrategy === 'index' && this._index) {
                        return this._index[date.getTime() - 1];
                    } else if (this._formatStrategy === 'moment') {
                        var fmt = this._formatOptions.dateFormat || 'YYYY-MM-DD HH:mm:ss';
                        return new moment(date).format(fmt);
                    }
                    return date.toString();
                },
                setFormatStrategy: function(strategy, options) {
                    this._formatStrategy = strategy;
                    this._formatOptions = options || {};
                    if (options && options.index) {
                        this._index = options.index;
                    }
                }
            });
        }

        var map = {{this._parent.get_name()}};
        if (!map.timeDimension) {
            map.timeDimension = L.timeDimension(
                {
                    period: {{ this.period|tojson }},
                }
            );
        }

        var controlOptions = {{ this.options|tojavascript }};
        controlOptions.formatStrategy = 'moment';
        controlOptions.formatOptions = { dateFormat: "{{this.date_options}}" };
        if (!map._timeDimensionControl) {
            var timeDimensionControl = new L.Control.TimeDimensionShared(controlOptions);
            map.addControl(timeDimensionControl);
            map._timeDimensionControl = timeDimensionControl;
        } else {
            map._timeDimensionControl.setFormatStrategy('moment', {dateFormat: "{{this.date_options}}"});
        }

        var geoJsonLayer = L.geoJson({{this.data}}, {
                pointToLayer: function (feature, latLng) {
                    if (feature.properties.icon == 'marker') {
                        if(feature.properties.iconstyle){
                            return new L.Marker(latLng, {
                                icon: L.icon(feature.properties.iconstyle)});
                        }
                        //else
                        return new L.Marker(latLng);
                    }
                    if (feature.properties.icon == 'circle') {
                        if (feature.properties.iconstyle) {
                            return new L.circleMarker(latLng, feature.properties.iconstyle)
                            };
                        //else
                        return new L.circleMarker(latLng);
                    }
                    //else

                    return new L.Marker(latLng);
                },
                style: function (feature) {
                    return feature.properties.style;
                },
                onEachFeature: function(feature, layer) {
                    if (feature.properties.popup) {
                    layer.bindPopup(feature.properties.popup);
                    }
                    if (feature.properties.tooltip) {
                    layer.bindTooltip(feature.properties.tooltip);
                    }
                }
            })

        var {{this.get_name()}} = L.timeDimension.layer.geoJson(
            geoJsonLayer,
            {
                updateTimeDimension: true,
                addlastPoint: {{ this.add_last_point|tojson }},
                duration: {{ this.duration }},
            }
        ).addTo({{this._parent.get_name()}});
    """)  # noqa
    expected = normalize(tmpl.render(this=tgj))
    assert expected in out

    bounds = m.get_bounds()
    assert bounds == [[-53.0, -158.0], [50.0, 158.0]], bounds
