"""
Release Resource Audit Tool for Folium.

Validates that CDN resource declarations stay consistent across:
  - Plugin / feature Python source files  (default_js / default_css)
  - The central resource_manifest.json     (single source of truth)
  - Documentation examples                 (docs/ directory)
  - Inline CDN URLs inside Jinja templates

Also validates public API export boundaries:
  - Every audited module defines __all__
  - All names in __all__ are importable from the module
  - Public names not in __all__ are flagged as potential leaks
  - Internal implementation names must not appear in __all__
  - folium.__init__.__all__ covers all public names from submodules
  - __all__ lists contain no duplicates

Checks performed:
  1. Duplicate resource names within the same class
  2. Version drift: the same library referenced at different versions
     across plugins / features
  3. URL inconsistency between source code and resource_manifest.json
  4. Manifest completeness: every resource in source must exist in the
     manifest, and every manifest entry must have a corresponding source
  5. Documentation CDN references that diverge from the manifest
  6. API boundary: __all__ consistency and internal name leakage

Usage:
    python -m folium.release_audit              # run all checks, exit non-zero on error
    python -m folium.release_audit --json        # machine-readable output
    python -m folium.release_audit --strict      # treat warnings as errors
"""

from __future__ import annotations

import ast
import importlib
import inspect
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

PACKAGE_VERSION_PATTERN = re.compile(
    r"@(?:^|/)([0-9]+(?:\.[0-9]+)*(?:\.[0-9]+)*)"
)

FOLIUM_ROOT = Path(__file__).resolve().parent


@dataclass
class AuditFinding:
    severity: str
    category: str
    message: str
    location: str = ""
    detail: str = ""


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


def load_manifest() -> dict[str, Any]:
    manifest_path = FOLIUM_ROOT / "resource_manifest.json"
    with open(manifest_path, encoding="utf-8") as f:
        return json.load(f)


def _collect_resources_from_class(cls: type) -> dict[str, list[tuple[str, str]]]:
    result: dict[str, list[tuple[str, str]]] = {"js": [], "css": []}
    for name, url in getattr(cls, "default_js", []):
        result["js"].append((name, url))
    for name, url in getattr(cls, "default_css", []):
        result["css"].append((name, url))
    return result


def _get_plugin_classes() -> dict[str, type]:
    from folium import plugins as plugins_pkg

    result = {}
    for name in plugins_pkg.__all__:
        obj = getattr(plugins_pkg, name, None)
        if obj is not None and isinstance(obj, type):
            result[name] = obj
    return result


def _get_feature_classes() -> dict[str, type]:
    from folium import features

    feature_names = [
        "RegularPolygonMarker",
        "Vega",
        "VegaLite",
        "Choropleth",
    ]
    result = {}
    for name in feature_names:
        obj = getattr(features, name, None)
        if obj is not None and isinstance(obj, type):
            result[name] = obj
    return result


def _extract_package_from_url(url: str) -> str | None:
    for pattern in [
        re.compile(r"cdn\.jsdelivr\.net/npm/([^/@]+)"),
        re.compile(r"cdn\.jsdelivr\.net/npm/@[^/]+/([^/@]+)"),
        re.compile(r"cdn\.jsdelivr\.net/gh/([^/]+/[^/@]+)"),
        re.compile(r"cdnjs\.cloudflare\.com/ajax/libs/([^/]+)"),
        re.compile(r"unpkg\.com/([^/@]+)"),
        re.compile(r"unpkg\.com/@[^/]+/([^/@]+)"),
    ]:
        m = pattern.search(url)
        if m:
            return m.group(1)
    return None


def _extract_version_from_url(url: str) -> str | None:
    m = PACKAGE_VERSION_PATTERN.search(url)
    if m:
        return m.group(1)
    m2 = re.search(r"/(\d+\.\d+(?:\.\d+)?)/", url)
    if m2:
        return m2.group(1)
    return None


def check_duplicate_names(result: AuditResult, resources: dict[str, list[tuple[str, str]]], class_name: str):
    for kind in ("js", "css"):
        names = [name for name, _ in resources.get(kind, [])]
        seen: dict[str, int] = {}
        for name in names:
            seen[name] = seen.get(name, 0) + 1
        for name, count in seen.items():
            if count > 1:
                result.add_error(
                    "duplicate_name",
                    f"Duplicate {kind} resource name '{name}' in {class_name}",
                    location=class_name,
                    detail=f"appears {count} times in default_{kind}",
                )


