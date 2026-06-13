"""
Batch smoke tests for Folium examples and documentation code.

Runs lightweight validations on core examples drawn from:
  - docs/ (Markdown/RST user guide and advanced guide)
  - examples/ (Jupyter notebooks, Python scripts)
  - Inline reproductions of README / getting_started code snippets

Tests are split into two markers:
  - smoke:            Offline, fast. Marked @pytest.mark.smoke (runs by default)
  - smoke_network:    Requires network access or remote data. Marked
                      @pytest.mark.smoke_network (skipped by default, pass
                      --run-smoke-network to enable).

Each example:
  1. Has its Python code extracted and executed.
  2. Captures all generated folium.Map instances.
  3. Renders each Map to an HTML string.
  4. Validates HTML structure and checks for suspicious template errors /
     broken resource links.
  5. Optionally saves generated HTML to --smoke-html-output=<dir>.
"""

from __future__ import annotations

import pytest

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from smoke_checker import (
    AuditSummary,
    ExampleSpec,
    SmokeResult,
    build_audit_summary,
    build_example_registry,
    filter_examples,
    run_example,
)


_ALL_SPECS = build_example_registry()

_OFFLINE_SPECS = filter_examples(_ALL_SPECS, include_network=False)
_NETWORK_SPECS = filter_examples(_ALL_SPECS, include_network=True)
_NETWORK_ONLY_SPECS = [s for s in _NETWORK_SPECS if s.requires_network]


def _spec_ids(specs: list[ExampleSpec]) -> list[str]:
    return [f"{s.name} [pri={s.priority}]" for s in specs]


@pytest.mark.smoke
@pytest.mark.parametrize("spec", _OFFLINE_SPECS, ids=_spec_ids(_OFFLINE_SPECS))
def test_smoke_example_offline(
    spec: ExampleSpec,
    smoke_html_output,
) -> None:
    """Run offline smoke examples (default, fast, no network)."""
    if spec.skip and spec.skip_reason:
        pytest.skip(spec.skip_reason)
    result: SmokeResult = run_example(
        spec,
        html_output_dir=smoke_html_output,
    )
    if result.skipped:
        pytest.skip(result.skip_reason or "Skipped by smoke checker")
    assert result.success, (
        f"Example '{spec.name}' failed ({spec.source}): {result.error}"
    )
    assert result.maps_captured >= 1, (
        f"Example '{spec.name}' did not produce any folium.Map "
        f"instance. Warnings: {result.warnings}"
    )
    assert result.html is not None, (
        f"Example '{spec.name}' produced no HTML output."
    )
    severe_warnings = [
        w for w in result.warnings
        if "Template error" in w or "TemplateNotFound" in w
        or "Traceback" in w or "parse error" in w.lower()
    ]
    assert not severe_warnings, (
        f"Example '{spec.name}' has HTML validation issues: {severe_warnings}"
    )


@pytest.mark.smoke_network
@pytest.mark.parametrize(
    "spec", _NETWORK_ONLY_SPECS, ids=_spec_ids(_NETWORK_ONLY_SPECS)
)
def test_smoke_example_network(
    spec: ExampleSpec,
    smoke_html_output,
) -> None:
    """Run smoke examples that require network access (opt-in only)."""
    assert spec.requires_network
    if spec.skip and spec.skip_reason:
        pytest.skip(spec.skip_reason)
    result: SmokeResult = run_example(
        spec,
        html_output_dir=smoke_html_output,
    )
    if result.skipped:
        pytest.skip(result.skip_reason or "Skipped by smoke checker")
    assert result.success, (
        f"Network example '{spec.name}' failed ({spec.source}): {result.error}"
    )
    assert result.maps_captured >= 1, (
        f"Network example '{spec.name}' did not produce any folium.Map "
        f"instance. Warnings: {result.warnings}"
    )


def test_smoke_registry_not_empty() -> None:
    """Sanity check: the registry must contain offline and network entries."""
    assert len(_OFFLINE_SPECS) >= 5, (
        "Expected at least 5 offline smoke examples in the registry."
    )
    assert len(_NETWORK_ONLY_SPECS) >= 1, (
        "Expected at least 1 network-only smoke example in the registry."
    )
    for spec in _OFFLINE_SPECS:
        assert not spec.requires_network, (
            f"Offline example '{spec.name}' should not require network."
        )
    for spec in _NETWORK_ONLY_SPECS:
        assert spec.requires_network, (
            f"Network example '{spec.name}' should require network."
        )


@pytest.mark.smoke
def test_smoke_coverage_audit() -> None:
    """Coverage audit — ensures every code-bearing doc/example file is either
    registered for testing or explicitly skipped with a reason.

    Also prints the full audit report when run with ``-v -s``.
    """
    summary: AuditSummary = build_audit_summary(_ALL_SPECS)

    unregistered_with_code = [
        e for e in summary.entries if e.has_code and not e.registered
    ]
    assert not unregistered_with_code, (
        "Found source files with code blocks that are NOT registered in the "
        "smoke test registry and not explicitly skipped. Add them to "
        "POLICY_MANIFEST in tests/smoke_checker.py.  Unregistered files:\n  - "
        + "\n  - ".join(e.source for e in unregistered_with_code)
    )

    print("\n" + summary.format_report())
