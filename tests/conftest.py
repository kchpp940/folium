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
collect_ignore = [
    str(Path(__file__).parent / "snapshots" / "modules"),
]


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
