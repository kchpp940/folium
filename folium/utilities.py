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
from os import PathLike
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


def _is_array_like(obj: Any) -> bool:
    """Check if an object is array-like (numpy ndarray, list, tuple, etc.)."""
    if "ndarray" in obj.__class__.__name__:
        return True
    if isinstance(obj, (list, tuple)):
        return True
    if hasattr(obj, "__array__"):
        return True
    return False


def _is_path_like(obj: Any) -> bool:
    """Check if an object is path-like (os.PathLike)."""
    return isinstance(obj, PathLike)


_SVG_START_RE = re.compile(r"^\s*(<\?xml[^>]*>\s*)?<svg[\s>]", re.IGNORECASE)
_BASE64_RE = re.compile(r"^[A-Za-z0-9+/]+={0,2}$")

_IMAGE_MAGIC_PREFIXES: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"BM", "image/bmp"),
    (b"RIFF", "image/webp"),
)


def _detect_image_mime(data: bytes) -> Optional[str]:
    """Detect image MIME type from bytes using magic numbers. Returns None if not an image."""
    for prefix, mime in _IMAGE_MAGIC_PREFIXES:
        if data.startswith(prefix):
            if mime == "image/webp" and (len(data) < 12 or data[8:12] != b"WEBP"):
                continue
            return mime
    try:
        text = data.decode("utf-8")
        if _SVG_START_RE.match(text):
            return "image/svg+xml"
    except UnicodeDecodeError:
        pass
    return None


def _raw_to_renderable_image_data_uri(raw: str) -> Optional[str]:
    """
    Convert raw content string to a renderable image data URI.

    Only handles content that can legitimately be used as an <img> src:
    - SVG markup → data:image/svg+xml;base64,...
    - Naked base64-encoded image binary (PNG/JPEG/GIF/etc.) → data:image/*;base64,...

    Returns None if the raw string is not a renderable image.
    Does NOT wrap JSON or arbitrary text — those are not image sources.
    """
    stripped = raw.strip()

    if _SVG_START_RE.match(stripped):
        b64 = base64.b64encode(stripped.encode("utf-8")).decode("ascii")
        return f"data:image/svg+xml;base64,{b64}"

    if (
        len(stripped) >= 4
        and len(stripped) % 4 == 0
        and _BASE64_RE.match(stripped)
    ):
        try:
            decoded = base64.b64decode(stripped, validate=True)
        except Exception:
            return None
        mime = _detect_image_mime(decoded)
        if mime is not None:
            return f"data:{mime};base64,{stripped}"

    return None


def _is_renderable_image_source(image: Any) -> tuple[bool, Optional[str]]:
    """
    Check whether an input is a valid renderable image source for image layers.

    Returns (is_valid, reason).
    Valid renderable sources are: array, pathlike (file must exist), URL,
    local file string (file must exist), SVG raw string, and naked base64
    image binary.
    JSON strings, arbitrary plain text, and nonexistent paths are NOT valid.
    """
    src_type = _image_source_type(image)

    if src_type == "array":
        return True, None

    if src_type == "url":
        return True, None

    if src_type == "file":
        return True, None

    if src_type == "pathlike":
        file_path = os.fspath(image)
        if os.path.isfile(file_path):
            return True, None
        return False, (
            f"PathLike object points to a nonexistent file: {file_path!r}. "
            "The file must exist to be used as an image source."
        )

    if src_type == "raw":
        assert isinstance(image, str)
        if _raw_to_renderable_image_data_uri(image) is not None:
            return True, None
        return False, (
            "Raw string is not a renderable image source. "
            "Expected a URL, path to an existing file, PathLike object, "
            "SVG markup, base64-encoded image binary, or array-like image data. "
            "Got a plain string or JSON that cannot be rendered as an image."
        )

    return False, f"Unsupported image source type: {type(image).__name__}"


def _image_source_type(image: Any) -> str:
    """
    Determine the type of an image source.

    Returns one of: 'array', 'pathlike', 'url', 'file', 'raw'.
    """
    if isinstance(image, str):
        if _is_url(image):
            return "url"
        if os.path.isfile(image):
            return "file"
        return "raw"

    if _is_path_like(image):
        return "pathlike"

    if _is_array_like(image):
        return "array"

    return "raw"


