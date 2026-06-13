"""
Release Resource Audit Tool for Folium (Policy-Driven Architecture).

Source of truth: plugin/feature Python source code (default_js / default_css).
Rules: release_audit_policy.json (NOT a static resource list).

Checks performed:
  1. Duplicate resource names within the same class
  2. Version drift: same package referenced at different versions
  3. Empty resources on classes that SHOULD have them (policy violation)
  4. Unexpected empty resources on classes that SHOULD NOT (policy violation)
  5. Inherited resource consistency: subclass matches parent declaration
  6. Dynamic resource (VegaLite variants) URL consistency across variants
  7. Documentation CDN URL consistency vs. source-derived URL set
  8. Inline CDN URLs outside default_js/default_css (policy-checked)

Usage:
    python -m folium.release_audit              # run audit, exit non-zero on error
    python -m folium.release_audit --json        # machine-readable output
    python -m folium.release_audit --strict      # promote warnings to errors (per policy)
    python -m folium.release_audit --generate-manifest  # generate JSON from source
    python -m folium.release_audit --generate-manifest --pretty
"""

from __future__ import annotations

import ast
import importlib
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CDN_PATTERN = re.compile(
    r"https?://(?:cdn\.jsdelivr\.net|cdnjs\.cloudflare\.com|unpkg\.com|code\.jquery\.com|d3js\.org|teastman\.github\.io|www\.webglearth\.com|netdna\.bootstrapcdn\.com)/[^\s\"'<>]+"
)

PACKAGE_VERSION_PATTERN = re.compile(r"@([0-9]+(?:\.[0-9]+)*)")
PATH_SEGMENT_VERSION_PATTERN = re.compile(r"/(\d+\.\d+(?:\.\d+)?)/")

FOLIUM_ROOT = Path(__file__).resolve().parent


@dataclass
class AuditFinding:
    severity: str
    category: str
    message: str
    location: str = ""
    detail: str = ""


@dataclass
class ResourceEntry:
    name: str
    url: str


@dataclass
class ClassResources:
    class_name: str
    module: str
    js: list[ResourceEntry]
    css: list[ResourceEntry]
    declared_on_class: bool
    is_jscssmixin_subclass: bool
    inherited_from: str | None = None


@dataclass
class AuditResult:
    errors: list[AuditFinding] = field(default_factory=list)
    warnings: list[AuditFinding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0

    def add_error(self, category: str, message: str, location: str = "", detail: str = ""):
        self.errors.append(AuditFinding("error", category, message, location, detail))

    def add_warning(self, category: str, message: str, location: str = "", detail: str = ""):
        self.warnings.append(AuditFinding("warning", category, message, location, detail))

    def merge(self, other: AuditResult):
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "errors": [
                {"severity": f.severity, "category": f.category, "message": f.message, "location": f.location, "detail": f.detail}
                for f in self.errors
            ],
            "warnings": [
                {"severity": f.severity, "category": f.category, "message": f.message, "location": f.location, "detail": f.detail}
                for f in self.warnings
            ],
        }


def load_policy() -> dict[str, Any]:
    policy_path = FOLIUM_ROOT / "release_audit_policy.json"
    with open(policy_path, encoding="utf-8") as f:
        return json.load(f)


def _is_jscssmixin_subclass(cls: type) -> bool:
    from folium.elements import JSCSSMixin

    return isinstance(cls, type) and issubclass(cls, JSCSSMixin)


