"""
Thin shim for Folium Developer Diagnostics.

Actual implementation lives in folium._audit.diagnostics (internal).
This module provides the public CLI entry point via python -m folium.diagnostics.

Do NOT import from this module in application code.
The public API surface of Folium does not include diagnostics.

Usage:
    python -m folium.diagnostics              # human-readable report
    python -m folium.diagnostics --json       # machine-readable JSON
    python -m folium.diagnostics --sections environment,deps  # only specific sections
    python -m folium.diagnostics --schema     # print JSON schema

For internal tooling, import from folium._audit.diagnostics directly.
"""

from __future__ import annotations

from folium._audit.diagnostics import (
    format_human_readable,
    get_json_schema,
    run_diagnostics,
)

__all__: list[str] = []


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Folium Developer Diagnostics - gather environment and config info",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as structured JSON",
    )
    parser.add_argument(
        "--sections",
        type=str,
        default=None,
        help="Comma-separated list of sections to include (default: all)",
    )
    parser.add_argument(
        "--list-sections",
        action="store_true",
        help="List available diagnostic sections and exit",
    )
    parser.add_argument(
        "--schema",
        action="store_true",
        help="Print the JSON schema for the diagnostic report and exit",
    )
    args = parser.parse_args()

    from folium._audit.diagnostics import SECTION_COLLECTORS

    if args.list_sections:
        print("Available diagnostic sections:")
        for name in SECTION_COLLECTORS.keys():
            print(f"  - {name}")
        return

    if args.schema:
        import json
        print(json.dumps(get_json_schema(), indent=2))
        return

    sections = None
    if args.sections:
        sections = [s.strip() for s in args.sections.split(",")]

    report = run_diagnostics(sections=sections)

    if args.json:
        import json
        print(json.dumps(report.to_dict(), indent=2, default=str))
    else:
        print(format_human_readable(report))


if __name__ == "__main__":
    main()
