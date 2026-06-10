import copy
import sys
from folium import GeoJson, Map, Choropleth


def run_tests():
    results = []

    # Test 1: Original data not mutated with style
    try:
        original_data = {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "properties": {"name": "f1"}, "geometry": {"type": "Point", "coordinates": [0, 0]}},
                {"type": "Feature", "properties": {"name": "f2"}, "geometry": {"type": "Point", "coordinates": [1, 1]}}
            ]
        }
        original_copy = copy.deepcopy(original_data)
        m = Map()
        GeoJson(original_data, style_function=lambda x: {"color": "blue"}).add_to(m)
        m.get_root().render()
        assert original_data == original_copy
        results.append("PASS: test_original_data_not_mutated_with_style")
    except Exception as e:
        results.append(f"FAIL: test_original_data_not_mutated_with_style - {e}")

    # Test 2: ID injection does not leak to original
    try:
        original_data = {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "properties": {}, "geometry": {"type": "Point", "coordinates": [0, 0]}},
                {"type": "Feature", "properties": {}, "geometry": {"type": "Point", "coordinates": [1, 1]}}
            ]
        }
        original_copy = copy.deepcopy(original_data)
        m = Map()
        GeoJson(original_data, style_function=lambda x: {"color": "blue"}).add_to(m)
        m.get_root().render()
        assert original_data == original_copy
        assert "id" not in original_data["features"][0]
        results.append("PASS: test_original_data_not_mutated_with_id_injection")
    except Exception as e:
        results.append(f"FAIL: test_original_data_not_mutated_with_id_injection - {e}")

    # Test 3: Geometry to FeatureCollection does not mutate original
    try:
        original_data = {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}
        original_copy = copy.deepcopy(original_data)
        m = Map()
        GeoJson(original_data, style_function=lambda x: {"color": "blue"}).add_to(m)
        m.get_root().render()
        assert original_data == original_copy
        assert original_data["type"] == "LineString"
        results.append("PASS: test_original_data_not_mutated_geometry_to_featurecollection")
    except Exception as e:
        results.append(f"FAIL: test_original_data_not_mutated_geometry_to_featurecollection - {e}")

    # Test 4: Reuse same data multiple times
    try:
        original_data = {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "properties": {"value": 1}, "geometry": {"type": "Point", "coordinates": [0, 0]}}
            ]
        }
        original_copy = copy.deepcopy(original_data)
        m = Map()
        GeoJson(original_data, style_function=lambda x: {"color": "blue"}, name="L1").add_to(m)
        GeoJson(original_data, style_function=lambda x: {"color": "red"}, name="L2").add_to(m)
        GeoJson(original_data, style_function=lambda x: {"color": "green"}, name="L3").add_to(m)
        m.get_root().render()
        assert original_data == original_copy
        results.append("PASS: test_reuse_same_data_multiple_times")
    except Exception as e:
        results.append(f"FAIL: test_reuse_same_data_multiple_times - {e}")

    # Test 5: Duplicate ids handled correctly (internally unique)
    try:
        original_data = {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "id": "same-id", "properties": {"value": 1}, "geometry": {"type": "Point", "coordinates": [0, 0]}},
                {"type": "Feature", "id": "same-id", "properties": {"value": 1}, "geometry": {"type": "Point", "coordinates": [1, 1]}}
            ]
        }
        original_copy = copy.deepcopy(original_data)
        m = Map()
        geojson = GeoJson(original_data, style_function=lambda x: {"color": "blue"}).add_to(m)
        m.get_root().render()
        assert original_data == original_copy, "Original data was mutated!"
        internal_ids = [f.get("id") for f in geojson.data["features"]]
        assert len(set(internal_ids)) == len(internal_ids), f"Internal ids not unique: {internal_ids}"
        results.append("PASS: test_duplicate_ids_handled")
    except Exception as e:
        results.append(f"FAIL: test_duplicate_ids_handled - {e}")

    # Test 6: Properties None handled without mutation
    try:
        original_data = {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "properties": None, "geometry": {"type": "Point", "coordinates": [0, 0]}}
            ]
        }
        original_copy = copy.deepcopy(original_data)
        m = Map()
        GeoJson(original_data, style_function=lambda x: {"color": "blue"}).add_to(m)
        m.get_root().render()
        assert original_data == original_copy
        results.append("PASS: test_properties_none_not_mutated")
    except Exception as e:
        results.append(f"FAIL: test_properties_none_not_mutated - {e}")

    # Test 7: Missing properties handled without mutation
    try:
        original_data = {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "geometry": {"type": "Point", "coordinates": [0, 0]}}
            ]
        }
        original_copy = copy.deepcopy(original_data)
        m = Map()
        GeoJson(original_data, style_function=lambda x: {"color": "blue"}).add_to(m)
        m.get_root().render()
        assert original_data == original_copy
        results.append("PASS: test_missing_properties_not_mutated")
    except Exception as e:
        results.append(f"FAIL: test_missing_properties_not_mutated - {e}")

    # Test 8: GeoJson without style/highlight still normalizes embed data
    try:
        original_data = {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "properties": None, "geometry": {"type": "Point", "coordinates": [0, 0]}},
                {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1, 1]}}
            ]
        }
        original_copy = copy.deepcopy(original_data)
        geojson = GeoJson(original_data)
        # No style, but embed=True so data should still be normalized internally
        for feat in geojson.data["features"]:
            assert "properties" in feat and isinstance(feat["properties"], dict), \
                f"properties not normalized: {feat}"
        assert original_data == original_copy, "Original was mutated!"
        results.append("PASS: test_embed_data_normalized_without_style")
    except Exception as e:
        results.append(f"FAIL: test_embed_data_normalized_without_style - {e}")

    # Test 9: Single feature (not FeatureCollection) with style
    try:
        original_data = {
            "type": "Feature",
            "properties": {"name": "single"},
            "geometry": {"type": "Point", "coordinates": [0, 0]}
        }
        original_copy = copy.deepcopy(original_data)
        m = Map()
        geojson = GeoJson(original_data, style_function=lambda x: {"color": "blue"}).add_to(m)
        m.get_root().render()
        assert original_data == original_copy, "Original was mutated!"
        assert geojson.data["type"] == "FeatureCollection", "Not converted to FeatureCollection"
        assert len(geojson.data["features"]) == 1
        results.append("PASS: test_single_feature_normalized")
    except Exception as e:
        results.append(f"FAIL: test_single_feature_normalized - {e}")

    # Test 10: Raw geometry (Point) with style
    try:
        original_data = {"type": "Point", "coordinates": [0, 0]}
        original_copy = copy.deepcopy(original_data)
        m = Map()
        geojson = GeoJson(original_data, style_function=lambda x: {"color": "blue"}).add_to(m)
        m.get_root().render()
        assert original_data == original_copy, "Original was mutated!"
        assert geojson.data["type"] == "FeatureCollection"
        assert geojson.data["features"][0]["geometry"]["type"] == "Point"
        assert "properties" in geojson.data["features"][0]
        results.append("PASS: test_raw_geometry_normalized")
    except Exception as e:
        results.append(f"FAIL: test_raw_geometry_normalized - {e}")

    # Test 11: get_feature_id and style_map consistency
    try:
        data = {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "id": "a", "properties": {"name": "f1"}, "geometry": {"type": "Point", "coordinates": [0, 0]}},
                {"type": "Feature", "id": "b", "properties": {"name": "f2"}, "geometry": {"type": "Point", "coordinates": [1, 1]}},
                {"type": "Feature", "id": "c", "properties": {"name": "f3"}, "geometry": {"type": "Point", "coordinates": [2, 2]}}
            ]
        }
        style_func = lambda x: {"color": "blue" if x["id"] == "a" else "red"}
        m = Map()
        geojson = GeoJson(data, style_function=style_func).add_to(m)
        m.get_root().render()

        all_ids = []
        for style_key, ids in geojson.style_map.items():
            if style_key != "default":
                all_ids.extend(ids)
        assert len(all_ids) == 1 and "a" in all_ids, f"style_map incorrect: {geojson.style_map}"
        results.append("PASS: test_style_map_consistency")
    except Exception as e:
        results.append(f"FAIL: test_style_map_consistency - {e}")

    with open("/tmp/test_results_v2.txt", "w") as f:
        f.write("\n".join(results))


if __name__ == "__main__":
    run_tests()
