import json
from typing import Union

import jinja2
from branca.element import Element

from folium.utilities import JsCode, TypeJsonValue, camelize
from folium.safe_serialize import (
    safe_text,
    safe_html,
    safe_url,
    safe_css_value,
    safe_js_value,
    safe_js_options,
    safe_layer_name,
    safe_css_identifier,
    safe_json_to_js,
)


def tojavascript(obj: Union[str, JsCode, dict, list, Element]) -> str:
    if isinstance(obj, JsCode):
        return obj.js_code
    elif isinstance(obj, Element):
        return obj.get_name()
    elif isinstance(obj, dict):
        out = ["{\n"]
        for key, value in obj.items():
            if isinstance(key, str):
                out.append(f'  "{camelize(key)}": ')
            else:
                out.append(f"  {key}: ")
            out.append(tojavascript(value))
            out.append(",\n")
        out.append("}")
        return "".join(out)
    elif isinstance(obj, list):
        out = ["[\n"]
        for value in obj:
            out.append(tojavascript(value))
            out.append(",\n")
        out.append("]")
        return "".join(out)
    else:
        return _to_escaped_json(obj)


def _to_escaped_json(obj: TypeJsonValue) -> str:
    return (
        json.dumps(obj)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("'", "\\u0027")
    )


class Environment(jinja2.Environment):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.filters["tojavascript"] = tojavascript
        self.filters["safe_text"] = safe_text
        self.filters["safe_html"] = safe_html
        self.filters["safe_url"] = safe_url
        self.filters["safe_css_value"] = safe_css_value
        self.filters["safe_js_value"] = safe_js_value
        self.filters["safe_js_options"] = safe_js_options
        self.filters["safe_layer_name"] = safe_layer_name
        self.filters["safe_css_identifier"] = safe_css_identifier
        self.filters["safe_json_to_js"] = safe_json_to_js


class Template(jinja2.Template):
    environment_class = Environment
