"""
Folium Developer Diagnostics (INTERNAL).

Unified diagnostic entry point that collects:
  - Environment info (Python, OS, dependencies)
  - Optional dependency status
  - Resource policy (manifest summary, plugin resources)
  - Cache directory status
  - Template filter registration
  - Plugin resource audit (reuses _audit.resources)
  - API boundary audit (reuses _audit.api_audit)
  - Test markers and smoke policy (reuses _audit.smoke)

This is an INTERNAL module. Use python -m folium.diagnostics instead,
or import from folium._audit.diagnostics for internal tooling.

The JSON output has a STABLE schema with version number, suitable for
automated consumption by CI pipelines and issue template bots.
"""

from __future__ import annotations

import importlib
import os
import platform
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from folium._audit.api_audit import (
    collect_api_summary,
    run_api_audit,
)
from folium._audit.resources import (
    FOLIUM_ROOT,
    collect_plugin_resources,
    collect_resource_summary,
)
from folium._audit.resources import (
    run_audit as run_resource_audit,
)
from folium._audit.smoke import (
    collect_smoke_example_summary,
    collect_test_marker_summary,
)

PROJECT_ROOT = FOLIUM_ROOT.parent

DIAGNOSTICS_SCHEMA_VERSION = "1.1.0"
DIAGNOSTICS_SCHEMA_URL = "https://python-visualization.github.io/folium/schemas/diagnostics/v1.1.json"


OPTIONAL_DEPENDENCIES: dict[str, list[str]] = {
    "pandas": ["pandas"],
    "geopandas": ["geopandas"],
    "geodatasets": ["geodatasets"],
    "selenium": ["selenium"],
    "pillow": ["PIL"],
    "matplotlib": ["matplotlib"],
    "scipy": ["scipy"],
    "vega_datasets": ["vega_datasets"],
    "altair": ["altair"],
    "fiona": ["fiona"],
    "gpxpy": ["gpxpy"],
    "jenkspy": ["jenkspy"],
    "owslib": ["owslib"],
    "cartopy": ["cartopy"],
    "descartes": ["descartes"],
    "vincent": ["vincent"],
    "xyzservices": ["xyzservices"],
    "requests": ["requests"],
    "pixelmatch": ["pixelmatch"],
}


@dataclass
class DiagnosticSection:
    """A single section of the diagnostic report.

    Fields:
        name: Section identifier (stable across schema versions)
        status: One of "ok", "warning", "error", "info"
        available: Whether the data source for this section is available.
                   False means the section could not be fully collected
                   (e.g. tests/ directory missing in an installed package).
        reason: Human-readable reason when available=False
        data_source: Metadata about where the data came from
        summary: One-line human-readable summary
        details: Structured section-specific data
    """
    name: str
    status: str = "info"
    available: bool = True
    reason: str = ""
    data_source: dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "available": self.available,
            "reason": self.reason,
            "data_source": self.data_source,
            "summary": self.summary,
            "details": self.details,
        }


@dataclass
class DiagnosticReport:
    """Complete diagnostic report with schema metadata."""
    schema_version: str = DIAGNOSTICS_SCHEMA_VERSION
    schema_url: str = DIAGNOSTICS_SCHEMA_URL
    generated_at: str = ""
    sections: list[DiagnosticSection] = field(default_factory=list)

    def add_section(self, section: DiagnosticSection) -> None:
        self.sections.append(section)

    def to_dict(self) -> dict[str, Any]:
        import datetime
        return {
            "$schema": self.schema_url,
            "schema_version": self.schema_version,
            "generated_at": self.generated_at or datetime.datetime.utcnow().isoformat() + "Z",
            "overall_status": self._overall_status(),
            "sections": [s.to_dict() for s in self.sections],
            "section_names": [s.name for s in self.sections],
            "section_count": len(self.sections),
        }

    def _overall_status(self) -> str:
        has_error = any(s.status == "error" for s in self.sections)
        has_warning = any(s.status == "warning" for s in self.sections)
        if has_error:
            return "error"
        if has_warning:
            return "warning"
        return "ok"


def _try_import(module_name: str) -> tuple[bool, str | None]:
    try:
        mod = importlib.import_module(module_name)
        version = getattr(mod, "__version__", "unknown")
        return True, version
    except ImportError:
        return False, None


