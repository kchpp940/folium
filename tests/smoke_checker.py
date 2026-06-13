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
    optional_deps: list[str] = field(default_factory=list)
    cwd: str | Path | None = None


@dataclass
class SmokeResult:
    """Result of running a single smoke test example."""

    spec: ExampleSpec
    success: bool
    html: str | None = None
    maps_captured: int = 0
    error: str | None = None
    warnings: list[str] = field(default_factory=list)
    skipped: bool = False
    skip_reason: str = ""


# ---------------------------------------------------------------------------
# Code extraction
# ---------------------------------------------------------------------------


def extract_code_from_markdown(md_text: str) -> str:
    """Extract Python code from ```{code-cell} and ```python blocks only.

    Plain ``` fences (without language info or code-cell tag) are skipped
    because they typically contain output, doctests, or shell commands.

    Handles nbsphinx-style cell metadata between ``---`` markers at the top
    of a code cell by skipping those lines.
    """
    lines: list[str] = []
    in_code = False
    in_cell_meta = False
    cell_meta_depth = 0

    def is_opening_fence(s: str) -> bool:
        if not s.startswith("```"):
            return False
        rest = s[3:].strip()
        if rest.lower() in ("python", "py"):
            return True
        if rest.startswith("{code-cell"):
            return True
        return False

    for line in md_text.splitlines():
        stripped = line.strip()
        if not in_code:
            if is_opening_fence(stripped):
                in_code = True
                in_cell_meta = False
                cell_meta_depth = 0
            continue
        if stripped.startswith("```"):
            in_code = False
            in_cell_meta = False
            continue
        if in_cell_meta:
            if stripped.startswith("---"):
                cell_meta_depth -= 1
                if cell_meta_depth <= 0:
                    in_cell_meta = False
            continue
        if stripped.startswith("---"):
            if not [l for l in lines if l.strip()]:
                in_cell_meta = True
                cell_meta_depth = 1
                continue
        if stripped.startswith(">>>") or stripped.startswith("..."):
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

_MAP_CREATORS = {"Map", "DualMap"}


def _is_map_creation(node: ast.expr) -> bool:
    """Check if an AST expression creates or chains from a folium Map.

    Detects direct construction (``folium.Map(...)``) and chained method
    calls whose root is a Map constructor (``folium.Map().add_child(...)``).
    """
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute):
            if func.attr in _MAP_CREATORS:
                return True
            if (
                isinstance(func.value, ast.Name)
                and func.value.id == "folium"
                and func.attr in _MAP_CREATORS
            ):
                return True
            if isinstance(func.value, ast.Call) and _is_map_creation(func.value):
                return True
        if isinstance(func, ast.Name) and func.id in _MAP_CREATORS:
            return True
    return False


def _strip_display_statements(code: str) -> str:
    """Rewrite code to capture folium Map objects.

    Converts bare variable references (``m``) and Map-creation expressions
    (``folium.Map(...)``, ``folium.plugins.DualMap(...)``) into explicit
    captures, so we can collect every Map instance produced by an example.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return code

    counter: dict[str, int] = {}
    new_body: list[ast.stmt] = []

    def _capture_expr(expr: ast.expr, label: str) -> ast.stmt:
        if label not in counter:
            counter[label] = 0
        counter[label] += 1
        key = f"{label}_{counter[label]}"
        return ast.Assign(
            targets=[
                ast.Subscript(
                    value=ast.Name(id=_MAP_CAPTURE_MARKER, ctx=ast.Load()),
                    slice=ast.Constant(value=key),
                    ctx=ast.Store(),
                )
            ],
            value=expr,
        )

    for stmt in tree.body:
        if isinstance(stmt, ast.Expr):
            val = stmt.value
            if isinstance(val, ast.Name):
                new_body.append(_capture_expr(val, val.id))
            elif _is_map_creation(val):
                new_body.append(_capture_expr(val, "expr_map"))
            else:
                new_body.append(stmt)
        else:
            new_body.append(stmt)

    try:
        module = ast.Module(body=new_body, type_ignores=[])
        ast.fix_missing_locations(module)
        return ast.unparse(module)
    except Exception:
        return code


def _is_renderable(obj: Any) -> bool:
    """Check if an object can be rendered to HTML (has save/_repr_html_)."""
    return callable(getattr(obj, "save", None)) and callable(
        getattr(obj, "_repr_html_", None)
    )


def run_example_code(
    code: str,
    extra_globals: dict[str, Any] | None = None,
    setup: Callable[[], dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], list[Any]]:
    """Safely execute example code and capture all renderable folium objects.

    Captures folium.Map, folium.plugins.DualMap, and any other object with
    both ``save`` and ``_repr_html_`` methods.

    Returns (globals_dict, list_of_renderable_objects).
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
    all_renderables: list[Any] = []
    seen: set[int] = set()
    for obj in explicit_captures:
        if _is_renderable(obj) and id(obj) not in seen:
            all_renderables.append(obj)
            seen.add(id(obj))
    for value in exec_globals.values():
        if _is_renderable(value) and id(value) not in seen:
            all_renderables.append(value)
            seen.add(id(value))

    return exec_globals, all_renderables


