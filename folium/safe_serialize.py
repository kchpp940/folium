"""
Safe serialization helpers for Folium.

This module provides a unified security boundary for serializing user input
into JavaScript/HTML contexts. Each function is specialized for a specific
output context with a clearly defined allow/escape strategy.

Strategy Summary
================

text → HTML context (safe_text)
  Escape strategy: Full HTML entity encoding
  Escapes: & &amp;   < &lt;   > &gt;   " &quot;   ' &#39;
  Use for: Layer names, labels, captions, any plain text

html → HTML context (safe_html)
  Allow strategy: Whitelist of tags + whitelist of attributes per tag
  Allowed tags: a, b, blockquote, br, caption, code, col, colgroup, dd, div,
                dl, dt, em, h1, h2, h3, h4, h5, h6, hr, i, img, li, ol, p,
                pre, span, strong, table, tbody, td, tfoot, th, thead, tr,
                ul, small, sub, sup
  Allowed attrs: class, id, style, title, alt, src, href, target, rel,
                 width, height, rowspan, colspan, cellpadding, cellspacing
  URL attrs (href/src): additionally validated via safe_url_validate
  style attrs: additionally validated via safe_css_value
  Blocked: <script>, <iframe>, <object>, <embed>, on* handlers, javascript: URLs,
           data:text/html, expression(), etc.
  Use for: Popup content, tooltip content where HTML is intended

url → JS string / HTML attribute (safe_url)
  Allow strategy: Scheme whitelist + URL template placeholder support
  Allowed schemes: http, https, ftp, ftps, mailto, data (image/ only), blob
  URL templates: Placeholders like {z}, {x}, {y}, {s}, {r}, {id} are preserved
                 as-is (common in tile URLs). The non-placeholder portion is
                 validated for scheme safety.
  Output: JavaScript string literal with XSS-prevention escapes
  Use for: Tile URLs, image URLs, attribution links, icon URLs

css_value → HTML style / JS string (safe_css_value)
  Block strategy: Deny known-dangerous patterns, pass everything else through
  Blocked: expression(), javascript:, vbscript:, eval(), moz-binding, behavior,
           url() with non-image protocols, data:text/html
  Note: We do NOT try to validate CSS value grammar. Instead we block known
        dangerous constructs and otherwise pass values through. This avoids
        false positives on legitimate CSS values.
  Output: The value with quote/backslash escapes applied for use in quoted strings
  Use for: Inline style values, CSS property values

js_value → JS context (safe_js_value)
  Strategy: JSON serialization with XSS-prevention escapes
  - None → null, bool → true/false, numbers → as-is
  - Strings → JSON string with <, >, &, ' escaped as \\uXXXX
  - Dicts/lists → compact JSON with XSS escapes
  - JsCode instances → passed through verbatim
  Use for: Data values, config values, JSON-like structures

js_options → JS context (safe_js_options)
  Strategy: Dict → JS object literal, with camelCased keys
  - Keys are camelized (Python snake_case → JS camelCase)
  - Values are recursively serialized via safe_js_value
  - JsCode values are preserved as-is (for callbacks/expressions)
  - Output: compact "key": value format
  Use for: Leaflet options objects, plugin configuration

layer_name → JS string + HTML label (safe_layer_name)
  Strategy: Same as safe_js_value (JSON string with XSS escapes)
  Use for: LayerControl base layer names and overlay names

css_identifier → CSS context (safe_css_identifier)
  Allow strategy: Only characters valid in CSS identifiers
  Allowed: a-z, A-Z, 0-9, _, - (hyphen)
  Everything else replaced with _
  Leading digit → prefixed with _
  Use for: Generated class names, id attributes
"""

import json
import re
from html.parser import HTMLParser
from typing import Any, Union
from urllib.parse import urlparse, quote

from folium.utilities import JsCode, camelize


# =============================================================================
# Configuration constants
# =============================================================================

_SAFE_URL_SCHEMES = {"http", "https", "ftp", "ftps", "mailto", "data", "blob"}

_SAFE_DATA_URL_PREFIXES = (
    "data:image/",
    "data:application/json",
)