def collect_environment() -> DiagnosticSection:
    import branca
    import jinja2
    import numpy

    import folium

    section = DiagnosticSection(name="environment", status="info")
    section.data_source = {
        "type": "runtime",
        "always_available": True,
    }
    section.summary = f"Python {sys.version.split()[0]} on {platform.system()}"
    section.details = {
        "python_version": sys.version,
        "python_implementation": platform.python_implementation(),
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "system": platform.system(),
        "machine": platform.machine(),
        "release": platform.release(),
        "folium_version": getattr(folium, "__version__", "unknown"),
        "branca_version": getattr(branca, "__version__", "unknown"),
        "jinja2_version": getattr(jinja2, "__version__", "unknown"),
        "numpy_version": getattr(numpy, "__version__", "unknown"),
        "folium_install_path": str(FOLIUM_ROOT),
        "working_directory": os.getcwd(),
    }
    return section


def collect_optional_deps() -> DiagnosticSection:
    section = DiagnosticSection(name="optional_dependencies", status="info")
    section.data_source = {
        "type": "python_modules",
        "always_available": True,
    }
    available: dict[str, dict[str, Any]] = {}
    missing: list[str] = []

    for display_name, module_names in OPTIONAL_DEPENDENCIES.items():
        found = False
        version = None
        for mod_name in module_names:
            ok, ver = _try_import(mod_name)
            if ok:
                found = True
                version = ver
                break
        if found:
            available[display_name] = {
                "available": True,
                "version": version,
            }
        else:
            missing.append(display_name)
            available[display_name] = {
                "available": False,
                "version": None,
            }

    section.summary = f"{len(available) - len(missing)}/{len(available)} optional deps available"
    section.details = {
        "available_count": len(available) - len(missing),
        "total_count": len(available),
        "missing": sorted(missing),
        "dependencies": available,
    }

    if missing:
        section.status = "warning"

    return section


def collect_resource_policy() -> DiagnosticSection:
    section = DiagnosticSection(name="resource_policy", status="info")
    section.data_source = {
        "type": "package_file",
        "path": str(FOLIUM_ROOT / "resource_manifest.json"),
        "always_available": True,
    }
    summary = collect_resource_summary()

    map_js = summary["map_defaults"]["js_count"]
    map_css = summary["map_defaults"]["css_count"]
    feature_count = summary["feature_count"]
    plugin_count = summary["plugin_count"]

    section.summary = (
        f"Manifest: {map_js} JS + {map_css} CSS (map), "
        f"{feature_count} features, {plugin_count} plugins"
    )
    section.details = summary

    plugin_resources = collect_plugin_resources()
    section.details["plugin_resources"] = plugin_resources

    return section


def collect_cache_info() -> DiagnosticSection:
    section = DiagnosticSection(name="cache_directory", status="info")
    section.data_source = {
        "type": "system",
        "always_available": True,
    }

    temp_dir = tempfile.gettempdir()
    folium_temp_prefix = "folium_"

    try:
        temp_path = Path(temp_dir)
        folium_files = [
            f.name for f in temp_path.iterdir()
            if f.name.startswith(folium_temp_prefix)
        ] if temp_path.exists() else []
    except (PermissionError, OSError):
        folium_files = []

    xdg_cache = os.environ.get("XDG_CACHE_HOME")
    home_cache = Path.home() / ".cache"
    folium_cache_candidates = [
        ("tempfile.gettempdir()", temp_dir),
        ("XDG_CACHE_HOME", xdg_cache if xdg_cache else "not set"),
        ("~/.cache/folium", str(home_cache / "folium") if home_cache.exists() else "~/.cache does not exist"),
    ]

    section.summary = f"Temp dir: {temp_dir}, folium temp files: {len(folium_files)}"
    section.details = {
        "temp_directory": temp_dir,
        "folium_temp_prefix": folium_temp_prefix,
        "folium_temp_file_count": len(folium_files),
        "folium_temp_files": folium_files[:20],
        "cache_locations": {
            name: path for name, path in folium_cache_candidates
        },
        "environment_variables": {
            "TMPDIR": os.environ.get("TMPDIR", ""),
            "TEMP": os.environ.get("TEMP", ""),
            "TMP": os.environ.get("TMP", ""),
            "XDG_CACHE_HOME": os.environ.get("XDG_CACHE_HOME", ""),
        },
    }
    return section


