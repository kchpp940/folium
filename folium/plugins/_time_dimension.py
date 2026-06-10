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
            this._combinedIndex = {};
            this._defaultDateFormat = (
                options.formatOptions && options.formatOptions.dateFormat
                ? options.formatOptions.dateFormat
                : 'YYYY-MM-DD HH:mm:ss'
            );
        },
        registerIndex: function(times, labels) {
            if (!times || !labels || times.length !== labels.length) {
                return;
            }
            for (var i = 0; i < times.length; i++) {
                var key = Number(times[i]).toString();
                this._combinedIndex[key] = labels[i];
            }
        },
        registerDateFormat: function(fmt) {
            if (fmt) {
                this._defaultDateFormat = fmt;
            }
        },
        _getDisplayDateFormat: function(date) {
            var key = Number(date.getTime()).toString();
            if (this._combinedIndex[key] !== undefined) {
                return this._combinedIndex[key];
            }
            return new moment(date).format(this._defaultDateFormat);
        }
    });
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
