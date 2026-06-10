import base64
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from folium import FeatureGroup, Map, Marker, Popup
from folium.utilities import (
    JsCode,
    _is_url,
    _image_source_type,
    _is_renderable_image_source,
    camelize,
    deep_copy,
    escape_double_quotes,
    get_obj_in_upper_tree,
    if_pandas_df_convert_to_numpy,
    image_to_url,
    javascript_identifier_path_to_array_notation,
    normalize_bounds_type,
    parse_font_size,
    parse_options,
    validate_location,
    validate_locations,
    validate_multi_locations,
)


@pytest.mark.parametrize(
    "location",
    [
        (5, 3),
        [5.0, 3.0],
        np.array([5, 3]),
        np.array([[5, 3]]),
        pd.Series([5, 3]),
        pd.DataFrame([5, 3]),
        pd.DataFrame([[5, 3]]),
        ("5.0", "3.0"),
        ("5", "3"),
    ],
)
def test_validate_location(location):
    outcome = validate_location(location)
    assert outcome == [5.0, 3.0]


@pytest.mark.parametrize(
    "location",
    [
        None,
        [None, None],
        (),
        [0],
        ["hi"],
        "hi",
        ("lat", "lon"),
        Marker,
        (Marker, Marker),
        (3.0, np.nan),
        {3.0, 5.0},
        {"lat": 5.0, "lon": 3.0},
        range(4),
        [0, 1, 2],
        [(0,), (1,)],
    ],
)
def test_validate_location_exceptions(location):
    """Test input that should raise an exception."""
    with pytest.raises((TypeError, ValueError)):
        validate_location(location)


@pytest.mark.parametrize(
    "locations",
    [
        [(0, 5), (1, 6), (2, 7)],
        [[0, 5], [1, 6], [2, 7]],
        np.array([[0, 5], [1, 6], [2, 7]]),
        pd.DataFrame([[0, 5], [1, 6], [2, 7]]),
    ],
)
def test_validate_locations(locations):
    outcome = validate_locations(locations)
    assert outcome == [[0.0, 5.0], [1.0, 6.0], [2.0, 7.0]]


@pytest.mark.parametrize(
    "locations",
    [
        [[(0, 5), (1, 6), (2, 7)], [(3, 8), (4, 9)]],
    ],
)
def test_validate_multi_locations(locations):
    outcome = validate_multi_locations(locations)
    assert outcome == [[[0, 5], [1, 6], [2, 7]], [[3, 8], [4, 9]]]


@pytest.mark.parametrize(
    "locations",
    [
        None,
        [None, None],
        (),
        [0],
        ["hi"],
        "hi",
        ("lat", "lon"),
        Marker,
        (Marker, Marker),
        (3.0, np.nan),
        {3.0, 5.0},
        {"lat": 5.0, "lon": 3.0},
        range(4),
        [0, 1, 2],
        [(0,), (1,)],
    ],
)
def test_validate_locations_exceptions(locations):
    """Test input that should raise an exception."""
    with pytest.raises((TypeError, ValueError)):
        validate_locations(locations)


def test_if_pandas_df_convert_to_numpy():
    data = [[0, 5, "red"], [1, 6, "blue"], [2, 7, "something"]]
    df = pd.DataFrame(data, columns=["lat", "lng", "color"])
    res = if_pandas_df_convert_to_numpy(df)
    assert isinstance(res, np.ndarray)
    expected = np.array(data)
    assert all(
        [
            [all([i == j]) for i, j in zip(row1, row2)]
            for row1, row2 in zip(res, expected)
        ]
    )
    # Also check if it ignores things that are not Pandas DataFrame:
    assert if_pandas_df_convert_to_numpy(data) is data
    assert if_pandas_df_convert_to_numpy(expected) is expected


@pytest.mark.parametrize(
    "bounds, expected",
    [
        ([[1, 2], [3, 4]], [[1.0, 2.0], [3.0, 4.0]]),
        ([[None, 2], [3, None]], [[None, 2.0], [3.0, None]]),
        ([[1.1, 2.2], [3.3, 4.4]], [[1.1, 2.2], [3.3, 4.4]]),
        ([[None, None], [None, None]], [[None, None], [None, None]]),
        ([[0, -1], [-2, 3]], [[0.0, -1.0], [-2.0, 3.0]]),
    ],
)
def test_normalize_bounds_type(bounds, expected):
    assert normalize_bounds_type(bounds) == expected


def test_camelize():
    assert camelize("variable_name") == "variableName"
    assert camelize("variableName") == "variableName"
    assert camelize("name") == "name"
    assert camelize("very_long_variable_name") == "veryLongVariableName"