_SAFE_DATA_PATH_PREFIXES = (
    "image/",
    "application/json",
)

# HTML tag whitelist
_SAFE_HTML_TAGS = {
    "a", "b", "blockquote", "br", "caption", "code", "col", "colgroup",
    "dd", "div", "dl", "dt", "em", "h1", "h2", "h3", "h4", "h5", "h6",
    "hr", "i", "img", "li", "ol", "p", "pre", "span", "strong", "table",
    "tbody", "td", "tfoot", "th", "thead", "tr", "ul", "small", "sub",
    "sup",
}

# HTML attribute whitelist (global + per-tag)
_SAFE_HTML_ATTRS_GLOBAL = {"class", "id", "style", "title"}

_SAFE_HTML_ATTRS_BY_TAG = {
    "a": {"href", "target", "rel"},
    "img": {"src", "alt", "width", "height"},
    "td": {"rowspan", "colspan"},
    "th": {"rowspan", "colspan"},
    "table": {"cellpadding", "cellspacing", "width", "border"},
    "col": {"span", "width"},
    "colgroup": {"span", "width"},
}

# Attributes that contain URLs (require extra validation)
_URL_ATTRS = {"href", "src"}

# URL template placeholder pattern: {identifier}
_URL_TEMPLATE_PLACEHOLDER_RE = re.compile(r"\{[a-zA-Z_][a-zA-Z0-9_\-]*\}")

# Dangerous CSS patterns - these are always blocked
_DANGEROUS_CSS_PATTERNS = re.compile(
    r"expression\s*\(|"
    r"javascript\s*:|"
    r"vbscript\s*:|"
    r"eval\s*\(|"
    r"moz-binding\s*:|"
    r"behavior\s*:|"
    r"@import",
    re.IGNORECASE,
)

# Detect url() in CSS to validate the inner URL
_CSS_URL_RE = re.compile(r"url\s*\(\s*(['\"]?)(.*?)\1\s*\)", re.IGNORECASE)

# Regex to match a valid-ish CSS identifier
_CSS_IDENT_RE = re.compile(r"^-?[a-zA-Z_][a-zA-Z0-9_\-]*$")


# =============================================================================
# Internal helpers
# =============================================================================

def _escape_html(text: str) -> str:
    """Escape text for safe inclusion in HTML context (as text content)."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _escape_html_attr(text: str) -> str:
    """Escape text for safe inclusion in a double-quoted HTML attribute."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _escape_js_string(text: str) -> str:
    """Escape text as a JavaScript string literal with XSS-prevention escapes.

    The result is a properly quoted JSON string (including the quotes), with
    <, >, &, ' escaped to \\uXXXX to prevent XSS via closing script tags etc.
    """
    return (
        json.dumps(text)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("'", "\\u0027")
    )


def _escape_js_string_for_html(text: str) -> str:
    """Escape pre-processed HTML content as a JavaScript string literal.

    For HTML content that has already been sanitized/escaped at the HTML level
    (via safe_text, safe_html, or trusted_html), we only need to do JS string
    escaping (quotes, backslashes, newlines) without additional XSS escapes
    for <, >, &, '. The HTML-level processing has already handled security.

    The result is a properly quoted JSON string (including the quotes).
    """
    return json.dumps(text)


def _to_escaped_json(obj: Any) -> str:
    """JSON serialization with XSS-prevention escapes applied."""
    return (
        json.dumps(obj)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("'", "\\u0027")
    )


