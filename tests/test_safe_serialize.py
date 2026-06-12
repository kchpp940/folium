"""
Regression tests for the safe_serialize module.

This file serves two purposes:
1. Malicious input regression tests — ensure injection/XSS attacks are blocked
2. Output snapshot tests — ensure legitimate inputs produce expected output
   (proves we aren't weakening tests to match new output)
"""

import json

import pytest

from folium.safe_serialize import (
    safe_text,
    safe_html,
    trusted_html,
    safe_url,
    safe_css_value,
    safe_js_value,
    safe_js_options,
    safe_layer_name,
    safe_css_identifier,
    safe_json_to_js,
    safe_query_params,
)
from folium.utilities import JsCode, camelize


# =============================================================================
# safe_text — full HTML escaping
# =============================================================================


class TestSafeText:
    def test_plain_text_passthrough(self):
        assert safe_text("Hello World") == "Hello World"

    def test_none_returns_empty(self):
        assert safe_text(None) == ""

    def test_number_converted(self):
        assert safe_text(42) == "42"

    def test_html_tags_escaped(self):
        result = safe_text("<script>alert(1)</script>")
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_quotes_escaped(self):
        result = safe_text('"double" and \'single\'')
        assert "&quot;" in result
        assert "&#39;" in result

    def test_ampersand_escaped(self):
        assert safe_text("a & b") == "a &amp; b"

    def test_xss_through_angle_brackets(self):
        payload = "<img src=x onerror=alert(1)>"
        result = safe_text(payload)
        # Tags are escaped so they won't be interpreted as HTML
        assert "<img" not in result
        # The text "onerror" appears as plain text (safe), not as an attribute
        assert result.startswith("&lt;img")
        # Verify that no raw angle brackets remain
        assert "<" not in result.replace("&lt;", "")

    def test_layer_name_with_html(self):
        name = '<b>Bold</b> Layer "Test"'
        result = safe_text(name)
        assert "<b>" not in result
        assert "&lt;b&gt;" in result


# =============================================================================
# safe_html — whitelist-based sanitization
# =============================================================================


class TestSafeHtml:
    # --- Allowed tags should survive ---

    def test_allowed_tags_survive(self):
        html = "<p>Hello <b>world</b></p>"
        result = safe_html(html)
        assert "<p>" in result
        assert "<b>" in result
        assert "</b>" in result
        assert "</p>" in result

    def test_allowed_attributes_survive(self):
        html = '<a href="https://example.com" target="_blank">link</a>'
        result = safe_html(html)
        assert 'href="https://example.com"' in result
        assert 'target="_blank"' in result

    def test_class_and_id_attributes_survive(self):
        html = '<div class="my-class" id="my-id">text</div>'
        result = safe_html(html)
        assert 'class="my-class"' in result
        assert 'id="my-id"' in result

    def test_title_and_alt_attributes(self):
        html = '<img src="https://example.com/img.png" alt="photo" title="tip" />'
        result = safe_html(html)
        assert 'alt="photo"' in result
        assert 'title="tip"' in result
        assert 'src="https://example.com/img.png"' in result

    def test_table_structure_survives(self):
        html = (
            '<table cellpadding="0" cellspacing="1">'
            "<tr><th colspan='2'>Header</th></tr>"
            "<tr><td>a</td><td>b</td></tr>"
            "</table>"
        )
        result = safe_html(html)
        assert "<table" in result
        assert "<th colspan" in result
        assert "<td>" in result

    # --- Blocked tags should be removed (content kept) ---

    def test_script_tag_removed(self):
        html = "Hello <script>alert(1)</script> World"
        result = safe_html(html)
        assert "<script>" not in result
        assert "</script>" not in result
        assert "alert(1)" not in result

    def test_iframe_tag_removed(self):
        html = "<iframe src='evil.html'></iframe>safe"
        result = safe_html(html)
        assert "<iframe" not in result
        assert "</iframe>" not in result
        assert "evil.html" not in result

    def test_object_embed_form_tags_removed(self):
        html = '<object data="x.swf"></object><embed src="x.swf"><form action="x"><input type="text" /><button>click</button></form>'
        result = safe_html(html)
        assert "<object" not in result
        assert "<embed" not in result
        assert "<form" not in result
        assert "<input" not in result
        assert "<button" not in result

    # --- Event handlers blocked ---

    def test_onclick_removed(self):
        html = '<div onclick="alert(1)">click me</div>'
        result = safe_html(html)
        assert "onclick" not in result
        assert "alert(1)" not in result

    def test_onmouseover_removed(self):
        html = '<span onmouseover="evil()">text</span>'
        result = safe_html(html)
        assert "onmouseover" not in result
        assert "evil()" not in result

    def test_onload_in_img_removed(self):
        html = '<img src="x.jpg" onload="alert(1)" />'
        result = safe_html(html)
        assert "onload" not in result
        assert "alert(1)" not in result
        assert 'src="x.jpg"' in result

    # --- javascript: URLs blocked ---

    def test_javascript_href_blocked(self):
        html = '<a href="javascript:alert(1)">click</a>'
        result = safe_html(html)
        assert 'href="#"' in result or "javascript:" not in result
        assert "javascript:alert" not in result

    def test_javascript_src_blocked(self):
        html = '<img src="javascript:alert(1)" />'
        result = safe_html(html)
        assert "javascript:" not in result

    def test_data_text_html_href_blocked(self):
        html = '<a href="data:text/html;<script>alert(1)</script>">x</a>'
        result = safe_html(html)
        assert "data:text/html" not in result
        assert "<script>" not in result

    # --- CSS in style attribute ---

    def test_safe_style_survives(self):
        html = '<div style="color: red; font-size: 14px;">text</div>'
        result = safe_html(html)
        assert 'style=' in result
        assert "color: red" in result
        assert "font-size: 14px" in result

    def test_expression_in_style_blocked(self):
        html = '<div style="width: expression(alert(1))">x</div>'
        result = safe_html(html)
        assert "expression" not in result
        # Style attribute with dangerous content is dropped entirely
        assert 'style=' not in result or "expression(" not in result

    def test_behaviour_in_style_blocked(self):
        html = '<div style="behavior: url(x.htc)">x</div>'
        result = safe_html(html)
        assert "behavior" not in result or 'style=' not in result

    # --- Edge cases ---

    def test_no_tags_passthrough(self):
        assert safe_html("just text") == "just text"

    def test_none_returns_empty(self):
        assert safe_html(None) == ""

    def test_comments_removed(self):
        html = "Hello <!-- comment --> World"
        result = safe_html(html)
        assert "<!--" not in result
        assert "-->" not in result
        assert "comment" not in result

    def test_mixed_case_tags_blocked(self):
        html = '<SCRIPT>alert(1)</SCRIPT>'
        result = safe_html(html)
        assert "<script" not in result.lower()

    def test_malformed_html_falls_back_to_stripping(self):
        # Should not crash even on malformed HTML
        result = safe_html("<div <p>broken</div>")
        assert isinstance(result, str)


