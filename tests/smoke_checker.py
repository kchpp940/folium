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


@dataclass
class FilePolicy:
    """Policy override for a discovered source file.

    Any field set to a non-None value overrides the auto-discovered default.
    Set ``skip=True`` with a reason to exclude a file from smoke testing.
    """

    skip: bool | None = None
    skip_reason: str | None = None
    requires_network: bool | None = None
    priority: int | None = None
    tags: list[str] | None = None
    optional_deps: list[str] | None = None
    cwd: str | None = None
    preamble: str | None = None


@dataclass
class AuditEntry:
    """Single file's audit entry for coverage summary."""

    source: str
    source_kind: str
    has_code: bool
    code_lines: int
    registered: bool
    requires_network: bool
    priority: int
    skip_reason: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass
class AuditSummary:
    """Full coverage audit across all source files."""

    entries: list[AuditEntry] = field(default_factory=list)

    def by_category(self) -> dict[str, list[AuditEntry]]:
        cats: dict[str, list[AuditEntry]] = {}
        for e in self.entries:
            cats.setdefault(e.source_kind, []).append(e)
        return cats

    def format_report(self) -> str:
        lines: list[str] = []
        lines.append("=" * 90)
        lines.append("FOLIUM SMOKE TEST COVERAGE AUDIT")
        lines.append("=" * 90)
        by_cat = self.by_category()
        for cat in sorted(by_cat.keys()):
            items = by_cat[cat]
            total = len(items)
            with_code = sum(1 for e in items if e.has_code)
            registered = sum(1 for e in items if e.registered)
            skipped = sum(1 for e in items if e.registered and e.skip_reason)
            net = sum(1 for e in items if e.registered and e.requires_network)
            p1 = sum(1 for e in items if e.priority == 1)
            p2 = sum(1 for e in items if e.priority == 2)
            p3 = sum(1 for e in items if e.priority == 3)
            lines.append("")
            lines.append(f"  {cat}")
            lines.append(f"    files total:        {total}")
            lines.append(f"    with code blocks:   {with_code}")
            lines.append(f"    in smoke registry:  {registered}")
            lines.append(f"      skipped:          {skipped}")
            lines.append(f"      needs network:    {net}")
            lines.append(f"      by priority:      p1={p1}  p2={p2}  p3={p3}")
            lines.append("")
            unregistered = [e for e in items if e.has_code and not e.registered]
            if unregistered:
                lines.append(f"    ⚠  UNREGISTERED files with code ({len(unregistered)}):")
                for e in sorted(unregistered, key=lambda x: x.source):
                    lines.append(f"      - {e.source}  [{e.code_lines} lines]")
            skipped_items = [e for e in items if e.registered and e.skip_reason]
            if skipped_items:
                lines.append(f"    ℹ  SKIPPED files ({len(skipped_items)}):")
                for e in sorted(skipped_items, key=lambda x: x.source):
                    lines.append(f"      - {e.source}  ({e.skip_reason})")
        lines.append("")
        lines.append("=" * 90)
        total_all = len(self.entries)
        total_code = sum(1 for e in self.entries if e.has_code)
        total_reg = sum(1 for e in self.entries if e.registered)
        lines.append(
            f"  OVERALL: {total_reg}/{total_code} code-bearing files registered "
            f"({100*total_reg/total_code:.0f}% coverage over {total_all} files)"
        )
        lines.append("=" * 90)
        return "\n".join(lines)


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


def _sanitize_code(code: str) -> str:
    """Remove IPython magics, shell escapes, and other non-Python lines."""
    clean_lines: list[str] = []
    for line in code.splitlines():
        stripped = line.lstrip()
        if stripped.startswith(("%", "!", "?")):
            continue
        clean_lines.append(line)
    return "\n".join(clean_lines)


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

    sanitized = _sanitize_code(code)
    prepared_code = _strip_display_statements(sanitized)
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


# ---------------------------------------------------------------------------
# Policy manifest — per-file overrides for auto-discovered sources.
#
# Keys are relative paths from the project root.
# Any non-None field in FilePolicy overrides the auto-discovered default.
# ---------------------------------------------------------------------------