def _safe_url_validate(url: str) -> tuple[bool, str]:
    """Validate a URL for safety.

    Returns (is_safe, reason_or_url).
    Preserves URL template placeholders like {z}/{x}/{y}/{s} by temporarily
    replacing them, validating the structural part, then restoring them.
    """
    if not url:
        return False, "empty"

    # Step 1: Extract and remove URL template placeholders
    placeholders: list[str] = []

    def _placeholder_replacer(match: re.Match[str]) -> str:
        idx = len(placeholders)
        placeholders.append(match.group(0))
        return f"__TPL_{idx}__"

    url_for_validation = _URL_TEMPLATE_PLACEHOLDER_RE.sub(
        _placeholder_replacer, url
    )

    # Step 2: Parse and validate the scheme
    try:
        parsed = urlparse(url_for_validation)
    except Exception:
        return False, "parse error"

    # No scheme: relative URL - safe
    if parsed.scheme:
        scheme = parsed.scheme.lower()
        if scheme not in _SAFE_URL_SCHEMES:
            return False, f"unsafe scheme: {scheme}"

        if scheme == "data":
            # data: URLs - only allow image/ and application/json
            rest = parsed.path
            if not any(
                rest.lower().startswith(prefix)
                for prefix in _SAFE_DATA_PATH_PREFIXES
            ):
                return False, "unsafe data URL"

    # Step 3: Restore placeholders (for output)
    result = url_for_validation
    for idx, ph in enumerate(placeholders):
        result = result.replace(f"__TPL_{idx}__", ph)

    return True, result


# =============================================================================
# HTML sanitizer using a whitelist approach
# =============================================================================

_TAGS_TO_STRIP_CONTENT = {
    "script", "style", "iframe", "object", "embed", "noembed",
    "noscript", "noframes", "frame", "frameset",
}


class _SafeHtmlParser(HTMLParser):
    """HTML parser that sanitizes using tag + attribute whitelists.

    Strategy: parse HTML, drop tags/attrs not on the whitelist, re-emit.
    Dangerous tags (script, style, iframe, etc.) have their entire content
    stripped, not just the tags.
    """

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self._output_parts: list[str] = []
        self._skip_depth = 0  # >0 means we're inside a dangerous tag

    def _is_safe_attr(self, tag: str, attr: str) -> bool:
        attr_lower = attr.lower()
        if attr_lower.startswith("on"):
            return False
        if attr_lower in _SAFE_HTML_ATTRS_GLOBAL:
            return True
        tag_attrs = _SAFE_HTML_ATTRS_BY_TAG.get(tag.lower(), set())
        return attr_lower in tag_attrs

    def _sanitize_url_attr(self, value: str) -> str:
        is_safe, cleaned = _safe_url_validate(value)
        if not is_safe:
            return "#"
        return cleaned

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        tag_lower = tag.lower()

        # Entering a dangerous tag: start skipping content
        if tag_lower in _TAGS_TO_STRIP_CONTENT:
            self._skip_depth += 1
            return

        if self._skip_depth > 0:
            return  # Still inside a dangerous tag, skip everything

        if tag_lower not in _SAFE_HTML_TAGS:
            return  # Drop tag, but keep content

        safe_attrs: list[tuple[str, str]] = []
        for attr_name, attr_value in attrs:
            attr_lower = attr_name.lower()
            if not self._is_safe_attr(tag_lower, attr_lower):
                continue
            if attr_value is None:
                # Boolean attribute (e.g. <hr noshade>) - keep as-is
                safe_attrs.append((attr_lower, ""))
                continue

            value = attr_value

            # URL attributes get extra validation
            if attr_lower in _URL_ATTRS:
                value = self._sanitize_url_attr(value)

            # style attribute gets CSS sanitization
            if attr_lower == "style":
                if not _is_safe_css_inline(value):
                    continue  # drop unsafe style attribute entirely

            safe_attrs.append((attr_lower, value))

        # Build tag output
        attr_str = ""
        for name, val in safe_attrs:
            if val == "":
                attr_str += f" {name}"
            else:
                attr_str += f' {name}="{_escape_html_attr(val)}"'

        self._output_parts.append(f"<{tag_lower}{attr_str}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]):
        """Handle self-closing tags (e.g. <img />)."""
        tag_lower = tag.lower()
        if tag_lower in _TAGS_TO_STRIP_CONTENT:
            return  # Skip entirely
        if tag_lower not in _SAFE_HTML_TAGS:
            return
        # Reuse starttag logic (no content inside)
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str):
        tag_lower = tag.lower()
        if tag_lower in _TAGS_TO_STRIP_CONTENT:
            if self._skip_depth > 0:
                self._skip_depth -= 1
            return
        if self._skip_depth > 0:
            return
        if tag_lower in _SAFE_HTML_TAGS:
            self._output_parts.append(f"</{tag_lower}>")

    def handle_data(self, data: str):
        if self._skip_depth == 0:
            self._output_parts.append(data)

    def handle_entityref(self, name: str):
        if self._skip_depth == 0:
            self._output_parts.append(f"&{name};")

    def handle_charref(self, name: str):
        if self._skip_depth == 0:
            self._output_parts.append(f"&#{name};")

    def handle_comment(self, data: str):
        pass  # strip comments

    def get_output(self) -> str:
        return "".join(self._output_parts)


