import base64
import collections
import copy
import json
import math
import os
import re
import tempfile
import uuid
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Literal,
    Optional,
    Union,
)
from urllib.parse import urlparse, uses_netloc, uses_params, uses_relative

import numpy as np
from branca.element import Div, Element, Figure

# import here for backwards compatibility
from branca.utilities import (  # noqa F401
    _locations_mirror,
    _parse_size,
    none_max,
    none_min,
    write_png,
)

try:
    import pandas as pd
except ImportError:
    pd = None

if TYPE_CHECKING:
    from .features import Popup


TypeLine = Iterable[Sequence[float]]
TypeMultiLine = Union[TypeLine, Iterable[TypeLine]]

TypeJsonValueNoNone = Union[str, float, bool, Sequence, dict]
TypeJsonValue = Union[TypeJsonValueNoNone, None]

TypePathOptions = Union[bool, str, float, None]

TypeBounds = Sequence[Sequence[float]]
TypeBoundsReturn = list[list[Optional[float]]]

TypeContainer = Union[Figure, Div, "Popup"]
TypePosition = Literal["bottomright", "bottomleft", "topright", "topleft"]


_VALID_URLS = set(uses_relative + uses_netloc + uses_params)
_VALID_URLS.discard("")
_VALID_URLS.add("data")


def validate_location(location: Sequence[float]) -> list[float]:
    """Validate a single lat/lon coordinate pair and convert to a list

    Validate that location:
    * is a sized variable
    * with size 2
    * allows indexing (i.e. has an ordering)
    * where both values are floats (or convertible to float)
    * and both values are not NaN
    """
    if isinstance(location, np.ndarray) or (
        pd is not None and isinstance(location, pd.DataFrame)
    ):
        location = np.squeeze(location).tolist()
    if not hasattr(location, "__len__"):
        raise TypeError(
            "Location should be a sized variable, "
            "for example a list or a tuple, instead got "
            f"{location!r} of type {type(location)}."
        )
    if len(location) != 2:
        raise ValueError(
            "Expected two (lat, lon) values for location, "
            f"instead got: {location!r}."
        )
    try:
        coords = (location[0], location[1])
    except (TypeError, KeyError):
        raise TypeError(
            "Location should support indexing, like a list or "
            f"a tuple does, instead got {location!r} of type {type(location)}."
        )
    for coord in coords:
        try:
            float(coord)
        except (TypeError, ValueError):
            raise ValueError(
                "Location should consist of two numerical values, "
                f"but {coord!r} of type {type(coord)} is not convertible to float."
            )
        if math.isnan(float(coord)):
            raise ValueError("Location values cannot contain NaNs.")
    return [float(x) for x in coords]


def _validate_locations_basics(locations: TypeMultiLine) -> None:
    """Helper function that does basic validation of line and multi-line types."""
    try:
        iter(locations)
    except TypeError:
        raise TypeError(
            "Locations should be an iterable with coordinate pairs,"
            f" but instead got {locations!r}."
        )
    try:
        next(iter(locations))
    except StopIteration:
        raise ValueError("Locations is empty.")


def validate_locations(locations: TypeLine) -> list[list[float]]:
    """Validate an iterable with lat/lon coordinate pairs."""
    locations = if_pandas_df_convert_to_numpy(locations)
    _validate_locations_basics(locations)
    return [validate_location(coord_pair) for coord_pair in locations]


def validate_multi_locations(
    locations: TypeMultiLine,
) -> Union[list[list[float]], list[list[list[float]]]]:
    """Validate an iterable with possibly nested lists of coordinate pairs."""
    locations = if_pandas_df_convert_to_numpy(locations)
    _validate_locations_basics(locations)
    try:
        float(next(iter(next(iter(next(iter(locations)))))))  # type: ignore
    except (TypeError, StopIteration):
        # locations is a list of coordinate pairs
        return [validate_location(coord_pair) for coord_pair in locations]  # type: ignore
    else:
        # locations is a list of a list of coordinate pairs, recurse
        return [validate_locations(lst) for lst in locations]  # type: ignore


def if_pandas_df_convert_to_numpy(obj: Any) -> Any:
    """Return a Numpy array from a Pandas dataframe.

    Iterating over a DataFrame has weird side effects, such as the first
    row being the column names. Converting to Numpy is more safe.
    """
    if pd is not None and isinstance(obj, pd.DataFrame):
        return obj.values
    else:
        return obj