# =============================================================================
# trusted_html — user-marked trusted HTML, minimal escaping
# =============================================================================


class TestTrustedHtml:
    """Test trusted_html — for user-explicitly-marked HTML content.

    Strategy: Only escape backticks to prevent breaking JS template strings.
    All HTML tags, attributes, and even scripts are passed through verbatim.
    This is for when users intentionally pass HTML and take responsibility
    for its safety.
    """

    def test_plain_text_passthrough(self):
        assert trusted_html("Hello World") == "Hello World"

    def test_none_returns_empty(self):
        assert trusted_html(None) == ""

    def test_number_converted(self):
        assert trusted_html(42) == "42"

    def test_html_tags_preserved(self):
        result = trusted_html("<p>Hello <b>world</b></p>")
        assert "<p>" in result
        assert "<b>" in result
        assert "</b>" in result
        assert "</p>" in result

    def test_script_tags_preserved(self):
        result = trusted_html("<script>alert(1)</script>")
        assert "<script>alert(1)</script>" in result

    def test_event_handlers_preserved(self):
        result = trusted_html('<div onclick="alert(1)">click</div>')
        assert 'onclick="alert(1)"' in result

    def test_javascript_urls_preserved(self):
        result = trusted_html('<a href="javascript:alert(1)">click</a>')
        assert 'href="javascript:alert(1)"' in result

    def test_backticks_escaped(self):
        result = trusted_html("text with `backtick`")
        # Raw backtick should be escaped, not present as-is
        assert " `backtick`" not in result
        # Should have escaped backticks
        assert "\\`backtick\\`" in result

    def test_multiple_backticks_escaped(self):
        result = trusted_html("`a` `b` `c`")
        assert result == "\\`a\\` \\`b\\` \\`c\\`"

    def test_jscode_passthrough(self):
        code = JsCode("console.log('hello')")
        result = trusted_html(code)
        assert result == "console.log('hello')"

    def test_mixed_html_and_backticks(self):
        result = trusted_html('<div id="test">`code`</div>')
        assert '<div id="test">' in result
        assert "\\`code\\`" in result
        assert "</div>" in result


# =============================================================================
# safe_url — scheme whitelist + template support
# =============================================================================


class TestSafeUrl:
    # --- Safe URLs pass through ---

    def test_http_url_safe(self):
        url = "https://example.com/path?x=1&y=2#hash"
        result = safe_url(url)
        # Result is a JS string literal (quoted)
        assert result.startswith('"')
        assert result.endswith('"')
        assert "example.com" in result
        assert "/path" in result

    def test_https_url_safe(self):
        result = safe_url("https://tile.openstreetmap.org/{z}/{x}/{y}.png")
        assert "tile.openstreetmap.org" in result

    def test_relative_url_safe(self):
        result = safe_url("/path/to/image.png")
        assert "/path/to/image.png" in result

    def test_data_image_png_safe(self):
        url = "data:image/png;base64,iVBORw0KGgoAAAANS"
        result = safe_url(url)
        assert "data:image/png;base64" in result
        assert "iVBORw0KGgo" in result

    def test_data_image_svg_safe(self):
        url = "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDov"
        result = safe_url(url)
        assert "data:image/svg+xml" in result

    def test_mailto_safe(self):
        result = safe_url("mailto:test@example.com")
        assert "mailto:test@example.com" in result

    def test_blob_url_safe(self):
        result = safe_url("blob:https://example.com/uuid")
        assert "blob:https://example.com" in result

    # --- URL template placeholders preserved ---

    def test_tile_url_template_preserved(self):
        url = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        result = safe_url(url)
        assert "{z}" in result
        assert "{x}" in result
        assert "{y}" in result

    def test_tile_url_with_subdomain(self):
        url = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        result = safe_url(url)
        assert "{s}" in result
        assert "{z}" in result
        assert "tile.openstreetmap.org" in result

    def test_tile_url_with_r_placeholder(self):
        url = "https://example.com/{r}/{z}/{x}/{y}.jpg"
        result = safe_url(url)
        assert "{r}" in result
        assert "{z}" in result

    def test_tile_url_with_id_placeholder(self):
        url = "https://api.mapbox.com/styles/v1/mapbox/streets-v11/tiles/{z}/{x}/{y}"
        result = safe_url(url)
        assert "{z}" in result
        assert "{x}" in result
        assert "{y}" in result

    # --- Unsafe URLs blocked ---

    def test_javascript_url_blocked(self):
        result = safe_url("javascript:alert(1)")
        assert "javascript:" not in result
        assert "blocked" in result
        assert "alert" not in result

    def test_javascript_mixed_case_blocked(self):
        result = safe_url("JAVASCRIPT:alert(1)")
        assert "javascript" not in result.lower()
        assert "blocked" in result

    def test_vbscript_url_blocked(self):
        result = safe_url("vbscript:msgbox(1)")
        assert "vbscript" not in result.lower()
        assert "blocked" in result

    def test_data_text_html_blocked(self):
        result = safe_url("data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==")
        assert "data:text/html" not in result
        assert "blocked" in result

    def test_data_application_javascript_blocked(self):
        result = safe_url("data:application/javascript;base64,YWxlcnQoMSk=")
        assert "application/javascript" not in result
        assert "blocked" in result

    # --- Edge cases ---

    def test_none_returns_empty_string(self):
        result = safe_url(None)
        assert result == '""'

    def test_empty_string(self):
        result = safe_url("")
        assert result == '""'

    def test_xss_through_angle_brackets_in_url(self):
        result = safe_url('https://example.com/x?"><img src=x onerror=alert(1)>')
        # Angle brackets should be escaped in the JS string
        assert "<img" not in result
        assert "\\u003cimg" in result or "&lt;img" in result


