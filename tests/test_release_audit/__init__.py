"""
Tests for folium.release_audit package.

Tests are organized by module responsibility:
  test_policy.py    — _policy.py:  policy file loading, policy helper functions
  test_extract.py   — _extract.py: data classes, source code resource extraction, URL parsing
  test_audit.py     — _audit.py:   all audit rule checks (duplicate names, version drift, etc.)
  test_manifest.py  — _manifest.py: stable schema, manifest generation, validation
  test_offline.py   — _offline.py: offline download and caching
  test_cli.py       — __main__.py: CLI argument dispatch and integration
  test_package.py   — __init__.py: public API surface, backward compatibility, packaging
"""

import pytest

pytestmark = pytest.mark.audit
