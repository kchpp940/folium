"""
Tests for folium.release_audit CLI (python -m folium.release_audit ...)

Responsibility coverage:
  - Subcommand parsing (audit, manifest, offline)
  - Backward-compatible legacy flags (--strict, --generate-manifest)
  - Exit codes
  - Manifest --validate flag works correctly
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.audit

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PY = [sys.executable, "-m", "folium.release_audit"]


def _run(args, **kwargs):
    cmd = PY + args
    return subprocess.run(
        cmd, cwd=str(PROJECT_ROOT),
        capture_output=True, text=True,
        **kwargs,
    )


class TestAuditSubcommand:
    def test_audit_default_subcommand(self):
        r = _run([])
        assert r.returncode in (0, 1)
        assert "Error" not in r.stdout or "ERRORS" in r.stdout or "passed" in r.stdout

    def test_audit_explicit_subcommand(self):
        r = _run(["audit"])
        assert r.returncode in (0, 1)

    def test_audit_strict_exit_code(self):
        r = _run(["audit", "--strict"])
        assert r.returncode == 0, f"Strict audit should pass: {r.stdout + r.stderr}"

    def test_audit_json_output(self):
        r = _run(["audit", "--json"])
        data = json.loads(r.stdout)
        assert "ok" in data
        assert "error_count" in data
        assert "warning_count" in data


class TestManifestSubcommand:
    def test_manifest_generate_valid_json(self):
        r = _run(["manifest", "--generate"])
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert "manifest_schema_version" in data

    def test_manifest_pretty_output(self):
        r = _run(["manifest", "--generate", "--pretty"])
        assert r.returncode == 0
        assert "\n" in r.stdout

    def test_manifest_print_schema(self):
        r = _run(["manifest", "--print-schema"])
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert "$schema" in data
        assert "$defs" in data

    def test_manifest_validate_valid_file(self, tmp_path):
        r = _run(["manifest", "--generate"])
        manifest_file = tmp_path / "m.json"
        manifest_file.write_text(r.stdout)

        rv = _run(["manifest", "--validate", str(manifest_file)])
        assert rv.returncode == 0
        assert "Manifest valid" in rv.stdout

    def test_manifest_validate_invalid_file(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("{\"foo\": \"bar\"}")

        rv = _run(["manifest", "--validate", str(bad)])
        assert rv.returncode == 1
        assert "FAILED" in rv.stdout

    def test_manifest_validate_nonexistent_file(self):
        rv = _run(["manifest", "--validate", "/does/not/exist.json"])
        assert rv.returncode == 2


class TestOfflineSubcommand:
    def test_offline_empty_run(self, tmp_path):
        out_dir = tmp_path / "offline"
        r = _run(["offline", "--dir", str(out_dir)], timeout=120)
        assert r.returncode == 0 or "Failed" in r.stdout or "Traceback" not in r.stderr
        # If network is available, check for structure; otherwise just ensure CLI doesn't crash
        if out_dir.exists() and (out_dir / "index.json").exists():
            idx = json.loads((out_dir / "index.json").read_text())
            assert "summary" in idx


class TestBackwardCompatibility:
    def test_legacy_strict_flag(self):
        r_sub = _run(["audit", "--strict"])
        r_legacy = _run(["--strict"])
        assert r_sub.returncode == r_legacy.returncode

    def test_legacy_generate_manifest_flag(self):
        r_sub = _run(["manifest", "--generate"])
        r_legacy = _run(["--generate-manifest"])
        data_sub = json.loads(r_sub.stdout)
        data_legacy = json.loads(r_legacy.stdout)
        assert data_sub["manifest_schema_version"] == data_legacy["manifest_schema_version"]
        assert data_sub["resource_count"] == data_legacy["resource_count"]