POLICY_MANIFEST: dict[str, FilePolicy] = {
    # --- README ---
    "README.rst": FilePolicy(
        priority=1,
        tags=["readme"],
    ),
    # --- Core docs/user_guide (priority 1/2, offline) ---
    "docs/getting_started.md": FilePolicy(
        priority=1,
        tags=["docs", "getting_started"],
        requires_network=True,
    ),
    "docs/user_guide/map.md": FilePolicy(
        priority=1,
        tags=["docs", "map"],
    ),
    "docs/user_guide/ui_elements/icons.md": FilePolicy(
        priority=2,
        tags=["docs", "ui"],
    ),
    "docs/user_guide/ui_elements/popups.md": FilePolicy(
        priority=2,
        tags=["docs", "ui"],
        optional_deps=["vincent"],
    ),
    "docs/user_guide/ui_elements/layer_control.md": FilePolicy(
        priority=2,
        tags=["docs", "ui"],
    ),
    "docs/user_guide/ui_elements/control.md": FilePolicy(
        priority=3,
        tags=["docs", "ui"],
    ),
    "docs/user_guide/vector_layers/circle_and_circle_marker.md": FilePolicy(
        priority=1,
        tags=["docs", "vector"],
    ),
    "docs/user_guide/vector_layers/polyline.md": FilePolicy(
        priority=1,
        tags=["docs", "vector"],
    ),
    "docs/user_guide/vector_layers/polygon.md": FilePolicy(
        priority=2,
        tags=["docs", "vector"],
    ),
    "docs/user_guide/vector_layers/rectangle.md": FilePolicy(
        priority=2,
        tags=["docs", "vector"],
    ),
    "docs/user_guide/vector_layers/colorline.md": FilePolicy(
        priority=3,
        tags=["docs", "vector"],
    ),
    "docs/user_guide/raster_layers/tiles.md": FilePolicy(
        priority=2,
        tags=["docs", "raster"],
    ),
    "docs/user_guide/raster_layers/image_overlay.md": FilePolicy(
        priority=2,
        tags=["docs", "raster"],
        cwd="docs/user_guide/raster_layers",
    ),
    "docs/user_guide/raster_layers/video_overlay.md": FilePolicy(
        priority=3,
        tags=["docs", "raster", "network"],
        requires_network=True,
    ),
    "docs/user_guide/raster_layers/wms_tile_layer.md": FilePolicy(
        priority=3,
        tags=["docs", "raster", "wms", "network"],
        requires_network=True,
    ),
    "docs/user_guide/geojson/geojson.md": FilePolicy(
        priority=1,
        tags=["docs", "geojson", "network"],
        requires_network=True,
    ),
    "docs/user_guide/geojson/choropleth.md": FilePolicy(
        priority=1,
        tags=["docs", "geojson", "choropleth", "network"],
        requires_network=True,
    ),
    "docs/user_guide/geojson/geojson_popup_and_tooltip.md": FilePolicy(
        priority=2,
        tags=["docs", "geojson"],
    ),
    "docs/user_guide/geojson/geojson_marker.md": FilePolicy(
        priority=2,
        tags=["docs", "geojson"],
    ),
    "docs/user_guide/geojson/smoothing.md": FilePolicy(
        priority=3,
        tags=["docs", "geojson"],
    ),
    "docs/user_guide/geojson/geojson_advanced_on_each_feature.md": FilePolicy(
        priority=3,
        tags=["docs", "geojson"],
    ),
    "docs/user_guide/geojson/coordinate_ordering.md": FilePolicy(
        priority=3,
        tags=["docs", "geojson"],
    ),
    "docs/user_guide/geojson/geopandas_and_geo_interface.md": FilePolicy(
        priority=3,
        tags=["docs", "geojson", "geopandas", "network"],
        requires_network=True,
    ),
    "docs/user_guide/features/click_related_classes.md": FilePolicy(
        priority=2,
        tags=["docs", "features"],
    ),
    "docs/user_guide/features/fit_overlays.md": FilePolicy(
        priority=2,
        tags=["docs", "features"],
    ),
    # --- plugins (most are offline, some need network) ---
    "docs/user_guide/plugins/antpath.md": FilePolicy(
        priority=1,
        tags=["docs", "plugin", "antpath"],
    ),
    "docs/user_guide/plugins/heatmap.md": FilePolicy(
        priority=2,
        tags=["docs", "plugin", "heatmap"],
    ),
    "docs/user_guide/plugins/heatmap_with_time.md": FilePolicy(
        priority=3,
        tags=["docs", "plugin", "heatmap"],
    ),
    "docs/user_guide/plugins/marker_cluster.md": FilePolicy(
        priority=2,
        tags=["docs", "plugin", "marker_cluster"],
    ),
    "docs/user_guide/plugins/mini_map.md": FilePolicy(
        priority=2,
        tags=["docs", "plugin", "minimap"],
    ),
    "docs/user_guide/plugins/fullscreen.md": FilePolicy(
        priority=2,
        tags=["docs", "plugin"],
    ),
    "docs/user_guide/plugins/draw.md": FilePolicy(
        priority=2,
        tags=["docs", "plugin", "draw"],
    ),
    "docs/user_guide/plugins/dual_map.md": FilePolicy(
        priority=2,
        tags=["docs", "plugin", "dual_map"],
    ),
    "docs/user_guide/plugins/search.md": FilePolicy(
        priority=3,
        tags=["docs", "plugin", "search", "network"],
        requires_network=True,
    ),
    "docs/user_guide/plugins/realtime.md": FilePolicy(
        priority=3,
        tags=["docs", "plugin", "realtime", "network"],
        requires_network=True,
    ),
    "docs/user_guide/plugins/geocoder.md": FilePolicy(
        priority=3,
        tags=["docs", "plugin", "geocoder", "network"],
        requires_network=True,
    ),
    "docs/user_guide/plugins/boat_marker.md": FilePolicy(
        priority=3,
        tags=["docs", "plugin", "network"],
        requires_network=True,
    ),
    "docs/user_guide/plugins/webgl_earth.md": FilePolicy(
        priority=3,
        tags=["docs", "plugin", "webgl", "network"],
        requires_network=True,
    ),
    "docs/user_guide/plugins/vector_tiles.md": FilePolicy(
        priority=3,
        tags=["docs", "plugin", "vector_tiles", "network"],
        requires_network=True,
    ),
    "docs/user_guide/plugins/WmsTimeDimension.md": FilePolicy(
        priority=3,
        tags=["docs", "plugin", "wms", "network"],
        requires_network=True,
    ),
    "docs/user_guide/plugins/measure_control.md": FilePolicy(
        priority=3,
        tags=["docs", "plugin"],
    ),
    "docs/user_guide/plugins/side_by_side_layers.md": FilePolicy(
        priority=3,
        tags=["docs", "plugin"],
    ),
    "docs/user_guide/plugins/beautify_icon.md": FilePolicy(
        priority=3,
        tags=["docs", "plugin"],
    ),
    "docs/user_guide/plugins/pattern.md": FilePolicy(
        priority=3,
        tags=["docs", "plugin"],
    ),
    # Additional plugins — default priority 3, let auto-discovery detect offline/network
    "docs/user_guide/plugins/timeslider_choropleth.md": FilePolicy(priority=3, tags=["docs", "plugin"]),
    "docs/user_guide/plugins/timestamped_geojson.md": FilePolicy(priority=3, tags=["docs", "plugin"]),
    "docs/user_guide/plugins/timeline.md": FilePolicy(priority=3, tags=["docs", "plugin"]),
    "docs/user_guide/plugins/treelayercontrol.md": FilePolicy(priority=3, tags=["docs", "plugin"]),
    "docs/user_guide/plugins/terminator.md": FilePolicy(priority=3, tags=["docs", "plugin"]),
    "docs/user_guide/plugins/scroll_zoom_toggler.md": FilePolicy(priority=3, tags=["docs", "plugin"]),
    "docs/user_guide/plugins/polyline_offset.md": FilePolicy(priority=3, tags=["docs", "plugin"]),
    "docs/user_guide/plugins/semi_circle.md": FilePolicy(priority=3, tags=["docs", "plugin"]),
    "docs/user_guide/plugins/polyline_encoded.md": FilePolicy(priority=3, tags=["docs", "plugin"]),
    "docs/user_guide/plugins/overlapping_marker_spiderfier.md": FilePolicy(priority=3, tags=["docs", "plugin"]),
    "docs/user_guide/plugins/polyline_textpath.md": FilePolicy(priority=3, tags=["docs", "plugin"]),
    "docs/user_guide/plugins/tag_filter_button.md": FilePolicy(priority=3, tags=["docs", "plugin"]),
    "docs/user_guide/plugins/polygon_encoded.md": FilePolicy(priority=3, tags=["docs", "plugin"]),
    "docs/user_guide/plugins/mouse_position.md": FilePolicy(priority=3, tags=["docs", "plugin"]),
    "docs/user_guide/plugins/locate_control.md": FilePolicy(priority=3, tags=["docs", "plugin"]),
    "docs/user_guide/plugins/float_image.md": FilePolicy(priority=3, tags=["docs", "plugin"]),
    "docs/user_guide/plugins/grouped_layer_control.md": FilePolicy(priority=3, tags=["docs", "plugin"]),
    "docs/user_guide/plugins/geoman.md": FilePolicy(priority=3, tags=["docs", "plugin"]),
    "docs/user_guide/plugins/featuregroup_subgroup.md": FilePolicy(priority=3, tags=["docs", "plugin"]),
    # --- Advanced guide ---
    "docs/advanced_guide/custom_panes.md": FilePolicy(
        priority=3,
        tags=["docs", "advanced"],
    ),
    "docs/advanced_guide/colormaps.md": FilePolicy(
        priority=3,
        tags=["docs", "advanced", "network"],
        requires_network=True,
    ),
    "docs/advanced_guide/piechart_icons.md": FilePolicy(
        priority=3,
        tags=["docs", "advanced"],
    ),
    "docs/advanced_guide/subplots.md": FilePolicy(
        priority=3,
        tags=["docs", "advanced"],
        optional_deps=["vincent"],
    ),
    "docs/advanced_guide/custom_tiles.md": FilePolicy(
        priority=3,
        tags=["docs", "advanced", "network"],
        requires_network=True,
    ),
    "docs/advanced_guide/geodedetic_image_overlay.md": FilePolicy(
        priority=3,
        tags=["docs", "advanced", "network"],
        requires_network=True,
    ),
    "docs/advanced_guide/customize_javascript_and_css.md": FilePolicy(
        priority=3,
        tags=["docs", "advanced"],
    ),
    "docs/advanced_guide/world_copy.md": FilePolicy(
        priority=3,
        tags=["docs", "advanced"],
    ),
    "docs/advanced_guide/override_leaflet_class_methods.md": FilePolicy(
        priority=3,
        tags=["docs", "advanced"],
    ),
    "docs/advanced_guide/polygons_from_list_of_points.md": FilePolicy(
        priority=3,
        tags=["docs", "advanced"],
    ),
    "docs/advanced_guide/choropleth with Jenks natural breaks optimization.md": FilePolicy(
        priority=3,
        tags=["docs", "advanced", "choropleth"],
        optional_deps=["jenkspy"],
    ),
    # --- examples/ directory ---
    # Most notebooks are empty redirects; Flask example is standalone
    "examples/flask_example.py": FilePolicy(
        skip=True,
        skip_reason="Flask web app example, no renderable folium Map object",
        tags=["examples", "flask"],
    ),
    # Empty redirect notebooks — skipped with reason
    "examples/Quickstart.ipynb": FilePolicy(skip=True, skip_reason="Redirect-only notebook, no code cells"),
    "examples/Features.ipynb": FilePolicy(skip=True, skip_reason="Redirect-only notebook, no code cells"),
    "examples/VectorLayers.ipynb": FilePolicy(skip=True, skip_reason="Redirect-only notebook, no code cells"),
    "examples/Plugins.ipynb": FilePolicy(skip=True, skip_reason="Redirect-only notebook, no code cells"),
    "examples/MarkerCluster.ipynb": FilePolicy(skip=True, skip_reason="Redirect-only notebook, no code cells"),
    "examples/GeoJSON_and_choropleth.ipynb": FilePolicy(skip=True, skip_reason="Redirect-only notebook, no code cells"),
    "examples/Heatmap.ipynb": FilePolicy(skip=True, skip_reason="Redirect-only notebook, no code cells"),
    "examples/Popups.ipynb": FilePolicy(skip=True, skip_reason="Redirect-only notebook, no code cells"),
    "examples/ImageOverlay.ipynb": FilePolicy(skip=True, skip_reason="Redirect-only notebook, no code cells"),
    "examples/Geopandas_and_geo_interface.ipynb": FilePolicy(skip=True, skip_reason="Redirect-only notebook, no code cells"),
    "examples/WMS_and_WMTS.ipynb": FilePolicy(skip=True, skip_reason="Redirect-only notebook, no code cells"),
    "examples/plugin-Search.ipynb": FilePolicy(skip=True, skip_reason="Redirect-only notebook, no code cells"),
}