def collect_template_filters() -> DiagnosticSection:
    from folium.template import Environment

    section = DiagnosticSection(name="template_filters", status="info")
    section.data_source = {
        "type": "package_module",
        "module": "folium.template",
        "always_available": True,
    }

    env = Environment()
    filters = dict(env.filters)
    globals_dict = dict(env.globals)

    folium_filters = {
        name: str(type(fn).__name__)
        for name, fn in filters.items()
    }

    section.summary = f"{len(folium_filters)} Jinja2 filters registered"
    section.details = {
        "filter_count": len(filters),
        "filters": folium_filters,
        "globals_count": len(globals_dict),
        "builtin_filter_names": sorted(list(filters.keys())),
        "custom_filters": [
            name for name in filters
            if name in ("tojavascript",)
        ],
    }
    return section


def collect_plugin_resource_audit() -> DiagnosticSection:
    section = DiagnosticSection(name="plugin_resource_audit", status="info")
    section.data_source = {
        "type": "package_audit",
        "module": "folium._audit.resources",
        "always_available": True,
    }

    try:
        result = run_resource_audit(strict=False)
        status = "ok" if result.ok else "error"
        if result.warnings and result.ok:
            status = "warning"

        section.summary = (
            f"Audit: {len(result.errors)} errors, {len(result.warnings)} warnings"
        )
        section.status = status
        section.details = result.to_dict()
    except Exception as e:
        section.status = "error"
        section.summary = f"Audit failed: {e}"
        section.details = {"error": str(e)}

    return section


def collect_api_audit() -> DiagnosticSection:
    section = DiagnosticSection(name="api_boundary_audit", status="info")
    section.data_source = {
        "type": "package_audit",
        "module": "folium._audit.api_audit",
        "always_available": True,
    }

    try:
        result = run_api_audit(strict=False)
        status = "ok" if result.ok else "error"
        if result.warnings and result.ok:
            status = "warning"

        section.summary = (
            f"API audit: {len(result.errors)} errors, {len(result.warnings)} warnings"
        )
        section.status = status
        section.details = result.to_dict()

        api_summary = collect_api_summary()
        section.details["api_summary"] = api_summary
    except Exception as e:
        section.status = "error"
        section.summary = f"API audit failed: {e}"
        section.details = {"error": str(e)}

    return section


def collect_test_markers() -> DiagnosticSection:
    section = DiagnosticSection(name="test_markers", status="info")

    marker_info = collect_test_marker_summary()
    smoke_info = collect_smoke_example_summary()

    markers_available = marker_info.get("available", True)
    smoke_available = smoke_info.get("available", True)
    fully_available = markers_available and smoke_available

    section.available = fully_available
    section.data_source = {
        "type": "source_repo",
        "always_available": False,
        "markers_available": markers_available,
        "smoke_examples_available": smoke_available,
        "expected_paths": {
            **marker_info.get("expected_paths", {}),
            **smoke_info.get("expected_paths", {}),
        },
    }

    if not fully_available:
        reasons = []
        if not markers_available:
            reasons.append(marker_info.get("reason", "test marker data unavailable"))
        if not smoke_available:
            reasons.append(smoke_info.get("reason", "smoke example data unavailable"))
        section.reason = "; ".join(reasons)
        section.summary = (
            f"Test markers: source repo data not available "
            f"({section.reason[:60]}...)" if len(section.reason) > 60 else section.reason
        )
        section.status = "info"
    else:
        section.summary = f"{marker_info['marker_count']} test markers, {smoke_info['total_count']} smoke examples"

    section.details = {
        "markers": marker_info,
        "smoke_examples": smoke_info,
    }

    if not fully_available:
        pass
    elif not marker_info.get("marker_count", 0):
        section.status = "warning"

    return section


SECTION_COLLECTORS: dict[str, Any] = {
    "environment": collect_environment,
    "optional_dependencies": collect_optional_deps,
    "resource_policy": collect_resource_policy,
    "cache_directory": collect_cache_info,
    "template_filters": collect_template_filters,
    "plugin_resource_audit": collect_plugin_resource_audit,
    "api_boundary_audit": collect_api_audit,
    "test_markers": collect_test_markers,
}


def run_diagnostics(sections: list[str] | None = None) -> DiagnosticReport:
    """Run the full diagnostic suite and return a structured report."""
    if sections is None:
        sections = list(SECTION_COLLECTORS.keys())
    else:
        unknown = [s for s in sections if s not in SECTION_COLLECTORS]
        if unknown:
            raise ValueError(
                f"Unknown diagnostic sections: {', '.join(unknown)}. "
                f"Available: {', '.join(SECTION_COLLECTORS.keys())}"
            )

    report = DiagnosticReport()
    for section_name in sections:
        collector = SECTION_COLLECTORS[section_name]
        try:
            section = collector()
            report.add_section(section)
        except Exception as e:
            report.add_section(DiagnosticSection(
                name=section_name,
                status="error",
                summary=f"Collection failed: {e}",
                details={"error": str(e)},
            ))

    return report