def image_to_url(
    image: Any,
    colormap: Optional[Callable] = None,
    origin: str = "upper",
) -> str:
    """
    Infers the type of an image argument and transforms it into a URL.

    Parameters
    ----------
    image: string or array-like object
        *  If string is a path to an image file, its content will be converted and
           embedded in the output URL.
        *  If string is a URL, it will be linked in the output URL.
        *  Otherwise a string will be assumed to be JSON and embedded in the
           output URL.
        *  If array-like, it will be converted to PNG base64 string and embedded in the
           output URL.
    origin: ['upper' | 'lower'], optional, default 'upper'
        Place the [0, 0] index of the array in the upper left or
        lower left corner of the axes.
    colormap: callable, used only for `mono` image.
        Function of the form [x -> (r,g,b)] or [x -> (r,g,b,a)]
        for transforming a mono image into RGB.
        It must output iterables of length 3 or 4, with values between
        0. and 1.  You can use colormaps from `matplotlib.cm`.

    """
    if isinstance(image, str) and not _is_url(image):
        fileformat = os.path.splitext(image)[-1][1:]
        with open(image, "rb") as f:
            img = f.read()
        b64encoded = base64.b64encode(img).decode("utf-8")
        url = f"data:image/{fileformat};base64,{b64encoded}"
    elif "ndarray" in image.__class__.__name__:
        img = write_png(image, origin=origin, colormap=colormap)
        b64encoded = base64.b64encode(img).decode("utf-8")
        url = f"data:image/png;base64,{b64encoded}"
    else:
        # Round-trip to ensure a nice formatted json.
        url = json.loads(json.dumps(image))
    return url.replace("\n", " ")


def _is_url(url: str) -> bool:
    """Check to see if `url` has a valid protocol."""
    try:
        return urlparse(url).scheme in _VALID_URLS
    except Exception:
        return False


def mercator_transform(
    data: Any,
    lat_bounds: tuple[float, float],
    origin: str = "upper",
    height_out: Optional[int] = None,
) -> np.ndarray:
    """
    Transforms an image computed in (longitude,latitude) coordinates into
    the a Mercator projection image.

    Parameters
    ----------

    data: numpy array or equivalent list-like object.
        Must be NxM (mono), NxMx3 (RGB) or NxMx4 (RGBA)

    lat_bounds : length 2 tuple
        Minimal and maximal value of the latitude of the image.
        Bounds must be between -85.051128779806589 and 85.051128779806589
        otherwise they will be clipped to that values.

    origin : ['upper' | 'lower'], optional, default 'upper'
        Place the [0,0] index of the array in the upper left or lower left
        corner of the axes.

    height_out : int, default None
        The expected height of the output.
        If None, the height of the input is used.

    See https://en.wikipedia.org/wiki/Web_Mercator for more details.

    """

    def mercator(x):
        return np.arcsinh(np.tan(x * np.pi / 180.0)) * 180.0 / np.pi

    array = np.atleast_3d(data).copy()
    height, width, nblayers = array.shape

    lat_min = max(lat_bounds[0], -85.051128779806589)
    lat_max = min(lat_bounds[1], 85.051128779806589)
    if height_out is None:
        height_out = height

    # Eventually flip the image
    if origin == "upper":
        array = array[::-1, :, :]

    lats = lat_min + np.linspace(0.5 / height, 1.0 - 0.5 / height, height) * (
        lat_max - lat_min
    )
    latslats = mercator(lat_min) + np.linspace(
        0.5 / height_out, 1.0 - 0.5 / height_out, height_out
    ) * (mercator(lat_max) - mercator(lat_min))

    out: np.ndarray = np.zeros((height_out, width, nblayers))
    for i in range(width):
        for j in range(nblayers):
            out[:, i, j] = np.interp(latslats, mercator(lats), array[:, i, j])

    # Eventually flip the image.
    if origin == "upper":
        out = out[::-1, :, :]
    return out


