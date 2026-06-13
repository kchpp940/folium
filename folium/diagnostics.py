"""
Folium Developer Diagnostics Tool.

Provides a unified diagnostic entry point that collects environment info,
optional dependency status, resource policy, cache directory, template filter
registration, plugin resource audit, and test marker status.

Designed to help developers and maintainers diagnose "works locally, fails in CI"
problems by gathering all relevant context in one structured report.

Usage:
    python -m folium.diagnostics              # human-readable report
    python -m folium.diagnostics --json       # machine-readable JSON
    python -m folium.diagnostics --sections environment,deps  # only specific sections
"""

from __future__ import annotations

import importlib
import json
import os
import platform
import re
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

FOLIUM_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = FOLIUM_ROOT.parent


@dataclass
class DiagnosticSection:
    name: str
    status: str = "info"
    summary: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class DiagnosticReport:
    sections: list[DiagnosticSection] = field(default_factory=list)

    def add_section(self, section: DiagnosticSection) -> None:
        self.sections.append(section)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sections": [
                {
                    "name": s.name,
                    "status": s.status,
                    "summary": s.summary,
                    "details": s.details,
                }
                for s in self.sections
            ]
        }


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


def collect_optional_deps() -> DiagnosticSection:
    section = DiagnosticSection(name="optional_dependencies", status="info")
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
    from folium.release_audit import load_manifest

    section = DiagnosticSection(name="resource_policy", status="info")
    manifest = load_manifest()

    map_js = len(manifest.get("map_defaults", {}).get("js", []))
    map_css = len(manifest.get("map_defaults", {}).get("css", []))
    features = list(manifest.get("features", {}).keys())
    plugins = list(manifest.get("plugins", {}).keys())

    section.summary = (
        f"Manifest: {map_js} JS + {map_css} CSS (map), "
        f"{len(features)} features, {len(plugins)} plugins"
    )
    section.details = {
        "manifest_path": str(FOLIUM_ROOT / "resource_manifest.json"),
        "map_defaults": {
            "js_count": map_js,
            "css_count": map_css,
            "js_resources": [
                r["name"] for r in manifest.get("map_defaults", {}).get("js", [])
            ],
            "css_resources": [
                r["name"] for r in manifest.get("map_defaults", {}).get("css", [])
            ],
        },
        "features": features,
        "feature_count": len(features),
        "plugins": plugins,
        "plugin_count": len(plugins),
    }
    return section


def collect_cache_info() -> DiagnosticSection:
    section = DiagnosticSection(name="cache_directory", status="info")

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


def collect_plugin_audit() -> DiagnosticSection:
    from folium.release_audit import run_audit

    section = DiagnosticSection(name="plugin_resource_audit", status="info")

    try:
        result = run_audit(strict=False)
        status = "ok" if result.ok else "error"
        if result.warnings and result.ok:
            status = "warning"

        section.summary = (
            f"Audit: {len(result.errors)} errors, {len(result.warnings)} warnings"
        )
        section.status = status
        section.details = {
            "ok": result.ok,
            "error_count": len(result.errors),
            "warning_count": len(result.warnings),
            "errors": [
                {
                    "severity": f.severity,
                    "category": f.category,
                    "message": f.message,
                    "location": f.location,
                    "detail": f.detail,
                }
                for f in result.errors
            ],
            "warnings": [
                {
                    "severity": f.severity,
                    "category": f.category,
                    "message": f.message,
                    "location": f.location,
                    "detail": f.detail,
                }
                for f in result.warnings
            ],
        }
    except Exception as e:
        section.status = "error"
        section.summary = f"Audit failed: {e}"
        section.details = {"error": str(e)}

    return section


def collect_test_markers() -> DiagnosticSection:
    section = DiagnosticSection(name="test_markers", status="info")

    conftest_path = PROJECT_ROOT / "tests" / "conftest.py"

    markers: dict[str, dict[str, Any]] = {}

    if conftest_path.exists():
        content = conftest_path.read_text(encoding="utf-8")

        marker_descriptions: dict[str, str] = {}
        for match in re.finditer(
            r'"markers",\s*\n\s*"([^"]+):\s*([^"]+)"',
            content,
        ):
            name = match.group(1).strip()
            desc = match.group(2).strip()
            marker_descriptions[name] = desc

        cli_options: dict[str, dict[str, str]] = {}
        for match in re.finditer(
            r'parser\.addoption\(\s*\n\s*"(--[\w-]+)",',
            content,
        ):
            opt_name = match.group(1)
            cli_options[opt_name] = {
                "flag": opt_name,
            }

        default_markers = ["core", "plugins", "audit", "smoke"]
        requires_flag_markers = [
            "external_data",
            "render",
            "selenium",
            "smoke_network",
        ]

        for name in default_markers + requires_flag_markers:
            markers[name] = {
                "name": name,
                "description": marker_descriptions.get(name, ""),
                "runs_by_default": name in default_markers,
                "required_flag": f"--run-{name.replace('_', '-')}" if name in requires_flag_markers else None,
            }

        pyproject_path = PROJECT_ROOT / "pyproject.toml"
        pytest_config: dict[str, Any] = {}
        if pyproject_path.exists():
            try:
                import tomllib
                with open(pyproject_path, "rb") as f:
                    config = tomllib.load(f)
                pytest_config = config.get("tool", {}).get("pytest", {}).get("ini_options", {})
            except (ImportError, Exception):
                pytest_config = {}

        section.summary = f"{len(markers)} test markers defined"
        section.details = {
            "markers": markers,
            "marker_count": len(markers),
            "default_markers": [m for m in markers if markers[m]["runs_by_default"]],
            "optional_markers": [m for m in markers if not markers[m]["runs_by_default"]],
            "conftest_path": str(conftest_path),
            "pytest_config": pytest_config,
            "run_all_flag": "--run-all",
        }
    else:
        section.status = "warning"
        section.summary = "conftest.py not found"
        section.details = {"conftest_path": str(conftest_path)}

    return section