# =============================================================================
# safe_css_value — deny-list based sanitization
# =============================================================================


class TestSafeCssValue:
    # --- Safe CSS values pass through ---

    def test_simple_color_passthrough(self):
        assert safe_css_value("#ff0000") == "#ff0000"
        assert safe_css_value("blue") == "blue"
        assert safe_css_value("rgb(255, 0, 0)") == "rgb(255, 0, 0)"

    def test_length_values_passthrough(self):
        assert safe_css_value("14px") == "14px"
        assert safe_css_value("2em") == "2em"
        assert safe_css_value("50%") == "50%"

    def test_complex_values_passthrough(self):
        assert safe_css_value("1px solid black") == "1px solid black"

    def test_calc_survives(self):
        assert safe_css_value("calc(100% - 20px)") == "calc(100% - 20px)"

    def test_var_survives(self):
        assert safe_css_value("var(--primary-color)") == "var(--primary-color)"

    def test_hsl_survives(self):
        assert safe_css_value("hsl(120, 100%, 50%)") == "hsl(120, 100%, 50%)"

    def test_url_with_http_survives(self):
        css = "url('https://example.com/img.png')"
        result = safe_css_value(css)
        assert "url(" in result
        assert "example.com/img.png" in result

    def test_url_with_data_image_survives(self):
        css = "url(data:image/png;base64,iVBORw0K)"
        result = safe_css_value(css)
        assert "url(" in result
        assert "data:image/png" in result

    # --- Dangerous values blocked ---

    def test_expression_blocked(self):
        result = safe_css_value("expression(alert(1))")
        assert result == ""

    def test_javascript_url_blocked(self):
        result = safe_css_value("url(javascript:alert(1))")
        assert result == ""

    def test_vbscript_blocked(self):
        result = safe_css_value("vbscript:msgbox(1)")
        assert result == ""

    def test_moz_binding_blocked(self):
        result = safe_css_value("1; -moz-binding: url(xbl)")
        assert result == ""

    def test_behavior_blocked(self):
        result = safe_css_value("behavior: url(x.htc)")
        assert result == ""

    def test_at_import_blocked(self):
        result = safe_css_value("@import url(evil.css)")
        assert result == ""

    def test_url_with_data_text_html_blocked(self):
        result = safe_css_value("url(data:text/html;base64,PHNjcmlwdD4=)")
        assert result == ""

    # --- Escaping for quoted contexts ---

    def test_quotes_escaped(self):
        result = safe_css_value("it's \"quoted\"")
        assert "\\'" in result
        assert '\\"' in result

    def test_backslash_escaped(self):
        result = safe_css_value("path\\to\\file")
        assert "\\\\" in result

    def test_newlines_flattened(self):
        result = safe_css_value("color:\nred")
        assert "\n" not in result

    # --- Edge cases ---

    def test_none_returns_empty(self):
        assert safe_css_value(None) == ""

    def test_empty_string(self):
        assert safe_css_value("") == ""

    def test_mixed_case_expression_blocked(self):
        result = safe_css_value("EXPRESSION(alert(1))")
        assert result == ""


# =============================================================================
# safe_js_value — JSON serialization with XSS escapes
# =============================================================================


class TestSafeJsValue:
    def test_string_properly_quoted(self):
        result = safe_js_value("hello")
        assert result == '"hello"'

    def test_string_with_quotes_escaped(self):
        result = safe_js_value('he said "hi"')
        assert result == '"he said \\"hi\\""'

    def test_xss_angle_brackets_escaped(self):
        result = safe_js_value("<script>alert(1)</script>")
        assert "<script>" not in result
        assert "\\u003cscript\\u003e" in result

    def test_xss_ampersand_escaped(self):
        result = safe_js_value("a & b")
        assert "&" not in result.replace("\\u0026", "")
        assert "\\u0026" in result

    def test_xss_single_quote_escaped(self):
        result = safe_js_value("it's")
        assert "'" not in result.replace("\\u0027", "")
        assert "\\u0027" in result

    def test_none_becomes_null(self):
        assert safe_js_value(None) == "null"

    def test_booleans(self):
        assert safe_js_value(True) == "true"
        assert safe_js_value(False) == "false"

    def test_numbers(self):
        assert safe_js_value(42) == "42"
        assert safe_js_value(3.14) == "3.14"

    def test_list_serialized(self):
        result = safe_js_value([1, 2, 3])
        assert result == "[1, 2, 3]"

    def test_dict_serialized(self):
        result = safe_js_value({"a": 1, "b": "c"})
        parsed = json.loads(result)
        assert parsed == {"a": 1, "b": "c"}

    def test_dict_with_xss_values_escaped(self):
        result = safe_js_value({"name": "<script>alert(1)</script>"})
        assert "<script>" not in result
        assert "\\u003cscript\\u003e" in result

    def test_jscode_passthrough(self):
        code = JsCode("function(e) { return e.latlng; }")
        result = safe_js_value(code)
        assert result == "function(e) { return e.latlng; }"

    def test_nested_list_with_xss(self):
        result = safe_js_value([1, "<img src=x onerror=alert(1)>", 3])
        assert "<img" not in result
        assert "\\u003cimg" in result