def iter_coords(obj: Any) -> Iterator[tuple[float, ...]]:
    """
    Returns all the coordinate tuples from a geometry or feature.

    """
    if isinstance(obj, (tuple, list)):
        coords = obj
    elif "features" in obj:
        coords = [
            geom["geometry"]["coordinates"]
            for geom in obj["features"]
            if geom["geometry"]
        ]
    elif "geometry" in obj:
        coords = obj["geometry"]["coordinates"] if obj["geometry"] else []
    elif (
        "geometries" in obj
        and obj["geometries"][0]
        and "coordinates" in obj["geometries"][0]
    ):
        coords = obj["geometries"][0]["coordinates"]
    else:
        coords = obj.get("coordinates", obj)
    for coord in coords:
        if isinstance(coord, (float, int)):
            yield tuple(coords)
            break
        else:
            yield from iter_coords(coord)


def get_bounds(
    locations: Any,
    lonlat: bool = False,
) -> list[list[Optional[float]]]:
    """
    Computes the bounds of the object in the form
    [[lat_min, lon_min], [lat_max, lon_max]]

    """
    bounds: list[list[Optional[float]]] = [[None, None], [None, None]]
    for point in iter_coords(locations):
        bounds = [
            [
                none_min(bounds[0][0], point[0]),
                none_min(bounds[0][1], point[1]),
            ],
            [
                none_max(bounds[1][0], point[0]),
                none_max(bounds[1][1], point[1]),
            ],
        ]
    if lonlat:
        bounds = _locations_mirror(bounds)
    return bounds


def normalize_bounds_type(bounds: TypeBounds) -> TypeBoundsReturn:
    return [[float(x) if x is not None else None for x in y] for y in bounds]


def camelize(key: str) -> str:
    """Convert a python_style_variable_name to lowerCamelCase.

    Examples
    --------
    >>> camelize("variable_name")
    'variableName'
    >>> camelize("variableName")
    'variableName'
    """
    return "".join(x.capitalize() if i > 0 else x for i, x in enumerate(key.split("_")))


def compare_rendered(obj1: str, obj2: str) -> bool:
    """
    Return True/False if the normalized rendered version of
    two folium map objects are the equal or not.

    """
    return normalize(obj1) == normalize(obj2)


def normalize(rendered: str) -> str:
    """Return the input string without non-functional spaces or newlines."""
    out = "".join([line.strip() for line in rendered.splitlines() if line.strip()])
    out = out.replace(", ", ",")
    return out


@contextmanager
def temp_html_filepath(data: str) -> Iterator[str]:
    """Yields the path of a temporary HTML file containing data."""
    filepath = ""
    try:
        fid, filepath = tempfile.mkstemp(suffix=".html", prefix="folium_")
        os.write(fid, data.encode("utf8") if isinstance(data, str) else data)
        os.close(fid)
        yield filepath
    finally:
        if os.path.isfile(filepath):
            os.remove(filepath)


def deep_copy(item_original: Element) -> Element:
    """Return a recursive deep-copy of item where each copy has a new ID."""
    item = copy.copy(item_original)
    item._id = uuid.uuid4().hex
    if hasattr(item, "_children") and len(item._children) > 0:
        children_new = collections.OrderedDict()
        for subitem_original in item._children.values():
            subitem = deep_copy(subitem_original)
            subitem._parent = item
            children_new[subitem.get_name()] = subitem
        item._children = children_new
    return item


def get_obj_in_upper_tree(element: Element, cls: type) -> Element:
    """Return the first object in the parent tree of class `cls`."""
    parent = element._parent
    if parent is None:
        raise ValueError(f"The top of the tree was reached without finding a {cls}")
    if not isinstance(parent, cls):
        return get_obj_in_upper_tree(parent, cls)
    return parent  # type: ignore


def parse_options(**kwargs: TypeJsonValue) -> dict[str, TypeJsonValueNoNone]:
    """Return a dict with lower-camelcase keys and non-None values.."""
    return {camelize(key): value for key, value in kwargs.items() if value is not None}


def remove_empty(**kwargs: TypeJsonValue) -> dict[str, TypeJsonValueNoNone]:
    """Return a dict without None values."""
    return {key: value for key, value in kwargs.items() if value is not None}


def escape_backticks(text: str) -> str:
    """Escape backticks so text can be used in a JS template."""
    return re.sub(r"(?<!\\)`", r"\`", text)


def escape_double_quotes(text: str) -> str:
    return text.replace('"', r"\"")