def test_deep_copy():
    m = Map()
    fg = FeatureGroup().add_to(m)
    Marker(location=(0, 0)).add_to(fg)
    m_copy = deep_copy(m)

    def check(item, item_copy):
        assert type(item) is type(item_copy)
        assert item._name == item_copy._name
        for attr in item.__dict__.keys():
            if not attr.startswith("_"):
                assert getattr(item, attr) == getattr(item_copy, attr)
        assert item is not item_copy
        assert item._id != item_copy._id
        for child, child_copy in zip(
            item._children.values(), item_copy._children.values()
        ):
            check(child, child_copy)

    check(m, m_copy)


def test_get_obj_in_upper_tree():
    m = Map()
    fg = FeatureGroup().add_to(m)
    marker = Marker(location=(0, 0)).add_to(fg)
    assert get_obj_in_upper_tree(marker, FeatureGroup) is fg
    assert get_obj_in_upper_tree(marker, Map) is m
    # The search should only go up, not down:
    with pytest.raises(ValueError):
        assert get_obj_in_upper_tree(fg, Marker)
    with pytest.raises(ValueError):
        assert get_obj_in_upper_tree(marker, Popup)


def test_parse_options():
    assert parse_options(thing=42) == {"thing": 42}
    assert parse_options(thing=None) == {}
    assert parse_options(long_thing=42) == {"longThing": 42}
    assert parse_options(thing=42, lst=[1, 2]) == {"thing": 42, "lst": [1, 2]}


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/img.png",
        "http://example.com/img.png",
        "ftp://example.com/img.png",
        "file:///t.jpg",
        "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7",
    ],
)
def test_is_url(url):
    assert _is_url(url) is True


@pytest.mark.parametrize(
    "text,result",
    [
        ("bla", "bla"),
        ('bla"bla', r"bla\"bla"),
        ('"bla"bla"', r"\"bla\"bla\""),
    ],
)
def test_escape_double_quotes(text, result):
    assert escape_double_quotes(text) == result


@pytest.mark.parametrize(
    "text,result",
    [
        ("bla", '["bla"]'),
        ("obj-1.obj2", '["obj-1"]["obj2"]'),
        ('obj-1.obj"2', r'["obj-1"]["obj\"2"]'),
    ],
)
def test_javascript_identifier_path_to_array_notation(text, result):
    assert javascript_identifier_path_to_array_notation(text) == result


def test_js_code_init_str():
    js_code = JsCode("hi")
    assert isinstance(js_code, JsCode)
    assert isinstance(js_code.js_code, str)


def test_js_code_init_js_code():
    js_code = JsCode("hi")
    js_code_2 = JsCode(js_code)
    assert isinstance(js_code_2, JsCode)
    assert isinstance(js_code_2.js_code, str)


@pytest.mark.parametrize(
    "value,expected",
    [
        (10, "10px"),
        (12.5, "12.5px"),
        ("1rem", "1rem"),
        ("1em", "1em"),
    ],
)
def test_parse_font_size_valid(value, expected):
    assert parse_font_size(value) == expected


invalid_values = ["1", "1unit"]
expected_errors = "The font size must be expressed in rem, em, or px."


@pytest.mark.parametrize("value,error_message", zip(invalid_values, expected_errors))
def test_parse_font_size_invalid(value, error_message):
    with pytest.raises(ValueError, match=error_message):
        parse_font_size(value)


_SVG_DATA = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
    '<circle cx="50" cy="50" r="40" fill="red"/></svg>'
)

_SVG_DATA_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<svg xmlns="http://www.w3.org/2000/svg"><rect width="100" height="100"/></svg>'
)

_JSON_OBJECT = '{"type": "Feature", "properties": {"name": "test"}}'
_JSON_ARRAY = '[{"type": "Feature"}, {"type": "Feature"}]'

_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
    "AAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)

_GIF_BASE64 = "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"


@pytest.mark.parametrize(
    "image,expected_type",
    [
        ("https://example.com/img.png", "url"),
        ("http://example.com/img.png", "url"),
        ("ftp://example.com/img.png", "url"),
        ("file:///tmp/img.png", "url"),
        ("data:image/png;base64,iVBORw0KGgo=", "url"),
        (np.array([[[1, 0, 0]]]), "array"),
        ([[[1, 0, 0]], [[0, 1, 0]]], "array"),
        (_SVG_DATA, "raw"),
        (_JSON_OBJECT, "raw"),
        (_PNG_BASE64, "raw"),
        ("plain_string", "raw"),
    ],
)
def test_image_source_type(image, expected_type):
    assert _image_source_type(image) == expected_type


def test_image_source_type_pathlike():
    p = Path("/nonexistent/path.png")
    assert _image_source_type(p) == "pathlike"


def test_image_source_type_existing_file(tmp_path):
    f = tmp_path / "test.png"
    f.write_bytes(b"\x89PNG\r\n\x1a\n")
    assert _image_source_type(str(f)) == "file"


