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


def generate_manifest(all_resources: dict[str, ClassResources], pretty: bool = False) -> str:
    manifest: dict[str, Any] = {
        "_generated": "Generated from folium.release_audit --generate-manifest. Source of truth is default_js/default_css in source code.",
        "_generated_at": "",
        "map_defaults": {"js": [], "css": []},
        "features": {},
        "plugins": {},
    }

    import datetime

    manifest["_generated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")

    for class_name, cr in all_resources.items():
        js_list = [{"name": r.name, "url": r.url} for r in cr.js]
        css_list = [{"name": r.name, "url": r.url} for r in cr.css]
        entry = {"js": js_list, "css": css_list}
        if cr.inherited_from:
            entry["inherited_from"] = cr.inherited_from
        if not cr.declared_on_class:
            entry["inherited"] = True
        entry["module"] = cr.module

        if class_name == "Map":
            manifest["map_defaults"]["js"] = js_list
            manifest["map_defaults"]["css"] = css_list
            manifest["map_defaults"]["module"] = cr.module
        elif cr.module.startswith("folium.features"):
            manifest["features"][class_name] = entry
        elif cr.module.startswith("folium.plugins"):
            manifest["plugins"][class_name] = entry

    return json.dumps(manifest, indent=2 if pretty else None, sort_keys=True)


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

    parser = argparse.ArgumentParser(description="Folium Release Resource Audit")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    parser.add_argument("--strict", action="store_true", help="Promote warnings to errors per policy")
    parser.add_argument("--generate-manifest", action="store_true", help="Generate JSON manifest from source code")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print generated manifest")
    args = parser.parse_args()

    if args.generate_manifest:
        all_res = collect_all_resources()
        print(generate_manifest(all_res, pretty=args.pretty))
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