# ---------------------------------------------------------------------------
# Auto-discovery — scan the filesystem for verifiable source files.
# ---------------------------------------------------------------------------


def _classify_source(rel_path: str) -> str:
    p = rel_path.replace("\\", "/")
    if p == "README.rst" or p.startswith("README"):
        return "README"
    if p.startswith("docs/"):
        if "advanced_guide" in p:
            return "docs/advanced_guide"
        if "user_guide/plugins" in p:
            return "docs/user_guide/plugins"
        if "user_guide/geojson" in p:
            return "docs/user_guide/geojson"
        if "user_guide" in p:
            return "docs/user_guide"
        return "docs/other"
    if p.startswith("examples/"):
        return "examples"
    return "other"


def discover_source_files() -> list[tuple[str, str]]:
    """Return list of (relative_path, source_category) for all candidate files.

    Scans:
      - README*
      - docs/**/*.{md,rst}
      - examples/**/*.{ipynb,py}
    """
    results: list[tuple[str, str]] = []
    root = _PROJECT_ROOT

    patterns: list[tuple[str, str]] = [
        ("README*", ""),
        ("docs/**/*.md", ""),
        ("docs/**/*.rst", ""),
        ("examples/*.ipynb", ""),
        ("examples/**/*.py", ""),
    ]
    seen: set[str] = set()
    for pat, _ in patterns:
        for match in root.glob(pat):
            if not match.is_file():
                continue
            rel = str(match.relative_to(root)).replace("\\", "/")
            if rel in seen:
                continue
            seen.add(rel)
            cat = _classify_source(rel)
            # Skip index/toctree RST files (they have no code)
            if rel.endswith(".rst") and cat.startswith("docs/"):
                results.append((rel, cat))
            else:
                results.append((rel, cat))
    results.sort()
    return results