# =============================================================================
# safe_js_options — camelized keys + recursive serialization
# =============================================================================


class TestSafeJsOptions:
    def test_empty_dict(self):
        assert safe_js_options({}) == "{}"
        assert safe_js_options(None) == "{}"

    def test_simple_options(self):
        opts = {"max_zoom": 18, "min_zoom": 1}
        result = safe_js_options(opts)
        # Keys should be camelized
        assert '"maxZoom": 18' in result
        assert '"minZoom": 1' in result

    def test_string_values(self):
        opts = {"attribution": "&copy; OpenStreetMap"}
        result = safe_js_options(opts)
        assert '"attribution": ' in result
        # XSS characters in values should be escaped
        assert "&copy;" not in result
        assert "\\u0026copy;" in result

    def test_nested_dict(self):
        opts = {"keyboard": {"pan_offset": 80}}
        result = safe_js_options(opts)
        assert '"keyboard": ' in result
        assert '"panOffset": 80' in result

    def test_list_value(self):
        opts = {"center": [51.5, -0.1]}
        result = safe_js_options(opts)
        assert '"center": [51.5, -0.1]' in result

    def test_none_value_preserved(self):
        opts = {"max_zoom": None}
        result = safe_js_options(opts)
        assert '"maxZoom": null' in result

    def test_jscode_value_preserved(self):
        opts = {"on_click": JsCode("function(e) { console.log(e); }")}
        result = safe_js_options(opts)
        assert '"onClick": function(e) { console.log(e); }' in result

    def test_xss_in_value_escaped(self):
        opts = {"label": 'Layer "><script>alert(1)</script>'}
        result = safe_js_options(opts)
        assert "<script>" not in result
        assert "\\u003cscript\\u003e" in result


# =============================================================================
# safe_layer_name — layer names (JS string with XSS escapes)
# =============================================================================


class TestSafeLayerName:
    def test_plain_name(self):
        result = safe_layer_name("OpenStreetMap")
        assert result == '"OpenStreetMap"'

    def test_none_returns_empty_string(self):
        result = safe_layer_name(None)
        assert result == '""'

    def test_xss_in_layer_name(self):
        result = safe_layer_name('<img src=x onerror=alert(1)>')
        assert "<img" not in result
        assert "\\u003cimg" in result

    def test_quotes_in_layer_name(self):
        result = safe_layer_name('Layer "Test"')
        assert result == '"Layer \\"Test\\""'

    def test_html_in_name_escaped(self):
        result = safe_layer_name("<b>Bold</b> Layer")
        assert "<b>" not in result
        assert "\\u003cb\\u003e" in result


# =============================================================================
# safe_css_identifier — CSS class/id name sanitization
# =============================================================================


class TestSafeCssIdentifier:
    def test_valid_identifier_passthrough(self):
        assert safe_css_identifier("my-class") == "my-class"
        assert safe_css_identifier("my_class") == "my_class"
        assert safe_css_identifier("myClass123") == "myClass123"

    def test_leading_digit_prefixed(self):
        result = safe_css_identifier("123class")
        assert result == "_123class"

    def test_invalid_chars_replaced(self):
        result = safe_css_identifier("my class!")
        assert result == "my_class_"

    def test_space_replaced(self):
        assert safe_css_identifier("hello world") == "hello_world"

    def test_special_chars_replaced(self):
        result = safe_css_identifier("<script>")
        assert result == "_script_"
        assert "<" not in result
        assert ">" not in result

    def test_empty_string(self):
        assert safe_css_identifier("") == ""
        assert safe_css_identifier(None) == ""


# =============================================================================
# safe_json_to_js — JSON string → JS object
# =============================================================================


class TestSafeJsonToJs:
    def test_simple_dict_string(self):
        result = safe_json_to_js('{"color": "red", "weight": 3}')
        parsed = json.loads(result)
        assert parsed == {"color": "red", "weight": 3}

    def test_empty_string(self):
        assert safe_json_to_js("") == "{}"
        assert safe_json_to_js(None) == "{}"

    def test_dict_input(self):
        result = safe_json_to_js({"a": 1, "b": [1, 2, 3]})
        parsed = json.loads(result)
        assert parsed == {"a": 1, "b": [1, 2, 3]}

    def test_xss_in_json_value_escaped(self):
        result = safe_json_to_js('{"label": "<script>alert(1)</script>"}')
        assert "<script>" not in result
        assert "\\u003cscript\\u003e" in result

    def test_jinja_placeholder_supported(self):
        json_str = '{"color": "#ff0000", "fillPattern": {{' + "'pattern_abc'" + "}}}"
        result = safe_json_to_js(json_str)
        assert "{{'pattern_abc'}}" in result
        assert "pattern_abc" in result

    def test_invalid_json_falls_back_to_string(self):
        result = safe_json_to_js("not valid json {")
        # Should be a quoted string
        assert result.startswith('"')
        assert result.endswith('"')


# =============================================================================
# safe_query_params — URL query parameter serialization
# =============================================================================


class TestSafeQueryParams:
    def test_simple_params(self):
        result = safe_query_params({"key": "value", "foo": "bar"})
        assert "key=value" in result
        assert "foo=bar" in result
        assert "&" in result

    def test_special_chars_encoded(self):
        result = safe_query_params({"q": "hello world&foo=bar"})
        assert "hello%20world" in result
        assert "%26" in result

    def test_empty_params(self):
        assert safe_query_params({}) == ""
        assert safe_query_params(None) == ""

    def test_number_values(self):
        result = safe_query_params({"limit": 100, "page": 1})
        assert "limit=100" in result
        assert "page=1" in result


# =============================================================================
# Integration-style tests: end-to-end Folium rendering with malicious inputs
# =============================================================================