def check_version_drift(result: AuditResult, all_resources: dict[str, dict[str, list[tuple[str, str]]]]):
    package_versions: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for class_name, resources in all_resources.items():
        for kind in ("js", "css"):
            for name, url in resources.get(kind, []):
                pkg = _extract_package_from_url(url)
                ver = _extract_version_from_url(url)
                if pkg and ver:
                    package_versions[pkg][ver].append(f"{class_name}.{kind}.{name}")

    for pkg, versions in package_versions.items():
        if len(versions) > 1:
            ver_list = ", ".join(f"{v} (used by {', '.join(locs)})" for v, locs in versions.items())
            result.add_warning(
                "version_drift",
                f"Package '{pkg}' referenced at multiple versions",
                detail=ver_list,
            )


def check_manifest_consistency(result: AuditResult, manifest: dict[str, Any], class_name: str, resources: dict[str, list[tuple[str, str]]], manifest_section: str):
    if manifest_section == "map_defaults":
        manifest_js = manifest.get("map_defaults", {}).get("js", [])
        manifest_css = manifest.get("map_defaults", {}).get("css", [])
    elif manifest_section == "features":
        entry = manifest.get("features", {}).get(class_name, {})
        if not entry:
            result.add_error(
                "manifest_missing",
                f"Feature class '{class_name}' not found in manifest",
                location=class_name,
            )
            return
        manifest_js = entry.get("js", [])
        manifest_css = entry.get("css", [])
    elif manifest_section == "plugins":
        entry = manifest.get("plugins", {}).get(class_name, {})
        if not entry:
            result.add_error(
                "manifest_missing",
                f"Plugin class '{class_name}' not found in manifest",
                location=class_name,
            )
            return
        if entry.get("js_dynamic"):
            return
        manifest_js = entry.get("js", [])
        manifest_css = entry.get("css", [])
    else:
        return

    manifest_js_map = {item["name"]: item["url"] for item in manifest_js}
    manifest_css_map = {item["name"]: item["url"] for item in manifest_css}

    source_js_map = {name: url for name, url in resources.get("js", [])}
    source_css_map = {name: url for name, url in resources.get("css", [])}

    for name, url in source_js_map.items():
        if name not in manifest_js_map:
            result.add_error(
                "manifest_missing",
                f"JS resource '{name}' in {class_name} not in manifest",
                location=class_name,
                detail=f"URL: {url}",
            )
        elif manifest_js_map[name] != url:
            result.add_error(
                "url_mismatch",
                f"JS resource '{name}' URL mismatch in {class_name}",
                location=class_name,
                detail=f"source: {url}\nmanifest: {manifest_js_map[name]}",
            )

    for name, url in source_css_map.items():
        if name not in manifest_css_map:
            result.add_error(
                "manifest_missing",
                f"CSS resource '{name}' in {class_name} not in manifest",
                location=class_name,
                detail=f"URL: {url}",
            )
        elif manifest_css_map[name] != url:
            result.add_error(
                "url_mismatch",
                f"CSS resource '{name}' URL mismatch in {class_name}",
                location=class_name,
                detail=f"source: {url}\nmanifest: {manifest_css_map[name]}",
            )

    for name in manifest_js_map:
        if name not in source_js_map:
            result.add_warning(
                "manifest_orphan",
                f"JS resource '{name}' in manifest but not in {class_name} source",
                location=class_name,
            )

    for name in manifest_css_map:
        if name not in source_css_map:
            result.add_warning(
                "manifest_orphan",
                f"CSS resource '{name}' in manifest but not in {class_name} source",
                location=class_name,
            )


def check_docs_consistency(result: AuditResult, manifest: dict[str, Any]):
    docs_dir = FOLIUM_ROOT.parent / "docs"
    if not docs_dir.exists():
        return

    manifest_urls: set[str] = set()
    for section_key in ("map_defaults",):
        for kind in ("js", "css"):
            for item in manifest.get(section_key, {}).get(kind, []):
                manifest_urls.add(item["url"])
    for section_key in ("features", "plugins"):
        for class_name, entry in manifest.get(section_key, {}).items():
            for kind in ("js", "css"):
                for item in entry.get(kind, []):
                    manifest_urls.add(item["url"])

    doc_files = list(docs_dir.rglob("*.md")) + list(docs_dir.rglob("*.rst"))
    for doc_file in doc_files:
        content = doc_file.read_text(encoding="utf-8", errors="ignore")
        doc_urls = CDN_PATTERN.findall(content)
        for url in doc_urls:
            if url not in manifest_urls:
                result.add_warning(
                    "docs_url_not_in_manifest",
                    f"CDN URL in docs not found in manifest",
                    location=str(doc_file.relative_to(FOLIUM_ROOT.parent)),
                    detail=url,
                )


