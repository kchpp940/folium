"""
CLI entry point: `python -m folium.release_audit`

Responsibility: parse arguments, dispatch to the right module.
Does NOT contain audit/manifest/download logic directly.

Subcommands:
  audit     — run resource consistency checks (default)
  manifest  — generate, validate, or inspect the resource manifest schema
  offline   — download and cache CDN resources for offline use
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ._audit import AuditResult, run_audit
from ._extract import collect_all_resources
from ._manifest import (
    build_stable_manifest,
    generate_manifest,
    manifest_json_schema,
    validate_manifest,
)
from ._offline import download_resources


def _format_findings(findings: list, label: str) -> str:
    if not findings:
        return ""
    lines = [f"\n{'='*60}", f"  {label} ({len(findings)})", f"{'='*60}"]
    for f in findings:
        lines.append(f"\n  [{f.severity.upper()}] {f.category}")
        lines.append(f"  {f.message}")
        if f.location:
            lines.append(f"  Location: {f.location}")
        if f.detail:
            lines.append(f"  Detail: {f.detail}")
    return "\n".join(lines)


def _cmd_audit(args) -> int:
    result = run_audit(strict=args.strict)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        output = _format_findings(result.errors, "ERRORS")
        output += _format_findings(result.warnings, "WARNINGS")
        if not result.errors and not result.warnings:
            output = "\n✓ All resource consistency checks passed."
        else:
            summary = f"\n\nSummary: {len(result.errors)} error(s), {len(result.warnings)} warning(s)"
            if result.ok:
                summary += "\nNo blocking errors found."
            else:
                summary += "\n❌ Blocking errors found — fix before release."
            output += summary
        print(output)

    return 0 if result.ok else 1


def _cmd_manifest(args) -> int:
    print_schema = getattr(args, "print_schema", False)
    validate = getattr(args, "validate", None)
    pretty = getattr(args, "pretty", False)

    if print_schema:
        schema = manifest_json_schema()
        print(json.dumps(schema, indent=2 if pretty else None, sort_keys=True))
        return 0

    if validate:
        manifest_file = Path(validate)
        if not manifest_file.exists():
            print(f"ERROR: manifest file not found: {manifest_file}", file=sys.stderr)
            return 2
        manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
        errors = validate_manifest(manifest_data)
        if errors:
            print(f"Manifest validation FAILED ({len(errors)} error(s)):")
            for e in errors:
                print(f"  - {e}")
            return 1
        print(f"Manifest valid. Schema version: {manifest_data.get('manifest_schema_version')}, "
              f"resources: {manifest_data.get('resource_count')}")
        return 0

    all_res = collect_all_resources()
    print(generate_manifest(all_res, pretty=pretty))
    return 0


def _cmd_offline(args) -> int:
    output_dir = Path(args.dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.manifest:
        manifest_file = Path(args.manifest).resolve()
        if not manifest_file.exists():
            print(f"ERROR: manifest file not found: {manifest_file}", file=sys.stderr)
            return 2
        manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
        errors = validate_manifest(manifest_data)
        if errors:
            print("ERROR: provided manifest fails validation:", file=sys.stderr)
            for e in errors:
                print(f"  - {e}", file=sys.stderr)
            return 2
    else:
        all_res = collect_all_resources()
        manifest_data = build_stable_manifest(all_res)

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest_data, indent=2, sort_keys=True), encoding="utf-8"
    )

    report = download_resources(manifest_data, output_dir, timeout=args.timeout)
    summary = report["summary"]
    print(f"\nOffline download complete. Output directory: {output_dir}")
    print(f"  Total resources: {summary['total_resources']}")
    print(f"  Cached:          {summary['cached']}")
    print(f"  Downloaded:      {summary['downloaded']}")
    print(f"  Failed:          {summary['failed']}")
    print(f"\nManifest saved to: {manifest_path}")
    print(f"Download index:    {output_dir / 'index.json'}")

    return 1 if summary["failed"] > 0 else 0


def main():
    parser = argparse.ArgumentParser(
        description="Folium Release Resource Audit & Offline Resource Tool"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    audit_p = subparsers.add_parser("audit", help="Run resource consistency audit (default)")
    audit_p.add_argument("--json", action="store_true", help="Output results as JSON")
    audit_p.add_argument("--strict", action="store_true", help="Promote warnings per policy")

    manifest_p = subparsers.add_parser("manifest", help="Resource manifest generation/validation")
    manifest_p.add_argument("--generate", action="store_true", help="Generate manifest from source")
    manifest_p.add_argument("--validate", type=str, metavar="FILE",
                            help="Validate a manifest file against schema")
    manifest_p.add_argument("--print-schema", action="store_true",
                            help="Print JSON Schema for the manifest format")
    manifest_p.add_argument("--pretty", action="store_true", help="Pretty-print output")

    offline_p = subparsers.add_parser("offline", help="Offline CDN resource download")
    offline_p.add_argument("--dir", type=str, default=".folium_offline",
                           help="Output directory for downloaded resources")
    offline_p.add_argument("--manifest", type=str, metavar="FILE",
                           help="Use existing manifest file (skip regeneration)")
    offline_p.add_argument("--timeout", type=float, default=30.0,
                           help="Per-file download timeout in seconds")

    parser.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--strict", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--generate-manifest", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--pretty", action="store_true", help=argparse.SUPPRESS)

    args = parser.parse_args()

    if args.command is None:
        if args.generate_manifest:
            args.command = "manifest"
        else:
            args.command = "audit"

    if args.command == "audit":
        sys.exit(_cmd_audit(args))
    elif args.command == "manifest":
        if not hasattr(args, "pretty"):
            args.pretty = False
        sys.exit(_cmd_manifest(args))
    elif args.command == "offline":
        sys.exit(_cmd_offline(args))
    else:
        parser.print_help()
        sys.exit(2)


if __name__ == "__main__":
    main()
