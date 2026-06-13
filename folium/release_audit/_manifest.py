"""
Resource manifest schema, generation, and validation.

Responsibility:
  - Define stable JSON Schema for the CDN resource manifest
  - Build manifest from extracted ClassResources
  - Validate manifest files against the schema

Depends on: _extract (data classes + resource collection + URL parsing)

This module does NOT do any audit checking — it purely transforms the
extracted resource data into a stable, machine-consumable format.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any

from ._extract import (
    ClassResources,
    cdn_host,
    collect_all_resources,
    extract_package_from_url,
    extract_version_from_url,
    resource_id,
)

MANIFEST_SCHEMA_VERSION = "1.0.0"

MANIFEST_JSON_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://python-visualization.github.io/folium/schemas/resource-manifest-v1.json",
    "title": "Folium CDN Resource Manifest",
    "type": "object",
    "version": MANIFEST_SCHEMA_VERSION,
    "required": ["manifest_schema_version", "source_of_truth", "generated_at",
                 "resources"],
    "properties": {
        "manifest_schema_version": {
            "type": "string",
            "description": "Semantic version of this manifest schema. Consumers should validate compatible major version."
        },
        "source_of_truth": {
            "type": "string",
            "const": "default_js/default_css in Python source",
            "description": "Where the manifest was generated from — always the source code default_js/default_css declarations."
        },
        "generated_at": {
            "type": "string",
            "format": "date-time",
            "description": "UTC timestamp when manifest was generated (ISO 8601)."
        },
        "folium_version": {
            "type": "string",
            "description": "Folium package version that produced this manifest."
        },
        "resource_count": {
            "type": "integer",
            "minimum": 0,
            "description": "Total number of unique (name, url) pairs in resources array."
        },
        "resources": {
            "type": "array",
            "description": "Flat list of all CDN resources, de-duplicated by URL.",
            "items": {
                "$ref": "#/$defs/ResourceEntry"
            }
        },
        "by_class": {
            "type": "object",
            "description": "Resources grouped by the class that declares/uses them.",
            "additionalProperties": {
                "$ref": "#/$defs/ClassResources"
            }
        }
    },
    "$defs": {
        "ResourceEntry": {
            "type": "object",
            "required": ["id", "name", "resource_type", "url",
                         "source_class", "module"],
            "properties": {
                "id": {
                    "type": "string",
                    "description": "Stable identifier: sha256(url)[:12]. Use as cache key."
                },
                "name": {
                    "type": "string",
                    "description": "Logical resource name as declared in default_js/default_css."
                },
                "resource_type": {
                    "type": "string",
                    "enum": ["js", "css"],
                    "description": "Resource type: js or css."
                },
                "url": {
                    "type": "string",
                    "format": "uri",
                    "description": "Full CDN URL."
                },
                "source_class": {
                    "type": "string",
                    "description": "Name of the class that uses this resource."
                },
                "module": {
                    "type": "string",
                    "description": "Fully-qualified Python module where the class lives."
                },
                "package": {
                    "type": ["string", "null"],
                    "description": "Extracted package/library name from URL (e.g. leaflet, jquery)."
                },
                "version": {
                    "type": ["string", "null"],
                    "description": "Extracted semantic version from URL if present."
                },
                "cdn_host": {
                    "type": ["string", "null"],
                    "description": "CDN provider host (jsdelivr, cdnjs, unpkg, ...)."
                },
                "inherited": {
                    "type": "boolean",
                    "default": False,
                    "description": "True if resource is inherited from a parent class rather than declared directly."
                },
                "inherited_from": {
                    "type": ["string", "null"],
                    "description": "Name of parent class from which resource is inherited."
                }
            }
        },
        "ClassResources": {
            "type": "object",
            "required": ["module", "js", "css"],
            "properties": {
                "module": {"type": "string"},
                "js": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Resource ids (sha256[:12]) of JS resources for this class."
                },
                "css": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Resource ids (sha256[:12]) of CSS resources for this class."
                },
                "inherited_resources": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Resource ids that are inherited from parent classes."
                },
                "note": {
                    "type": "string",
                    "description": "Optional explanatory note from audit policy."
                }
            }
        }
    }
}


def manifest_json_schema() -> dict[str, Any]:
    return json.loads(json.dumps(MANIFEST_JSON_SCHEMA))


def build_stable_manifest(all_resources: dict[str, ClassResources]) -> dict[str, Any]:
    resources_flat: dict[str, dict[str, Any]] = {}
    by_class: dict[str, dict[str, Any]] = {}

    for class_name, cr in sorted(all_resources.items()):
        class_entry: dict[str, Any] = {
            "module": cr.module,
            "js": [],
            "css": [],
            "inherited_resources": [],
        }

        for rtype, resource_list in [("js", cr.js), ("css", cr.css)]:
            for r in resource_list:
                rid = resource_id(r.url)
                if rid not in resources_flat:
                    resources_flat[rid] = {
                        "id": rid,
                        "name": r.name,
                        "resource_type": rtype,
                        "url": r.url,
                        "source_class": class_name,
                        "module": cr.module,
                        "package": extract_package_from_url(r.url),
                        "version": extract_version_from_url(r.url),
                        "cdn_host": cdn_host(r.url),
                        "inherited": not cr.declared_on_class,
                        "inherited_from": cr.inherited_from,
                    }
                class_entry[rtype].append(rid)
                if not cr.declared_on_class:
                    class_entry["inherited_resources"].append(rid)

        by_class[class_name] = class_entry

    resources_list = sorted(resources_flat.values(), key=lambda x: x["id"])

    try:
        from folium._version import __version__ as folium_ver
    except ImportError:
        folium_ver = "unknown"

    manifest: dict[str, Any] = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "source_of_truth": "default_js/default_css in Python source",
        "generated_at": datetime.datetime.now(datetime.timezone.utc)
        .isoformat().replace("+00:00", "Z"),
        "folium_version": folium_ver,
        "resource_count": len(resources_list),
        "resources": resources_list,
        "by_class": by_class,
    }
    return manifest


def generate_manifest(all_resources: dict[str, ClassResources],
                      pretty: bool = False) -> str:
    manifest = build_stable_manifest(all_resources)
    return json.dumps(manifest, indent=2 if pretty else None, sort_keys=True)


def validate_manifest(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    for field in ["manifest_schema_version", "source_of_truth", "generated_at",
                  "resource_count", "resources", "by_class"]:
        if field not in manifest:
            errors.append(f"Missing required top-level field: {field}")

    if manifest.get("manifest_schema_version", "").split(".")[0] != MANIFEST_SCHEMA_VERSION.split(".")[0]:
        errors.append(
            f"Major schema version mismatch: manifest={manifest.get('manifest_schema_version')}, "
            f"expected={MANIFEST_SCHEMA_VERSION}"
        )

    if manifest.get("source_of_truth") != "default_js/default_css in Python source":
        errors.append("source_of_truth is not the expected value")

    if not isinstance(manifest.get("resources"), list):
        errors.append("'resources' must be an array")
    else:
        for idx, res in enumerate(manifest.get("resources", [])):
            for required in ["id", "name", "resource_type", "url", "source_class", "module"]:
                if required not in res:
                    errors.append(f"resources[{idx}] missing required field: {required}")
            if res.get("resource_type") not in ("js", "css"):
                errors.append(f"resources[{idx}].resource_type must be 'js' or 'css'")

    actual_count = len(manifest.get("resources", []))
    declared_count = manifest.get("resource_count")
    if declared_count is not None and declared_count != actual_count:
        errors.append(
            f"resource_count ({declared_count}) does not match actual resources array length ({actual_count})"
        )

    return errors
