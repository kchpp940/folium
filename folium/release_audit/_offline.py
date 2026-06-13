"""
Offline CDN resource download and caching.

Responsibility:
  - Download resources from a validated manifest
  - Local file cache (by resource id, which is a URL-based hash)
  - Capture content hash for downstream integrity verification
  - Generate download index report

Depends on: _manifest (manifest validation utilities)

This module does NOT do any audit checking or manifest generation —
it purely downloads resources described by an existing manifest.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import urlopen

from ._manifest import validate_manifest


def download_resources(manifest: dict[str, Any], output_dir: Path,
                       timeout: float = 30.0) -> dict[str, Any]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    cache_dir = output_dir / "cache"
    cache_dir.mkdir(exist_ok=True)

    index_path = output_dir / "index.json"
    download_report: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for res in manifest.get("resources", []):
        rid = res["id"]
        url = res["url"]
        rtype = res["resource_type"]
        name = res["name"]

        parsed = urlparse(url)
        path_part = parsed.path.lstrip("/")
        safe_filename = path_part.replace("/", "_").replace("@", "_at_")
        file_path = cache_dir / f"{rid}_{safe_filename}"

        entry = {
            "id": rid,
            "name": name,
            "resource_type": rtype,
            "url": url,
            "local_path": str(file_path.relative_to(output_dir)),
            "source_class": res.get("source_class"),
            "package": res.get("package"),
            "version": res.get("version"),
            "cdn_host": res.get("cdn_host"),
        }

        if file_path.exists() and file_path.stat().st_size > 0:
            entry["status"] = "cached"
            download_report.append(entry)
            continue

        try:
            with urlopen(url, timeout=timeout) as resp:
                content = resp.read()
                content_sha = hashlib.sha256(content).hexdigest()[:12]
                entry["status"] = "downloaded"
                entry["size_bytes"] = len(content)
                entry["content_hash"] = content_sha
                file_path.write_bytes(content)
            download_report.append(entry)
        except Exception as exc:
            errors.append({
                "id": rid,
                "url": url,
                "error": str(exc),
            })
            entry["status"] = "failed"
            entry["error"] = str(exc)
            download_report.append(entry)

    summary = {
        "manifest_schema_version": manifest.get("manifest_schema_version"),
        "folium_version": manifest.get("folium_version"),
        "generated_at": manifest.get("generated_at"),
        "total_resources": manifest.get("resource_count"),
        "cached": sum(1 for d in download_report if d.get("status") == "cached"),
        "downloaded": sum(1 for d in download_report if d.get("status") == "downloaded"),
        "failed": sum(1 for d in download_report if d.get("status") == "failed"),
    }

    index_data = {
        "manifest_schema_version": manifest.get("manifest_schema_version"),
        "generated_at": manifest.get("generated_at"),
        "folium_version": manifest.get("folium_version"),
        "summary": summary,
        "resources": download_report,
        "errors": errors,
    }
    index_path.write_text(json.dumps(index_data, indent=2, sort_keys=True), encoding="utf-8")

    return index_data


def download_from_file(manifest_path: Path, output_dir: Path,
                       timeout: float = 30.0) -> dict[str, Any]:
    manifest_path = Path(manifest_path)
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))

    errors = validate_manifest(manifest_data)
    if errors:
        raise ValueError(
            f"Manifest validation failed ({len(errors)} error(s)):\n"
            + "\n".join(f"  - {e}" for e in errors)
        )

    return download_resources(manifest_data, output_dir, timeout=timeout)
