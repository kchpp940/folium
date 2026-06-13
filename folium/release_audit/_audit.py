"""
Resource consistency audit checks.

Responsibility: all audit rule checks.
Depends on: _extract (data classes + resource collection), _policy (policy rules).

Each check function: takes an AuditResult + relevant inputs, mutates the result
in place by appending errors/warnings.
"""

from __future__ import annotations

import ast
import inspect
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from ._extract import (
    CDN_PATTERN,
    AuditResult,
    ClassResources,
    FOLIUM_ROOT,
    collect_all_resources,
    extract_package_from_url,
    extract_version_from_url,
)
from ._policy import (
    is_dynamic_resource_class,
    is_ignored_inline_cdn,
    is_inheritance_class,
    is_no_resources_class,
    is_strict_promotable,
    load_policy,
)


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


def check_version_drift(result: AuditResult, all_resources: dict[str, ClassResources],
                        policy: dict[str, Any]):
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
                pkg = extract_package_from_url(r.url)
                ver = extract_version_from_url(r.url)
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


def check_policy_compliance(result: AuditResult, all_resources: dict[str, ClassResources],
                            policy: dict[str, Any]):
    for class_name, cr in all_resources.items():
        has_resources = len(cr.js) > 0 or len(cr.css) > 0
        is_no_res, no_res_entry = is_no_resources_class(policy, class_name)
        is_inherit, inherit_entry = is_inheritance_class(policy, class_name)
        is_dynamic, dynamic_entry = is_dynamic_resource_class(policy, class_name)

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
                    f"JSCSSMixin subclass '{class_name}' has empty default_js/default_css "
                    f"but not in no_resources_expected policy",
                    location=class_name,
                )

        if is_inherit and cr.inherited_from:
            expected_parent = inherit_entry.get("parent_class")
            if expected_parent and cr.inherited_from != expected_parent:
                result.add_warning(
                    "inheritance_mismatch",
                    f"Class '{class_name}' inherits from '{cr.inherited_from}' "
                    f"but policy says '{expected_parent}'",
                    location=class_name,
                )


def check_inheritance_consistency(result: AuditResult, all_resources: dict[str, ClassResources],
                                  policy: dict[str, Any]):
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


def check_docs_consistency(result: AuditResult, all_resources: dict[str, ClassResources],
                           policy: dict[str, Any]):
    docs_config = policy.get("docs", {})
    if not docs_config.get("check_docs", True):
        return

    source_urls = _collect_all_urls(all_resources)

    try:
        from folium import features

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
                    if is_ignored_inline_cdn(policy, rel, url):
                        continue
                    result.add_warning(
                        "inline_cdn_url",
                        f"CDN URL found outside default_js/default_css",
                        location=rel,
                        detail=url[:120],
                    )


def apply_strict_policy(result: AuditResult, policy: dict[str, Any]):
    new_errors: list = []
    new_warnings: list = []

    for f in result.warnings:
        if is_strict_promotable(policy, f.category):
            new_errors.append(
                AuditFinding("error", f.category, f.message, f.location, f.detail)
            )
        else:
            new_warnings.append(f)

    result.errors.extend(new_errors)
    result.warnings = new_warnings


def run_audit(strict: bool = False) -> AuditResult:
    result = AuditResult()
    policy = load_policy()
    all_resources = collect_all_resources()

    for class_name, resources in all_resources.items():
        is_dynamic, _ = is_dynamic_resource_class(policy, class_name)
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