def _sanitize_html(html: str) -> str:
    """Sanitize HTML using tag+attribute whitelist strategy."""
    if not html:
        return ""
    parser = _SafeHtmlParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        # If parsing fails, strip ALL tags as a safe fallback
        return re.sub(r"<[^>]*>", "", html)
    return parser.get_output()


def _is_safe_css_inline(css: str) -> bool:
    """Quick check if inline CSS is safe enough to allow in a style attribute.

    We don't try to fully validate CSS grammar; we just reject known-dangerous
    patterns. This reduces false positives.
    """
    if not css:
        return True

    if _DANGEROUS_CSS_PATTERNS.search(css):
        return False

    # Check url() values - validate the URL
    for match in _CSS_URL_RE.finditer(css):
        inner_url = match.group(2)
        is_safe, _ = _safe_url_validate(inner_url)
        if not is_safe:
            return False

    return True


# =============================================================================
# Public API - each with a clearly defined strategy
# =============================================================================

def safe_text(value: Any) -> str:
    """Serialize a value as plain text for HTML context.

    **Strategy**: Full HTML entity escaping.
    **Escapes**: & → &amp;   < → &lt;   > → &gt;   " → &quot;   ' → &#39;

    Use this for layer names, labels, captions, and any user-provided
    text that should be displayed literally, NOT interpreted as HTML.

    This is the safest default for text that doesn't need markup.

    Example:
        {{ layer_name | safe_text }}
    """
    if value is None:
        return ""
    return _escape_html(str(value))


def safe_html(value: Union[str, Any]) -> str:
    """Serialize a value as HTML content with whitelist sanitization.

    **Strategy**: Tag whitelist + attribute whitelist + URL validation.

    Allowed tags:
        a, b, blockquote, br, caption, code, col, colgroup, dd, div, dl,
        dt, em, h1-h6, hr, i, img, li, ol, p, pre, span, strong, table,
        tbody, td, tfoot, th, thead, tr, ul, small, sub, sup

    Allowed attributes (global):
        class, id, style, title

    Allowed attributes (tag-specific):
        a: href, target, rel
        img: src, alt, width, height
        td/th: rowspan, colspan
        table: cellpadding, cellspacing, width, border
        col/colgroup: span, width

    URL attributes (href/src) are additionally validated (scheme whitelist).
    style attributes additionally pass through CSS safety checks.

    Blocks:
        <script>, <iframe>, <object>, <embed>, <form>, <input>, <button>
        All on* event handlers
        javascript:, vbscript: URLs
        Dangerous CSS (expression(), behavior, etc.)
        HTML comments

    Use this for popup/tooltip content where HTML is intentionally allowed.

    Example:
        {{ popup_content | safe_html }}
    """
    if value is None:
        return ""
    if isinstance(value, JsCode):
        return value.js_code
    text = str(value)
    if "<" not in text:
        return text  # No tags, nothing to sanitize
    return _sanitize_html(text)


def trusted_html(value: Union[str, Any]) -> str:
    """Serialize a value as trusted HTML content with NO sanitization.

    **Strategy**: Pass-through with minimal escaping for JS template strings.

    Only escapes backticks (`) to prevent breaking JavaScript template
    string literals. All HTML tags, attributes, and scripts are passed
    through verbatim.

    **WARNING**: This is for user-provided HTML that is explicitly marked
    as trusted. Use with extreme caution. For most use cases, prefer
    `safe_html` (sanitized) or `safe_text` (escaped).

    Use this when:
    - The user explicitly passed `html=True` to indicate the content
      contains intentional HTML
    - The content comes from a trusted source and needs full HTML support

    Example:
        {{ popup_content | trusted_html }}
    """
    if value is None:
        return ""
    if isinstance(value, JsCode):
        return value.js_code
    text = str(value)
    return text.replace("`", "\\`")


