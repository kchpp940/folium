"""Tests for unified vector layer event binding system."""

import pytest
import folium
from folium import (
    Circle,
    CircleMarker,
    Polygon,
    PolyLine,
    Rectangle,
    Marker,
    GeoJson,
    RegularPolygonMarker,
    PREDEFINED_EVENT_ACTIONS,
    validate_events,
)
from folium.utilities import JsCode, EventMixin


@pytest.fixture
def test_map():
    """Provide a test map for layers to be added to."""
    return folium.Map(location=[0.0, 0.0], zoom_start=8)


def _render_layer(layer, test_map):
    """Helper: add layer to map and return rendered script."""
    layer.add_to(test_map)
    test_map._repr_html_()  # Ensure parent contexts are set
    return layer._template.module.script(layer)


class TestPredefinedActions:
    """Tests for PREDEFINED_EVENT_ACTIONS dictionary."""

    def test_required_actions_exist(self):
        """Test that all required predefined actions are available."""
        required_actions = [
            "zoom", "alert", "log", "highlight",
            "reset_highlight", "open_popup", "close_popup",
        ]
        for action in required_actions:
            assert action in PREDEFINED_EVENT_ACTIONS
            assert PREDEFINED_EVENT_ACTIONS[action].startswith("function")

    def test_all_actions_are_valid_js(self):
        """Test that all predefined actions look like valid JS functions."""
        for name, code in PREDEFINED_EVENT_ACTIONS.items():
            assert "function(e)" in code, f"{name} should have function(e)"

    def test_validate_events_valid(self):
        """Test validate_events with valid input."""
        valid_events = {
            "click": "alert",
            "mouseover": "log",
        }
        result = validate_events(valid_events)
        assert result is None or isinstance(result, dict)

    def test_validate_events_invalid_event_name(self):
        """Test validate_events rejects invalid event names."""
        with pytest.raises((ValueError, TypeError)):
            validate_events({"invalid_event_xyz": "alert"})


class TestEventHandlerTypes:
    """Tests for three types of event handlers."""

    def test_reference_type_function_name(self, test_map):
        """Test global JS function name reference."""
        layer = Circle(location=[0, 0], events={"click": "myApp.handler"})
        rendered = _render_layer(layer, test_map)
        name = layer.get_name()
        assert f'{name}.on("click", myApp.handler);' in rendered

    def test_reference_type_namespaced(self, test_map):
        """Test namespaced function reference with dots."""
        layer = Circle(location=[0, 0], events={"click": "App.UI.showPopup"})
        rendered = _render_layer(layer, test_map)
        name = layer.get_name()
        assert f'{name}.on("click", App.UI.showPopup);' in rendered

    def test_inline_type_str_function(self, test_map):
        """Test inline JS function as string."""
        handler = "function(e) { console.log('test', e.type); }"
        layer = Circle(location=[0, 0], events={"click": handler})
        rendered = _render_layer(layer, test_map)
        assert "console.log('test', e.type)" in rendered

    def test_inline_type_jscode(self, test_map):
        """Test inline JS function as JsCode object."""
        handler = JsCode("function(e) { alert('jscode test'); }")
        layer = Circle(location=[0, 0], events={"click": handler})
        rendered = _render_layer(layer, test_map)
        assert "alert('jscode test')" in rendered

    def test_predefined_type_alert(self, test_map):
        """Test predefined 'alert' action."""
        layer = Circle(location=[0, 0], events={"click": "alert"})
        rendered = _render_layer(layer, test_map)
        assert "alert(msg)" in rendered

    def test_predefined_type_zoom(self, test_map):
        """Test predefined 'zoom' action."""
        layer = Circle(location=[0, 0], events={"click": "zoom"})
        rendered = _render_layer(layer, test_map)
        assert "fitBounds" in rendered or "flyTo" in rendered

    def test_predefined_type_log(self, test_map):
        """Test predefined 'log' action."""
        layer = Circle(location=[0, 0], events={"click": "log"})
        rendered = _render_layer(layer, test_map)
        assert "console.log" in rendered

    def test_predefined_type_highlight(self, test_map):
        """Test predefined 'highlight' action."""
        layer = Circle(location=[0, 0], events={"mouseover": "highlight"})
        rendered = _render_layer(layer, test_map)
        assert "setStyle" in rendered