def _collect_resources_from_class(cls: type) -> ClassResources:
    from folium.elements import JSCSSMixin

    declared_js = []
    declared_css = []

    if "default_js" in cls.__dict__:
        declared_js = [ResourceEntry(name=n, url=u) for n, u in getattr(cls, "default_js", [])]
    if "default_css" in cls.__dict__:
        declared_css = [ResourceEntry(name=n, url=u) for n, u in getattr(cls, "default_css", [])]

    inherited_from = None
    if not declared_js and not declared_css and _is_jscssmixin_subclass(cls):
        for base in cls.__mro__[1:]:
            if base is JSCSSMixin:
                break
            if "default_js" in base.__dict__ or "default_css" in base.__dict__:
                inherited_from = base.__name__
                break

    js = [ResourceEntry(name=n, url=u) for n, u in getattr(cls, "default_js", [])]
    css = [ResourceEntry(name=n, url=u) for n, u in getattr(cls, "default_css", [])]
    declared_on_class = "default_js" in cls.__dict__ or "default_css" in cls.__dict__

    return ClassResources(
        class_name=cls.__name__,
        module=cls.__module__,
        js=js,
        css=css,
        declared_on_class=declared_on_class,
        is_jscssmixin_subclass=_is_jscssmixin_subclass(cls),
        inherited_from=inherited_from,
    )


def _get_plugin_classes() -> dict[str, type]:
    from folium import plugins as plugins_pkg

    result = {}
    for name in plugins_pkg.__all__:
        obj = getattr(plugins_pkg, name, None)
        if obj is not None and isinstance(obj, type):
            result[name] = obj
    return result


def _get_feature_classes() -> dict[str, type]:
    from folium import features as features_pkg

    target_names = ["RegularPolygonMarker", "Vega", "VegaLite", "TopoJson", "Choropleth"]
    result = {}
    for name in target_names:
        obj = getattr(features_pkg, name, None)
        if obj is not None and isinstance(obj, type):
            result[name] = obj
    return result


def _get_map_class() -> type:
    from folium.folium import Map

    return Map


def _extract_package_from_url(url: str) -> str | None:
    for pattern in [
        re.compile(r"cdn\.jsdelivr\.net/npm/@[^/]+/([^/@]+)"),
        re.compile(r"cdn\.jsdelivr\.net/npm/([^/@]+)"),
        re.compile(r"cdn\.jsdelivr\.net/gh/([^/]+/[^/@]+)"),
        re.compile(r"cdnjs\.cloudflare\.com/ajax/libs/([^/]+)"),
        re.compile(r"unpkg\.com/@[^/]+/([^/@]+)"),
        re.compile(r"unpkg\.com/([^/@]+)"),
    ]:
        m = pattern.search(url)
        if m:
            return m.group(1)
    return None


def _extract_version_from_url(url: str) -> str | None:
    m = PACKAGE_VERSION_PATTERN.search(url)
    if m:
        return m.group(1)
    m2 = PATH_SEGMENT_VERSION_PATTERN.search(url)
    if m2:
        return m2.group(1)
    return None


def _is_no_resources_class(policy: dict[str, Any], class_name: str) -> tuple[bool, dict | None]:
    for entry in policy.get("classes", {}).get("no_resources_expected", []):
        if entry.get("class_name") == class_name:
            return True, entry
    return False, None


def _is_inheritance_class(policy: dict[str, Any], class_name: str) -> tuple[bool, dict | None]:
    for entry in policy.get("classes", {}).get("inherit_resources_from", []):
        if entry.get("class_name") == class_name:
            return True, entry
    return False, None


def _is_dynamic_resource_class(policy: dict[str, Any], class_name: str) -> tuple[bool, dict | None]:
    for entry in policy.get("classes", {}).get("dynamic_resource_classes", []):
        if entry.get("class_name") == class_name:
            return True, entry
    return False, None


def _is_ignored_inline_cdn(policy: dict[str, Any], file_path: str, url: str) -> bool:
    for entry in policy.get("classes", {}).get("ignore_inline_cdn_locations", []):
        if entry.get("file") in file_path and entry.get("url_pattern") == url:
            return True
    return False


def _is_strict_promotable(policy: dict[str, Any], category: str) -> bool:
    promote_list = policy.get("strict", {}).get("promote_warnings_to_errors", [])
    never_list = policy.get("strict", {}).get("never_promote", [])
    if category in never_list:
        return False
    return category in promote_list