@pytest.mark.parametrize(
    "raw,expected_prefix",
    [
        (_SVG_DATA, "data:image/svg+xml;base64,"),
        (_SVG_DATA_XML, "data:image/svg+xml;base64,"),
        (_PNG_BASE64, "data:image/png;base64,"),
        (_GIF_BASE64, "data:image/gif;base64,"),
    ],
)
def test_raw_to_renderable_image_data_uri(raw, expected_prefix):
    from folium.utilities import _raw_to_renderable_image_data_uri

    result = _raw_to_renderable_image_data_uri(raw)
    assert result is not None, f"Expected renderable data URI for {raw[:40]}"
    assert result.startswith(
        expected_prefix
    ), f"Expected {expected_prefix}, got {result[:60]}"
    b64part = result.split(",", 1)[1]
    base64.b64decode(b64part)


def test_raw_to_renderable_image_data_uri_rejects_json():
    from folium.utilities import _raw_to_renderable_image_data_uri

    assert _raw_to_renderable_image_data_uri(_JSON_OBJECT) is None
    assert _raw_to_renderable_image_data_uri(_JSON_ARRAY) is None


def test_raw_to_renderable_image_data_uri_rejects_plain_text():
    from folium.utilities import _raw_to_renderable_image_data_uri

    assert _raw_to_renderable_image_data_uri("hello_world") is None
    assert _raw_to_renderable_image_data_uri("not base64 & spaces") is None


def test_raw_to_renderable_image_data_uri_rejects_non_image_base64():
    from folium.utilities import _raw_to_renderable_image_data_uri

    json_b64 = base64.b64encode(_JSON_OBJECT.encode("utf-8")).decode("ascii")
    assert _raw_to_renderable_image_data_uri(json_b64) is None


@pytest.mark.parametrize(
    "image,is_valid",
    [
        ("https://example.com/img.png", True),
        ("data:image/png;base64,iVBORw0KGgo=", True),
        (_SVG_DATA, True),
        (_PNG_BASE64, True),
        (np.array([[[1, 0, 0]]]), True),
        ([[[1, 0, 0]]], True),
        (_JSON_OBJECT, False),
        (_JSON_ARRAY, False),
        ("plain_string", False),
        ("{not valid json", False),
    ],
)
def test_is_renderable_image_source(image, is_valid):
    ok, _ = _is_renderable_image_source(image)
    assert ok is is_valid, f"Expected {is_valid} for input {type(image).__name__}: {str(image)[:40]}"


def test_is_renderable_image_source_pathlike_nonexistent():
    p = Path("/definitely/does/not/exist/12345.png")
    ok, reason = _is_renderable_image_source(p)
    assert ok is False
    assert reason is not None


def test_is_renderable_image_source_existing_file(tmp_path):
    f = tmp_path / "test.png"
    f.write_bytes(b"\x89PNG\r\n\x1a\n")
    ok, _ = _is_renderable_image_source(str(f))
    assert ok is True


@pytest.mark.parametrize(
    "image,check_fn",
    [
        (
            _SVG_DATA,
            lambda url: url.startswith("data:image/svg+xml;base64,"),
        ),
        (
            _PNG_BASE64,
            lambda url: url.startswith("data:image/png;base64,"),
        ),
        (
            _GIF_BASE64,
            lambda url: url.startswith("data:image/gif;base64,"),
        ),
        (
            _JSON_OBJECT,
            lambda url: not url.startswith("data:application/json;base64,"),
        ),
        (
            "https://example.com/img.png",
            lambda url: url == "https://example.com/img.png",
        ),
        (
            np.array([[[1, 0, 0, 1]]]),
            lambda url: url.startswith("data:image/png;base64,"),
        ),
        (
            [[[1, 0, 0, 1]], [[0, 1, 0, 1]]],
            lambda url: url.startswith("data:image/png;base64,"),
        ),
    ],
)
def test_image_to_url(image, check_fn):
    result = image_to_url(image)
    assert check_fn(result), f"Failed for input type {type(image).__name__}"


def test_image_to_url_plain_text_escaped():
    plain = 'plain text with "quotes" and \'apostrophes\''
    result = image_to_url(plain)
    assert "data:image" not in result
    assert "data:application/json" not in result
    assert "\n" not in result


def test_image_to_url_json_not_wrapped_as_data_uri():
    result = image_to_url(_JSON_OBJECT)
    assert not result.startswith("data:application/json;base64,")
    assert "Feature" in result


def test_image_to_url_existing_file(tmp_path):
    f = tmp_path / "test.png"
    f.write_bytes(b"\x89PNG\r\n\x1a\n")
    result = image_to_url(str(f))
    assert result.startswith("data:image/png;base64,")


def test_image_to_url_pathlike_existing(tmp_path):
    f = tmp_path / "test.jpg"
    f.write_bytes(b"\xff\xd8\xff")
    result = image_to_url(Path(f))
    assert result.startswith("data:image/jpg;base64,")


def test_image_to_url_data_uri_passthrough():
    data_uri = "data:image/svg+xml;base64,PHN2Zz48L3N2Zz4="
    assert image_to_url(data_uri) == data_uri


def test_image_to_url_special_scheme():
    special = "blob:https://example.com/uuid"
    assert image_to_url(special) == special