def javascript_identifier_path_to_array_notation(path: str) -> str:
    """Convert a path like obj1.obj2 to array notation: ["obj1"]["obj2"]."""
    return "".join(f'["{escape_double_quotes(x)}"]' for x in path.split("."))


def get_and_assert_figure_root(obj: Element) -> Figure:
    """Return the root element of the tree and assert it's a Figure."""
    figure = obj.get_root()
    assert isinstance(
        figure, Figure
    ), "You cannot render this Element if it is not in a Figure."
    return figure


class JsCode:
    """Wrapper around Javascript code."""

    def __init__(self, js_code: Union[str, "JsCode"]):
        if isinstance(js_code, JsCode):
            self.js_code: str = js_code.js_code
        else:
            self.js_code = js_code

    def __str__(self):
        return self.js_code


def parse_font_size(value: Union[str, int, float]) -> str:
    """Parse a font size value, if number set as px"""
    if isinstance(value, (int, float)):
        return f"{value}px"

    if (value[-3:] != "rem") and (value[-2:] not in ["em", "px"]):
        raise ValueError("The font size must be expressed in rem, em, or px.")
    return value


PREDEFINED_EVENT_ACTIONS: dict[str, str] = {
    "zoom": "function(e) { if (typeof e.target.getBounds === 'function') { map.fitBounds(e.target.getBounds()); } else if (typeof e.target.getLatLng === 'function') { let zoom = map.getZoom(); zoom = zoom > 12 ? zoom : zoom + 1; map.flyTo(e.target.getLatLng(), zoom); } }",
    "alert": "function(e) { let props = e.target.feature ? e.target.feature.properties : null; let msg = props ? (props.name || props.title || JSON.stringify(props)) : 'Clicked'; alert(msg); }",
    "log": "function(e) { console.log('Event:', e.type, 'Target:', e.target, 'Event:', e); }",
    "highlight": "function(e) { if (typeof e.target.setStyle === 'function') { e.target.setStyle({ weight: e.target.options.weight ? e.target.options.weight + 2 : 5, opacity: 1 }); } }",
    "reset_highlight": "function(e) { if (typeof e.target.resetStyle !== 'undefined' && e.target._map) { e.target._map.eachLayer(function(layer) { if (typeof layer.resetStyle === 'function') { layer.resetStyle(e.target); } }); } else if (typeof e.target.setStyle === 'function' && e.target._originalStyle) { e.target.setStyle(e.target._originalStyle); } }",
    "open_popup": "function(e) { if (typeof e.target.openPopup === 'function') { e.target.openPopup(); } }",
    "close_popup": "function(e) { if (typeof e.target.closePopup === 'function') { e.target.closePopup(); } }",
}


class EventHandlerSpec:
    """
    Internal: Encapsulates an event handler specification for Leaflet layers.
    
    This is used internally by EventMixin to normalize event handler definitions.
    Users should interact with the `events` parameter instead of this class directly.
    
    Supports three types of handlers:
    1. String function name: e.g., "myGlobalClickHandler"
    2. Inline JS function body (JsCode or str starting with 'function'): 
       e.g., JsCode("function(e) { alert('Clicked!'); }")
    3. Predefined action name: e.g., "zoom", "alert", "log"
    
    Parameters
    ----------
    handler : str or JsCode
        The event handler. Can be:
        - A string referencing a global JS function name
        - A JsCode object containing an inline function
        - A string with a predefined action name from PREDEFINED_EVENT_ACTIONS
        - A string starting with 'function' for inline JS
    """

    def __init__(self, handler: Union[str, "JsCode", "EventHandlerSpec"]):
        if isinstance(handler, EventHandlerSpec):
            self.handler_type: str = handler.handler_type
            self.raw_handler: Union[str, JsCode] = handler.raw_handler
            self.resolved_handler: JsCode = handler.resolved_handler
            return

        if isinstance(handler, JsCode):
            self.handler_type = "inline"
            self.raw_handler = handler
            self.resolved_handler = handler
            return

        if not isinstance(handler, str):
            raise TypeError(
                f"Event handler must be str, JsCode, or EventHandlerSpec, "
                f"got {type(handler).__name__}"
            )

        handler_stripped = handler.strip()

        if handler_stripped.startswith("function"):
            self.handler_type = "inline"
            self.raw_handler = handler_stripped
            self.resolved_handler = JsCode(handler_stripped)
        elif handler_stripped in PREDEFINED_EVENT_ACTIONS:
            self.handler_type = "predefined"
            self.raw_handler = handler_stripped
            self.resolved_handler = JsCode(PREDEFINED_EVENT_ACTIONS[handler_stripped])
        elif handler_stripped and re.match(
            r"^[a-zA-Z_$][a-zA-Z0-9_$.]*$", handler_stripped
        ):
            self.handler_type = "reference"
            self.raw_handler = handler_stripped
            self.resolved_handler = JsCode(handler_stripped)
        else:
            self.handler_type = "inline"
            self.raw_handler = handler_stripped
            self.resolved_handler = JsCode(handler_stripped)

    def to_javascript(self) -> str:
        """Return the JavaScript representation of the handler."""
        return str(self.resolved_handler)

    def __str__(self) -> str:
        return self.to_javascript()

    def __repr__(self) -> str:
        return f"EventHandlerSpec(type={self.handler_type!r}, handler={self.raw_handler!r})"