def check_duplicate_names(result: AuditResult, resources: ClassResources):
    for kind_name, resource_list in [("JS", resources.js), ("CSS", resources.css)]:
        names: dict[str, int] = {}
        for r in resource_list:
            names[r.name] = names.get(r.name, 0) + 1
        for name, count in names.items():
            if count > 1:
                result.add_error(
                    "duplicate_name",
                    f"Duplicate {kind_name} resource name '{name}' in {resources.class_name}",
                    location=resources.class_name,
                    detail=f"appears {count} times in default_{kind_name.lower()}",
                )


def check_version_drift(result: AuditResult, all_resources: dict[str, ClassResources], policy: dict[str, Any]):
    if not policy.get("version_drift", {}).get("enabled", True):
        return

    package_versions: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    unversioned_packages: dict[str, list[str]] = defaultdict(list)

    allowed_multi = set(policy.get("version_drift", {}).get("allowed_multi_version_packages", []))
    allow_unversioned = policy.get("version_drift", {}).get("allow_unversioned_packages", True)
    unversioned_warn = policy.get("version_drift", {}).get("unversioned_warning", True)

    for class_name, cr in all_resources.items():
        for kind_name, resource_list in [("js", cr.js), ("css", cr.css)]:
            for r in resource_list:
                pkg = _extract_package_from_url(r.url)
                ver = _extract_version_from_url(r.url)
                if pkg:
                    if ver:
                        if pkg not in allowed_multi:
                            package_versions[pkg][ver].append(f"{class_name}.{kind_name}.{r.name}")
                    else:
                        unversioned_packages[pkg].append(f"{class_name}.{kind_name}.{r.name}")

    for pkg, versions in package_versions.items():
        if len(versions) > 1:
            ver_list = ", ".join(f"{v} (used by {', '.join(locs)})" for v, locs in versions.items())
            result.add_warning(
                "version_drift",
                f"Package '{pkg}' referenced at multiple versions",
                detail=ver_list,
            )

    if unversioned_warn and not allow_unversioned:
        for pkg, locs in unversioned_packages.items():
            result.add_warning(
                "unversioned_package",
                f"Package '{pkg}' referenced without version number",
                detail=f"used by {', '.join(locs)}",
            )


def check_policy_compliance(result: AuditResult, all_resources: dict[str, ClassResources], policy: dict[str, Any]):
    for class_name, cr in all_resources.items():
        has_resources = len(cr.js) > 0 or len(cr.css) > 0
        is_no_res, no_res_entry = _is_no_resources_class(policy, class_name)
        is_inherit, inherit_entry = _is_inheritance_class(policy, class_name)
        is_dynamic, dynamic_entry = _is_dynamic_resource_class(policy, class_name)

        if is_no_res and has_resources:
            result.add_warning(
                "policy_violation",
                f"Class '{class_name}' marked as no_resources_expected but has resources",
                location=class_name,
                detail=f"policy reason: {no_res_entry.get('reason', 'N/A')}",
            )

        if not is_no_res and not is_dynamic and not has_resources:
            if cr.is_jscssmixin_subclass:
                result.add_warning(
                    "policy_violation",
                    f"JSCSSMixin subclass '{class_name}' has empty default_js/default_css but not in no_resources_expected policy",
                    location=class_name,
                )

        if is_inherit and cr.inherited_from:
            expected_parent = inherit_entry.get("parent_class")
            if expected_parent and cr.inherited_from != expected_parent:
                result.add_warning(
                    "inheritance_mismatch",
                    f"Class '{class_name}' inherits from '{cr.inherited_from}' but policy says '{expected_parent}'",
                    location=class_name,
                )


def check_inheritance_consistency(result: AuditResult, all_resources: dict[str, ClassResources], policy: dict[str, Any]):
    for entry in policy.get("classes", {}).get("inherit_resources_from", []):
        class_name = entry.get("class_name")
        parent_name = entry.get("parent_class")

        if class_name not in all_resources or parent_name not in all_resources:
            continue

        child = all_resources[class_name]
        parent = all_resources[parent_name]

        if child.declared_on_class:
            child_js_urls = {(r.name, r.url) for r in child.js}
            parent_js_urls = {(r.name, r.url) for r in parent.js}
            child_css_urls = {(r.name, r.url) for r in child.css}
            parent_css_urls = {(r.name, r.url) for r in parent.css}

            if child_js_urls != parent_js_urls:
                diff = child_js_urls.symmetric_difference(parent_js_urls)
                result.add_warning(
                    "inheritance_resource_mismatch",
                    f"'{class_name}' declares own JS resources that differ from parent '{parent_name}'",
                    location=class_name,
                    detail=f"differences: {diff}",
                )

            if child_css_urls != parent_css_urls:
                diff = child_css_urls.symmetric_difference(parent_css_urls)
                result.add_warning(
                    "inheritance_resource_mismatch",
                    f"'{class_name}' declares own CSS resources that differ from parent '{parent_name}'",
                    location=class_name,
                    detail=f"differences: {diff}",
                )


