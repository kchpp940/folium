"""
Pytest configuration for folium tests.

Test tiers (pytest markers)
---------------------------

Markers are defined in ``pyproject.toml`` ``[tool.pytest.ini_options]``
and registered here via ``pytest_configure``.  They fall into two groups:

Category tags (informational, for ``-m`` selection):
    core       Fast unit tests for folium core modules (features, map,
               utilities, vector_layers, etc.).  Runs by default.
    plugins    Tests for :mod:`folium.plugins`.  Runs by default.

Gate tags (require an explicit CLI flag to run):
    external_data  Tests that import ``geodatasets`` or make network
                   requests at runtime.  Needs ``--run-external-data``.
    render         Slow PNG rendering tests that compare against a
                   golden screenshot with ``pixelmatch``.
                   Needs ``--run-render``.
    selenium       Browser automation tests driven by Selenium / Chrome.
                   Needs ``--run-selenium``.

The flag ``--run-all`` is a shorthand that enables every gate tag.

Default run (no flags)
    ``core`` + ``plugins`` → everything that does **not** carry a gate
    tag.  This is the "fast, stable, no-network, no-browser" set every
    developer should be able to run offline.

Skip reasons explained
----------------------

Each skipped test reports exactly *why* it was skipped:

* ``Need --run-<tier> or --run-all`` – the corresponding gate flag was
  not passed (default behaviour for external/render/selenium).
* ``<dependency> not installed (--run-<tier> passed but …)`` – the gate
  flag **was** passed, but the optional Python package cannot be
  imported, so we skip cleanly instead of letting the test crash with an
  ``ImportError``.

This distinction is important: the first kind is "opt-in" (the user
asked for a subset), the second kind is "environment issue" (the user
asked for the full set but the machine is missing a piece).
"""

from __future__ import annotations

from pathlib import Path

import pytest

# Prevent pytest from treating snapshot helper modules as test modules.
# ``tests/snapshots/modules/*.py`` are imported dynamically by
# ``tests/snapshots/test_snapshots.py`` and must not be collected on their
# own (they do top-level data fetching / geopandas imports that we only
# want to pay for inside the render tier).
#
# We use ``pytest_ignore_collect`` instead of the plain ``collect_ignore``
# list because the latter does not reliably match nested sub-packages in
# all pytest versions.
collect_ignore = [
    "tests/snapshots/modules",
]


def pytest_ignore_collect(collection_path, config):
    """Skip ``tests/snapshots/modules/`` entirely during collection."""
    # collection_path is a py.path.local; convert to a Path for comparison.
    rel = Path(str(collection_path)).resolve().relative_to(
        Path(__file__).parent.resolve()
    )
    parts = rel.parts
    if len(parts) >= 2 and parts[0] == "snapshots" and parts[1] == "modules":
        return True
    return None


# ---------------------------------------------------------------------------
# Marker registration – keep in sync with pyproject.toml [tool.pytest.ini_options]
# ---------------------------------------------------------------------------

def pytest_configure(config):
    for marker in (
        "core: Fast, stable unit tests (no network, no browser, no external data). "
        "These run by default.",
        "plugins: Tests for folium plugins. These run by default.",
        "external_data: Tests requiring geodatasets, network requests, or remote APIs. "
        "Requires --run-external-data flag.",
        "render: Slow PNG rendering tests using pixelmatch comparison. "
        "Requires --run-render flag.",
        "selenium: Browser automation tests requiring Selenium webdriver. "
        "Requires --run-selenium flag.",
    ):
        config.addinivalue_line("markers", marker)


# ---------------------------------------------------------------------------
# CLI options
# ---------------------------------------------------------------------------

def pytest_addoption(parser):
    group = parser.getgroup("folium", "Folium test-tier options")
    group.addoption(
        "--run-external-data",
        action="store_true",
        default=False,
        help=(
            "Run tests marked 'external_data' (geodatasets, network requests). "
            "Without this flag those tests are SKIPPED."
        ),
    )
    group.addoption(
        "--run-render",
        action="store_true",
        default=False,
        help=(
            "Run tests marked 'render' (PNG snapshot with pixelmatch). "
            "Without this flag those tests are SKIPPED."
        ),
    )
    group.addoption(
        "--run-selenium",
        action="store_true",
        default=False,
        help=(
            "Run tests marked 'selenium' (browser automation). "
            "Without this flag those tests are SKIPPED."
        ),
    )
    group.addoption(
        "--run-all",
        action="store_true",
        default=False,
        help="Shorthand: --run-external-data --run-render --run-selenium.",
    )


# ---------------------------------------------------------------------------
# Session-scoped dependency checks – cached so we only import once
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def _folium_dep_status(request):
    """Return a dict describing which optional deps are importable."""
    status = {}

    try:
        import geodatasets  # noqa: F401
        status["geodatasets"] = True
    except ImportError:
        status["geodatasets"] = False

    try:
        from pixelmatch.contrib.PIL import pixelmatch  # noqa: F401
        from PIL import Image  # noqa: F401
        status["pixelmatch"] = True
    except ImportError:
        status["pixelmatch"] = False

    try:
        from selenium import webdriver  # noqa: F401
        from selenium.webdriver import ChromeOptions  # noqa: F401
        status["selenium"] = True
    except ImportError:
        status["selenium"] = False

    return status