TypeEventHandlers = dict[str, Union[str, JsCode, EventHandlerSpec]]


class EventMixin:
    """
    Mixin class that provides unified event binding capabilities.

    Add this mixin to any MacroElement subclass to enable event binding
    through the `events` parameter. This mixin also intercepts
    ``add_child(EventHandler(...))`` calls and absorbs them into the
    same internal ``_event_handlers`` dictionary, so there is only one
    rendering path for all event bindings.

    For simple layers (Circle, Polygon, etc.) there is only one event
    level, so ``events`` is unambiguous. For GeoJson, which has two
    levels (feature-level and layer-level), use the explicit
    ``feature_events`` and ``layer_events`` parameters instead of
    ``events`` to avoid confusion about which binding level is intended.

    Examples
    --------
    >>> class MyLayer(EventMixin, MacroElement):
    ...     def __init__(self, events=None, **kwargs):
    ...         super().__init__(events=events, **kwargs)
    >>> 
    >>> layer = MyLayer(events={
    ...     "click": "myClickHandler",
    ...     "mouseover": "function(e) { console.log('over'); }",
    ...     "mouseout": "log",
    ... })
    """

    _supported_events: set[str] = {
        "click",
        "dblclick",
        "mousedown",
        "mouseup",
        "mouseover",
        "mouseout",
        "mousemove",
        "contextmenu",
        "focus",
        "blur",
        "preclick",
        "add",
        "remove",
        "popupopen",
        "popupclose",
        "tooltipopen",
        "tooltipclose",
    }

    def __init__(
        self,
        events: Optional[TypeEventHandlers] = None,
        **kwargs: Any,
    ) -> None:
        self._event_handlers: dict[str, EventHandlerSpec] = {}
        if events:
            self.set_events(events)
        super().__init__(**kwargs)

    def set_events(self, events: TypeEventHandlers) -> None:
        """
        Set multiple event handlers at once.
        
        Parameters
        ----------
        events : dict
            Dictionary mapping event names to handlers.
            Keys are event names (e.g., 'click', 'mouseover').
            Values are handlers (str function name, JsCode, or predefined action).
        """
        if not isinstance(events, dict):
            raise TypeError("events must be a dictionary")
        for event_name, handler in events.items():
            self.set_event(event_name, handler)

    def set_event(
        self, event_name: str, handler: Union[str, JsCode, EventHandlerSpec]
    ) -> None:
        """
        Set a single event handler.
        
        Parameters
        ----------
        event_name : str
            Name of the event (e.g., 'click', 'mouseover').
        handler : str, JsCode, or EventHandlerSpec
            The event handler to bind. Can be:
            - Global JS function name (str)
            - Inline function body starting with 'function' (str or JsCode)
            - Predefined action name: 'zoom', 'alert', 'log', 
              'highlight', 'reset_highlight', 'open_popup', 'close_popup'
        """
        if not isinstance(event_name, str):
            raise TypeError("event_name must be a string")
        event_name_lower = event_name.lower()
        if (
            event_name != event_name_lower
            and event_name_lower in self._supported_events
        ):
            import warnings

            warnings.warn(
                f"Event name '{event_name}' should be lowercase, "
                f"using '{event_name_lower}' instead",
                UserWarning,
                stacklevel=2,
            )
            event_name = event_name_lower
        self._event_handlers[event_name] = EventHandlerSpec(handler)

    def get_event(self, event_name: str) -> Optional[EventHandlerSpec]:
        """Get the handler for a specific event, or None if not set."""
        return self._event_handlers.get(event_name)

    def remove_event(self, event_name: str) -> bool:
        """Remove an event handler. Returns True if handler existed."""
        if event_name in self._event_handlers:
            del self._event_handlers[event_name]
            return True
        return False

    def clear_events(self) -> None:
        """Remove all event handlers."""
        self._event_handlers.clear()

    def has_events(self) -> bool:
        """Check if any event handlers are configured."""
        return bool(self._event_handlers)

    def _absorb_event_handler(self, event_handler: Any) -> bool:
        """Absorb an elements.EventHandler into the unified _event_handlers dict.

        Returns True if the handler was absorbed, False if it is not
        an EventHandler instance.
        """
        from folium.elements import EventHandler as _LegacyEventHandler

        if not isinstance(event_handler, _LegacyEventHandler):
            return False
        event_name = event_handler.event
        if event_name in self._event_handlers:
            import warnings
            source = "feature_events" if hasattr(self, "_layer_event_handlers") else "events"
            warnings.warn(
                f"Event '{event_name}' already set via `{source}` parameter. "
                f"The add_child(EventHandler(...)) call for the same event "
                f"is ignored to avoid duplicate bindings.",
                UserWarning,
                stacklevel=4,
            )
            return True
        self._event_handlers[event_name] = EventHandlerSpec(event_handler.handler)
        return True

    def add_child(self, child: Any, name: Optional[str] = None, index: Optional[int] = None):
        """Override add_child to intercept EventHandler children.

        When an EventHandler is added as a child, it is absorbed into
        the internal _event_handlers dictionary instead of being rendered
        as a separate MacroElement, avoiding duplicate bindings.
        """
        if self._absorb_event_handler(child):
            return self
        return super().add_child(child, name=name, index=index)

    def _render_event_bindings(self, layer_var_name: str) -> str:
        """
        Generate the JavaScript code for binding events.
        
        Parameters
        ----------
        layer_var_name : str
            The JavaScript variable name of the Leaflet layer.
            
        Returns
        -------
        str
            JavaScript code with .on() calls.
        """
        if not self._event_handlers:
            return ""
        lines = []
        for event_name, event_handler in self._event_handlers.items():
            lines.append(
                f"{layer_var_name}.on({json.dumps(event_name)}, "
                f"{event_handler.to_javascript()});"
            )
        return "\n".join(lines)

    def _render_on_each_feature_events(self) -> str:
        """
        Generate the JavaScript code for binding events inside onEachFeature.
        
        This is used by GeoJson to bind events to individual feature layers.
        
        Returns
        -------
        str
            JavaScript code for layer.on({...}) object content.
        """
        if not self._event_handlers:
            return ""
        entries = []
        for event_name, event_handler in self._event_handlers.items():
            entries.append(
                f"    {json.dumps(event_name)}: {event_handler.to_javascript()}"
            )
        return ",\n".join(entries)


def validate_events(
    events: Optional[TypeEventHandlers],
    allowed_events: Optional[set[str]] = None,
) -> dict[str, EventHandlerSpec]:
    """
    Validate and normalize event handlers dictionary.
    
    Parameters
    ----------
    events : dict or None
        Dictionary of event handlers.
    allowed_events : set or None
        If provided, only allow events in this set.
        Defaults to all standard Leaflet events.
        
    Returns
    -------
    dict[str, EventHandlerSpec]
        Normalized dictionary with EventHandlerSpec instances.
        
    Raises
    ------
    ValueError
        If an event name is not in allowed_events.
    """
    if events is None:
        return {}
    if not isinstance(events, dict):
        raise TypeError("events must be a dictionary")
    if allowed_events is None:
        allowed_events = EventMixin._supported_events
    result: dict[str, EventHandlerSpec] = {}
    for event_name, handler in events.items():
        if event_name not in allowed_events:
            raise ValueError(
                f"Unsupported event: '{event_name}'. "
                f"Supported events: {sorted(allowed_events)}"
            )
        result[event_name] = EventHandlerSpec(handler)
    return result