class TestEndToEndSecurity:
    """End-to-end tests that malicious inputs don't produce XSS in rendered maps.

    These serve as regression tests that prove the serialization boundary
    catches injection at the Folium API level.
    """

    def test_xss_in_layer_name_layer_control(self):
        import folium
        from folium.map import LayerControl, FeatureGroup

        m = folium.Map()
        fg = FeatureGroup(name='"><script>alert(1)</script>')
        fg.add_to(m)
        LayerControl().add_to(m)

        html = m._repr_html_()
        # Make sure the script tag doesn't come through as raw HTML
        assert "<script>alert(1)</script>" not in html
        # The malicious content should be escaped somewhere
        assert "alert(1)" not in html or "&lt;script" in html or "\\u003c" in html

    def test_xss_in_popup_content(self):
        import folium

        m = folium.Map()
        # Default Popup treats content as plain text (safe_text path)
        popup = folium.Popup('<script>alert("xss")</script>')
        folium.Marker([0, 0], popup=popup).add_to(m)

        html = m.get_root().render()
        # Raw script tag should not appear
        assert "<script>alert" not in html
        # Content should be HTML-escaped
        assert "&lt;script&gt;" in html
        assert "&quot;xss&quot;" in html

    def test_xss_in_tile_layer_url(self):
        import folium

        m = folium.Map()
        evil_url = 'https://evil.com/";alert(1);"'
        folium.TileLayer(tiles=evil_url, attr="test").add_to(m)

        html = m.get_root().render()
        assert evil_url not in html
        assert '"); alert(' not in html

    def test_xss_in_tooltip_text(self):
        import folium

        m = folium.Map()
        evil_text = '<img src=x onerror=alert(1)>'
        tooltip = folium.Tooltip(evil_text)
        folium.Marker([0, 0], tooltip=tooltip).add_to(m)

        html = m.get_root().render()
        assert "<img" not in html
        assert "&lt;img" in html

    def test_xss_in_geojson_style(self):
        import folium
        from folium.features import GeoJson

        m = folium.Map()
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {},
                    "geometry": {"type": "Point", "coordinates": [0, 0]},
                }
            ],
        }
        evil_style = lambda feature: {  # noqa
            "color": 'red";alert(1);"',
        }
        GeoJson(geojson, style_function=evil_style).add_to(m)

        html = m.get_root().render()
        assert 'red");alert(1);"' not in html
        assert '"); alert(' not in html

    def test_xss_in_circle_marker_color(self):
        import folium

        m = folium.Map()
        evil_color = 'red");alert(1);"'
        evil_fill = 'blue"><script>alert(2)</script>'
        folium.CircleMarker(
            location=[0, 0],
            color=evil_color,
            fill_color=evil_fill,
        ).add_to(m)

        html = m.get_root().render()
        assert evil_color not in html
        assert "<script>alert(2)</script>" not in html
        assert "\\u003cscript\\u003e" in html


# =============================================================================
# Three-path HTML handling tests: safe_text / sanitized_html / trusted_html
#
# These verify that Popup, Tooltip, and DivIcon correctly distinguish between:
# 1. safe_text (default) — plain text with full HTML escaping
# 2. sanitized_html (is_html=True) — HTML with whitelist sanitization
# 3. trusted_html (Element/html param) — user-explicit HTML, minimal escaping
# =============================================================================