def _auto_tags_from_path(rel_path: str) -> list[str]:
    tags: list[str] = []
    p = rel_path.replace("\\", "/")
    if p.startswith("docs/"):
        tags.append("docs")
        if "plugins" in p:
            tags.append("plugin")
        if "advanced_guide" in p:
            tags.append("advanced")
        if "geojson" in p.lower():
            tags.append("geojson")
    elif p.startswith("examples/"):
        tags.append("examples")
    elif p.lower().startswith("readme"):
        tags.append("readme")
    return tags


def _auto_priority_from_path(rel_path: str) -> int:
    p = rel_path.replace("\\", "/")
    if p in ("README.rst", "README.md", "docs/getting_started.md"):
        return 1
    if p.startswith("docs/user_guide/") and "plugins" not in p:
        return 2
    return 3


def _apply_policy(spec: ExampleSpec, policy: FilePolicy | None) -> ExampleSpec:
    if policy is None:
        return spec
    if policy.skip is not None:
        spec.skip = policy.skip
    if policy.skip_reason is not None:
        spec.skip_reason = policy.skip_reason
    if policy.requires_network is not None:
        spec.requires_network = policy.requires_network
    if policy.priority is not None:
        spec.priority = policy.priority
    if policy.tags is not None:
        spec.tags = list(dict.fromkeys(spec.tags + policy.tags))
    if policy.optional_deps is not None:
        spec.optional_deps = list(dict.fromkeys(spec.optional_deps + policy.optional_deps))
    if policy.cwd is not None:
        spec.cwd = _PROJECT_ROOT / policy.cwd
    return spec


