"""
Safe serialization helpers for Folium.

This module provides a unified boundary for serializing user input into
JavaScript/HTML contexts. Each function is specialized for a specific
output context to ensure consistent escaping and prevent injection.

Context types:
    - text:       Plain text in HTML context (HTML-escaped)
    - html:       Trusted/allowed HTML content (sanitized)
    - url:        URL values (protocol-validated, properly encoded)
    - css_value:  CSS property values (sanitized, no expression() etc.)
    - js_value:   JavaScript literal values (JSON-like, no code execution)
    - js_options: JavaScript options objects (recursive, keys camelized)
"""

import json
import re
from typing import Any, Union
from urllib.parse import urlparse, urlencode, parse_qs, urlunparse

from folium.utilities import JsCode, camelize


_SAFE_URL_SCHEMES = {"http", "https", "ftp", "ftps", "mailto", "data", "blob"}

_DANGEROUS_CSS_PATTERNS = re.compile(
    r"expression|javascript|vbscript|eval\(|moz-binding|behavior|url\s*\(",
    re.IGNORECASE,
)

_HTML_TAG_RE = re.compile(r"<[^>]+>")

_JS_IDENTIFIER_RE = re.compile(r"^[a-zA-Z_$][a-zA-Z0-9_$]*$")


def _escape_html(text: str) -> str:
    """Escape text for safe inclusion in HTML context."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _escape_js_string(text: str) -> str:
    """Escape text for safe inclusion as a JavaScript string literal.
    
    Applies XSS-prevention escapes for <, >, &, ' characters.
    """
    return (
        json.dumps(text)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("'", "\\u0027")
    )


def _to_escaped_json(obj: Any) -> str:
    """Convert to JSON with XSS-prevention escapes applied."""
    return (
        json.dumps(obj)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("'", "\\u0027")
    )


def safe_text(value: Any) -> str:
    """
    Serialize a value as plain text for HTML context.
    
    Use this for layer names, labels, captions, and any user-provided
    text that should be displayed literally, not interpreted as HTML.
    
    Example:
        {{ layer_name | safe_text }}
    """
    if value is None:
        return ""
    return _escape_html(str(value))


def safe_html(value: Union[str, Any]) -> str:
    """
    Serialize a value as HTML content.
    
    Use this for popup/tooltip content where HTML is intentionally allowed.
    This still blocks dangerous patterns like <script> tags and javascript: URLs.
    
    Note: This provides a basic level of sanitization. For untrusted content,
    consider using a dedicated HTML sanitization library.
    """
    if value is None:
        return ""
    if isinstance(value, JsCode):
        return value.js_code
    text = str(value)
    text = re.sub(
        r'(?i)<\s*script[^>]*>.*?<\s*/\s*script\s*>', '', text, flags=re.DOTALL
    )
    text = re.sub(
        r'(?i)<\s*iframe[^>]*>.*?<\s*/\s*iframe\s*>', '', text, flags=re.DOTALL
    )
    text = re.sub(
        r'(?i)\son\w+\s*=', ' data-blocked-on=', text
    )
    text = re.sub(
        r'(?i)(href|src|action)\s*=\s*["\']?javascript:',
        r'\1="#', text
    )
    return text


def safe_url(value: Any, allowed_schemes: set = _SAFE_URL_SCHEMES) -> str:
    """
    Serialize and validate a URL value.
    
    Use this for tile URLs, image URLs, attribution links, etc.
    Validates the URL scheme and properly encodes it.
    
    Example:
        {{ tiles_url | safe_url }}
    """
    if value is None:
        return ""
    url = str(value)
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        if parsed.scheme and parsed.scheme.lower() not in allowed_schemes:
            return "#blocked-unsafe-url"
        if parsed.scheme == "data":
            if not url.lower().startswith(("data:image/", "data:application/json")):
                return "#blocked-unsafe-data-url"
        encoded = urlunparse(parsed)
        return _escape_js_string(encoded)
    except Exception:
        return "#blocked-invalid-url"


def safe_css_value(value: Any) -> str:
    """
    Serialize and sanitize a CSS property value.
    
    Use this for style attributes, CSS property values passed by users.
    Blocks dangerous CSS features like expression(), javascript:, url(), etc.
    
    Example:
        {{ tooltip_style | safe_css_value }}
    """
    if value is None:
        return ""
    css = str(value)
    if _DANGEROUS_CSS_PATTERNS.search(css):
        return ""
    css = css.replace("\\", "\\\\")
    css = css.replace('"', '\\"')
    css = css.replace("'", "\\'")
    css = css.replace("\n", " ")
    css = css.replace("\r", " ")
    return css


def safe_js_value(value: Any) -> str:
    """
    Serialize a value as a safe JavaScript literal.
    
    Use this for strings, numbers, booleans, and JSON-like data that
    will be embedded directly in JavaScript. This is the preferred
    alternative to Jinja's built-in `tojson` filter.
    
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
    """
    Serialize a dictionary of options as a JavaScript object literal.
    
    Use this for Leaflet options objects. Keys are automatically camelized.
    Values are recursively processed through safe_js_value.
    JsCode instances are preserved as-is for callbacks and expressions.
    
    Output uses compact JSON-like format with quoted keys for maximum
    compatibility with existing tests and templates.
    
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
    """
    Serialize a layer name for use in LayerControl.
    
    Layer names appear as JavaScript object keys and HTML labels.
    This ensures they are safe for both contexts.
    """
    if name is None:
        return ""
    text = str(name)
    return _to_escaped_json(text)


def safe_css_identifier(value: str) -> str:
    """
    Sanitize a value for use as a CSS identifier (class name, id).
    
    Removes characters that are not allowed in CSS identifiers.
    """
    if not value:
        return ""
    value = str(value)
    value = re.sub(r'[^a-zA-Z0-9_\-]', '_', value)
    if value and value[0].isdigit():
        value = '_' + value
    return value


def safe_query_params(params: dict) -> str:
    """
    Serialize a dictionary of query parameters.
    
    Properly URL-encodes keys and values.
    """
    if not params:
        return ""
    from urllib.parse import quote
    encoded_pairs: list[str] = []
    for key, value in params.items():
        encoded_key = quote(str(key))
        encoded_value = quote(str(value))
        encoded_pairs.append(f"{encoded_key}={encoded_value}")
    return "&".join(encoded_pairs)


def safe_json_to_js(value: Any) -> str:
    """
    Convert a JSON-formatted string to a safe JavaScript object literal.
    
    Use this for values that are already JSON strings (e.g., style maps
    from GeoJsonStyleMapper) and need to be output as JavaScript objects.
    
    This parses the JSON string, then re-serializes it with XSS-prevention
    escapes applied, maintaining compact JSON format for compatibility.
    
    Supports embedded Jinja2 template expressions like {{'var_name'}} inside
    the JSON structure by temporarily extracting them before parsing and
    restoring them after serialization.
    """
    if not value:
        return "{}"
    if isinstance(value, str):
        if "{{" in value and "}}" in value:
            placeholders: list[str] = []

            def replace_expr(match: re.Match[str]) -> str:
                idx = len(placeholders)
                placeholders.append(match.group(0))
                return f'"__JINJA_PH_{idx}__"'

            processed = re.sub(
                r"\{\{.*?\}\}", replace_expr, value, flags=re.DOTALL
            )
            try:
                parsed = json.loads(processed)
                result = _to_escaped_json(parsed)
                for idx, original in enumerate(placeholders):
                    placeholder_key = f"__JINJA_PH_{idx}__"
                    quoted_placeholder = json.dumps(placeholder_key)
                    result = result.replace(quoted_placeholder, original)
                    result = result.replace(placeholder_key, original)
                return result
            except (json.JSONDecodeError, TypeError):
                pass
        try:
            parsed = json.loads(value)
            return _to_escaped_json(parsed)
        except (json.JSONDecodeError, TypeError):
            return _escape_js_string(value)
    if isinstance(value, dict):
        return _to_escaped_json(value)
    return safe_js_value(value)