class TestCircleEvents:
    """Tests for Circle layer events."""

    def test_multiple_events(self, test_map):
        """Test binding multiple events to Circle."""
        c = Circle(
            location=[45.5, -122.3],
            radius=1000,
            events={
                "click": "alert",
                "mouseover": "highlight",
                "mouseout": "reset_highlight",
            },
        )
        rendered = _render_layer(c, test_map)
        name = c.get_name()
        assert f'{name}.on("click"' in rendered
        assert f'{name}.on("mouseover"' in rendered
        assert f'{name}.on("mouseout"' in rendered
        assert c.has_events()
        assert len(c._event_handlers) == 3


class TestCircleMarkerEvents:
    """Tests for CircleMarker layer events."""

    def test_basic_events(self, test_map):
        """Test basic event binding on CircleMarker."""
        cm = CircleMarker(
            location=[45.5, -122.3],
            radius=20,
            events={
                "dblclick": JsCode("function(e) { console.log('dbl', e); }"),
                "contextmenu": "log",
            },
        )
        rendered = _render_layer(cm, test_map)
        name = cm.get_name()
        assert f'{name}.on("dblclick"' in rendered
        assert f'{name}.on("contextmenu"' in rendered
        assert "console.log('dbl', e)" in rendered


class TestPolygonEvents:
    """Tests for Polygon layer events."""

    def test_polygon_zoom_action(self, test_map):
        """Test Polygon with zoom action on click."""
        p = Polygon(
            locations=[[45.51, -122.68], [37.77, -122.43], [34.04, -118.2]],
            events={"click": "zoom", "mouseover": "log"},
        )
        rendered = _render_layer(p, test_map)
        name = p.get_name()
        assert f'{name}.on("click"' in rendered
        assert f'{name}.on("mouseover"' in rendered
        assert "fitBounds" in rendered or "flyTo" in rendered


class TestPolylineEvents:
    """Tests for PolyLine layer events."""

    def test_function_reference(self, test_map):
        """Test PolyLine with global function references."""
        pl = PolyLine(
            locations=[[40.0, -80.0], [45.0, -80.0]],
            events={
                "click": "myApp.onPolyClick",
                "mouseover": "UI.highlightLayer",
            },
        )
        rendered = _render_layer(pl, test_map)
        name = pl.get_name()
        assert f'{name}.on("click", myApp.onPolyClick);' in rendered
        assert f'{name}.on("mouseover", UI.highlightLayer);' in rendered


class TestRectangleEvents:
    """Tests for Rectangle layer events."""

    def test_rectangle_events(self, test_map):
        """Test basic Rectangle event binding."""
        r = Rectangle(
            bounds=[[45.6, -122.8], [45.61, -122.7]],
            events={"click": "alert"},
        )
        rendered = _render_layer(r, test_map)
        name = r.get_name()
        assert f'{name}.on("click"' in rendered


class TestMarkerEvents:
    """Tests for Marker layer events (parent class for many)."""

    def test_marker_events(self, test_map):
        """Test Marker supports events since Circle inherits from it."""
        marker = Marker(
            location=[45.5, -122.3],
            popup="Test",
            events={"click": "alert", "mouseover": "log"},
        )
        rendered = _render_layer(marker, test_map)
        name = marker.get_name()
        assert f'{name}.on("click"' in rendered
        assert f'{name}.on("mouseover"' in rendered


class TestRegularPolygonMarkerEvents:
    """Tests for RegularPolygonMarker events."""

    def test_regular_polygon_marker(self, test_map):
        """Test RegularPolygonMarker supports events."""
        rpm = RegularPolygonMarker(
            location=[45.5, -122.3],
            number_of_sides=6,
            radius=30,
            events={"click": "alert"},
        )
        rendered = _render_layer(rpm, test_map)
        name = rpm.get_name()
        assert f'{name}.on("click"' in rendered