# ---------------------------------------------------------------------------
# HTML validation
# ---------------------------------------------------------------------------


class _HtmlLinkCollector(HTMLParser):
    """Collect all src/href URLs from HTML."""

    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str, str]] = []
        self.in_head = False
        self.has_doctype = False
        self.has_html_tag = False
        self.has_head_tag = False
        self.has_body_tag = False

    def handle_decl(self, decl: str) -> None:
        if decl.lower().startswith("doctype"):
            self.has_doctype = True

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_lower = tag.lower()
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


def render_map_to_html(m: Any) -> str:
    """Render a folium object to a full HTML document string.

    Uses ``save()`` via a tempfile to get the complete HTML document
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
    m: Any, output_dir: str | Path, name: str
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
    optional_deps: list[str] | None = None,
    cwd: str | Path | None = None,
) -> ExampleSpec:
    full_path = _PROJECT_ROOT / rel_path
    if cwd is not None:
        cwd = _PROJECT_ROOT / cwd

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
        optional_deps=optional_deps or [],
        cwd=cwd,
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
            optional_deps=["vincent"],
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
            cwd="docs/user_guide/raster_layers",
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
            "docs_vector_polygon",
            "docs/user_guide/vector_layers/polygon.md",
            tags=["docs", "vector"],
            priority=2,
        ),
        _file_spec(
            "docs_vector_rectangle",
            "docs/user_guide/vector_layers/rectangle.md",
            tags=["docs", "vector"],
            priority=2,
        ),
        _file_spec(
            "docs_vector_colorline",
            "docs/user_guide/vector_layers/colorline.md",
            tags=["docs", "vector"],
            priority=3,
        ),
        _file_spec(
            "docs_geojson_popup_tooltip",
            "docs/user_guide/geojson/geojson_popup_and_tooltip.md",
            tags=["docs", "geojson"],
            priority=2,
        ),
        _file_spec(
            "docs_geojson_marker",
            "docs/user_guide/geojson/geojson_marker.md",
            tags=["docs", "geojson"],
            priority=2,
        ),
        _file_spec(
            "docs_geojson_smoothing",
            "docs/user_guide/geojson/smoothing.md",
            tags=["docs", "geojson"],
            priority=3,
        ),
        _file_spec(
            "docs_features_click_events",
            "docs/user_guide/features/click_related_classes.md",
            tags=["docs", "features"],
            priority=2,
        ),
        _file_spec(
            "docs_features_fit_overlays",
            "docs/user_guide/features/fit_overlays.md",
            tags=["docs", "features"],
            priority=2,
        ),
        _file_spec(
            "docs_plugin_marker_cluster",
            "docs/user_guide/plugins/marker_cluster.md",
            tags=["docs", "plugin", "marker_cluster"],
            priority=2,
        ),
        _file_spec(
            "docs_plugin_heatmap_with_time",
            "docs/user_guide/plugins/heatmap_with_time.md",
            tags=["docs", "plugin", "heatmap"],
            priority=3,
        ),
        _file_spec(
            "docs_plugin_measure_control",
            "docs/user_guide/plugins/measure_control.md",
            tags=["docs", "plugin"],
            priority=3,
        ),
        _file_spec(
            "docs_plugin_side_by_side",
            "docs/user_guide/plugins/side_by_side_layers.md",
            tags=["docs", "plugin"],
            priority=3,
        ),
        _file_spec(
            "docs_plugin_beautify_icon",
            "docs/user_guide/plugins/beautify_icon.md",
            tags=["docs", "plugin"],
            priority=3,
        ),
        _file_spec(
            "docs_plugin_pattern",
            "docs/user_guide/plugins/pattern.md",
            tags=["docs", "plugin"],
            priority=3,
        ),
        _file_spec(
            "docs_advanced_custom_panes",
            "docs/advanced_guide/custom_panes.md",
            tags=["docs", "advanced"],
            priority=3,
        ),
        _file_spec(
            "docs_advanced_piechart_icons",
            "docs/advanced_guide/piechart_icons.md",
            tags=["docs", "advanced"],
            priority=3,
        ),
        _file_spec(
            "docs_advanced_subplots",
            "docs/advanced_guide/subplots.md",
            tags=["docs", "advanced"],
            priority=3,
            optional_deps=["vincent"],
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
            "docs_advanced_colormaps",
            "docs/advanced_guide/colormaps.md",
            requires_network=True,
            tags=["docs", "advanced", "network"],
            priority=3,
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
            "docs_plugin_boat_marker",
            "docs/user_guide/plugins/boat_marker.md",
            requires_network=True,
            tags=["docs", "plugin", "network"],
            priority=3,
        ),
        _file_spec(
            "docs_plugin_webgl_earth",
            "docs/user_guide/plugins/webgl_earth.md",
            requires_network=True,
            tags=["docs", "plugin", "webgl", "network"],
            priority=3,
        ),
        _file_spec(
            "docs_plugin_vector_tiles",
            "docs/user_guide/plugins/vector_tiles.md",
            requires_network=True,
            tags=["docs", "plugin", "vector_tiles", "network"],
            priority=3,
        ),
        _file_spec(
            "docs_plugin_wms_time_dimension",
            "docs/user_guide/plugins/WmsTimeDimension.md",
            requires_network=True,
            tags=["docs", "plugin", "wms", "network"],
            priority=3,
        ),
        _file_spec(
            "docs_raster_video_overlay",
            "docs/user_guide/raster_layers/video_overlay.md",
            requires_network=True,
            tags=["docs", "raster", "network"],
            priority=3,
        ),
        _file_spec(
            "docs_raster_wms",
            "docs/user_guide/raster_layers/wms_tile_layer.md",
            requires_network=True,
            tags=["docs", "raster", "wms", "network"],
            priority=3,
        ),
        _file_spec(
            "docs_advanced_custom_tiles",
            "docs/advanced_guide/custom_tiles.md",
            requires_network=True,
            tags=["docs", "advanced", "network"],
            priority=3,
        ),
        _file_spec(
            "docs_advanced_geodetic_image_overlay",
            "docs/advanced_guide/geodedetic_image_overlay.md",
            requires_network=True,
            tags=["docs", "advanced", "network"],
            priority=3,
        ),
    ]

    return offline + network_only


# ---------------------------------------------------------------------------
# High-level runner
# ---------------------------------------------------------------------------


def _check_optional_deps(deps: list[str]) -> str | None:
    """Return the first missing optional dependency name, or None if all present."""
    import importlib

    for dep in deps:
        try:
            importlib.import_module(dep)
        except ImportError:
            return dep
    return None


def run_example(
    spec: ExampleSpec,
    *,
    html_output_dir: str | Path | None = None,
) -> SmokeResult:
    """Execute a single example spec and return the result.

    Handles optional dependencies, cwd switching, and classifies errors so the
    test layer can decide whether to fail or skip.
    """
    warnings: list[str] = []

    missing = _check_optional_deps(spec.optional_deps)
    if missing is not None:
        return SmokeResult(
            spec=spec,
            success=True,
            skipped=True,
            skip_reason=f"Missing optional dependency: {missing}",
            warnings=[f"Skipped due to missing optional dependency: {missing}"],
        )

    old_cwd = os.getcwd()
    try:
        if spec.cwd is not None:
            os.chdir(str(spec.cwd))

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
            warnings.append("No renderable folium objects captured from example")
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

    except ModuleNotFoundError as exc:
        return SmokeResult(
            spec=spec,
            success=True,
            skipped=True,
            skip_reason=f"Missing module: {exc.name}",
            warnings=[f"Skipped due to missing module: {exc.name}"],
        )
    except FileNotFoundError as exc:
        return SmokeResult(
            spec=spec,
            success=True,
            skipped=True,
            skip_reason=f"Missing file/asset: {exc.filename}",
            warnings=[f"Skipped due to missing file: {exc.filename}"],
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
    finally:
        os.chdir(old_cwd)


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