@pytest.fixture(scope="session")
def geodatasets_available(_folium_dep_status):
    """Return True if geodatasets can be imported."""
    return _folium_dep_status["geodatasets"]


@pytest.fixture(scope="session")
def pixelmatch_available(_folium_dep_status):
    """Return True if pixelmatch + Pillow can both be imported."""
    return _folium_dep_status["pixelmatch"]


@pytest.fixture(scope="session")
def selenium_available(_folium_dep_status):
    """Return True if selenium + ChromeOptions can be imported."""
    return _folium_dep_status["selenium"]


# ---------------------------------------------------------------------------
# Auto-skip logic – runs before every test item
# ---------------------------------------------------------------------------

def pytest_runtest_setup(item):
    run_all = item.config.getoption("--run-all")
    run_external_data = run_all or item.config.getoption("--run-external-data")
    run_render = run_all or item.config.getoption("--run-render")
    run_selenium = run_all or item.config.getoption("--run-selenium")

    # Fetch the session-scoped dependency status without triggering
    # collection-time imports (we look it up on the session stash).
    status = _session_dep_status(item.session)

    has_external = "external_data" in item.keywords
    has_render = "render" in item.keywords
    has_selenium = "selenium" in item.keywords

    # --- external_data ---------------------------------------------------
    if has_external:
        if not run_external_data:
            pytest.skip("external_data: pass --run-external-data or --run-all")
        # Flag was passed – make sure the optional deps are there
        if not status["geodatasets"] and _uses_geodatasets(item):
            pytest.skip(
                "external_data: --run-external-data passed but geodatasets "
                "is not installed (pip install geodatasets)"
            )

    # --- render ----------------------------------------------------------
    if has_render:
        if not run_render:
            pytest.skip("render: pass --run-render or --run-all")
        if not status["pixelmatch"]:
            pytest.skip(
                "render: --run-render passed but pixelmatch/Pillow "
                "is not installed (pip install pixelmatch pillow)"
            )

    # --- selenium --------------------------------------------------------
    if has_selenium:
        if not run_selenium:
            pytest.skip("selenium: pass --run-selenium or --run-all")
        if not status["selenium"]:
            pytest.skip(
                "selenium: --run-selenium passed but selenium "
                "is not installed (pip install selenium)"
            )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _session_dep_status(session):
    """Lazily compute (and cache) optional-dependency status on the session.

    We cannot use the fixture machinery from inside a ``pytest_runtest_*``
    hook, so we cache on ``session._folium_dep_status`` instead.
    """
    cache = getattr(session, "_folium_dep_status", None)
    if cache is not None:
        return cache

    cache = {}
    try:
        import geodatasets  # noqa: F401
        cache["geodatasets"] = True
    except ImportError:
        cache["geodatasets"] = False

    try:
        from pixelmatch.contrib.PIL import pixelmatch  # noqa: F401
        from PIL import Image  # noqa: F401
        cache["pixelmatch"] = True
    except ImportError:
        cache["pixelmatch"] = False

    try:
        from selenium import webdriver  # noqa: F401
        from selenium.webdriver import ChromeOptions  # noqa: F401
        cache["selenium"] = True
    except ImportError:
        cache["selenium"] = False

    session._folium_dep_status = cache
    return cache


def _uses_geodatasets(item) -> bool:
    """Heuristic: does a test item actually depend on the geodatasets package?

    We only want to skip for missing ``geodatasets`` when the test would
    really import it.  ``test_folium.py::TestFolium::test_json_request``
    is marked ``external_data`` but only fetches a URL with ``requests``,
    so it should **not** be skipped when geodatasets is absent.
    """
    fspath = str(item.fspath) if getattr(item, "fspath", None) else ""
    if "test_time_slider_choropleth" in fspath:
        return True
    if "snapshots/modules/issue_1989" in fspath:
        return False  # uses requests + geopandas, not geodatasets
    return False


# ---------------------------------------------------------------------------
# Reporting – print a summary header so users know which tiers are active
# ---------------------------------------------------------------------------

def pytest_report_header(config):
    run_all = config.getoption("--run-all")
    run_external_data = run_all or config.getoption("--run-external-data")
    run_render = run_all or config.getoption("--run-render")
    run_selenium = run_all or config.getoption("--run-selenium")

    lines = ["folium test tiers:"]
    lines.append(
        f"  [x] core + plugins    (default, always collected)"
    )
    for name, enabled in (
        ("external_data", run_external_data),
        ("render       ", run_render),
        ("selenium     ", run_selenium),
    ):
        tag = "x" if enabled else " "
        lines.append(f"  [{tag}] {name}")
    if run_all:
        lines.append("  (--run-all: all gate tags enabled)")
    return lines


