"""
Tests for the Resource Manifest workflow.

Covers:
  - ResourceManifest save/load/roundtrip
  - collect_resources with various plugin configurations
  - download_manifest (idempotent caching, sha256 recording)
  - resolve_from_manifest (sha256 mismatch detection)
  - CLI module (argparse structure, _load_map_from_file)
"""

import os
import re
import tempfile
import warnings
from pathlib import Path

import pytest

import folium
from folium.plugins import Fullscreen, HeatMap


def count_cdn_links(html: str) -> int:
    exclude = ["leafletjs.com", "openstreetmap.org", "creativecommons.org", "osm.org"]
    urls = re.findall(r'(?:src|href)="(https?://[^"]+)"', html)
    return sum(1 for u in urls if not any(d in u for d in exclude))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_global_state():
    yield
    folium.set_resource_mode("cdn")
    folium.clear_resource_overrides()


# ---------------------------------------------------------------------------
# ResourceManifest basic operations
# ---------------------------------------------------------------------------


class TestResourceManifestBasic:
    def test_manifest_save_load_roundtrip(self):
        m = folium.Map()
        manifest = folium.collect_resources(m)
        leaflet_entry = manifest.get("leaflet")
        assert leaflet_entry is not None

        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = os.path.join(tmpdir, "manifest.json")
            manifest.save(manifest_path)
            assert os.path.exists(manifest_path)

            loaded = folium.ResourceManifest.load(manifest_path)
            assert loaded.version == manifest.version
            assert len(loaded) == len(manifest)
            assert loaded.get("leaflet").url == leaflet_entry.url

    def test_manifest_iter_and_len(self):
        m = folium.Map()
        manifest = folium.collect_resources(m)
        assert len(manifest) >= 1
        names = [r.name for r in manifest]
        assert "leaflet" in names


# ---------------------------------------------------------------------------
# collect_resources
# ---------------------------------------------------------------------------


class TestCollectResources:
    def test_collect_resources_basic(self):
        m = folium.Map()
        Fullscreen().add_to(m)
        HeatMap([[45.5, -122.7, 1.0]]).add_to(m)

        manifest = folium.collect_resources(m)
        assert len(manifest) > 0, "Must collect at least Leaflet"
        assert manifest.get("leaflet") is not None
        assert manifest.get("Control.Fullscreen.js") is not None
        assert manifest.get("leaflet-heat.js") is not None
        names = [r.name for r in manifest]
        assert len(names) == len(set(names)), "Resources must be de-duplicated"

    def test_collect_resources_dedup(self):
        """Multiple HeatMaps should not cause duplicate resource entries."""
        m = folium.Map()
        HeatMap([[45.5, -122.7, 1.0]]).add_to(m)
        HeatMap([[45.6, -122.8, 0.5]]).add_to(m)
        manifest = folium.collect_resources(m)
        matches = [r for r in manifest if r.name == "leaflet-heat.js"]
        assert len(matches) == 1, "Duplicate names must be de-duplicated"


# ---------------------------------------------------------------------------
# download_manifest
# ---------------------------------------------------------------------------


