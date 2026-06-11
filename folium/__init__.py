import branca
from branca.colormap import ColorMap, LinearColormap, StepColormap
from branca.element import (
    CssLink,
    Div,
    Element,
    Figure,
    Html,
    IFrame,
    JavascriptLink,
    Link,
    MacroElement,
)

from folium.features import (
    Choropleth,
    ClickForLatLng,
    ClickForMarker,
    ColorLine,
    Control,
    CustomIcon,
    DivIcon,
    GeoJson,
    GeoJsonPopup,
    GeoJsonTooltip,
    LatLngPopup,
    RegularPolygonMarker,
    TopoJson,
    Vega,
    VegaLite,
)
from folium.folium import Map
from folium.map import (
    FeatureGroup,
    FitBounds,
    FitOverlays,
    Icon,
    LayerControl,
    LayerGroup,
    Marker,
    Popup,
    Tooltip,
)
from folium.raster_layers import TileLayer, WmsTileLayer
from folium.utilities import (
    JsCode,
    ResourceMode,
    clear_resource_overrides,
    get_local_path,
    get_resource_mode,
    get_resource_override,
    set_resource_mode,
    set_resource_override,
)
from folium.vector_layers import Circle, CircleMarker, Polygon, PolyLine, Rectangle

try:
    from ._version import __version__
except ImportError:  # pragma: no cover
    __version__ = "unknown"


if branca.__version__ != "unknown" and tuple(
    int(x) for x in branca.__version__.split(".")[:2]
) < (
    0,
    3,
):  # pragma: no cover
    raise ImportError(
        "branca version 0.3.0 or higher is required. "
        "Update branca with e.g. `pip install branca --upgrade`."
    )


__all__ = [
    "Choropleth",
    "ClickForMarker",
    "ClickForLatLng",
    "ColorLine",
    "ColorMap",
    "Control",
    "CssLink",
    "CustomIcon",
    "Div",
    "DivIcon",
    "Element",
    "FeatureGroup",
    "Figure",
    "FitBounds",
    "FitOverlays",
    "GeoJson",
    "GeoJsonPopup",
    "GeoJsonTooltip",
    "Html",
    "IFrame",
    "Icon",
    "JavascriptLink",
    "JsCode",
    "LatLngPopup",
    "LayerControl",
    "LayerGroup",
    "LinearColormap",
    "Link",
    "MacroElement",
    "Map",
    "Marker",
    "Popup",
    "RegularPolygonMarker",
    "ResourceMode",
    "StepColormap",
    "TileLayer",
    "Tooltip",
    "TopoJson",
    "Vega",
    "VegaLite",
    "WmsTileLayer",
    # Resource management
    "clear_resource_overrides",
    "get_local_path",
    "get_resource_mode",
    "get_resource_override",
    "set_resource_mode",
    "set_resource_override",
    # vector_layers
    "Circle",
    "CircleMarker",
    "PolyLine",
    "Polygon",
    "Rectangle",
]
