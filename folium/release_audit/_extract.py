"""
Resource extraction from source code.

Responsibility:
  - Data classes: ResourceEntry, ClassResources
  - URL parsing utilities: package, version, CDN host, resource ID
  - Extract default_js/default_css from plugin/feature classes via introspection

This is the SHARED FOUNDATION used by both audit checks and manifest generation.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

CDN_PATTERN = re.compile(
    r"https?://(?:cdn\.jsdelivr\.net|cdnjs\.cloudflare\.com|unpkg\.com|code\.jquery\.com|d3js\.org|teastman\.github\.io|www\.webglearth\.com|netdna\.bootstrapcdn\.com)/[^\s\"'<>]+"
)

PACKAGE_VERSION_PATTERN = re.compile(r"@([0-9]+(?:\.[0-9]+)*)")
PATH_SEGMENT_VERSION_PATTERN = re.compile(r"/(\d+\.\d+(?:\.\d+)?)/")

FOLIUM_ROOT = Path(__file__).resolve().parent.parent


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
                {"severity": f.severity, "category": f.category, "message": f.message,
                 "location": f.location, "detail": f.detail}
                for f in self.errors
            ],
            "warnings": [
                {"severity": f.severity, "category": f.category, "message": f.message,
                 "location": f.location, "detail": f.detail}
                for f in self.warnings
            ],
        }


def resource_id(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]


def extract_package_from_url(url: str) -> str | None:
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


def extract_version_from_url(url: str) -> str | None:
    m = PACKAGE_VERSION_PATTERN.search(url)
    if m:
        return m.group(1)
    m2 = PATH_SEGMENT_VERSION_PATTERN.search(url)
    if m2:
        return m2.group(1)
    return None


def cdn_host(url: str) -> str | None:
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


def _is_jscssmixin_subclass(cls: type) -> bool:
    from folium.elements import JSCSSMixin

    return isinstance(cls, type) and issubclass(cls, JSCSSMixin)


def collect_resources_from_class(cls: type) -> ClassResources:
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


def get_plugin_classes() -> dict[str, type]:
    from folium import plugins as plugins_pkg

    result = {}
    for name in plugins_pkg.__all__:
        obj = getattr(plugins_pkg, name, None)
        if obj is not None and isinstance(obj, type):
            result[name] = obj
    return result


def get_feature_classes() -> dict[str, type]:
    from folium import features as features_pkg

    target_names = ["RegularPolygonMarker", "Vega", "VegaLite", "TopoJson", "Choropleth"]
    result = {}
    for name in target_names:
        obj = getattr(features_pkg, name, None)
        if obj is not None and isinstance(obj, type):
            result[name] = obj
    return result


def get_map_class() -> type:
    from folium.folium import Map

    return Map


def collect_all_resources() -> dict[str, ClassResources]:
    result: dict[str, ClassResources] = {}

    map_cls = get_map_class()
    result["Map"] = collect_resources_from_class(map_cls)

    for name, cls in get_feature_classes().items():
        result[name] = collect_resources_from_class(cls)

    for name, cls in get_plugin_classes().items():
        result[name] = collect_resources_from_class(cls)

    return result