def _collect_all_urls(all_resources: dict[str, ClassResources]) -> set[str]:
    urls: set[str] = set()
    for cr in all_resources.values():
        for r in cr.js + cr.css:
            urls.add(r.url)
    return urls


def check_docs_consistency(result: AuditResult, all_resources: dict[str, ClassResources], policy: dict[str, Any]):
    import inspect

    docs_config = policy.get("docs", {})
    if not docs_config.get("check_docs", True):
        return

    source_urls = _collect_all_urls(all_resources)

    from folium import features

    try:
        source = inspect.getsource(features)
        for url in CDN_PATTERN.findall(source):
            source_urls.add(url)
    except Exception:
        pass

    docs_root = FOLIUM_ROOT.parent / docs_config.get("docs_root", "docs")
    if not docs_root.exists():
        return

    allowed_patterns = [re.compile(p) for p in docs_config.get("allowed_extra_url_patterns", [])]
    allowed_exact = set(docs_config.get("allowed_extra_urls_exact", []))
    ignore_paths = set(docs_config.get("ignore_paths", []))

    file_patterns = docs_config.get("file_patterns", ["*.md", "*.rst"])
    doc_files: list[Path] = []
    for pattern in file_patterns:
        doc_files.extend(docs_root.rglob(pattern))

    for doc_file in doc_files:
        rel_doc = str(doc_file.relative_to(FOLIUM_ROOT.parent))
        if any(ignore in rel_doc for ignore in ignore_paths):
            continue

        content = doc_file.read_text(encoding="utf-8", errors="ignore")
        doc_urls = CDN_PATTERN.findall(content)
        for url in doc_urls:
            if url in source_urls:
                continue
            if url in allowed_exact:
                result.add_warning(
                    "docs_allowed_extra_url",
                    f"CDN URL in docs is in allowed_exact list",
                    location=rel_doc,
                    detail=url,
                )
                continue
            if any(p.search(url) for p in allowed_patterns):
                result.add_warning(
                    "docs_allowed_extra_url",
                    f"CDN URL in docs matches allowed_extra_url_patterns",
                    location=rel_doc,
                    detail=url,
                )
                continue
            result.add_warning(
                "docs_url_not_in_source",
                f"CDN URL in docs not found in source code resources",
                location=rel_doc,
                detail=url,
            )


def check_inline_cdn_urls(result: AuditResult, policy: dict[str, Any]):
    src_dir = FOLIUM_ROOT
    py_files = list(src_dir.rglob("*.py"))

    for py_file in py_files:
        rel = str(py_file.relative_to(FOLIUM_ROOT))
        content = py_file.read_text(encoding="utf-8", errors="ignore")
        try:
            tree = ast.parse(content, filename=rel)
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue

            is_resource_decl = False
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in ("default_js", "default_css"):
                    is_resource_decl = True
                    break
            if is_resource_decl:
                continue

            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                url = node.value.value
                if CDN_PATTERN.match(url):
                    if _is_ignored_inline_cdn(policy, rel, url):
                        continue
                    result.add_warning(
                        "inline_cdn_url",
                        f"CDN URL found outside default_js/default_css",
                        location=rel,
                        detail=url[:120],
                    )


