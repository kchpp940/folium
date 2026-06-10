TIME_DIMENSION_SHARED_CLASS_JS = """\
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
}"""

TIME_DIMENSION_INIT_TEMPLATE = """\
var map = {{this._parent.get_name()}};
if (!map.timeDimension) {
    map.timeDimension = L.timeDimension(
        {{ time_dimension_options }}
    );
}"""

TIME_DIMENSION_CONTROL_INIT_TEMPLATE = """\
if (!map._timeDimensionControl) {
    var {{this._control_name}} = new L.Control.TimeDimensionShared(
        {{ control_options }}
    );
    {{this._control_name}}.addTo(map);
    map._timeDimensionControl = {{this._control_name}};
} else {
    map._timeDimensionControl.setFormatStrategy({{ format_strategy }}, {{ format_options }});
}"""

TIMELINE_SLIDER_ISOLATION_CSS = """\
.leaflet-control-container > .leaflet-timeline-controls {
    position: relative;
    z-index: 1000;
}
.leaflet-control-container > .leaflet-control-timecontrol {
    position: relative;
    z-index: 1001;
}"""