def safe_url(value: Any) -> str:
    """Serialize and validate a URL value for use in JavaScript strings.

    **Strategy**: Scheme whitelist + URL template placeholder support.

    Allowed schemes:
        http, https, ftp, ftps, mailto, data (image/ only), blob

    URL templates:
        Placeholders like {z}, {x}, {y}, {s}, {r}, {id} are preserved
        as-is. These are common in tile URLs (e.g. OpenStreetMap).
        Only the non-placeholder structural portion is validated.

    Output: JavaScript string literal with XSS-prevention escapes.
    Unsafe URLs return `"#blocked-unsafe-url"` (as a JS string).

    Use this for tile URLs, image URLs, attribution links, icon URLs.

    Example:
        {{ tiles_url | safe_url }}
    """
    if value is None:
        return '""'
    url = str(value)
    if not url:
        return '""'

    is_safe, cleaned = _safe_url_validate(url)
    if not is_safe:
        return _escape_js_string("#blocked-unsafe-url")

    return _escape_js_string(cleaned)


def safe_css_value(value: Any) -> str:
    """Serialize and sanitize a CSS property value.

    **Strategy**: Deny known-dangerous patterns, pass everything else through.

    Blocked constructs:
        expression()     javascript:    vbscript:
        eval()           moz-binding     behavior
        @import          url() with non-safe protocols

    IMPORTANT: We do NOT attempt to validate CSS value grammar here.
    Instead we block known dangerous CSS injection vectors and otherwise
    pass values through. This avoids false positives on legitimate CSS
    like custom properties, calc(), var(), hsl(), etc.

    Output: The CSS value with backslash and quote escapes applied, suitable
    for embedding inside a quoted JavaScript string or HTML attribute.
    Newlines are flattened to spaces.

    Use this for inline style attributes, CSS property values from users.

    Example:
        {{ tooltip_style | safe_css_value }}
    """
    if value is None:
        return ""
    css = str(value)

    # Block dangerous patterns
    if _DANGEROUS_CSS_PATTERNS.search(css):
        return ""

    # Validate any url() references
    for match in _CSS_URL_RE.finditer(css):
        inner_url = match.group(2)
        is_safe, _ = _safe_url_validate(inner_url)
        if not is_safe:
            return ""

    # Apply escapes for embedding in quoted contexts
    css = css.replace("\\", "\\\\")
    css = css.replace('"', '\\"')
    css = css.replace("'", "\\'")
    css = css.replace("\n", " ")
    css = css.replace("\r", " ")
    return css


def safe_js_value(value: Any) -> str:
    """Serialize a value as a safe JavaScript literal.

    **Strategy**: JSON serialization with XSS-prevention escapes.

    - None → "null"
    - bool → "true" / "false"
    - int/float → string representation
    - str → JSON-quoted string with <, >, &, ' → \\uXXXX escapes
    - dict/list/tuple → compact JSON with XSS escapes
    - JsCode instances → passed through verbatim (trusted JS code)

    Use this for strings, numbers, booleans, and JSON-like data that
    will be embedded directly in JavaScript. This is the safe alternative
    to Jinja's built-in `tojson` filter for values.

    Example:
        {{ this.option_value | safe_js_value }}
    """
    if isinstance(value, JsCode):
        return value.js_code
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return _escape_js_string(value)
    if isinstance(value, (dict, list, tuple)):
        return _to_escaped_json(value)
    return _escape_js_string(str(value))


