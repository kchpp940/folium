"""
Smoke test helper module for validating Folium examples.

Provides:
  - Code extraction from Markdown, Jupyter notebooks, Python files, and RST.
  - Safe code execution that captures generated folium.Map objects.
  - HTML validation (template errors, suspicious resource links, structure).
  - Example registry with metadata (network requirement, priority, etc.).
"""

from __future__ import annotations

import ast
import io
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urlparse

import folium


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class ExampleSpec:
    """Metadata and execution spec for a smoke test example."""

    name: str
    source: str
    kind: str = "inline"
    requires_network: bool = False
    priority: int = 1
    tags: list[str] = field(default_factory=list)
    extra_globals: dict[str, Any] = field(default_factory=dict)
    setup: Callable[[], dict[str, Any]] | None = None
    teardown: Callable[[], None] | None = None
    skip: bool = False
    skip_reason: str = ""


@dataclass
class SmokeResult:
    """Result of running a single smoke test example."""

    spec: ExampleSpec
    success: bool
    html: str | None = None
    maps_captured: int = 0
    error: str | None = None
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Code extraction
# ---------------------------------------------------------------------------


def extract_code_from_markdown(md_text: str) -> str:
    """Extract Python code from ```{code-cell} and ```python blocks."""
    lines: list[str] = []
    in_code = False
    fence_pattern = re.compile(
        r"^```(?:\{code-cell\}\s*(?:ipython3)?|python|py)\s*$", re.IGNORECASE
    )

    for line in md_text.splitlines():
        stripped = line.strip()
        if not in_code:
            if fence_pattern.match(stripped):
                in_code = True
            continue
        if stripped.startswith("```"):
            in_code = False
            continue
        if stripped.startswith("---") and not lines or (
            lines and lines[-1].strip() == "---"
        ):
            continue
        lines.append(line)

    return "\n".join(lines)


def extract_code_from_notebook(nb_text: str) -> str:
    """Extract Python code cells from a Jupyter notebook JSON."""
    try:
        nb = json.loads(nb_text)
    except json.JSONDecodeError:
        return ""

    lines: list[str] = []
    for cell in nb.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        source = cell.get("source", [])
        if isinstance(source, list):
            cell_lines = "".join(source).splitlines()
        else:
            cell_lines = str(source).splitlines()
        for cl in cell_lines:
            if cl.strip().startswith("!"):
                continue
            lines.append(cl)
        lines.append("")

    return "\n".join(lines)


def extract_code_from_rst(rst_text: str) -> str:
    """Extract Python code from .. code:: python / .. code-block:: python blocks."""
    lines: list[str] = []
    in_code = False
    code_indent: int | None = None
    code_block_pattern = re.compile(
        r"^\.\.\s+code(?:-block)?::\s*(?:python|py)\s*$", re.IGNORECASE
    )

    for raw_line in rst_text.splitlines():
        stripped = raw_line.rstrip()
        if not in_code:
            if code_block_pattern.match(stripped.strip()):
                in_code = True
            continue
        if stripped.strip() == "":
            if lines:
                lines.append("")
            continue
        current_indent = len(raw_line) - len(raw_line.lstrip())
        if code_indent is None:
            if current_indent == 0:
                in_code = False
                code_indent = None
                continue
            code_indent = current_indent
        if current_indent < code_indent and stripped.strip() != "":
            in_code = False
            code_indent = None
            continue
        lines.append(raw_line[code_indent:])

    return "\n".join(lines)


def extract_code_from_file(file_path: str | Path) -> str:
    """Dispatch extraction based on file extension."""
    path = Path(file_path)
    text = path.read_text(encoding="utf-8")
    ext = path.suffix.lower()

    if ext == ".py":
        return text
    if ext == ".md":
        return extract_code_from_markdown(text)
    if ext == ".ipynb":
        return extract_code_from_notebook(text)
    if ext in (".rst", ".rest"):
        return extract_code_from_rst(text)
    raise ValueError(f"Unsupported file type for code extraction: {ext}")


# ---------------------------------------------------------------------------
# Safe code execution
# ---------------------------------------------------------------------------


_MAP_CAPTURE_MARKER = "__folium_maps__"