def image_to_url(
    image: Any,
    colormap: Optional[Callable] = None,
    origin: str = "upper",
) -> str:
    """
    Infers the type of an image argument and transforms it into a URL.

    This function focuses on image source resolution only. For raw strings
    that are not renderable as images (JSON, plain text, etc.), the
    original string is returned unchanged — callers that require safe
    embedding are responsible for escaping at the template injection point,
    and image-layer entry points (ImageOverlay/FloatImage/CustomIcon)
    validate renderability and reject non-image sources explicitly.

    Parameters
    ----------
    image: string, PathLike, or array-like object
        *  If string is a path to an image file and the file exists,
           its content will be converted and embedded in the output URL.
        *  If PathLike object, it will be treated as a file path and
           its content will be converted and embedded in the output URL.
        *  If string is a URL, it will be linked in the output URL.
        *  If string is SVG markup or naked base64-encoded image binary,
           it will be wrapped into a proper image data URI.
        *  If array-like, it will be converted to PNG base64 string and
           embedded in the output URL.
    origin: ['upper' | 'lower'], optional, default 'upper'
        Place the [0, 0] index of the array in the upper left or
        lower left corner of the axes.
    colormap: callable, used only for `mono` image.
        Function of the form [x -> (r,g,b)] or [x -> (r,g,b,a)]
        for transforming a mono image into RGB.
        It must output iterables of length 3 or 4, with values between
        0. and 1.  You can use colormaps from `matplotlib.cm`.

    """
    source_type = _image_source_type(image)

    if source_type == "array":
        img = write_png(image, origin=origin, colormap=colormap)
        b64encoded = base64.b64encode(img).decode("utf-8")
        url = f"data:image/png;base64,{b64encoded}"
    elif source_type == "pathlike":
        file_path = os.fspath(image)
        fileformat = os.path.splitext(file_path)[-1][1:]
        with open(file_path, "rb") as f:
            img = f.read()
        b64encoded = base64.b64encode(img).decode("utf-8")
        url = f"data:image/{fileformat};base64,{b64encoded}"
    elif source_type == "url":
        url = image
    elif source_type == "file":
        fileformat = os.path.splitext(image)[-1][1:]
        with open(image, "rb") as f:
            img = f.read()
        b64encoded = base64.b64encode(img).decode("utf-8")
        url = f"data:image/{fileformat};base64,{b64encoded}"
    else:
        if isinstance(image, str):
            renderable = _raw_to_renderable_image_data_uri(image)
            url = renderable if renderable is not None else image
        else:
            url = json.dumps(image)

    return url.replace("\n", " ")


def image_source_to_url(
    image: Any,
    *,
    require_renderable: bool = True,
    colormap: Optional[Callable] = None,
    origin: str = "upper",
    caller: Optional[str] = None,
) -> str:
    """
    Unified entry point for image layers to convert an image source into a URL.

    Combines renderability validation (optional) and URL conversion into a
    single call so that callers cannot accidentally skip validation.

    Parameters
    ----------
    image: string, PathLike, or array-like object
        The image source — see image_to_url() for supported image formats.
    require_renderable: bool, default True
        When True, raises ValueError if ``image`` is not a source that can
        be rendered by the browser as an <img> src (e.g. JSON strings,
        plain text, or nonexistent PathLike objects are rejected).
        Set to False to bypass the check and match plain image_to_url().
    colormap: callable or None, default None
        Forwarded to image_to_url() — only used for array-like mono images.
    origin: {'upper', 'lower'}, default 'upper'
        Forwarded to image_to_url().
    caller: str or None, default None
        If provided, used as a prefix in ValueError messages so the user
        can tell which class rejected the input (e.g. "ImageOverlay").

    Returns
    -------
    str
        A URL or data URI suitable for use as an image src.

    Raises
    ------
    ValueError
        If require_renderable is True and the image source is not renderable.
    """
    if require_renderable:
        is_valid, reason = _is_renderable_image_source(image)
        if not is_valid:
            prefix = f"{caller} received a non-renderable image source. " if caller else ""
            raise ValueError(f"{prefix}{reason}")
    return image_to_url(image, colormap=colormap, origin=origin)


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
