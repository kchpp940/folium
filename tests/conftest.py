"""
Pytest configuration for folium tests.

Defines test markers, CLI options, and auto-skip logic to separate:
- core: fast, stable unit tests (run by default)
- plugins: plugin tests (run by default)
- audit: release resource consistency audit (run by default)
- smoke: lightweight example validation from docs/examples/notebooks (run by default)
- external_data: tests requiring geodatasets or network resources
- render: slow PNG rendering tests with pixelmatch
- selenium: browser automation tests
- smoke_network: smoke tests requiring network access or remote resources
"""

import pytest

collect_ignore = ["snapshots/modules"]

# ---------------------------------------------------------------------------
# Marker registration
# ---------------------------------------------------------------------------

def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "core: Fast, stable unit tests (no network, no browser, no external data). "
        "These run by default.",
    )
    config.addinivalue_line(
        "markers",
        "plugins: Tests for folium plugins. These run by default.",
    )
    config.addinivalue_line(
        "markers",
        "external_data: Tests requiring geodatasets, network requests, or remote APIs. "
        "Requires --run-external-data flag.",
    )
    config.addinivalue_line(
        "markers",
        "render: Slow PNG rendering tests using pixelmatch comparison. "
        "Requires --run-render flag.",
    )
    config.addinivalue_line(
        "markers",
        "audit: Release resource consistency audit tests. "
        "Requires --run-audit flag.",
    )
    config.addinivalue_line(
        "markers",
        "selenium: Browser automation tests requiring Selenium webdriver. "
        "Requires --run-selenium flag.",
    )
    config.addinivalue_line(
        "markers",
        "smoke: Lightweight example validation from docs, examples, and notebooks. "
        "Runs offline, generates minimal HTML, checks for template errors. "
        "These run by default.",
    )
    config.addinivalue_line(
        "markers",
        "smoke_network: Smoke tests requiring network access, remote tile services, "
        "or external data URLs. Requires --run-smoke-network flag.",
    )


# ---------------------------------------------------------------------------
# CLI options
# ---------------------------------------------------------------------------

def pytest_addoption(parser):
    parser.addoption(
        "--run-external-data",
        action="store_true",
        default=False,
        help="Run tests that depend on external data (geodatasets, network requests).",
    )
    parser.addoption(
        "--run-render",
        action="store_true",
        default=False,
        help="Run slow PNG rendering tests with pixelmatch comparison.",
    )
    parser.addoption(
        "--run-selenium",
        action="store_true",
        default=False,
        help="Run browser automation tests requiring Selenium webdriver.",
    )
    parser.addoption(
        "--run-audit",
        action="store_true",
        default=False,
        help="Run release resource consistency audit tests.",
    )
    parser.addoption(
        "--run-all",
        action="store_true",
        default=False,
        help="Run all tests including external_data, render, and selenium.",
    )
    parser.addoption(
        "--run-smoke-network",
        action="store_true",
        default=False,
        help="Run smoke tests that require network access or remote resources.",
    )
    parser.addoption(
        "--smoke-html-output",
        type=str,
        default=None,
        help="Directory to save generated HTML from smoke tests for inspection.",
    )


# ---------------------------------------------------------------------------
# Auto-skip logic based on markers and CLI flags
# ---------------------------------------------------------------------------

def pytest_runtest_setup(item):
    # Determine which optional test categories are enabled
    run_all = item.config.getoption("--run-all")
    run_audit = run_all or item.config.getoption("--run-audit")
    run_external_data = run_all or item.config.getoption("--run-external-data")
    run_render = run_all or item.config.getoption("--run-render")
    run_selenium = run_all or item.config.getoption("--run-selenium")
    run_smoke_network = run_all or item.config.getoption("--run-smoke-network")

    if "audit" in item.keywords and not run_audit:
        pytest.skip("Need --run-audit or --run-all to run this test")

    # Check for optional markers and skip if not enabled
    if "external_data" in item.keywords and not run_external_data:
        pytest.skip("Need --run-external-data or --run-all to run this test")

    if "render" in item.keywords and not run_render:
        pytest.skip("Need --run-render or --run-all to run this test")

    if "selenium" in item.keywords and not run_selenium:
        pytest.skip("Need --run-selenium or --run-all to run this test")

    if "smoke_network" in item.keywords and not run_smoke_network:
        pytest.skip("Need --run-smoke-network or --run-all to run this test")


@pytest.fixture(scope="session")
def smoke_html_output(request):
    """Return the directory path for saving smoke test HTML output, or None."""
    return request.config.getoption("--smoke-html-output")


# ---------------------------------------------------------------------------
# Dependency check fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def geodatasets_available():
    """Return geodatasets module if available, skip otherwise."""
    try:
        import geodatasets  # noqa: F401
        return True
    except ImportError:
        return False


@pytest.fixture(scope="session")
def pixelmatch_available():
    """Return True if pixelmatch and PIL are available."""
    try:
        from pixelmatch.contrib.PIL import pixelmatch  # noqa: F401
        from PIL import Image  # noqa: F401
        return True
    except ImportError:
        return False


@pytest.fixture(scope="session")
def selenium_available():
    """Return True if selenium and Chrome webdriver are available."""
    try:
        from selenium import webdriver  # noqa: F401
        from selenium.webdriver import ChromeOptions  # noqa: F401
        return True
    except ImportError:
        return False