def check_inline_cdn_urls(result: AuditResult):
    src_dir = FOLIUM_ROOT
    py_files = list(src_dir.rglob("*.py"))

    for py_file in py_files:
        rel = py_file.relative_to(FOLIUM_ROOT)
        content = py_file.read_text(encoding="utf-8", errors="ignore")
        try:
            tree = ast.parse(content, filename=str(rel))
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in (
                    "default_js",
                    "default_css",
                    "_default_js",
                    "_default_css",
                ):
                    continue

            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                url = node.value.value
                if CDN_PATTERN.match(url):
                    result.add_warning(
                        "inline_cdn_url",
                        f"CDN URL found outside default_js/default_css",
                        location=str(rel),
                        detail=url[:120],
                    )


def check_features_dynamic_urls(result: AuditResult):
    features_path = FOLIUM_ROOT / "features.py"
    if not features_path.exists():
        return

    content = features_path.read_text(encoding="utf-8")
    urls = CDN_PATTERN.findall(content)

    method_url_map: dict[str, list[str]] = defaultdict(list)
    current_method = None
    for line in content.splitlines():
        m = re.match(r"\s+def (_embed_\w+)", line)
        if m:
            current_method = m.group(1)
        for url in CDN_PATTERN.findall(line):
            if current_method:
                method_url_map[current_method].append(url)

    manifest_variants = load_manifest().get("features", {}).get("VegaLite", {}).get("variants", {})
    for variant_name, variant_data in manifest_variants.items():
        variant_urls = set()
        for item in variant_data.get("js", []):
            variant_urls.add(item["url"])
        for item in variant_data.get("css", []):
            variant_urls.add(item["url"])

        method_name = f"_embed_vegalite_{variant_name}"
        if method_name in method_url_map:
            method_urls = set(method_url_map[method_name])
            missing = method_urls - variant_urls
            if missing:
                result.add_error(
                    "url_mismatch",
                    f"VegaLite variant '{variant_name}': URLs in source not in manifest",
                    location=f"features.py::{method_name}",
                    detail=f"missing from manifest: {missing}",
                )
            extra = variant_urls - method_urls
            if extra:
                result.add_warning(
                    "manifest_orphan",
                    f"VegaLite variant '{variant_name}': URLs in manifest not in source",
                    location=f"features.py::{method_name}",
                    detail=f"extra in manifest: {extra}",
                )


AUDITED_MODULES = {
    "folium": "folium",
    "folium.map": "folium.map",
    "folium.features": "folium.features",
    "folium.raster_layers": "folium.raster_layers",
    "folium.vector_layers": "folium.vector_layers",
    "folium.elements": "folium.elements",
    "folium.folium": "folium.folium",
    "folium.utilities": "folium.utilities",
    "folium.plugins": "folium.plugins",
}

_NAMES_ALLOWED_IN_MODULE_NS_WITHOUT_ALL = {
    "__name__",
    "__doc__",
    "__package__",
    "__loader__",
    "__spec__",
    "__file__",
    "__path__",
    "__cached__",
    "__builtins__",
    "__all__",
    "__version__",
    "__pdoc__",
    "annotations",
}

_INIT_REEXPORT_MODULES = {
    "folium.map",
    "folium.features",
    "folium.raster_layers",
    "folium.vector_layers",
}

_KNOWN_INTERNAL_NAMES: dict[str, set[str]] = {
    "folium.map": {"classproperty", "Class", "Evented", "Layer"},
    "folium.features": {"GeoJsonStyleMapper", "GeoJsonDetail", "TypeStyleMapping"},
    "folium.vector_layers": {"path_options", "BaseMultiLocation"},
    "folium.elements": {
        "leaflet_method",
        "JSCSSMixin",
        "EventHandler",
        "ElementAddToElement",
        "IncludeStatement",
        "MethodCall",
        "CssLink",
        "JavascriptLink",
    },
    "folium.folium": {"GlobalSwitches"},
    "folium.utilities": {
        "_validate_locations_basics",
        "_is_url",
        "if_pandas_df_convert_to_numpy",
        "parse_font_size",
        "escape_double_quotes",
        "get_and_assert_figure_root",
    },
}


def _is_module_defined(mod_name: str, obj) -> bool:
    obj_module = getattr(obj, "__module__", None)
    if obj_module is None:
        return False
    return obj_module == mod_name or obj_module.startswith(mod_name + ".")


def check_all_defined(result: AuditResult):
    for label, module_name in AUDITED_MODULES.items():
        mod = importlib.import_module(module_name)
        if not hasattr(mod, "__all__"):
            result.add_error(
                "missing_all",
                f"Module {module_name} does not define __all__",
                location=module_name,
            )


