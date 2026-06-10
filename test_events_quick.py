"""Quick validation script for the unified vector layer event binding system."""

import json
import folium
from folium import (
    Circle,
    CircleMarker,
    Polygon,
    PolyLine,
    Rectangle,
    Marker,
    GeoJson,
)
from folium.utilities import JsCode


def test_basic_circle_events():
    """Test basic event binding on Circle layer."""
    m = folium.Map(location=[45.5, -122.3])
    circle = Circle(
        location=[45.5, -122.3],
        radius=1000,
        events={
            "click": "alert",
            "mouseover": "highlight",
            "mouseout": "reset_highlight",
        },
    )
    circle.add_to(m)
    # Check template render directly (more reliable than full HTML parse)
    circle_name = circle.get_name()
    rendered = circle._template.module.script(circle)

    # Check that .on() calls are generated
    assert f'{circle_name}.on("click"' in rendered, "Click event binding not found for Circle"
    assert f'{circle_name}.on("mouseover"' in rendered, "Mouseover event binding not found for Circle"
    assert f'{circle_name}.on("mouseout"' in rendered, "Mouseout event binding not found for Circle"
    print("✓ Circle events: PASS")


def test_circle_marker_with_inline_js():
    """Test CircleMarker with inline JS function."""
    m = folium.Map(location=[45.5, -122.3])
    cm = CircleMarker(
        location=[45.5, -122.3],
        radius=20,
        events={
            "dblclick": JsCode("function(e) { console.log('double clicked', e); }"),
            "click": "function(e) { alert('CircleMarker clicked'); }",
        },
    )
    cm.add_to(m)
    cm_name = cm.get_name()
    rendered = cm._template.module.script(cm)

    assert f'{cm_name}.on("dblclick"' in rendered, "Dblclick event binding not found"
    assert "double clicked" in rendered, "Inline JS function body not found"
    assert "CircleMarker clicked" in rendered, "Inline click handler message not found"
    print("✓ CircleMarker with inline JS: PASS")


def test_polygon_predefined_actions():
    """Test Polygon with predefined event actions."""
    m = folium.Map(location=[45.5, -122.3])
    polygon = Polygon(
        locations=[
            [45.51, -122.68],
            [37.77, -122.43],
            [34.04, -118.2],
        ],
        events={
            "click": "zoom",
            "mouseover": "log",
        },
    )
    polygon.add_to(m)
    poly_name = polygon.get_name()
    rendered = polygon._template.module.script(polygon)

    assert f'{poly_name}.on("click"' in rendered, "Click zoom event not found"
    assert f'{poly_name}.on("mouseover"' in rendered, "Mouseover log event not found"
    assert "fitBounds" in rendered or "flyTo" in rendered, "Zoom action not included"
    print("✓ Polygon predefined actions: PASS")


def test_polyline_function_reference():
    """Test PolyLine with global JS function name reference."""
    m = folium.Map(location=[45.5, -122.3])
    polyline = PolyLine(
        locations=[[40.0, -80.0], [45.0, -80.0]],
        events={
            "click": "myApp.globalClickHandler",
            "contextmenu": "App.showContextMenu",
        },
    )
    polyline.add_to(m)
    pl_name = polyline.get_name()
    rendered = polyline._template.module.script(polyline)

    assert f'{pl_name}.on("click", myApp.globalClickHandler);' in rendered, "Function reference not found"
    assert f'{pl_name}.on("contextmenu", App.showContextMenu);' in rendered, "Context menu handler not found"
    print("✓ PolyLine function reference: PASS")


def test_rectangle_set_event():
    """Test Rectangle with programmatic event setting."""
    m = folium.Map(location=[45.5, -122.3])
    rect = Rectangle(
        bounds=[[45.6, -122.8], [45.61, -122.7]],
    )
    rect.set_event("click", "alert")
    rect.set_event("mouseover", "log")
    rect.add_to(m)
    rect_name = rect.get_name()
    rendered = rect._template.module.script(rect)

    assert rect.has_events(), "has_events should return True"
    assert f'{rect_name}.on("click"' in rendered, "Programmatically set click event not found"
    assert rect.remove_event("mouseover"), "remove_event should return True"
    assert not rect.get_event("mouseover"), "Event should be removed"
    rect.clear_events()
    assert not rect.has_events(), "clear_events should remove all events"
    print("✓ Rectangle programmatic events: PASS")