def build_example_registry_from_discovery() -> list[ExampleSpec]:
    """Build registry purely from file-system discovery + policy manifest.

    Inline examples (regression specs) are NOT included here; combine with
    build_example_registry() for the full set.
    """
    specs: list[ExampleSpec] = []
    for rel_path, source_kind in discover_source_files():
        full_path = _PROJECT_ROOT / rel_path
        try:
            raw_code = extract_code_from_file(full_path)
        except Exception:
            raw_code = ""
        code_lines = [l for l in raw_code.splitlines() if l.strip()]

        # If file has no code, still register it (for audit) but mark skip
        has_code = len(code_lines) > 0

        # Derive a friendly name
        stem = Path(rel_path).stem
        safe_stem = re.sub(r"[^a-zA-Z0-9_]", "_", stem)
        if source_kind == "README":
            name = "readme_rst"
        elif rel_path.startswith("docs/"):
            rel_no_ext = rel_path[: rel_path.rfind(".")]
            parts = rel_no_ext.split("/")[1:]  # drop 'docs/'
            name = "docs_" + "_".join(re.sub(r"[^a-zA-Z0-9_]", "_", p) for p in parts)
        elif rel_path.startswith("examples/"):
            name = "examples_" + safe_stem
        else:
            name = safe_stem

        policy = POLICY_MANIFEST.get(rel_path)
        auto_tags = _auto_tags_from_path(rel_path)
        auto_priority = _auto_priority_from_path(rel_path)

        preamble = ""
        cwd_val: str | Path | None = None
        optional_deps: list[str] = []
        if policy is not None:
            if policy.preamble is not None:
                preamble = policy.preamble
            if policy.cwd is not None:
                cwd_val = _PROJECT_ROOT / policy.cwd
            if policy.optional_deps is not None:
                optional_deps = list(policy.optional_deps)

        full_path_ref = full_path

        def _setup_factory(
            p: Path, pre: str
        ) -> Callable[[], dict[str, Any]]:
            def _setup() -> dict[str, Any]:
                code = extract_code_from_file(p)
                if pre:
                    code = pre + "\n" + code
                return {"__preloaded_code__": code}
            return _setup

        spec = ExampleSpec(
            name=name,
            source=rel_path,
            kind="file",
            requires_network=False,
            priority=auto_priority,
            tags=auto_tags,
            setup=_setup_factory(full_path_ref, preamble),
            optional_deps=optional_deps,
            cwd=cwd_val,
        )
        if not has_code:
            spec.skip = True
            spec.skip_reason = "No executable code blocks found"
        spec = _apply_policy(spec, policy)
        specs.append(spec)
    return specs


