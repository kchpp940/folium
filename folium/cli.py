"""
folium-resource CLI – manage resource manifests for offline maps.

Typical workflow::

    # 1. Collect resources from a map definition file
    folium-resource collect my_map.py --manifest resources/manifest.json

    # 2. Download everything into a cache directory
    folium-resource download resources/manifest.json --dir resources/

    # 3. Verify files exist and sha256 checksums match
    folium-resource verify resources/manifest.json

The manifest can then be used in your Python code::

    folium.set_resource_mode("manifest", manifest_path="resources/manifest.json")
    m.save("offline_report.html")
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import warnings
from typing import Optional

from folium.resource_manifest import (
    ResourceManifest,
    collect_resources,
    download_manifest,
    resolve_from_manifest,
)


# ---------------------------------------------------------------------------
# Map file loading
# ---------------------------------------------------------------------------


def _load_map_from_file(filepath: str) -> object:
    """Load a user's map file and return the folium.Map instance.

    Supports two patterns:
      1. Module has a top-level variable named ``m`` or ``map``.
      2. Module has a function named ``build_map()`` that returns a Map.
    """
    abs_path = os.path.abspath(filepath)
    spec = importlib.util.spec_from_file_location(
        "_folium_user_map_" + os.path.basename(abs_path).replace(".py", ""),
        abs_path,
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load Python file: {abs_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    # Try named map variables
    for candidate in ("m", "map", "folium_map", "my_map"):
        val = getattr(module, candidate, None)
        if val is not None and type(val).__name__ == "Map":
            return val

    # Try build_map()
    build = getattr(module, "build_map", None)
    if callable(build):
        val = build()
        if type(val).__name__ == "Map":
            return val

    # Fallback: scan module for any Map instance
    for name, val in vars(module).items():
        if type(val).__name__ == "Map":
            return val

    raise ValueError(
        f"Could not find a folium.Map instance in {abs_path}. "
        "Either name it 'm', assign to 'map', or define a build_map() function."
    )


# ---------------------------------------------------------------------------
# Subcommand: collect
# ---------------------------------------------------------------------------


def cmd_collect(args: argparse.Namespace) -> int:
    map_obj = _load_map_from_file(args.map_file)
    manifest = collect_resources(map_obj, include_map_defaults=True)
    manifest.local_path = os.path.abspath(args.dir) if args.dir else None
    out_path = args.manifest or "manifest.json"
    manifest.save(out_path)
    print(f"✓ Collected {len(manifest)} resources → {out_path}")
    for r in manifest:
        print(f"  · {r.name:35s} {r.type:3s} {r.filename}")
    return 0


# ---------------------------------------------------------------------------
# Subcommand: download
# ---------------------------------------------------------------------------


def cmd_download(args: argparse.Namespace) -> int:
    manifest = ResourceManifest.load(args.manifest)
    target_dir = args.dir or manifest.local_path or os.path.dirname(
        os.path.abspath(args.manifest)
    )
    print(f"Downloading {len(manifest)} resources → {target_dir}")
    results = download_manifest(
        manifest,
        target_dir,
        overwrite=args.overwrite,
        retries=args.retries,
        timeout=args.timeout,
    )
    # Re-save manifest so sha256/size are persisted
    manifest.save(args.manifest)
    print(f"✓ {len(results)} resources downloaded, manifest updated with sha256")
    if args.verbose:
        for r in manifest:
            print(f"  · {r.name:35s} {r.sha256[:16]}… {r.size:>8d} bytes")
    return 0


# ---------------------------------------------------------------------------
# Subcommand: verify
# ---------------------------------------------------------------------------


def cmd_verify(args: argparse.Namespace) -> int:
    manifest = ResourceManifest.load(args.manifest)
    check_dir = args.dir or manifest.local_path or os.path.dirname(
        os.path.abspath(args.manifest)
    )
    print(f"Verifying {len(manifest)} resources in {check_dir}")
    errors = 0
    for entry in manifest:
        path = resolve_from_manifest(entry.name, manifest, check_dir)
        if path is None:
            errors += 1
            print(f"  ✗ {entry.name}: MISSING or sha256 MISMATCH")
        elif args.verbose:
            print(f"  ✓ {entry.name}: OK ({path})")
    if errors == 0:
        print(f"✓ All {len(manifest)} resources verified")
        return 0
    print(f"✗ {errors} resource(s) failed verification")
    return 1


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="folium-resource",
        description="Manage folium resource manifests for offline maps.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    # collect
    c = sub.add_parser("collect", help="Collect resources from a map definition")
    c.add_argument("map_file", help="Path to a Python file that defines a folium.Map")
    c.add_argument(
        "--manifest", "-o", default=None,
        help="Output manifest path (default: manifest.json)"
    )
    c.add_argument(
        "--dir", default=None,
        help="Default local path to store resources (saved into manifest)"
    )
    c.set_defaults(func=cmd_collect)

    # download
    d = sub.add_parser("download", help="Download all resources listed in a manifest")
    d.add_argument("manifest", help="Path to manifest.json")
    d.add_argument("--dir", default=None, help="Target directory")
    d.add_argument("--overwrite", action="store_true", help="Re-download existing files")
    d.add_argument("--retries", type=int, default=5, help="HTTP retries per resource (default: 5)")
    d.add_argument("--timeout", type=float, default=60.0, help="HTTP timeout per attempt (default: 60)")
    d.add_argument("--verbose", "-v", action="store_true", help="Print sha256 and sizes")
    d.set_defaults(func=cmd_download)

    # verify
    v = sub.add_parser("verify", help="Verify files exist and sha256 checksums match")
    v.add_argument("manifest", help="Path to manifest.json")
    v.add_argument("--dir", default=None, help="Directory holding cached files")
    v.add_argument("--verbose", "-v", action="store_true", help="Print each OK resource")
    v.set_defaults(func=cmd_verify)

    return p


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    # Silencing the warnings that get emitted during module import
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