def collect_plugin_info() -> DiagnosticSection:
    from folium import plugins

    section = DiagnosticSection(name="plugins", status="info")

    plugin_classes = []
    for name in plugins.__all__:
        cls = getattr(plugins, name, None)
        if cls is not None and isinstance(cls, type):
            default_js = getattr(cls, "default_js", [])
            default_css = getattr(cls, "default_css", [])
            plugin_classes.append({
                "name": name,
                "js_resources": len(default_js),
                "css_resources": len(default_css),
                "js_names": [n for n, _ in default_js],
                "css_names": [n for n, _ in default_css],
            })

    section.summary = f"{len(plugin_classes)} plugin classes available"
    section.details = {
        "plugin_count": len(plugin_classes),
        "plugins": plugin_classes,
        "__all___count": len(plugins.__all__),
    }
    return section


SECTION_COLLECTORS: dict[str, callable] = {
    "environment": collect_environment,
    "optional_dependencies": collect_optional_deps,
    "resource_policy": collect_resource_policy,
    "cache_directory": collect_cache_info,
    "template_filters": collect_template_filters,
    "plugin_resource_audit": collect_plugin_audit,
    "test_markers": collect_test_markers,
    "plugins": collect_plugin_info,
}


def run_diagnostics(sections: list[str] | None = None) -> DiagnosticReport:
    if sections is None:
        sections = list(SECTION_COLLECTORS.keys())

    report = DiagnosticReport()
    for section_name in sections:
        collector = SECTION_COLLECTORS.get(section_name)
        if collector:
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


def format_human_readable(report: DiagnosticReport) -> str:
    lines = []
    lines.append("=" * 70)
    lines.append("  FOLIUM DIAGNOSTIC REPORT")
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
            lines.append(f"      Plugins ({details.get('plugin_count', 0)}: {', '.join(details.get('plugins', [])[:5])}...")

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

        elif section.name == "plugin_resource_audit":
            lines.append(f"      OK: {details.get('ok', False)}")
            lines.append(f"      Errors: {details.get('error_count', 0)}")
            lines.append(f"      Warnings: {details.get('warning_count', 0)}")
            for err in details.get("errors", [])[:5]:
                lines.append(f"        ERROR [{err.get('category', '')}]: {err.get('message', '')}")
                if err.get("location"):
                    lines.append(f"          Location: {err['location']}")
            for warn in details.get("warnings", [])[:5]:
                lines.append(f"        WARN [{warn.get('category', '')}]: {warn.get('message', '')}")

        elif section.name == "test_markers":
            lines.append(f"      Total markers: {details.get('marker_count', 0)}")
            lines.append(f"      Default (run always): {', '.join(details.get('default_markers', []))}")
            lines.append(f"      Optional (need flag): {', '.join(details.get('optional_markers', []))}")
            lines.append(f"      Run all: {details.get('run_all_flag', '')}")

        elif section.name == "plugins":
            lines.append(f"      Plugin count: {details.get('plugin_count', 0)}")
            plugins_list = details.get("plugins", [])
            for p in plugins_list[:10]:
                js = p.get("js_resources", 0)
                css = p.get("css_resources", 0)
                lines.append(f"      - {p['name']}: {js} JS, {css} CSS")
            if len(plugins_list) > 10:
                lines.append(f"      ... and {len(plugins_list) - 10} more")

    lines.append("")
    lines.append("=" * 70)
    lines.append("  END OF DIAGNOSTIC REPORT")
    lines.append("=" * 70)

    return "\n".join(lines)


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Folium Developer Diagnostics - gather environment and config info",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as structured JSON",
    )
    parser.add_argument(
        "--sections",
        type=str,
        default=None,
        help="Comma-separated list of sections to include (default: all)",
    )
    parser.add_argument(
        "--list-sections",
        action="store_true",
        help="List available diagnostic sections and exit",
    )
    args = parser.parse_args()

    if args.list_sections:
        print("Available diagnostic sections:")
        for name in SECTION_COLLECTORS.keys():
            print(f"  - {name}")
        return

    sections = None
    if args.sections:
        sections = [s.strip() for s in args.sections.split(",")]

    report = run_diagnostics(sections=sections)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2, default=str))
    else:
        print(format_human_readable(report))


if __name__ == "__main__":
    main()