def _strip_display_statements(code: str) -> str:
    """Remove trailing bare expression statements that would display a map.

    In notebooks/docs, the last expression 'm' triggers display. We convert
    these to explicit captures so we can inspect the resulting Map.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return code

    new_body: list[ast.stmt] = []
    for stmt in tree.body:
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Name):
            name = stmt.value.id
            assign = ast.Assign(
                targets=[
                    ast.Subscript(
                        value=ast.Name(id=_MAP_CAPTURE_MARKER, ctx=ast.Load()),
                        slice=ast.Constant(value=name),
                        ctx=ast.Store(),
                    )
                ],
                value=ast.Name(id=name, ctx=ast.Load()),
            )
            new_body.append(assign)
        else:
            new_body.append(stmt)

    try:
        ast.fix_missing_locations(ast.Module(body=new_body, type_ignores=[]))
        return ast.unparse(ast.Module(body=new_body, type_ignores=[]))
    except Exception:
        return code


def run_example_code(
    code: str,
    extra_globals: dict[str, Any] | None = None,
    setup: Callable[[], dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], list[folium.Map]]:
    """Safely execute example code and capture all folium.Map instances.

    Returns (globals_dict, list_of_maps).
    """
    exec_globals: dict[str, Any] = {
        "__name__": "__smoke_test__",
        "__builtins__": __builtins__,
        "folium": folium,
        _MAP_CAPTURE_MARKER: {},
    }
    if extra_globals:
        exec_globals.update(extra_globals)
    if setup is not None:
        exec_globals.update(setup() or {})

    prepared_code = _strip_display_statements(code)
    exec(compile(prepared_code, "<smoke_example>", "exec"), exec_globals)

    explicit_captures = list(exec_globals.get(_MAP_CAPTURE_MARKER, {}).values())
    all_maps: list[folium.Map] = []
    seen: set[int] = set()
    for m in explicit_captures:
        if isinstance(m, folium.Map) and id(m) not in seen:
            all_maps.append(m)
            seen.add(id(m))
    for value in exec_globals.values():
        if isinstance(value, folium.Map) and id(value) not in seen:
            all_maps.append(value)
            seen.add(id(value))

    return exec_globals, all_maps


# ---------------------------------------------------------------------------
# HTML validation
# ---------------------------------------------------------------------------


class _HtmlLinkCollector(HTMLParser):
    """Collect all src/href URLs from HTML."""

    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self.in_head = False
        self.has_doctype = False
        self.has_html_tag = False
        self.has_head_tag = False
        self.has_body_tag = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_lower = tag.lower()
        if tag_lower == "!doctype":
            self.has_doctype = True
        if tag_lower == "html":
            self.has_html_tag = True
        if tag_lower == "head":
            self.in_head = True
            self.has_head_tag = True
        if tag_lower == "body":
            self.has_body_tag = True
        for attr, value in attrs:
            if attr.lower() in ("src", "href") and value:
                self.links.append((tag_lower, attr.lower(), value))

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "head":
            self.in_head = False


def validate_html(
    html: str,
    *,
    allow_network: bool = False,
) -> list[str]:
    """Validate rendered HTML, return list of warning/error strings.

    Checks:
      - Basic structure (DOCTYPE, html, head, body tags present)
      - No obviously suspicious resource URLs (file://, data: with odd content)
      - No template/Jinja error fragments in output
      - No broken CDN patterns
    """
    warnings: list[str] = []
    if not html:
        warnings.append("Empty HTML output")
        return warnings

    parser = _HtmlLinkCollector()
    try:
        parser.feed(html)
    except Exception as e:
        warnings.append(f"HTML parse error: {e}")
        return warnings

    if not parser.has_doctype:
        warnings.append("Missing <!DOCTYPE html> declaration")
    if not parser.has_html_tag:
        warnings.append("Missing <html> tag")
    if not parser.has_head_tag:
        warnings.append("Missing <head> tag")
    if not parser.has_body_tag:
        warnings.append("Missing <body> tag")

    error_fragments = [
        "TemplateNotFound",
        "TemplateSyntaxError",
        "UndefinedError",
        "jinja2",
        "Traceback (most recent call last)",
    ]
    for frag in error_fragments:
        if frag.lower() in html.lower():
            warnings.append(f"Possible template error fragment found: '{frag}'")

    for tag, attr, url in parser.links:
        parsed = urlparse(url)
        scheme = parsed.scheme.lower()
        if scheme == "file":
            warnings.append(
                f"Suspicious file:// URL in <{tag} {attr}>: {url[:100]}"
            )
        elif scheme in ("http", "https") and not allow_network:
            pass
        if attr == "src" and scheme in ("http", "https"):
            if re.search(r"\bv=undefined\b", url) or "None" in url:
                warnings.append(
                    f"Possible broken URL with undefined value: <{tag} {attr}>: {url[:100]}"
                )

    return warnings


def render_map_to_html(m: folium.Map) -> str:
    """Render a folium.Map to a full HTML document string.

    Uses Map.save() via a tempfile to get the complete HTML document
    including DOCTYPE, <html>, <head>, and <body> tags.
    """
    import tempfile

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".html", delete=False, encoding="utf-8"
    ) as f:
        path = f.name
    try:
        m.save(path)
        with open(path, encoding="utf-8") as f:
            return f.read()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def save_map_for_inspection(
    m: folium.Map, output_dir: str | Path, name: str
) -> Path:
    """Save HTML to a file for manual inspection and return the path."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^a-zA-Z0-9_.-]", "_", name)
    if not safe_name.endswith(".html"):
        safe_name += ".html"
    path = out_dir / safe_name
    m.save(str(path))
    return path