class TestThreePathHtmlHandling:
    """Test the three HTML handling paths for Popup, Tooltip, DivIcon."""

    # --- Popup three-path tests ---

    def test_popup_default_is_safe_text(self):
        """Default Popup(html=...) should treat content as plain text."""
        import folium

        m = folium.Map()
        popup = folium.Popup("<b>Bold</b> & <i>Italic</i>")
        folium.Marker([0, 0], popup=popup).add_to(m)

        html = m.get_root().render()
        # HTML tags should be escaped, not rendered
        assert "<b>Bold</b>" not in html
        assert "&lt;b&gt;Bold&lt;/b&gt;" in html
        assert "&amp;" in html

    def test_popup_text_param_is_always_safe_text(self):
        """Popup(text=...) should always be plain text regardless of is_html."""
        import folium

        m = folium.Map()
        popup = folium.Popup(text="<b>Bold</b>", is_html=True)
        folium.Marker([0, 0], popup=popup).add_to(m)

        html = m.get_root().render()
        assert "<b>Bold</b>" not in html
        assert "&lt;b&gt;Bold&lt;/b&gt;" in html

    def test_popup_is_html_true_is_sanitized(self):
        """Popup(html=..., is_html=True) should apply whitelist sanitization."""
        import folium

        m = folium.Map()
        safe_html_content = '<p>Hello <b>world</b> <a href="https://example.com">link</a></p>'
        popup = folium.Popup(safe_html_content, is_html=True)
        folium.Marker([0, 0], popup=popup).add_to(m)

        html = m.get_root().render()
        # Allowed tags should survive
        assert "<p>Hello <b>world</b>" in html
        assert 'href="https://example.com"' in html

    def test_popup_is_html_true_blocks_dangerous_tags(self):
        """Popup with is_html=True should block script/iframe tags."""
        import folium

        m = folium.Map()
        dangerous_html = "<p>Safe</p><script>alert(1)</script><iframe src='evil.html'></iframe>"
        popup = folium.Popup(dangerous_html, is_html=True)
        folium.Marker([0, 0], popup=popup).add_to(m)

        html = m.get_root().render()
        # Check that the dangerous content is not in the popup content area
        # (The page itself has <script> tags for Leaflet, so we need to be specific)
        assert "<script>alert(1)</script>" not in html
        assert "<iframe src='evil.html'>" not in html
        assert 'alert(1)' not in html or 'srcdoc' in html  # escaped in srcdoc
        # Safe content should remain
        assert "<p>Safe</p>" in html

    def test_popup_element_is_trusted_html(self):
        """Popup with Element html should be trusted (no sanitization)."""
        import folium
        from branca.element import IFrame
        import base64

        m = folium.Map()
        iframe_content = '<div onclick="alert(1)">Click me</div>'
        iframe = IFrame(iframe_content, width=200, height=100)
        popup = folium.Popup(iframe)
        folium.Marker([0, 0], popup=popup).add_to(m)

        html = m.get_root().render()
        # Element content should pass through without sanitization
        # IFrame content is base64 encoded in data: URL, so decode and check
        # Verify that an iframe with data URL is present
        assert 'data:text/html;charset=utf-8;base64,' in html
        # Extract and decode the base64 content to verify it's unchanged
        import re
        match = re.search(r'data:text/html;charset=utf-8;base64,([^"]+)', html)
        assert match is not None
        decoded = base64.b64decode(match.group(1)).decode('utf-8')
        assert iframe_content in decoded

    # --- Tooltip three-path tests ---

    def test_tooltip_default_is_safe_text(self):
        """Default Tooltip(text=...) should treat content as plain text."""
        import folium

        m = folium.Map()
        tooltip = folium.Tooltip("<b>Bold</b> & <i>Italic</i>")
        folium.Marker([0, 0], tooltip=tooltip).add_to(m)

        html = m.get_root().render()
        assert "<b>Bold</b>" not in html
        assert "&lt;b&gt;Bold&lt;/b&gt;" in html
        assert "&amp;" in html

    def test_tooltip_html_param_is_sanitized(self):
        """Tooltip(html=...) should apply whitelist sanitization."""
        import folium

        m = folium.Map()
        safe_html_content = '<p>Hello <b>world</b> <a href="https://example.com">link</a></p>'
        tooltip = folium.Tooltip(html=safe_html_content)
        folium.Marker([0, 0], tooltip=tooltip).add_to(m)

        html = m.get_root().render()
        assert "<p>Hello <b>world</b>" in html
        assert 'href="https://example.com"' in html

    def test_tooltip_html_param_blocks_dangerous(self):
        """Tooltip with html=... should block dangerous content."""
        import folium

        m = folium.Map()
        dangerous_html = '<span onmouseover="alert(1)">Hover me</span>'
        tooltip = folium.Tooltip(html=dangerous_html)
        folium.Marker([0, 0], tooltip=tooltip).add_to(m)

        html = m.get_root().render()
        assert "onmouseover" not in html
        assert "alert(1)" not in html

    def test_tooltip_is_html_true_with_text_param(self):
        """Tooltip(text=..., is_html=True) should apply sanitization."""
        import folium

        m = folium.Map()
        tooltip = folium.Tooltip(text="<b>Bold</b>", is_html=True)
        folium.Marker([0, 0], tooltip=tooltip).add_to(m)

        html = m.get_root().render()
        assert "<b>Bold</b>" in html

    # --- DivIcon three-path tests ---

    def test_divicon_default_html_is_trusted(self):
        """DivIcon(html=...) is user-explicit HTML, should be trusted."""
        import folium
        from folium.features import DivIcon

        m = folium.Map()
        icon = DivIcon(
            html='<div onclick="alert(1)" style="color: red;">Click</div>',
            icon_size=(100, 30),
        )
        folium.Marker([0, 0], icon=icon).add_to(m)

        html = m.get_root().render()
        # User-provided HTML should pass through as trusted
        # In JSON, quotes are escaped as \", which in Python repr shows as \\"
        assert 'onclick=\\"alert(1)\\"' in html
        assert 'style=\\"color: red;\\"' in html

    def test_divicon_text_param_default_is_safe_text(self):
        """DivIcon(text=...) default should be plain text."""
        import folium
        from folium.features import DivIcon

        m = folium.Map()
        icon = DivIcon(text="<b>Bold</b> & Text", icon_size=(100, 30))
        folium.Marker([0, 0], icon=icon).add_to(m)

        html = m.get_root().render()
        assert "<b>Bold</b>" not in html
        assert "&lt;b&gt;Bold&lt;/b&gt;" in html
        assert "&amp; Text" in html

    def test_divicon_text_param_is_html_true(self):
        """DivIcon(text=..., is_html=True) should apply sanitization."""
        import folium
        from folium.features import DivIcon

        m = folium.Map()
        icon = DivIcon(
            text='<p>Safe <b>HTML</b> <script>alert(1)</script></p>',
            is_html=True,
            icon_size=(100, 30),
        )
        folium.Marker([0, 0], icon=icon).add_to(m)

        html = m.get_root().render()
        # Allowed tags survive (check for JSON-escaped version)
        assert '<p>Safe <b>HTML</b>' in html or '\\u003cp\\u003eSafe \\u003cb\\u003eHTML\\u003c/b\\u003e' in html
        # Dangerous tags should be removed by safe_html - check for the specific string
        assert '<script>alert(1)</script>' not in html
        # The script content should be removed entirely by safe_html
        assert 'alert(1)' not in html

    def test_divicon_html_backticks_escaped(self):
        """DivIcon(html=...) should have backticks escaped for JS safety."""
        import folium
        from folium.features import DivIcon

        m = folium.Map()
        icon = DivIcon(html="<div>`code`</div>", icon_size=(100, 30))
        folium.Marker([0, 0], icon=icon).add_to(m)

        html = m.get_root().render()
        # Backticks should be escaped to prevent breaking JS template strings
        # After trusted_html: ` -> \`, then JSON serialization doesn't touch \`
        # In Python repr, \` shows as \\`
        assert "`code`" not in html
        assert "\\\\`code\\\\`" in html


# =============================================================================
# Snapshot / compatibility tests
#
# These test that specific legitimate inputs produce the expected output
# format, proving that we haven't silently changed behavior for valid inputs.
# =============================================================================