# ---------------------------------------------------------------------------
# Collection-level marker audit – enforce the tiering contract
# ---------------------------------------------------------------------------
#
# Rules applied to every collected test item:
#
# (A)  Category – every item must carry exactly ONE of {core, plugins},
#      unless it lives in a special directory that has its own contract.
#      Special directories:
#        • tests/selenium/  → every item MUST carry `selenium`
#        • tests/snapshots/ → every item MUST carry `render` + `selenium`
#      These two directories are allowed to omit the category markers
#      because their role is unambiguous from the path.
#
# (B)  Gate overlay – the markers {external_data, render, selenium} are
#      *opt-in gates only*.  They may never appear on a regular item
#      without a category marker.  On special directories, `render` and
#      `selenium` serve a dual purpose (category + gate), but
#      `external_data` remains an overlay everywhere.
#
# Any violation triggers a hard `pytest.exit` so that a new test file
# introduced without markers fails collection immediately – nobody can
# accidentally ship an unmarked test.
# ---------------------------------------------------------------------------

CATEGORY_MARKERS = {"core", "plugins"}
GATE_MARKERS = {"external_data", "render", "selenium"}
ALL_TIER_MARKERS = CATEGORY_MARKERS | GATE_MARKERS


def pytest_collection_modifyitems(config, items):
    root = Path(__file__).parent.resolve()  # tests/

    errors: list[str] = []
    stats = {m: 0 for m in ALL_TIER_MARKERS}
    stats["no_category"] = 0
    stats["gate_only"] = 0

    for item in items:
        path = Path(str(item.fspath)).resolve()
        try:
            rel = path.relative_to(root)
        except ValueError:
            continue  # not under tests/ – skip

        parts = rel.parts
        in_selenium_dir = len(parts) >= 2 and parts[0] == "selenium"
        in_snapshots_dir = len(parts) >= 2 and parts[0] == "snapshots"

        node_markers = {mark.name for mark in item.iter_markers()} & ALL_TIER_MARKERS
        categories_found = node_markers & CATEGORY_MARKERS
        gates_found = node_markers & GATE_MARKERS

        # Count for the summary line printed at the bottom.
        for m in node_markers:
            stats[m] += 1

        if in_selenium_dir:
            if "selenium" not in node_markers:
                errors.append(
                    f"[selenium-dir, missing 'selenium'] {item.nodeid}"
                )
            # external_data is allowed as an overlay; render on heat_map_selenium too.
            continue

        if in_snapshots_dir:
            missing = {"render", "selenium"} - node_markers
            if missing:
                errors.append(
                    f"[snapshots-dir, missing {sorted(missing)}] {item.nodeid}"
                )
            continue

        # Regular tests – everything under tests/ except selenium/ and
        # snapshots/.
        if not categories_found:
            stats["no_category"] += 1
            errors.append(
                f"[missing category – must be @pytest.mark.core OR "
                f"@pytest.mark.plugins] {item.nodeid}"
            )
            if gates_found and not categories_found:
                stats["gate_only"] += 1
                errors.append(
                    f"[gate marker(s) {sorted(gates_found)} used without "
                    f"a category marker – add @pytest.mark.core or "
                    f"@pytest.mark.plugins] {item.nodeid}"
                )
        elif len(categories_found) > 1:
            errors.append(
                f"[multiple categories {sorted(categories_found)} – pick "
                f"exactly one of core|plugins] {item.nodeid}"
            )

    # Always print a marker audit summary so the numbers are visible in
    # every CI log, even when nothing is broken.
    summary = [
        "",
        "folium marker audit summary:",
        f"  @pytest.mark.core          : {stats['core']:>4} items",
        f"  @pytest.mark.plugins       : {stats['plugins']:>4} items",
        f"  @pytest.mark.external_data : {stats['external_data']:>4} items (gate overlay)",
        f"  @pytest.mark.render        : {stats['render']:>4} items (gate overlay)",
        f"  @pytest.mark.selenium      : {stats['selenium']:>4} items (gate overlay)",
        f"  items missing a category   : {stats['no_category']:>4}",
        f"  items with only gate marks : {stats['gate_only']:>4}",
    ]
    config._folium_audit_lines = summary

    if errors:
        msg = "\n".join(
            [
                "",
                "=" * 78,
                "FOLIUM MARKER AUDIT FAILED",
                "=" * 78,
                "Every regular test under tests/ (excluding tests/selenium and",
                "tests/snapshots) must carry EXACTLY ONE of @pytest.mark.core or",
                "@pytest.mark.plugins.  Gate markers (external_data / render /",
                "selenium) may only be used as overlays on top of a category.",
                "",
                "Violations:",
            ]
            + [f"  • {e}" for e in errors]
            + [
                "",
                "If you are adding a new test file, add `pytestmark = pytest.mark.core`",
                "or `pytestmark = pytest.mark.plugins` near the top of the file, then",
                "use @pytest.mark.external_data / @pytest.mark.render /",
                "@pytest.mark.selenium on individual test functions where needed.",
                "=" * 78,
            ]
        )
        pytest.exit(msg, returncode=4)


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    lines = getattr(config, "_folium_audit_lines", None)
    if not lines:
        return
    tw = terminalreporter._tw
    tw.sep("-", "folium marker audit")
    for line in lines:
        tw.line(line)
    tw.sep("-")