class TestProgrammaticEventAPI:
    """Tests for set_event, get_event, remove_event, clear_events API."""

    def test_set_event_single(self, test_map):
        """Test adding a single event programmatically."""
        c = Circle(location=[0, 0], radius=100)
        assert not c.has_events()
        c.set_event("click", "alert")
        assert c.has_events()
        assert c.get_event("click") is not None
        rendered = _render_layer(c, test_map)
        name = c.get_name()
        assert f'{name}.on("click"' in rendered

    def test_set_event_overwrite(self, test_map):
        """Test that setting same event name overwrites old handler."""
        c = Circle(location=[0, 0], radius=100, events={"click": "alert"})
        old_handler = c.get_event("click")
        c.set_event("click", "log")
        new_handler = c.get_event("click")
        assert old_handler != new_handler
        # Should still only have 1 event
        assert len(c._event_handlers) == 1

    def test_remove_event(self, test_map):
        """Test removing an event."""
        c = Circle(location=[0, 0], radius=100, events={"click": "alert", "mouseover": "log"})
        assert len(c._event_handlers) == 2
        assert c.remove_event("click")
        assert len(c._event_handlers) == 1
        assert c.get_event("click") is None
        # remove non-existent event returns False
        assert not c.remove_event("nonexistent")

    def test_clear_events(self, test_map):
        """Test clearing all events."""
        c = Circle(
            location=[0, 0],
            radius=100,
            events={"click": "alert", "mouseover": "log", "mouseout": "reset_highlight"},
        )
        assert len(c._event_handlers) == 3
        c.clear_events()
        assert not c.has_events()
        assert len(c._event_handlers) == 0


class TestGeoJsonFeatureEvents:
    """Tests for GeoJson feature-level events (bound via onEachFeature)."""

    @pytest.fixture
    def sample_geojson(self):
        return {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[
                            [100.0, 0.0], [101.0, 0.0], [101.0, 1.0],
                            [100.0, 1.0], [100.0, 0.0],
                        ]],
                    },
                    "properties": {"name": "Area 1"},
                },
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [100.5, 0.5]},
                    "properties": {"name": "Point 1"},
                },
            ],
        }

    def test_feature_level_click(self, sample_geojson):
        """Test feature-level click event."""
        g = GeoJson(
            sample_geojson,
            events={"click": "alert"},
        )
        # Need parent_map context for full render
        import folium
        m = folium.Map(location=[0.5, 100.5], zoom_start=8)
        g.add_to(m)
        m._repr_html_()  # Trigger render to set contexts
        rendered = g._template.module.script(g)
        # Feature events go inside onEachFeature's layer.on({...})
        assert '"click": ' in rendered
        assert "alert(msg)" in rendered

    def test_feature_level_multiple_events(self, sample_geojson):
        """Test multiple feature-level events."""
        g = GeoJson(
            sample_geojson,
            events={
                "click": "alert",
                "mouseover": "highlight",
                "mouseout": "reset_highlight",
            },
        )
        import folium
        m = folium.Map(location=[0.5, 100.5], zoom_start=8)
        g.add_to(m)
        m._repr_html_()
        rendered = g._template.module.script(g)
        assert '"click": ' in rendered
        assert '"mouseover": ' in rendered
        assert '"mouseout": ' in rendered


class TestGeoJsonLayerEvents:
    """Tests for GeoJson layer-level events (bound to whole layer)."""

    @pytest.fixture
    def sample_geojson(self):
        return {"type": "Point", "coordinates": [100.0, 0.0]}

    def test_layer_level_events(self, sample_geojson):
        """Test layer-level events on GeoJson."""
        import folium
        m = folium.Map(location=[0.0, 100.0], zoom_start=8)
        g = GeoJson(
            sample_geojson,
            layer_events={
                "layeradd": "log",
                "layerremove": "log",
            },
        )
        g.add_to(m)
        m._repr_html_()
        rendered = g._template.module.script(g)
        name = g.get_name()
        assert f'{name}.on("layeradd"' in rendered
        assert f'{name}.on("layerremove"' in rendered
        assert "console.log" in rendered

    def test_layer_event_api_methods(self, sample_geojson):
        """Test GeoJson-specific layer event management methods."""
        g = GeoJson(sample_geojson)
        assert not g.has_layer_events()

        g.set_layer_event("layeradd", "log")
        assert g.has_layer_events()
        bindings = g._render_layer_event_bindings()
        assert '.on("layeradd"' in bindings

        assert g.remove_layer_event("layeradd")
        assert not g.has_layer_events()
        assert not g.remove_layer_event("nonexistent")

        g.set_layer_event("layeradd", "alert")
        g.clear_layer_events()
        assert not g.has_layer_events()

    def test_both_feature_and_layer_events(self, sample_geojson):
        """Test feature-level + layer-level events simultaneously."""
        feature_data = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": sample_geojson,
                "properties": {"name": "test"},
            }],
        }
        import folium
        m = folium.Map(location=[0.0, 100.0], zoom_start=8)
        g = GeoJson(
            feature_data,
            events={"click": "alert"},
            layer_events={"layeradd": "log"},
        )
        g.add_to(m)
        m._repr_html_()
        rendered = g._template.module.script(g)
        name = g.get_name()
        # Feature-level
        assert '"click": ' in rendered
        # Layer-level
        assert f'{name}.on("layeradd"' in rendered