def check_vegalite_variants(result: AuditResult, policy: dict[str, Any]):
    dynamic_cfg = policy.get("classes", {}).get("dynamic_resource_classes", [])
    vegalite_cfg = None
    for cfg in dynamic_cfg:
        if cfg.get("class_name") == "VegaLite":
            vegalite_cfg = cfg
            break
    if not vegalite_cfg:
        return

    features_path = FOLIUM_ROOT / "features.py"
    if not features_path.exists():
        return

    content = features_path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(content, filename="features.py")
    except SyntaxError:
        return

    method_url_map: dict[str, list[str]] = defaultdict(list)
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if not node.name.startswith(vegalite_cfg.get("method_prefix", "_embed_vegalite_v")):
            continue
        for child in ast.walk(node):
            if not isinstance(child, ast.Constant):
                continue
            if not isinstance(child.value, str):
                continue
            if CDN_PATTERN.match(child.value):
                method_url_map[node.name].append(child.value)

    variants = vegalite_cfg.get("variants", [])
    for variant in variants:
        method_name = f"{vegalite_cfg.get('method_prefix', '_embed_vegalite_v')}{variant}"
        if method_name not in method_url_map:
            result.add_error(
                "vegalite_variant_missing",
                f"VegaLite variant method '{method_name}' not found in features.py",
                location=f"features.py::{method_name}",
            )
            continue

        urls = method_url_map[method_name]
        if not urls:
            result.add_warning(
                "vegalite_variant_empty",
                f"VegaLite variant '{variant}' has no CDN URLs in its embed method",
                location=f"features.py::{method_name}",
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


def _resource_id(url: str) -> str:
    import hashlib

    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]


def _cdn_host(url: str) -> str | None:
    from urllib.parse import urlparse

    host = urlparse(url).netloc
    if "jsdelivr" in host:
        return "jsdelivr"
    if "cdnjs" in host:
        return "cdnjs"
    if "unpkg" in host:
        return "unpkg"
    if "jquery" in host:
        return "jquery"
    if "d3js" in host:
        return "d3js"
    if "bootstrapcdn" in host:
        return "bootstrapcdn"
    if "webglearth" in host:
        return "webglearth"
    if "github.io" in host:
        return "github_pages"
    if host:
        return host
    return None


def build_stable_manifest(all_resources: dict[str, ClassResources]) -> dict[str, Any]:
    import datetime

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
                rid = _resource_id(r.url)
                if rid not in resources_flat:
                    resources_flat[rid] = {
                        "id": rid,
                        "name": r.name,
                        "resource_type": rtype,
                        "url": r.url,
                        "source_class": class_name,
                        "module": cr.module,
                        "package": _extract_package_from_url(r.url),
                        "version": _extract_version_from_url(r.url),
                        "cdn_host": _cdn_host(r.url),
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
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
        "folium_version": folium_ver,
        "resource_count": len(resources_list),
        "resources": resources_list,
        "by_class": by_class,
    }
    return manifest


def manifest_json_schema() -> dict[str, Any]:
    return dict(MANIFEST_JSON_SCHEMA)


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


def generate_manifest(all_resources: dict[str, ClassResources], pretty: bool = False) -> str:
    manifest = build_stable_manifest(all_resources)
    return json.dumps(manifest, indent=2 if pretty else None, sort_keys=True)


def download_resources(manifest: dict[str, Any], output_dir: Path,
                       timeout: float = 30.0) -> dict[str, Any]:
    import hashlib
    from urllib.parse import urlparse
    from urllib.request import urlopen

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
                actual_sha = hashlib.sha256(content).hexdigest()[:12]
                if actual_sha != rid:
                    entry["status"] = "hash_mismatch_warning"
                    entry["hash_expected"] = rid
                    entry["hash_actual"] = actual_sha
                else:
                    entry["status"] = "downloaded"
                entry["size_bytes"] = len(content)
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
        "hash_mismatches": sum(1 for d in download_report if d.get("status") == "hash_mismatch_warning"),
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


def collect_all_resources() -> dict[str, ClassResources]:
    result: dict[str, ClassResources] = {}

    map_cls = _get_map_class()
    result["Map"] = _collect_resources_from_class(map_cls)

    for name, cls in _get_feature_classes().items():
        result[name] = _collect_resources_from_class(cls)

    for name, cls in _get_plugin_classes().items():
        result[name] = _collect_resources_from_class(cls)

    return result