def build_audit_summary(
    registry: list[ExampleSpec] | None = None,
) -> AuditSummary:
    """Build a full coverage audit of all discovered source files."""
    if registry is None:
        registry = build_example_registry()
    reg_by_source: dict[str, ExampleSpec] = {
        s.source: s for s in registry if s.kind == "file"
    }
    summary = AuditSummary()
    for rel_path, source_kind in discover_source_files():
        has_code = False
        code_lines = 0
        try:
            raw_code = extract_code_from_file(_PROJECT_ROOT / rel_path)
            lines = [l for l in raw_code.splitlines() if l.strip()]
            has_code = len(lines) > 0
            code_lines = len(lines)
        except Exception:
            pass
        spec = reg_by_source.get(rel_path)
        if spec is not None:
            registered = not (spec.skip and spec.skip_reason == "No executable code blocks found")
            summary.entries.append(
                AuditEntry(
                    source=rel_path,
                    source_kind=source_kind,
                    has_code=has_code,
                    code_lines=code_lines,
                    registered=registered,
                    requires_network=spec.requires_network,
                    priority=spec.priority,
                    skip_reason=spec.skip_reason if registered else "",
                    tags=list(spec.tags),
                )
            )
        else:
            summary.entries.append(
                AuditEntry(
                    source=rel_path,
                    source_kind=source_kind,
                    has_code=has_code,
                    code_lines=code_lines,
                    registered=False,
                    requires_network=False,
                    priority=0,
                    tags=[],
                )
            )
    return summary


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


def _core_inline_examples() -> list[ExampleSpec]:
    """Hand-curated regression tests for the most critical APIs.

    These complement auto-discovered file-based examples and guarantee a
    minimal set of core functionality is always exercised.
    """
    return [
        _inline_spec(
            "core_basic_map",
            "import folium\nm = folium.Map(location=(45.5236, -122.6750))\n",
            tags=["core", "getting_started"],
            priority=1,
        ),
        _inline_spec(
            "core_marker",
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
            priority=1,
        ),
        _inline_spec(
            "core_polyline",
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
            priority=1,
        ),
        _inline_spec(
            "core_layer_control",
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
            priority=1,
        ),
        _inline_spec(
            "core_map_bounds_limits",
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
            priority=1,
        ),
        _inline_spec(
            "core_vector_shapes",
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
            priority=1,
        ),
        _inline_spec(
            "core_plugin_antpath",
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
            tags=["core", "plugin", "antpath"],
            priority=1,
        ),
        _inline_spec(
            "core_geojson_local_file",
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
            priority=1,
        ),
        _inline_spec(
            "core_choropleth_local",
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
        _inline_spec(
            "network_tile_custom_provider",
            "import folium\nm = folium.Map((45.5236, -122.6750), tiles='cartodb positron')\n",
            requires_network=True,
            tags=["core", "network", "tiles"],
            priority=1,
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
            tags=["core", "network", "geojson"],
            priority=1,
        ),
    ]


def build_example_registry() -> list[ExampleSpec]:
    """Build the full registry of smoke test examples.

    Combines:
      1. Hand-curated core inline examples (critical regression tests).
      2. All files auto-discovered from docs/, examples/, README — with
         per-file policy applied from POLICY_MANIFEST.
    """
    all_specs: list[ExampleSpec] = list(_core_inline_examples())
    all_specs.extend(build_example_registry_from_discovery())
    return all_specs


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