# ---------------------------------------------------------------------------
# Example registry
# ---------------------------------------------------------------------------


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DOCS_DIR = _PROJECT_ROOT / "docs"
_EXAMPLES_DIR = _PROJECT_ROOT / "examples"


def _file_spec(
    name: str,
    rel_path: str,
    *,
    requires_network: bool = False,
    priority: int = 1,
    tags: list[str] | None = None,
    preamble: str = "",
) -> ExampleSpec:
    full_path = _PROJECT_ROOT / rel_path

    def _setup() -> dict[str, Any]:
        code = extract_code_from_file(full_path)
        if preamble:
            code = preamble + "\n" + code
        return {"__preloaded_code__": code}

    return ExampleSpec(
        name=name,
        source=str(rel_path),
        kind="file",
        requires_network=requires_network,
        priority=priority,
        tags=tags or [],
        setup=_setup,
    )


def _inline_spec(
    name: str,
    code: str,
    *,
    requires_network: bool = False,
    priority: int = 1,
    tags: list[str] | None = None,
) -> ExampleSpec:
    return ExampleSpec(
        name=name,
        source=f"inline:{name}",
        kind="inline",
        requires_network=requires_network,
        priority=priority,
        tags=tags or [],
        extra_globals={"__inline_code__": code},
    )