class TestEventMixinDirect:
    """Tests for using EventMixin directly in custom classes."""

    def test_mixin_inherits_correctly(self):
        """Test EventMixin can be mixed into a MacroElement subclass."""
        from branca.element import MacroElement

        class TestLayer(EventMixin, MacroElement):
            def __init__(self, events=None):
                super().__init__(events=events)
                self._name = "TestLayer"

        layer = TestLayer(
            events={
                "click": "alert",
                "mouseover": "function(e) { console.log(e); }",
            }
        )
        assert layer.has_events()
        assert layer.get_event("click") is not None

    def test_render_event_bindings_custom_var(self):
        """Test _render_event_bindings with custom variable name."""
        from branca.element import MacroElement

        class TestLayer(EventMixin, MacroElement):
            def __init__(self, events=None):
                super().__init__(events=events)

        layer = TestLayer(events={"click": "alert", "mouseover": "log"})
        bindings = layer._render_event_bindings("myCustomLayer")
        assert 'myCustomLayer.on("click"' in bindings
        assert 'myCustomLayer.on("mouseover"' in bindings


class TestEventRenderingStability:
    """Tests for stable event binding rendering."""

    def test_no_duplicate_bindings(self, test_map):
        """Test that events are only bound once, not duplicated."""
        c = Circle(location=[0, 0], radius=100, events={"click": "alert"})
        rendered = _render_layer(c, test_map)
        name = c.get_name()
        # Count occurrences of the .on("click" binding
        count = rendered.count(f'{name}.on("click"')
        assert count == 1, f"Event should be bound once, found {count} times"

    def test_all_supported_events(self, test_map):
        """Test rendering all supported Leaflet event types."""
        supported = [
            "click", "dblclick", "mousedown", "mouseup",
            "mouseover", "mouseout", "mousemove", "contextmenu",
            "focus", "blur", "preclick", "add", "remove",
            "popupopen", "popupclose", "tooltipopen", "tooltipclose",
        ]
        events_dict = {evt: "log" for evt in supported}
        c = Circle(location=[0, 0], radius=100, events=events_dict)
        rendered = _render_layer(c, test_map)
        name = c.get_name()
        for evt in supported:
            assert f'{name}.on("{evt}"' in rendered, f"Event {evt} not found in render"

    def test_empty_events_no_render(self, test_map):
        """Test that no event binding code is generated when no events."""
        c = Circle(location=[0, 0], radius=100)
        rendered = _render_layer(c, test_map)
        name = c.get_name()
        assert f'{name}.on(' not in rendered


class TestBackwardCompatibility:
    """Tests for backward compatibility with existing features."""

    def test_geojson_still_supports_on_each_feature(self):
        """Test that old-style on_each_feature still works."""
        from folium.utilities import JsCode
        feature_data = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [0, 0]},
                "properties": {},
            }],
        }
        on_each = JsCode("""function(feature, layer) {
            layer.bindPopup('Old style');
        }""")
        g = GeoJson(
            feature_data,
            on_each_feature=on_each,
            events={"click": "alert"},  # New system alongside old
        )
        import folium
        m = folium.Map(location=[0, 0], zoom_start=8)
        g.add_to(m)
        m._repr_html_()
        rendered = g._template.module.script(g)
        # Old style bindPopup should be there
        assert "Old style" in rendered
        # New style event should also be there
        assert '"click": ' in rendered

    def test_highlight_function_still_works(self):
        """Test that highlight_function parameter still works."""
        feature_data = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[[0,0],[1,0],[1,1],[0,1],[0,0]]]},
                "properties": {},
            }],
        }
        highlight_func = lambda x: {"weight": 3, "color": "#666", "dashArray": ""}
        g = GeoJson(
            feature_data,
            highlight_function=highlight_func,
            events={"click": "log"},
        )
        import folium
        m = folium.Map(location=[0.5, 0.5], zoom_start=8)
        g.add_to(m)
        m._repr_html_()
        rendered = g._template.module.script(g)
        # Highlight function creates mouseover/mouseout in onEachFeature
        assert "highlight" in rendered.lower() or "mouseover" in rendered.lower()
        # Our new click event is also there
        assert '"click": ' in rendered


