"""
Smoke test policy and marker metadata collection.

Provides:
  - Test marker definitions (from conftest.py)
  - Smoke test example registry metadata (from tests/smoke_checker.py)
  - HTML validation capabilities (re-used from smoke_checker)

This is an INTERNAL module. Do NOT import from public API.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from folium._audit.resources import FOLIUM_ROOT

PROJECT_ROOT = FOLIUM_ROOT.parent
TESTS_DIR = PROJECT_ROOT / "tests"
CONFTEST_PATH = TESTS_DIR / "conftest.py"
SMOKE_CHECKER_PATH = TESTS_DIR / "smoke_checker.py"
PYPROJECT_PATH = PROJECT_ROOT / "pyproject.toml"


def _source_available(path: Path) -> bool:
    """Check if a source file is available (not missing from installed package)."""
    return path.exists()


TEST_MARKERS: list[dict[str, Any]] = [
    {
        "name": "core",
        "description": "Core library unit tests (always run)",
        "runs_by_default": True,
        "required_flag": None,
    },
    {
        "name": "plugins",
        "description": "Plugin unit tests (always run)",
        "runs_by_default": True,
        "required_flag": None,
    },
    {
        "name": "audit",
        "description": "Release resource and API audit checks",
        "runs_by_default": True,
        "required_flag": None,
    },
    {
        "name": "smoke",
        "description": "Offline smoke tests for examples and docs",
        "runs_by_default": True,
        "required_flag": None,
    },
    {
        "name": "external_data",
        "description": "Tests that download external data (skip unless --run-external-data)",
        "runs_by_default": False,
        "required_flag": "--run-external-data",
    },
    {
        "name": "render",
        "description": "HTML render tests (skip unless --run-render)",
        "runs_by_default": False,
        "required_flag": "--run-render",
    },
    {
        "name": "selenium",
        "description": "Selenium browser tests (skip unless --run-selenium)",
        "runs_by_default": False,
        "required_flag": "--run-selenium",
    },
    {
        "name": "smoke_network",
        "description": "Smoke tests requiring network access (skip unless --run-smoke-network)",
        "runs_by_default": False,
        "required_flag": "--run-smoke-network",
    },
]


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


def extract_markers_from_conftest() -> list[dict[str, Any]]:
    """Parse conftest.py to extract marker definitions and CLI flags."""
    conftest_path = PROJECT_ROOT / "tests" / "conftest.py"
    if not conftest_path.exists():
        return []

    content = conftest_path.read_text(encoding="utf-8")

    markers: list[dict[str, Any]] = []

    import re
    marker_pattern = re.compile(
        r'"markers",\s*\n\s*"([^"]+):\s*([^"]+)"',
    )

    for match in marker_pattern.finditer(content):
        name = match.group(1).strip()
        desc = match.group(2).strip()

        runs_by_default = name in ("core", "plugins", "audit", "smoke")
        flag = f"--run-{name.replace('_', '-')}" if not runs_by_default else None

        markers.append({
            "name": name,
            "description": desc,
            "runs_by_default": runs_by_default,
            "required_flag": flag,
        })

    return markers


def collect_test_marker_summary() -> dict[str, Any]:
    """Collect a high-level summary of test markers and policies.

    Returns a dict with an 'available' top-level key indicating whether
    the source data (tests/conftest.py) was found. When unavailable,
    'reason' and 'expected_paths' explain what was missing.
    """
    expected_paths = {
        "conftest": str(CONFTEST_PATH),
        "pyproject": str(PYPROJECT_PATH),
        "tests_dir": str(TESTS_DIR),
    }

    if not _source_available(TESTS_DIR):
        return {
            "available": False,
            "reason": "tests/ directory not found - not running from a source checkout",
            "expected_paths": expected_paths,
            "markers": {},
            "marker_list": TEST_MARKERS,
            "marker_count": len(TEST_MARKERS),
            "fallback_used": True,
        }

    markers = extract_markers_from_conftest()
    fallback_used = False

    if not markers:
        markers = TEST_MARKERS
        fallback_used = True

    default_markers = [m for m in markers if m["runs_by_default"]]
    optional_markers = [m for m in markers if not m["runs_by_default"]]

    marker_map = {m["name"]: m for m in markers}

    pytest_config: dict[str, Any] = {}
    if PYPROJECT_PATH.exists():
        try:
            import tomllib
            with open(PYPROJECT_PATH, "rb") as f:
                config = tomllib.load(f)
            pytest_config = config.get("tool", {}).get("pytest", {}).get("ini_options", {})
        except (ImportError, Exception):
            pytest_config = {}

    return {
        "available": True,
        "reason": "",
        "expected_paths": expected_paths,
        "fallback_used": fallback_used,
        "markers": marker_map,
        "marker_list": markers,
        "marker_count": len(markers),
        "default_markers": [m["name"] for m in default_markers],
        "optional_markers": [m["name"] for m in optional_markers],
        "conftest_path": str(CONFTEST_PATH) if CONFTEST_PATH.exists() else None,
        "pytest_config": pytest_config,
        "run_all_flag": "--run-all",
        "flag_to_marker": {
            m["required_flag"]: m["name"]
            for m in optional_markers
            if m["required_flag"]
        },
    }


def collect_smoke_example_summary() -> dict[str, Any]:
    """Collect summary info about smoke test examples.

    Returns a dict with an 'available' top-level key indicating whether
    the smoke checker module is importable. When unavailable,
    'reason' and 'expected_paths' explain what was missing.
    """
    expected_paths = {
        "smoke_checker": str(SMOKE_CHECKER_PATH),
        "tests_dir": str(TESTS_DIR),
    }

    if not _source_available(SMOKE_CHECKER_PATH):
        return {
            "available": False,
            "reason": (
                "tests/smoke_checker.py not found - smoke example registry "
                "only available when running from a source checkout"
            ),
            "expected_paths": expected_paths,
            "total_count": 0,
            "offline_count": 0,
            "network_count": 0,
            "examples": [],
        }

    try:
        import sys
        sys.path.insert(0, str(TESTS_DIR))
        from smoke_checker import build_example_registry, filter_examples
    except Exception as e:
        return {
            "available": False,
            "reason": f"Failed to import smoke_checker: {e}",
            "expected_paths": expected_paths,
            "total_count": 0,
            "offline_count": 0,
            "network_count": 0,
            "examples": [],
        }

    registry = build_example_registry()

    offline = filter_examples(registry, include_network=False)
    network_only = filter_examples(registry, include_network=True)
    network_only = [s for s in network_only if s.requires_network]

    tags: dict[str, int] = {}
    for spec in registry:
        for tag in spec.tags:
            tags[tag] = tags.get(tag, 0) + 1

    priority_counts: dict[int, int] = {}
    for spec in registry:
        priority_counts[spec.priority] = priority_counts.get(spec.priority, 0) + 1

    examples = [
        {
            "name": spec.name,
            "source": spec.source,
            "kind": spec.kind,
            "requires_network": spec.requires_network,
            "priority": spec.priority,
            "tags": spec.tags,
        }
        for spec in registry
    ]

    return {
        "available": True,
        "reason": "",
        "expected_paths": expected_paths,
        "total_count": len(registry),
        "offline_count": len(offline),
        "network_count": len(network_only),
        "offline_examples": [e["name"] for e in examples if not e["requires_network"]],
        "network_examples": [e["name"] for e in examples if e["requires_network"]],
        "tags": tags,
        "priority_counts": priority_counts,
        "examples": examples,
    }


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


def validate_html(html: str, *, allow_network: bool = False) -> list[str]:
    """Validate rendered HTML, return list of warning/error strings."""
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
        if attr == "src" and scheme in ("http", "https"):
            if re.search(r"\bv=undefined\b", url) or "None" in url:
                warnings.append(
                    f"Possible broken URL with undefined value: <{tag} {attr}>: {url[:100]}"
                )

    return warnings