def get_json_schema() -> dict[str, Any]:
    """Return the JSON Schema for the diagnostic report output."""
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "$id": DIAGNOSTICS_SCHEMA_URL,
        "title": "Folium Diagnostic Report",
        "description": "Structured diagnostic report for Folium developer tooling",
        "version": DIAGNOSTICS_SCHEMA_VERSION,
        "type": "object",
        "required": ["schema_version", "sections"],
        "properties": {
            "$schema": {
                "type": "string",
                "const": DIAGNOSTICS_SCHEMA_URL,
            },
            "schema_version": {
                "type": "string",
                "pattern": r"^\d+\.\d+\.\d+$",
                "description": "Semantic version of the report schema",
            },
            "generated_at": {
                "type": "string",
                "format": "date-time",
                "description": "ISO 8601 UTC timestamp of report generation",
            },
            "overall_status": {
                "type": "string",
                "enum": ["ok", "warning", "error"],
                "description": "Overall status aggregated from all sections",
            },
            "section_count": {
                "type": "integer",
                "minimum": 0,
            },
            "section_names": {
                "type": "array",
                "items": {"type": "string"},
            },
            "sections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["name", "status", "available", "summary", "details"],
                    "properties": {
                        "name": {"type": "string"},
                        "status": {
                            "type": "string",
                            "enum": ["ok", "warning", "error", "info"],
                        },
                        "available": {
                            "type": "boolean",
                            "description": (
                                "Whether the data source for this section is available. "
                                "False means the section could not be fully collected "
                                "(e.g. tests/ directory missing in an installed package)."
                            ),
                        },
                        "reason": {
                            "type": "string",
                            "description": "Human-readable reason when available=False",
                        },
                        "data_source": {
                            "type": "object",
                            "description": "Metadata about where the section data comes from",
                            "properties": {
                                "type": {
                                    "type": "string",
                                    "enum": [
                                        "runtime",
                                        "python_modules",
                                        "package_file",
                                        "package_module",
                                        "package_audit",
                                        "system",
                                        "source_repo",
                                    ],
                                },
                                "always_available": {"type": "boolean"},
                                "path": {"type": "string"},
                                "module": {"type": "string"},
                                "expected_paths": {"type": "object"},
                            },
                            "additionalProperties": True,
                        },
                        "summary": {"type": "string"},
                        "details": {"type": "object"},
                    },
                },
            },
        },
    }