class TestEventHandlerAbsorption:
    """Tests for the unified event path: add_child(EventHandler) is absorbed."""

    def test_add_child_event_handler_absorbed(self, test_map):
        """Test that add_child(EventHandler(...)) is absorbed into _event_handlers."""
        from folium.elements import EventHandler
        from folium.utilities import JsCode

        c = Circle(location=[0, 0], radius=100)
        handler = JsCode("function(e) { console.log('absorbed'); }")
        c.add_child(EventHandler("click", handler))

        assert c.has_events(), "EventHandler should be absorbed into _event_handlers"
        assert c.get_event("click") is not None, "click event should exist"
        rendered = _render_layer(c, test_map)
        name = c.get_name()
        assert f'{name}.on("click"' in rendered, "Absorbed event should render"
        assert "console.log('absorbed')" in rendered, "Handler body should render"

    def test_add_child_event_handler_no_duplicate(self, test_map):
        """Test no duplicate binding when events= and add_child both set same event."""
        import warnings
        from folium.elements import EventHandler
        from folium.utilities import JsCode

        c = Circle(
            location=[0, 0],
            radius=100,
            events={"click": "alert"},
        )
        handler = JsCode("function(e) { console.log('from EventHandler'); }")

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            c.add_child(EventHandler("click", handler))
            assert len(w) == 1, "Should warn about duplicate event"
            assert "already set" in str(w[0].message)

        # Should still only have 1 click event (the original from events=)
        assert len(c._event_handlers) == 1
        rendered = _render_layer(c, test_map)
        name = c.get_name()
        # The original 'alert' action should be rendered, NOT the EventHandler one
        assert "alert(msg)" in rendered
        assert "from EventHandler" not in rendered

    def test_add_child_event_handler_different_events(self, test_map):
        """Test add_child(EventHandler) for a different event name works."""
        from folium.elements import EventHandler
        from folium.utilities import JsCode

        c = Circle(
            location=[0, 0],
            radius=100,
            events={"click": "alert"},
        )
        handler = JsCode("function(e) { console.log('hover'); }")
        c.add_child(EventHandler("mouseover", handler))

        assert len(c._event_handlers) == 2
        rendered = _render_layer(c, test_map)
        name = c.get_name()
        assert f'{name}.on("click"' in rendered
        assert f'{name}.on("mouseover"' in rendered

    def test_geojson_absorb_event_handler(self):
        """Test GeoJson absorbs add_child(EventHandler) into layer-level events."""
        from folium.elements import EventHandler
        from folium.utilities import JsCode

        feature_data = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [0, 0]},
                "properties": {"name": "test"},
            }],
        }
        g = GeoJson(feature_data)
        handler = JsCode("function(e) { console.log('geo event'); }")
        g.add_child(EventHandler("mouseover", handler))

        # Should go to layer-level events (matches original EventHandler behavior)
        assert g.has_layer_events(), "EventHandler should be absorbed into layer events"
        assert not g.has_events(), "Should NOT be in feature-level events"
        import folium
        m = folium.Map(location=[0, 0], zoom_start=8)
        g.add_to(m)
        m._repr_html_()
        rendered = g._template.module.script(g)
        g_name = g.get_name()
        assert f'{g_name}.on("mouseover"' in rendered, "Should render as layer-level .on()"

    def test_add_child_non_event_handler_passthrough(self, test_map):
        """Test that non-EventHandler children still get added normally."""
        c = Circle(location=[0, 0], radius=100, events={"click": "alert"})
        from folium.map import Popup
        c.add_child(Popup("test popup"))

        # Popup is added as a child (not absorbed)
        children_names = [child._name for child in c._children.values()]
        assert "Popup" in children_names, "Popup should be a normal child, not absorbed"

    def test_evented_on_uses_unified_path(self, test_map):
        """Test that Evented.on() uses the unified path for EventMixin layers."""
        from folium.utilities import JsCode

        m = folium.Map(location=[0, 0])
        handler = JsCode("function(e) { console.log('via_on_test'); }")
        m.on(click=handler)

        html = m._repr_html_()
        assert "via_on_test" in html, "Evented.on() handler should be in HTML"