def test_marker_events():
    """Test that Marker (parent class) also supports events."""
    m = folium.Map(location=[45.5, -122.3])
    marker = Marker(
        location=[45.5, -122.3],
        popup="Test Marker",
        events={
            "click": "alert",
            "mouseover": "highlight",
            "mouseout": "reset_highlight",
        },
    )
    marker.add_to(m)
    marker_name = marker.get_name()
    rendered = marker._template.module.script(marker)

    assert f'{marker_name}.on("click"' in rendered, "Marker click event not found"
    print("✓ Marker events: PASS")


def test_geojson_feature_events():
    """Test GeoJson feature-level events."""
    geojson_data = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [100.0, 0.0],
                        [101.0, 0.0],
                        [101.0, 1.0],
                        [100.0, 1.0],
                        [100.0, 0.0],
                    ]],
                },
                "properties": {"name": "Test Area", "value": 42},
            }
        ],
    }

    m = folium.Map(location=[0.5, 100.5], zoom_start=8)
    g = GeoJson(
        geojson_data,
        events={
            "click": "alert",
            "mouseover": "highlight",
            "mouseout": "reset_highlight",
        },
        layer_events={
            "layeradd": "log",
            "layerremove": "log",
        },
    )
    g.add_to(m)
    # Need to call render to set parent_map
    m._repr_html_()
    rendered = g._template.module.script(g)
    g_name = g.get_name()

    # Feature-level events should be inside onEachFeature's layer.on({...})
    assert '"click"' in rendered, "Feature click event not in onEachFeature"
    assert '"mouseover"' in rendered, "Feature mouseover event not in onEachFeature"
    assert "alert" in rendered, "Alert action not found in feature events"

    # Layer-level events should be at the GeoJson layer level
    assert f'{g_name}.on("layeradd"' in rendered, "Layer-level layeradd event not found"
    assert f'{g_name}.on("layerremove"' in rendered, "Layer-level layerremove event not found"
    print("✓ GeoJson feature + layer events: PASS")


def test_event_mixin_directly():
    """Test EventMixin with a custom class."""
    from folium.utilities import EventMixin
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
    rendered = layer._render_event_bindings("testLayerVar")
    assert 'testLayerVar.on("click"' in rendered
    assert 'testLayerVar.on("mouseover"' in rendered
    assert "console.log(e)" in rendered
    print("✓ EventMixin direct usage: PASS")


def test_geojson_layer_event_methods():
    """Test GeoJson layer-level event management methods."""
    geojson_data = {"type": "Point", "coordinates": [100.0, 0.0]}
    g = GeoJson(geojson_data)

    assert not g.has_layer_events()
    g.set_layer_event("layeradd", "log")
    assert g.has_layer_events()

    bindings = g._render_layer_event_bindings()
    assert '.on("layeradd"' in bindings
    assert "console.log" in bindings

    assert g.remove_layer_event("layeradd")
    assert not g.has_layer_events()
    assert not g.remove_layer_event("nonexistent")

    g.set_layer_event("layeradd", "log")
    g.clear_layer_events()
    assert not g.has_layer_events()
    print("✓ GeoJson layer event methods: PASS")


def test_predefined_actions_exist():
    """Test that all predefined actions are available."""
    from folium import PREDEFINED_EVENT_ACTIONS

    required_actions = ["zoom", "alert", "log", "highlight", "reset_highlight", "open_popup", "close_popup"]
    for action in required_actions:
        assert action in PREDEFINED_EVENT_ACTIONS, f"Predefined action '{action}' missing"
        assert PREDEFINED_EVENT_ACTIONS[action].startswith("function"), f"Action '{action}' should be a function"
    print(f"✓ Predefined actions ({len(PREDEFINED_EVENT_ACTIONS)}): PASS")


if __name__ == "__main__":
    print("=" * 60)
    print("Running Folium Unified Event System Validation Tests")
    print("=" * 60)
    print()

    try:
        test_basic_circle_events()
        test_circle_marker_with_inline_js()
        test_polygon_predefined_actions()
        test_polyline_function_reference()
        test_rectangle_set_event()
        test_marker_events()
        test_geojson_feature_events()
        test_event_mixin_directly()
        test_geojson_layer_event_methods()
        test_predefined_actions_exist()
        print()
        print("=" * 60)
        print("✅ ALL TESTS PASSED!")
        print("=" * 60)
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