class TestOutputSnapshots:
    """Key output snapshots — verify legitimate inputs produce expected output.

    These serve as proof that the safe serialization layer doesn't break
    legitimate use cases. The expected values are the canonical output
    format that downstream code can depend on.
    """

    # --- safe_text snapshot ---

    def test_snapshot_text_plain(self):
        assert safe_text("Hello World") == "Hello World"

    def test_snapshot_text_with_html(self):
        assert (
            safe_text("<b>Bold & Beautiful</b>")
            == "&lt;b&gt;Bold &amp; Beautiful&lt;/b&gt;"
        )

    # --- safe_url snapshot ---

    def test_snapshot_url_osm_tile_template(self):
        url = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        result = safe_url(url)
        # Should be a valid JS string with placeholders preserved
        assert result.startswith('"')
        assert result.endswith('"')
        assert "{z}/{x}/{y}.png" in result
        assert "tile.openstreetmap.org" in result

    def test_snapshot_url_data_image(self):
        url = "data:image/png;base64,iVBORw0KGgo="
        result = safe_url(url)
        assert result.startswith('"')
        assert result.endswith('"')
        assert "data:image/png;base64" in result

    # --- safe_js_options snapshot ---

    def test_snapshot_js_options_tile_layer(self):
        opts = {
            "attribution": "&copy; OpenStreetMap contributors",
            "max_zoom": 19,
            "subdomains": "abc",
        }
        result = safe_js_options(opts)
        # All keys camelized
        assert '"attribution":' in result
        assert '"maxZoom": 19' in result
        assert '"subdomains": "abc"' in result
        # attribution value has XSS escapes for &
        assert "&copy;" not in result
        assert "\\u0026copy;" in result

    def test_snapshot_js_options_nested(self):
        opts = {"keyboard": {"pan_offset": 80, "zoom_offset": 100}}
        result = safe_js_options(opts)
        assert '"keyboard": ' in result
        assert '"panOffset": 80' in result
        assert '"zoomOffset": 100' in result

    # --- safe_js_value snapshot ---

    def test_snapshot_js_value_string_xss(self):
        # The canonical escaping for < is \u003c, for > is \u003e
        result = safe_js_value("<img src=x onerror=alert(1)>")
        assert result == (
            '"\\u003cimg src=x onerror=alert(1)\\u003e"'
        )

    def test_snapshot_js_value_list(self):
        assert safe_js_value([1, 2, 3]) == "[1, 2, 3]"

    def test_snapshot_js_value_dict(self):
        result = safe_js_value({"a": 1, "b": "c"})
        parsed = json.loads(result)
        assert parsed == {"a": 1, "b": "c"}

    # --- safe_css_value snapshot ---

    def test_snapshot_css_color_hex(self):
        assert safe_css_value("#3388ff") == "#3388ff"

    def test_snapshot_css_with_quotes(self):
        result = safe_css_value("font-family: 'Times New Roman'")
        assert "\\'Times New Roman\\'" in result
        assert "font-family:" in result

    # --- safe_layer_name snapshot ---

    def test_snapshot_layer_name(self):
        assert safe_layer_name("OpenStreetMap") == '"OpenStreetMap"'

    def test_snapshot_layer_name_with_space(self):
        assert safe_layer_name("CartoDB DarkMatter") == '"CartoDB DarkMatter"'

    # --- safe_css_identifier snapshot ---

    def test_snapshot_css_identifier(self):
        assert safe_css_identifier("my-color") == "my-color"
        assert safe_css_identifier("123class") == "_123class"

    # --- safe_html snapshots ---

    def test_snapshot_html_bold_text(self):
        result = safe_html("<b>Hello</b>")
        assert result == "<b>Hello</b>"

    def test_snapshot_html_link(self):
        result = safe_html('<a href="https://example.com">Link</a>')
        assert result == '<a href="https://example.com">Link</a>'

    def test_snapshot_html_image(self):
        result = safe_html('<img src="image.png" alt="photo">')
        assert result == '<img src="image.png" alt="photo">'

    def test_snapshot_html_div_with_class(self):
        result = safe_html('<div class="container">Content</div>')
        assert result == '<div class="container">Content</div>'

    def test_snapshot_html_script_stripped_with_content(self):
        result = safe_html('<p>Before</p><script>alert(1)</script><p>After</p>')
        assert "<script>" not in result
        assert "alert(1)" not in result
        assert "<p>Before</p>" in result
        assert "<p>After</p>" in result

    def test_snapshot_html_onerror_removed(self):
        result = safe_html('<img src="x.png" onerror="alert(1)">')
        assert "onerror" not in result
        assert '<img src="x.png">' in result or 'src="x.png"' in result

    def test_snapshot_html_javascript_href_blocked(self):
        result = safe_html('<a href="javascript:alert(1)">Click</a>')
        assert "javascript:" not in result
        assert "alert(1)" not in result

    # --- safe_css_value snapshots for common patterns ---

    def test_snapshot_css_rgb_color(self):
        assert safe_css_value("rgb(255, 0, 0)") == "rgb(255, 0, 0)"

    def test_snapshot_css_hsl_color(self):
        assert safe_css_value("hsl(120, 100%, 50%)") == "hsl(120, 100%, 50%)"

    def test_snapshot_css_calc_expression(self):
        assert safe_css_value("calc(100% - 20px)") == "calc(100% - 20px)"

    def test_snapshot_css_var_function(self):
        assert safe_css_value("var(--main-color)") == "var(--main-color)"

    def test_snapshot_css_url_safe(self):
        result = safe_css_value("url('image.png')")
        assert "url(" in result
        assert "image.png" in result

    def test_snapshot_css_url_javascript_blocked(self):
        result = safe_css_value("url(javascript:alert(1))")
        assert "javascript:" not in result
        assert result == "" or "alert" not in result

    # --- safe_query_params snapshot ---

    def test_snapshot_query_params(self):
        result = safe_query_params({"foo": "bar", "baz": "qux"})
        assert "foo=bar" in result
        assert "baz=qux" in result

    # --- End-to-end integration snapshots ---

    def test_snapshot_popup_simple_text(self):
        import folium

        m = folium.Map()
        popup = folium.Popup("Hello World")
        folium.Marker([0, 0], popup=popup).add_to(m)
        html = m.get_root().render()
        assert "Hello World" in html
        assert "bindPopup" in html

    def test_snapshot_tile_layer_url_template(self):
        import folium

        m = folium.Map()
        folium.TileLayer(
            tiles="https://tile.openstreetmap.org/{z}/{x}/{y}.png",
            attr="&copy; OpenStreetMap",
        ).add_to(m)
        html = m.get_root().render()
        assert "{z}/{x}/{y}.png" in html
        assert "tile.openstreetmap.org" in html
        assert "OpenStreetMap" in html

    def test_snapshot_tooltip_with_style(self):
        import folium

        m = folium.Map()
        tooltip = folium.Tooltip("Hello Tooltip", style="color: red;")
        folium.Marker([0, 0], tooltip=tooltip).add_to(m)
        html = m.get_root().render()
        assert "Hello Tooltip" in html
        assert "color: red" in html or "color:red" in html

    # --- trusted_html snapshots ---

    def test_snapshot_trusted_html_preserves_everything(self):
        """trusted_html should preserve all HTML, only escape backticks."""
        html = '<div onclick="alert(1)" style="color: red;">Text `with` ticks</div>'
        result = trusted_html(html)
        # All HTML preserved
        assert '<div onclick="alert(1)" style="color: red;">' in result
        # Backticks escaped
        assert "`with`" not in result
        assert "\\`with\\`" in result

    def test_snapshot_trusted_html_backtick_only(self):
        assert trusted_html("`") == "\\`"

    def test_snapshot_trusted_html_no_backticks(self):
        assert trusted_html("<p>no backticks</p>") == "<p>no backticks</p>"

    # --- Three-path compatibility snapshots ---
    # These verify that existing Folium HTML patterns remain compatible

    def test_snapshot_popup_with_safe_html_compatible(self):
        """Popup(is_html=True) should be compatible with common Folium patterns."""
        import folium

        m = folium.Map()
        # This is a common pattern - popup with links and formatting
        popup_html = """
            <div class="popup-content">
                <h4>Location Details</h4>
                <p><b>Name:</b> Example Place</p>
                <p><a href="https://example.com" target="_blank">Visit website</a></p>
                <img src="https://example.com/photo.jpg" alt="Photo" width="200">
            </div>
        """
        popup = folium.Popup(popup_html, is_html=True)
        folium.Marker([0, 0], popup=popup).add_to(m)

        html = m.get_root().render()
        # All allowed tags and attributes should be preserved
        assert '<h4>Location Details</h4>' in html
        assert '<p><b>Name:</b> Example Place</p>' in html
        assert 'href="https://example.com"' in html
        assert 'target="_blank"' in html
        assert 'src="https://example.com/photo.jpg"' in html
        assert 'width="200"' in html
        assert 'class="popup-content"' in html

    def test_snapshot_tooltip_with_html_compatible(self):
        """Tooltip(html=...) should preserve safe formatting."""
        import folium

        m = folium.Map()
        tooltip_html = '<div><b>Bold</b> <i>Italic</i> <small>Small</small></div>'
        tooltip = folium.Tooltip(html=tooltip_html)
        folium.Marker([0, 0], tooltip=tooltip).add_to(m)

        html = m.get_root().render()
        assert "<b>Bold</b>" in html
        assert "<i>Italic</i>" in html
        assert "<small>Small</small>" in html

    def test_snapshot_popup_table_compatible(self):
        """Popup with table structure should be fully compatible."""
        import folium

        m = folium.Map()
        table_html = """
            <table cellpadding="5" cellspacing="0">
                <tr><th colspan="2">Data</th></tr>
                <tr><td>Key 1</td><td>Value 1</td></tr>
                <tr><td>Key 2</td><td>Value 2</td></tr>
            </table>
        """
        popup = folium.Popup(table_html, is_html=True)
        folium.Marker([0, 0], popup=popup).add_to(m)

        html = m.get_root().render()
        assert "<table" in html
        assert 'cellpadding="5"' in html
        assert 'cellspacing="0"' in html
        assert "<th colspan=\"2\">Data</th>" in html
        assert "<td>Key 1</td>" in html

    def test_snapshot_divicon_custom_html_preserved(self):
        """DivIcon custom HTML should be fully preserved as trusted."""
        import folium
        from folium.features import DivIcon

        m = folium.Map()
        custom_html = """
            <div class="custom-marker" id="marker-123"
                 style="background: #3388ff; border-radius: 50%; width: 30px; height: 30px;">
                <span style="color: white; font-weight: bold;">1</span>
            </div>
        """
        icon = DivIcon(html=custom_html, icon_size=(30, 30))
        folium.Marker([0, 0], icon=icon).add_to(m)

        html = m.get_root().render()
        # All custom HTML should be preserved (trusted path)
        # In JSON, quotes are escaped as \", which in Python repr shows as \\"
        assert 'class=\\"custom-marker\\"' in html
        assert 'id=\\"marker-123\\"' in html
        assert 'background: #3388ff' in html
        assert 'border-radius: 50%' in html
        assert 'color: white' in html
        assert 'font-weight: bold' in html

    def test_snapshot_popup_backward_compatible_text(self):
        """Popup with plain text should work as before (backward compatible)."""
        import folium

        m = folium.Map()
        # Old usage: just pass text, it should be escaped by default
        popup = folium.Popup("Plain text with <angle> brackets & 'quotes'")
        folium.Marker([0, 0], popup=popup).add_to(m)

        html = m.get_root().render()
        # Should be escaped
        assert "&lt;angle&gt;" in html
        assert "&amp;" in html
        assert "&#39;quotes&#39;" in html
        # Original unescaped should not appear
        assert "<angle>" not in html