def check_no_extra_public_names(result: AuditResult):
    for label, module_name in AUDITED_MODULES.items():
        mod = importlib.import_module(module_name)
        all_names = set(getattr(mod, "__all__", []))
        internal_names = _KNOWN_INTERNAL_NAMES.get(module_name, set())
        candidates: set[str] = set()
        for name in dir(mod):
            if name.startswith("_"):
                continue
            if name in _NAMES_ALLOWED_IN_MODULE_NS_WITHOUT_ALL:
                continue
            if name in internal_names:
                continue
            try:
                obj = getattr(mod, name)
            except Exception:
                continue
            if inspect.ismodule(obj):
                continue
            if not _is_module_defined(module_name, obj):
                continue
            if isinstance(obj, type) and not issubclass(obj, BaseException):
                candidates.add(name)
            elif callable(obj):
                candidates.add(name)
        extra = candidates - all_names
        if extra:
            result.add_warning(
                "name_not_in_all",
                f"Public names in {module_name} not in __all__",
                location=module_name,
                detail=", ".join(sorted(extra)),
            )


def check_init_all_superset(result: AuditResult):
    import folium

    for label, module_name in AUDITED_MODULES.items():
        if module_name == "folium":
            continue
        if module_name not in _INIT_REEXPORT_MODULES:
            continue
        mod = importlib.import_module(module_name)
        mod_all = set(getattr(mod, "__all__", []))
        for name in mod_all:
            if not hasattr(folium, name):
                result.add_warning(
                    "module_public_not_in_init",
                    f"{module_name}.{name} is public but not re-exported in folium.__init__",
                    location=f"{module_name}.{name}",
                )


def check_all_names_importable(result: AuditResult):
    for label, module_name in AUDITED_MODULES.items():
        mod = importlib.import_module(module_name)
        all_names = getattr(mod, "__all__", None)
        if all_names is None:
            continue
        for name in all_names:
            if not hasattr(mod, name):
                result.add_error(
                    "all_name_not_found",
                    f"Name '{name}' in __all__ not found in module {module_name}",
                    location=module_name,
                    detail=name,
                )


def check_internal_not_in_all(result: AuditResult):
    for module_name, internal_names in _KNOWN_INTERNAL_NAMES.items():
        mod = importlib.import_module(module_name)
        all_names = set(getattr(mod, "__all__", []))
        leaked = internal_names & all_names
        if leaked:
            result.add_error(
                "internal_in_all",
                f"Internal names should not be in __all__ of {module_name}",
                location=module_name,
                detail=", ".join(sorted(leaked)),
            )


def check_all_sorted_and_unique(result: AuditResult):
    for label, module_name in AUDITED_MODULES.items():
        mod = importlib.import_module(module_name)
        all_list = getattr(mod, "__all__", None)
        if all_list is None:
            continue
        if len(all_list) != len(set(all_list)):
            result.add_error(
                "all_duplicates",
                f"__all__ in {module_name} contains duplicates",
                location=module_name,
                detail=", ".join(
                    name for name in all_list if all_list.count(name) > 1
                ),
            )


def run_api_audit(strict: bool = False) -> AuditResult:
    result = AuditResult()

    check_all_defined(result)
    check_all_names_importable(result)
    check_no_extra_public_names(result)
    check_init_all_superset(result)
    check_internal_not_in_all(result)
    check_all_sorted_and_unique(result)

    if strict:
        for w in result.warnings:
            result.errors.append(w)
        result.warnings.clear()

    return result


def run_audit(strict: bool = False) -> AuditResult:
    result = AuditResult()

    manifest = load_manifest()

    from folium.folium import Map

    map_resources = _collect_resources_from_class(Map)
    check_duplicate_names(result, map_resources, "Map")
    check_manifest_consistency(result, manifest, "Map", map_resources, "map_defaults")

    feature_classes = _get_feature_classes()
    all_resources: dict[str, dict[str, list[tuple[str, str]]]] = {}
    all_resources["Map"] = map_resources

    for class_name, cls in feature_classes.items():
        if class_name == "VegaLite":
            continue
        resources = _collect_resources_from_class(cls)
        all_resources[class_name] = resources
        check_duplicate_names(result, resources, class_name)
        check_manifest_consistency(result, manifest, class_name, resources, "features")

    check_features_dynamic_urls(result)

    plugin_classes = _get_plugin_classes()
    for class_name, cls in plugin_classes.items():
        resources = _collect_resources_from_class(cls)
        all_resources[class_name] = resources
        check_duplicate_names(result, resources, class_name)
        check_manifest_consistency(result, manifest, class_name, resources, "plugins")

    check_version_drift(result, all_resources)
    check_docs_consistency(result, manifest)
    check_inline_cdn_urls(result)

    api_result = run_api_audit(strict=False)
    result.merge(api_result)

    if strict:
        for w in result.warnings:
            result.errors.append(w)
        result.warnings.clear()

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
    parser.add_argument("--strict", action="store_true", help="Treat warnings as errors")
    args = parser.parse_args()

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