def build_example_registry() -> list[ExampleSpec]:
    """Build the full registry of smoke test examples.

    Split into offline (smoke) and network (smoke_network) groups.
    """
    offline: list[ExampleSpec] = [
        _inline_spec(
            "getting_started_basic_map",
            """
import folium
m = folium.Map(location=(45.5236, -122.6750))
""",
            tags=["core", "getting_started"],
        ),
        _inline_spec(
            "getting_started_marker",
            """
import folium
m = folium.Map([45.35, -121.6972], zoom_start=12)
folium.Marker(
    location=[45.3288, -121.6625],
    tooltip="Click me!",
    popup="Mt. Hood Meadows",
    icon=folium.Icon(icon="cloud"),
).add_to(m)
folium.Marker(
    location=[45.3311, -121.7113],
    tooltip="Click me!",
    popup="Timberline Lodge",
    icon=folium.Icon(color="green"),
).add_to(m)
""",
            tags=["core", "marker"],
        ),
        _inline_spec(
            "getting_started_polyline",
            """
import folium
m = folium.Map(location=[-71.38, -73.9], zoom_start=11)
trail_coordinates = [
    (-71.351871840295871, -73.655963711222626),
    (-71.374144382613707, -73.719861619751498),
    (-71.391042575973145, -73.784922248007007),
]
folium.PolyLine(trail_coordinates, tooltip="Coast").add_to(m)
""",
            tags=["core", "vector"],
        ),
        _inline_spec(
            "getting_started_layer_control",
            """
import folium
m = folium.Map((0, 0), zoom_start=7)
group_1 = folium.FeatureGroup("first group").add_to(m)
folium.Marker((0, 0), icon=folium.Icon("red")).add_to(group_1)
folium.Marker((1, 0), icon=folium.Icon("red")).add_to(group_1)
group_2 = folium.FeatureGroup("second group").add_to(m)
folium.Marker((0, 1), icon=folium.Icon("green")).add_to(group_2)
folium.LayerControl().add_to(m)
""",
            tags=["core", "layer_control"],
        ),
        _inline_spec(
            "map_scale_and_zoom",
            """
import folium
m1 = folium.Map(location=(-38.625, -12.875), control_scale=True)
m2 = folium.Map(location=(-38.625, -12.875), zoom_control=False)
""",
            tags=["core", "map"],
            priority=1,
        ),
        _inline_spec(
            "map_bounds_limits",
            """
import folium
min_lon, max_lon = -45, -35
min_lat, max_lat = -25, -15
m = folium.Map(
    max_bounds=True,
    location=[-20, -40],
    zoom_start=6,
    min_lat=min_lat,
    max_lat=max_lat,
    min_lon=min_lon,
    max_lon=max_lon,
)
folium.CircleMarker([max_lat, min_lon], tooltip="Upper Left").add_to(m)
folium.CircleMarker([min_lat, min_lon], tooltip="Lower Left").add_to(m)
folium.CircleMarker([min_lat, max_lon], tooltip="Lower Right").add_to(m)
folium.CircleMarker([max_lat, max_lon], tooltip="Upper Right").add_to(m)
""",
            tags=["core", "map", "vector"],
        ),
        _inline_spec(
            "plugin_antpath",
            """
import folium
import folium.plugins
m = folium.Map()
wind_locations = [
    [59.35560, -31.992190],
    [55.178870, -42.89062],
    [47.754100, -43.94531],
    [38.272690, -37.96875],
]
folium.plugins.AntPath(
    locations=wind_locations, reverse="True", dash_array=[20, 30]
).add_to(m)
m.fit_bounds(m.get_bounds())
""",
            tags=["plugin", "antpath"],
        ),
        _inline_spec(
            "vector_shapes",
            """
import folium
m = folium.Map(location=[45.5236, -122.6750], zoom_start=13)
folium.CircleMarker(
    location=[45.5215, -122.6261],
    radius=50,
    popup="Laurelhurst Park",
    color="#3186cc",
    fill=True,
    fill_color="#3186cc",
).add_to(m)
folium.Polygon(
    locations=[(45.53, -122.68), (45.52, -122.68), (45.52, -122.67)],
    color="crimson",
    fill=True,
).add_to(m)
folium.Rectangle(
    bounds=[(45.51, -122.70), (45.54, -122.65)],
    color="blue",
    weight=2,
    fill=False,
).add_to(m)
""",
            tags=["core", "vector"],
        ),
        _inline_spec(
            "geojson_local_file",
            """
import json
import folium
import os
test_dir = os.path.dirname(os.path.abspath(__file__)) if "__file__" in dir() else "tests"
data_path = os.path.join(test_dir, "..", "examples", "data", "us-states.json")
data_path = os.path.normpath(data_path)
with open(data_path) as f:
    geo_data = json.load(f)
m = folium.Map(location=[48, -102], zoom_start=3)
folium.GeoJson(geo_data, name="states").add_to(m)
folium.LayerControl().add_to(m)
""",
            tags=["core", "geojson", "local_data"],
        ),
        _inline_spec(
            "choropleth_local",
            """
import json
import os
import pandas as pd
import folium
test_dir = os.path.dirname(os.path.abspath(__file__)) if "__file__" in dir() else "tests"
geo_path = os.path.normpath(os.path.join(test_dir, "..", "examples", "data", "us-states.json"))
csv_path = os.path.normpath(os.path.join(test_dir, "..", "examples", "data", "US_Unemployment_Oct2012.csv"))
with open(geo_path) as f:
    state_geo = json.load(f)
state_data = pd.read_csv(csv_path)
m = folium.Map(location=[48, -102], zoom_start=3)
folium.Choropleth(
    geo_data=state_geo,
    name="choropleth",
    data=state_data,
    columns=["State", "Unemployment"],
    key_on="feature.id",
    fill_color="YlGn",
    fill_opacity=0.7,
    line_opacity=0.2,
    legend_name="Unemployment Rate (%)",
).add_to(m)
folium.LayerControl().add_to(m)
""",
            tags=["core", "choropleth", "local_data"],
            priority=1,
        ),
        _file_spec(
            "docs_user_guide_map",
            "docs/user_guide/map.md",
            tags=["docs", "map"],
            priority=2,
        ),
        _file_spec(
            "docs_getting_started",
            "docs/getting_started.md",
            requires_network=True,
            tags=["docs", "getting_started"],
            priority=2,
        ),
        _file_spec(
            "docs_plugin_antpath",
            "docs/user_guide/plugins/antpath.md",
            tags=["docs", "plugin", "antpath"],
            priority=2,
        ),
        _file_spec(
            "docs_vector_circle",
            "docs/user_guide/vector_layers/circle_and_circle_marker.md",
            tags=["docs", "vector"],
            priority=2,
        ),
        _file_spec(
            "docs_vector_polyline",
            "docs/user_guide/vector_layers/polyline.md",
            tags=["docs", "vector"],
            priority=2,
        ),
        _file_spec(
            "docs_ui_icons",
            "docs/user_guide/ui_elements/icons.md",
            tags=["docs", "ui"],
            priority=2,
        ),
        _file_spec(
            "docs_ui_popups",
            "docs/user_guide/ui_elements/popups.md",
            tags=["docs", "ui"],
            priority=2,
        ),
        _file_spec(
            "docs_ui_layer_control",
            "docs/user_guide/ui_elements/layer_control.md",
            tags=["docs", "ui"],
            priority=2,
        ),
        _file_spec(
            "docs_raster_image_overlay",
            "docs/user_guide/raster_layers/image_overlay.md",
            tags=["docs", "raster"],
            priority=2,
        ),
        _file_spec(
            "docs_raster_tiles",
            "docs/user_guide/raster_layers/tiles.md",
            tags=["docs", "raster"],
            priority=2,
        ),
        _file_spec(
            "docs_geojson_basic",
            "docs/user_guide/geojson/geojson.md",
            requires_network=True,
            tags=["docs", "geojson"],
            priority=2,
        ),
        _file_spec(
            "docs_geojson_choropleth",
            "docs/user_guide/geojson/choropleth.md",
            requires_network=True,
            tags=["docs", "geojson", "choropleth"],
            priority=2,
        ),
        _file_spec(
            "docs_plugin_heatmap",
            "docs/user_guide/plugins/heatmap.md",
            tags=["docs", "plugin", "heatmap"],
            priority=2,
        ),
        _file_spec(
            "docs_plugin_marker_cluster",
            "docs/user_guide/plugins/marker_cluster.md",
            tags=["docs", "plugin", "marker_cluster"],
            priority=2,
        ),
        _file_spec(
            "docs_plugin_minimap",
            "docs/user_guide/plugins/mini_map.md",
            tags=["docs", "plugin", "minimap"],
            priority=2,
        ),
        _file_spec(
            "docs_plugin_fullscreen",
            "docs/user_guide/plugins/fullscreen.md",
            tags=["docs", "plugin"],
            priority=2,
        ),
        _file_spec(
            "docs_plugin_draw",
            "docs/user_guide/plugins/draw.md",
            tags=["docs", "plugin", "draw"],
            priority=2,
        ),
        _file_spec(
            "docs_plugin_dual_map",
            "docs/user_guide/plugins/dual_map.md",
            tags=["docs", "plugin", "dual_map"],
            priority=2,
        ),
        _file_spec(
            "examples_quickstart_notebook",
            "examples/Quickstart.ipynb",
            tags=["examples", "notebook", "getting_started"],
            priority=2,
        ),
        _file_spec(
            "examples_features_notebook",
            "examples/Features.ipynb",
            requires_network=True,
            tags=["examples", "notebook", "features"],
            priority=3,
        ),
        _file_spec(
            "examples_vector_layers_notebook",
            "examples/VectorLayers.ipynb",
            requires_network=True,
            tags=["examples", "notebook", "vector"],
            priority=3,
        ),
        _file_spec(
            "examples_plugins_notebook",
            "examples/Plugins.ipynb",
            requires_network=True,
            tags=["examples", "notebook", "plugins"],
            priority=3,
        ),
        _file_spec(
            "examples_marker_cluster_notebook",
            "examples/MarkerCluster.ipynb",
            tags=["examples", "notebook", "marker_cluster"],
            priority=3,
        ),
        _file_spec(
            "examples_geojson_choropleth_notebook",
            "examples/GeoJSON_and_choropleth.ipynb",
            requires_network=True,
            tags=["examples", "notebook", "geojson", "choropleth"],
            priority=3,
        ),
        _file_spec(
            "examples_heatmap_notebook",
            "examples/Heatmap.ipynb",
            tags=["examples", "notebook", "heatmap"],
            priority=3,
        ),
        _file_spec(
            "examples_popups_notebook",
            "examples/Popups.ipynb",
            tags=["examples", "notebook", "popups"],
            priority=3,
        ),
        _file_spec(
            "examples_image_overlay_notebook",
            "examples/ImageOverlay.ipynb",
            requires_network=True,
            tags=["examples", "notebook", "raster"],
            priority=3,
        ),
    ]

    network_only: list[ExampleSpec] = [
        _inline_spec(
            "network_tile_custom_provider",
            """
import folium
m = folium.Map((45.5236, -122.6750), tiles="cartodb positron")
""",
            requires_network=True,
            tags=["network", "tiles"],
        ),
        _inline_spec(
            "network_geojson_url",
            """
import folium
m = folium.Map(tiles="cartodbpositron")
folium.GeoJson(
    "https://raw.githubusercontent.com/python-visualization/folium/main/examples/data/us-states.json",
    name="states",
).add_to(m)
folium.LayerControl().add_to(m)
""",
            requires_network=True,
            tags=["network", "geojson"],
        ),
        _file_spec(
            "docs_plugin_search",
            "docs/user_guide/plugins/search.md",
            requires_network=True,
            tags=["docs", "plugin", "search", "network"],
            priority=3,
        ),
        _file_spec(
            "docs_plugin_realtime",
            "docs/user_guide/plugins/realtime.md",
            requires_network=True,
            tags=["docs", "plugin", "realtime", "network"],
            priority=3,
        ),
        _file_spec(
            "docs_plugin_geocoder",
            "docs/user_guide/plugins/geocoder.md",
            requires_network=True,
            tags=["docs", "plugin", "geocoder", "network"],
            priority=3,
        ),
        _file_spec(
            "examples_geopandas_notebook",
            "examples/Geopandas_and_geo_interface.ipynb",
            requires_network=True,
            tags=["examples", "notebook", "geopandas", "network"],
            priority=3,
        ),
        _file_spec(
            "examples_wms_notebook",
            "examples/WMS_and_WMTS.ipynb",
            requires_network=True,
            tags=["examples", "notebook", "wms", "network"],
            priority=3,
        ),
        _file_spec(
            "examples_search_notebook",
            "examples/plugin-Search.ipynb",
            requires_network=True,
            tags=["examples", "notebook", "plugin", "search", "network"],
            priority=3,
        ),
    ]

    return offline + network_only