def safe_js_options(options: Union[dict, None]) -> str:
    """Serialize a dictionary of options as a JavaScript object literal.

    **Strategy**: Dict → JS object literal with camelCased keys, recursively
    serialized via safe_js_value.

    - Keys are camelized (snake_case → camelCase)
    - Values go through safe_js_value recursively
    - JsCode values are preserved verbatim (callbacks, expressions)
    - None values are preserved (as null)
    - Output: compact {"key": value, ...} format

    Use this for Leaflet options objects and plugin configuration.

    Example:
        {{ this.options | safe_js_options }}
    """
    if options is None:
        return "{}"
    if not isinstance(options, dict):
        return "{}"

    parts: list[str] = []
    for key, value in options.items():
        if isinstance(key, str):
            js_key = camelize(key)
        else:
            js_key = str(key)

        if isinstance(value, dict):
            js_value = safe_js_options(value)
        elif isinstance(value, (list, tuple)):
            items = [safe_js_value(item) for item in value]
            js_value = "[" + ", ".join(items) + "]"
        else:
            js_value = safe_js_value(value)

        parts.append(f'"{js_key}": {js_value}')

    return "{" + ", ".join(parts) + "}"


def safe_layer_name(name: Union[str, None]) -> str:
    """Serialize a layer name for use in LayerControl.

    **Strategy**: Same as safe_js_value — JSON string with XSS escapes.

    Layer names appear as JavaScript object keys (in layer control) and
    as HTML labels. JSON string encoding with XSS escapes keeps them
    safe in both contexts.

    Example:
        {{ layer_name | safe_layer_name }}
    """
    if name is None:
        return '""'
    return _escape_js_string(str(name))


def safe_css_identifier(value: str) -> str:
    """Sanitize a value for use as a CSS identifier (class name, id).

    **Strategy**: Only allow characters valid in CSS identifiers; replace
    everything else with underscore.

    Allowed characters: a-z, A-Z, 0-9, _, - (hyphen)
    Leading digits are prefixed with an underscore.

    Example:
        {{ color_name | safe_css_identifier }}
    """
    if not value:
        return ""
    value = str(value)
    value = re.sub(r"[^a-zA-Z0-9_\-]", "_", value)
    if value and (value[0].isdigit() or value[0] == "-" and value[1:2].isdigit()):
        value = "_" + value
    return value


def safe_query_params(params: dict) -> str:
    """Serialize a dictionary of query parameters.

    **Strategy**: URL-encode keys and values per RFC 3986.

    Properly URL-encodes both keys and values.
    """
    if not params:
        return ""
    encoded_pairs: list[str] = []
    for key, value in params.items():
        encoded_key = quote(str(key))
        encoded_value = quote(str(value))
        encoded_pairs.append(f"{encoded_key}={encoded_value}")
    return "&".join(encoded_pairs)


def safe_json_to_js(value: Any) -> str:
    """Convert a JSON-formatted string to a safe JavaScript object literal.

    **Strategy**: Parse JSON → re-serialize with XSS escapes.

    Use this for values that are already JSON strings (e.g., style maps
    from GeoJsonStyleMapper) and need to be output as JavaScript objects.

    Supports embedded Jinja2 template expressions like {{'var_name'}} inside
    the JSON structure (used for Pattern objects and similar). These are
    temporarily extracted before parsing and restored after serialization.

    If JSON parsing fails, the value is returned as a safely escaped string.
    """
    if not value:
        return "{}"

    if isinstance(value, str):
        # Handle Jinja2 placeholders (e.g. from GeoJsonStyleMapper with Pattern)
        if "{{" in value and "}}" in value:
            placeholders: list[str] = []

            def _replace_expr(match: re.Match[str]) -> str:
                idx = len(placeholders)
                placeholders.append(match.group(0))
                return f'"__JINJA_PH_{idx}__"'

            processed = re.sub(
                r"\{\{.*?\}\}", _replace_expr, value, flags=re.DOTALL
            )
            try:
                parsed = json.loads(processed)
                result = _to_escaped_json(parsed)
                for idx, original in enumerate(placeholders):
                    ph_key = f"__JINJA_PH_{idx}__"
                    quoted_ph = json.dumps(ph_key)
                    result = result.replace(quoted_ph, original)
                    result = result.replace(ph_key, original)
                return result
            except (json.JSONDecodeError, TypeError):
                pass  # fall through to normal parse attempt

        try:
            parsed = json.loads(value)
            return _to_escaped_json(parsed)
        except (json.JSONDecodeError, TypeError):
            return _escape_js_string(value)

    if isinstance(value, dict):
        return _to_escaped_json(value)

    return safe_js_value(value)