class TestDownloadManifest:
    @pytest.mark.network
    def test_download_all_resources(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            m = folium.Map(location=[45.5, -122.7])
            Fullscreen().add_to(m)
            manifest = folium.collect_resources(m)
            results = folium.download_manifest(
                manifest, tmpdir, retries=6, timeout=60
            )
            assert len(results) == len(manifest)
            for name, path in results:
                assert os.path.exists(path), f"{name} file missing: {path}"
                assert os.path.getsize(path) > 0, f"{name} empty"
            # sha256 populated after download
            assert all(r.sha256 for r in manifest)

    @pytest.mark.network
    def test_download_idempotent_cached(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            m = folium.Map()
            manifest = folium.collect_resources(m)
            first = folium.download_manifest(
                manifest, tmpdir, retries=6, timeout=60
            )
            mtimes = {name: os.path.getmtime(p) for name, p in first}
            import time
            time.sleep(0.01)
            second = folium.download_manifest(
                manifest, tmpdir, overwrite=False, retries=6, timeout=60
            )
            reused = sum(
                1 for name, p in second if os.path.getmtime(p) == mtimes[name]
            )
            assert reused > 0, "At least some files should be reused from cache"

    @pytest.mark.network
    def test_full_pipeline_manifest_strict(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            m = folium.Map(location=[45.5, -122.7])
            Fullscreen().add_to(m)
            HeatMap([[45.5, -122.7, 1.0]]).add_to(m)

            manifest = folium.collect_resources(m)
            manifest_path = os.path.join(tmpdir, "manifest.json")
            manifest.save(manifest_path)

            folium.download_manifest(manifest, tmpdir, retries=6, timeout=60)
            manifest.save(manifest_path)

            m2 = folium.Map(
                location=[45.5, -122.7],
                resource_mode="manifest",
                manifest_path=manifest_path,
            )
            Fullscreen().add_to(m2)
            HeatMap([[45.5, -122.7, 1.0]]).add_to(m2)

            html = m2.get_root().render()
            cdn_count = count_cdn_links(html)
            assert cdn_count == 0, "Manifest mode must not produce CDN links"
            assert "cdn.jsdelivr.net" not in html
            assert "<script>" in html
            assert "<style>" in html


# ---------------------------------------------------------------------------
# resolve_from_manifest / sha256 protection
# ---------------------------------------------------------------------------


class TestResolveFromManifest:
    @pytest.mark.network
    def test_sha256_mismatch_warns_and_returns_none(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            m = folium.Map()
            manifest = folium.collect_resources(m)
            folium.download_manifest(manifest, tmpdir, retries=6, timeout=60)
            leaflet_path = os.path.join(tmpdir, manifest.get("leaflet").filename)
            with open(leaflet_path, "w") as f:
                f.write("// TAMPERED")

            from folium.resource_manifest import resolve_from_manifest
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                result = resolve_from_manifest("leaflet", manifest, tmpdir)
                warn_msgs = [str(x.message) for x in w]
                assert result is None
                assert any("sha256 mismatch" in m for m in warn_msgs)


# ---------------------------------------------------------------------------
# Manifest mode rendering (strict)
# ---------------------------------------------------------------------------


class TestManifestModeRendering:
    @pytest.mark.network
    def test_manifest_mode_missing_file_raises(self):
        """Manifest mode must never fall back to CDN."""
        with tempfile.TemporaryDirectory() as tmpdir:
            m = folium.Map()
            manifest = folium.collect_resources(m)
            manifest_path = os.path.join(tmpdir, "manifest.json")
            manifest.save(manifest_path)

            m2 = folium.Map(resource_mode="manifest", manifest_path=manifest_path)
            with pytest.raises(RuntimeError, match="manifest mode"):
                m2.get_root().render()

    @pytest.mark.network
    def test_manifest_mode_unlisted_resource_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            m_plain = folium.Map()
            manifest = folium.collect_resources(m_plain)
            folium.download_manifest(manifest, tmpdir, retries=6, timeout=60)
            mp = os.path.join(tmpdir, "manifest.json")
            manifest.save(mp)

            m_with_plugin = folium.Map(resource_mode="manifest", manifest_path=mp)
            Fullscreen().add_to(m_with_plugin)

            with pytest.raises(RuntimeError, match="not listed in the manifest"):
                m_with_plugin.get_root().render()

    @pytest.mark.network
    def test_global_manifest_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            m_build = folium.Map()
            Fullscreen().add_to(m_build)
            manifest = folium.collect_resources(m_build)
            folium.download_manifest(manifest, tmpdir, retries=6, timeout=60)
            mp = os.path.join(tmpdir, "manifest.json")
            manifest.save(mp)

            folium.set_resource_mode("manifest", manifest_path=mp)
            try:
                m = folium.Map()
                Fullscreen().add_to(m)
                html = m.get_root().render()
                assert count_cdn_links(html) == 0
            finally:
                folium.set_resource_mode("cdn")


# ---------------------------------------------------------------------------
# CLI module
# ---------------------------------------------------------------------------


class TestCLI:
    def test_build_parser_no_errors(self):
        from folium.cli import build_parser
        parser = build_parser()
        assert parser is not None
        # Help strings must not crash
        with pytest.raises(SystemExit):
            parser.parse_args(["--help"])

    def test_build_parser_subcommands_exist(self):
        from folium.cli import build_parser
        parser = build_parser()
        # No SystemExit for valid subcommand
        args = parser.parse_args(["collect", "dummy.py"])
        assert args.command == "collect"
        assert args.func is not None

    def test_load_map_from_file_variable_m(self, tmp_path: Path):
        p = tmp_path / "my_map.py"
        p.write_text("import folium\nm = folium.Map(location=[45.5, -122.7])\n")
        from folium.cli import _load_map_from_file
        result = _load_map_from_file(str(p))
        assert type(result).__name__ == "Map"
        assert result.location == [45.5, -122.7]

    def test_load_map_from_file_build_map(self, tmp_path: Path):
        p = tmp_path / "my_map.py"
        p.write_text(
            "import folium\ndef build_map():\n    return folium.Map(location=[1, 2])\n"
        )
        from folium.cli import _load_map_from_file
        result = _load_map_from_file(str(p))
        assert type(result).__name__ == "Map"
        assert result.location == [1, 2]

    def test_load_map_from_file_missing(self, tmp_path: Path):
        p = tmp_path / "no_map.py"
        p.write_text("x = 1\n")
        from folium.cli import _load_map_from_file
        with pytest.raises(ValueError, match="Could not find a folium.Map"):
            _load_map_from_file(str(p))


# ---------------------------------------------------------------------------
# ResourceConfig validation
# ---------------------------------------------------------------------------


class TestResourceConfigValidation:
    def test_manifest_mode_requires_manifest_or_path(self):
        with pytest.raises(ValueError, match="manifest"):
            folium.ResourceConfig(mode="manifest")

    def test_manifest_mode_accepts_manifest_path(self):
        cfg = folium.ResourceConfig(mode="manifest", manifest_path="/tmp/x.json")
        assert cfg.mode == "manifest"

    def test_local_mode_requires_path(self):
        with pytest.raises(ValueError, match="local_path"):
            folium.ResourceConfig(mode="local")

    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError, match="Invalid resource_mode"):
            folium.ResourceConfig(mode="bogus")