def apply_strict_policy(result: AuditResult, policy: dict[str, Any]):
    new_errors: list[AuditFinding] = []
    new_warnings: list[AuditFinding] = []

    for f in result.warnings:
        if _is_strict_promotable(policy, f.category):
            new_errors.append(AuditFinding("error", f.category, f.message, f.location, f.detail))
        else:
            new_warnings.append(f)

    result.errors.extend(new_errors)
    result.warnings = new_warnings


def run_audit(strict: bool = False) -> AuditResult:
    result = AuditResult()
    policy = load_policy()
    all_resources = collect_all_resources()

    for class_name, resources in all_resources.items():
        is_dynamic, _ = _is_dynamic_resource_class(policy, class_name)
        if is_dynamic:
            continue
        check_duplicate_names(result, resources)

    check_version_drift(result, all_resources, policy)
    check_policy_compliance(result, all_resources, policy)
    check_inheritance_consistency(result, all_resources, policy)
    check_vegalite_variants(result, policy)
    check_docs_consistency(result, all_resources, policy)
    check_inline_cdn_urls(result, policy)

    if strict:
        apply_strict_policy(result, policy)

    return result


def format_findings(findings: list[AuditFinding], label: str) -> str:
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


def main():
    import argparse

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
    manifest_p.add_argument("--print-schema", action="store_true", help="Print JSON Schema")
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

    if args.command == "manifest":
        if args.print_schema:
            schema = manifest_json_schema()
            print(json.dumps(schema, indent=2 if (args.pretty or getattr(args, "pretty", False)) else None, sort_keys=True))
            sys.exit(0)

        if args.validate:
            manifest_file = Path(args.validate)
            if not manifest_file.exists():
                print(f"ERROR: manifest file not found: {manifest_file}", file=sys.stderr)
                sys.exit(2)
            manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
            errors = validate_manifest(manifest_data)
            if errors:
                print(f"Manifest validation FAILED ({len(errors)} error(s)):")
                for e in errors:
                    print(f"  - {e}")
                sys.exit(1)
            print(f"Manifest valid. Schema version: {manifest_data.get('manifest_schema_version')}, "
                  f"resources: {manifest_data.get('resource_count')}")
            sys.exit(0)

        all_res = collect_all_resources()
        print(generate_manifest(all_res, pretty=args.pretty or getattr(args, "pretty", False)))
        sys.exit(0)

    if args.command == "offline":
        output_dir = Path(args.dir).resolve()
        if args.manifest:
            manifest_file = Path(args.manifest).resolve()
            manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
            errors = validate_manifest(manifest_data)
            if errors:
                print(f"ERROR: provided manifest fails validation:", file=sys.stderr)
                for e in errors:
                    print(f"  - {e}", file=sys.stderr)
                sys.exit(2)
        else:
            all_res = collect_all_resources()
            manifest_data = build_stable_manifest(all_res)

        manifest_path = output_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest_data, indent=2, sort_keys=True), encoding="utf-8")

        report = download_resources(manifest_data, output_dir, timeout=args.timeout)
        summary = report["summary"]
        print(f"\nOffline download complete. Output directory: {output_dir}")
        print(f"  Total resources: {summary['total_resources']}")
        print(f"  Cached:          {summary['cached']}")
        print(f"  Downloaded:      {summary['downloaded']}")
        print(f"  Failed:          {summary['failed']}")
        print(f"  Hash mismatches: {summary['hash_mismatches']}")
        print(f"\nManifest saved to: {manifest_path}")
        print(f"Download index:    {output_dir / 'index.json'}")

        if summary["failed"] > 0:
            sys.exit(1)
        sys.exit(0)

    result = run_audit(strict=args.strict)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        output = format_findings(result.errors, "ERRORS")
        output += format_findings(result.warnings, "WARNINGS")
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

    sys.exit(0 if result.ok else 1)


if __name__ == "__main__":
    main()