def format_human_readable(report: DiagnosticReport) -> str:
    lines = []
    lines.append("=" * 70)
    lines.append("  FOLIUM DIAGNOSTIC REPORT")
    lines.append(f"  Schema version: {report.schema_version}")
    lines.append("=" * 70)

    for section in report.sections:
        status_icon = {
            "ok": "✓",
            "warning": "⚠",
            "error": "✗",
            "info": "ℹ",
        }.get(section.status, "?")

        lines.append("")
        lines.append(f"  [{status_icon}] {section.name.upper()}")

        if not section.available:
            lines.append("      ⚠ DATA SOURCE UNAVAILABLE")
            if section.reason:
                lines.append(f"      Reason: {section.reason}")
            data_src = section.data_source
            if data_src and data_src.get("expected_paths"):
                lines.append("      Expected paths:")
                for label, path in data_src["expected_paths"].items():
                    lines.append(f"        - {label}: {path}")

        lines.append(f"      {section.summary}")
        lines.append(f"      {'-' * 50}")

        details = section.details

        if section.name == "environment":
            lines.append(f"      Python: {details.get('python_version', '').split(chr(10))[0]}")
            lines.append(f"      Platform: {details.get('platform', 'unknown')}")
            lines.append(f"      Folium: {details.get('folium_version', 'unknown')}")
            lines.append(f"      Branca: {details.get('branca_version', 'unknown')}")
            lines.append(f"      Jinja2: {details.get('jinja2_version', 'unknown')}")
            lines.append(f"      NumPy: {details.get('numpy_version', 'unknown')}")
            lines.append(f"      Install path: {details.get('folium_install_path', '')}")

        elif section.name == "optional_dependencies":
            deps = details.get("dependencies", {})
            for name in sorted(deps.keys()):
                info = deps[name]
                if info["available"]:
                    ver = info.get("version", "unknown")
                    lines.append(f"      ✓ {name}: {ver}")
                else:
                    lines.append(f"      ✗ {name}: not installed")

        elif section.name == "resource_policy":
            lines.append(f"      Manifest: {details.get('manifest_path', '')}")
            map_defs = details.get("map_defaults", {})
            lines.append(f"      Map defaults: {map_defs.get('js_count', 0)} JS, {map_defs.get('css_count', 0)} CSS")
            lines.append(f"      Features ({details.get('feature_count', 0)}): {', '.join(details.get('features', [])[:5])}...")
            lines.append(f"      Plugins ({details.get('plugin_count', 0)}): {', '.join(details.get('plugins', [])[:5])}...")
            plugins_list = details.get("plugin_resources", [])
            if plugins_list:
                lines.append(f"      Plugin resource details ({len(plugins_list)}):")
                for p in plugins_list[:8]:
                    js = p.get("js_resources", 0)
                    css = p.get("css_resources", 0)
                    lines.append(f"        - {p['name']}: {js} JS, {css} CSS")
                if len(plugins_list) > 8:
                    lines.append(f"        ... and {len(plugins_list) - 8} more")

        elif section.name == "cache_directory":
            lines.append(f"      Temp directory: {details.get('temp_directory', '')}")
            lines.append(f"      Folium temp files: {details.get('folium_temp_file_count', 0)}")
            if details.get("folium_temp_files"):
                for f in details["folium_temp_files"][:5]:
                    lines.append(f"        - {f}")

        elif section.name == "template_filters":
            lines.append(f"      Total filters: {details.get('filter_count', 0)}")
            lines.append(f"      Custom filters: {', '.join(details.get('custom_filters', []))}")
            filter_names = details.get("builtin_filter_names", [])
            if filter_names:
                lines.append(f"      All filters: {', '.join(filter_names[:10])}...")

        elif section.name in ("plugin_resource_audit", "api_boundary_audit"):
            lines.append(f"      OK: {details.get('ok', False)}")
            lines.append(f"      Errors: {details.get('error_count', 0)}")
            lines.append(f"      Warnings: {details.get('warning_count', 0)}")
            for err in details.get("errors", [])[:5]:
                lines.append(f"        ERROR [{err.get('category', '')}]: {err.get('message', '')}")
                if err.get("location"):
                    lines.append(f"          Location: {err['location']}")
            for warn in details.get("warnings", [])[:5]:
                lines.append(f"        WARN [{warn.get('category', '')}]: {warn.get('message', '')}")

            if section.name == "api_boundary_audit":
                api_sum = details.get("api_summary", {})
                if api_sum:
                    lines.append(f"      API surface: {api_sum.get('total_public_api_names', 0)} public names")
                    for mod, count in api_sum.get("module_all_counts", {}).items():
                        lines.append(f"        {mod}: {count} names")

        elif section.name == "test_markers":
            marker_info = details.get("markers", {})
            markers = marker_info.get("markers", {})
            lines.append(f"      Total markers: {marker_info.get('marker_count', 0)}")
            lines.append(f"      Default (run always): {', '.join(marker_info.get('default_markers', []))}")
            lines.append(f"      Optional (need flag): {', '.join(marker_info.get('optional_markers', []))}")
            lines.append(f"      Run all: {marker_info.get('run_all_flag', '')}")

            if markers:
                for mname, minfo in markers.items():
                    if isinstance(minfo, dict):
                        flag = minfo.get("required_flag") or "always"
                        lines.append(f"        - {mname}: {minfo.get('description', '')} [{flag}]")

            smoke = details.get("smoke_examples", {})
            if smoke.get("available"):
                lines.append(f"      Smoke examples: {smoke.get('total_count', 0)} total")
                lines.append(f"        Offline: {smoke.get('offline_count', 0)}")
                lines.append(f"        Network: {smoke.get('network_count', 0)}")
                lines.append(f"        Tags: {', '.join(smoke.get('tags', {}).keys())}")
            elif not section.available:
                lines.append("      Smoke examples: unavailable (see reason above)")

    overall = report._overall_status()
    icon = {"ok": "✓", "warning": "⚠", "error": "✗"}.get(overall, "?")
    lines.append("")
    lines.append(f"  OVERALL: [{icon}] {overall.upper()}")
    lines.append("=" * 70)

    return "\n".join(lines)
