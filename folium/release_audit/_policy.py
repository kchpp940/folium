"""
Release audit policy loading.

Responsibility: load and provide access to release_audit_policy.json.
Only depends on standard library + folium package path.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

POLICY_FILENAME = "release_audit_policy.json"


def policy_file_path() -> Path:
    return Path(__file__).resolve().parent.parent / POLICY_FILENAME


def load_policy() -> dict[str, Any]:
    path = policy_file_path()
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def is_no_resources_class(policy: dict[str, Any], class_name: str) -> tuple[bool, dict | None]:
    for entry in policy.get("classes", {}).get("no_resources_expected", []):
        if entry.get("class_name") == class_name:
            return True, entry
    return False, None


def is_inheritance_class(policy: dict[str, Any], class_name: str) -> tuple[bool, dict | None]:
    for entry in policy.get("classes", {}).get("inherit_resources_from", []):
        if entry.get("class_name") == class_name:
            return True, entry
    return False, None


def is_dynamic_resource_class(policy: dict[str, Any], class_name: str) -> tuple[bool, dict | None]:
    for entry in policy.get("classes", {}).get("dynamic_resource_classes", []):
        if entry.get("class_name") == class_name:
            return True, entry
    return False, None


def is_ignored_inline_cdn(policy: dict[str, Any], file_path: str, url: str) -> bool:
    for entry in policy.get("classes", {}).get("ignore_inline_cdn_locations", []):
        if entry.get("file") in file_path and entry.get("url_pattern") == url:
            return True
    return False


def is_strict_promotable(policy: dict[str, Any], category: str) -> bool:
    promote_list = policy.get("strict", {}).get("promote_warnings_to_errors", [])
    never_list = policy.get("strict", {}).get("never_promote", [])
    if category in never_list:
        return False
    return category in promote_list