# ---------------------------------------------------------------------------
# High-level runner
# ---------------------------------------------------------------------------


def run_example(
    spec: ExampleSpec,
    *,
    html_output_dir: str | Path | None = None,
) -> SmokeResult:
    """Execute a single example spec and return the result."""
    warnings: list[str] = []

    try:
        if spec.kind == "file":
            setup_globals = spec.setup() if spec.setup else {}
            code = setup_globals.get("__preloaded_code__", "")
        elif spec.kind == "inline":
            code = spec.extra_globals.get("__inline_code__", "")
        else:
            return SmokeResult(
                spec=spec,
                success=False,
                error=f"Unknown example kind: {spec.kind}",
            )

        if not code.strip():
            return SmokeResult(
                spec=spec,
                success=False,
                error="No code to execute",
            )

        exec_globals, maps = run_example_code(
            code,
            extra_globals=spec.extra_globals,
            setup=spec.setup if spec.kind != "file" else None,
        )

        if not maps:
            warnings.append("No folium.Map instances captured from example")
            return SmokeResult(
                spec=spec,
                success=True,
                maps_captured=0,
                warnings=warnings,
            )

        rendered_html: str | None = None
        for i, m in enumerate(maps):
            html = render_map_to_html(m)
            if i == 0:
                rendered_html = html
            html_warnings = validate_html(
                html, allow_network=spec.requires_network
            )
            warnings.extend(html_warnings)
            if html_output_dir:
                suffix = f"_{i}" if i > 0 else ""
                save_map_for_inspection(m, html_output_dir, spec.name + suffix)

        return SmokeResult(
            spec=spec,
            success=True,
            html=rendered_html,
            maps_captured=len(maps),
            warnings=warnings,
        )

    except Exception as exc:
        import traceback

        tb = traceback.format_exception_only(type(exc), exc)
        return SmokeResult(
            spec=spec,
            success=False,
            error="".join(tb).strip(),
            warnings=warnings,
        )


def filter_examples(
    registry: Iterable[ExampleSpec],
    *,
    include_network: bool = False,
    max_priority: int | None = None,
    tags: list[str] | None = None,
) -> list[ExampleSpec]:
    """Filter the registry by network requirement, priority, and tags."""
    result: list[ExampleSpec] = []
    for spec in registry:
        if spec.skip:
            continue
        if not include_network and spec.requires_network:
            continue
        if max_priority is not None and spec.priority > max_priority:
            continue
        if tags and not any(t in spec.tags for t in tags):
            continue
        result.append(spec)
    return result
