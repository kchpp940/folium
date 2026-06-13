"""
Tests for folium.release_audit._offline module.

Responsibility coverage:
  - download_resources: core download + cache + hash check function
  - download_from_file: manifest-file-based entry point
  - Output directory structure (manifest.json, index.json, cache/)
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from folium.release_audit import MANIFEST_SCHEMA_VERSION, download_resources
from folium.release_audit._offline import download_from_file

pytestmark = pytest.mark.audit


class TestDownloadResources:
    def test_empty_manifest_creates_structure(self, tmp_path):
        mini_manifest = {
            "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
            "source_of_truth": "default_js/default_css in Python source",
            "generated_at": "2026-01-01T00:00:00Z",
            "folium_version": "test",
            "resource_count": 0,
            "resources": [],
            "by_class": {},
        }
        report = download_resources(mini_manifest, tmp_path)

        assert report["summary"]["total_resources"] == 0
        assert (tmp_path / "index.json").exists()
        assert (tmp_path / "cache").is_dir()

        idx = json.loads((tmp_path / "index.json").read_text())
        assert "summary" in idx
        assert "resources" in idx
        assert "errors" in idx

    def test_downloaded_resource_has_metadata(self, tmp_path):
        test_url = "https://cdn.jsdelivr.net/npm/test-lib@1.0.0/test.js"
        from folium.release_audit._extract import resource_id
        test_rid = resource_id(test_url)

        mini_manifest = {
            "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
            "source_of_truth": "default_js/default_css in Python source",
            "generated_at": "2026-01-01T00:00:00Z",
            "folium_version": "test",
            "resource_count": 1,
            "resources": [
                {
                    "id": test_rid,
                    "name": "test_lib",
                    "resource_type": "js",
                    "url": test_url,
                    "source_class": "Test",
                    "module": "test",
                    "package": "test-lib",
                    "version": "1.0.0",
                    "cdn_host": "jsdelivr",
                    "inherited": False,
                    "inherited_from": None,
                }
            ],
            "by_class": {},
        }

        fake_content = b"console.log('test');"
        fake_response = MagicMock()
        fake_response.read.return_value = fake_content
        fake_response.__enter__ = lambda s: s
        fake_response.__exit__ = MagicMock(return_value=False)

        import folium.release_audit._offline as off_mod
        with patch.object(off_mod, "urlopen", return_value=fake_response) as mock_urlopen:
            report = download_resources(mini_manifest, tmp_path)

        assert mock_urlopen.called
        assert report["summary"]["downloaded"] == 1

        cache_files = list((tmp_path / "cache").iterdir())
        assert len(cache_files) >= 1
        for f in cache_files:
            assert test_rid in f.name
            if f.stat().st_size > 0:
                assert f.read_bytes() == fake_content

    def test_existing_file_is_cached(self, tmp_path):
        test_url = "https://cdn.jsdelivr.net/npm/test-lib@2.0.0/alreadyhere.js"
        from folium.release_audit._extract import resource_id
        test_rid = resource_id(test_url)

        mini_manifest = {
            "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
            "source_of_truth": "default_js/default_css in Python source",
            "generated_at": "2026-01-01T00:00:00Z",
            "folium_version": "test",
            "resource_count": 1,
            "resources": [
                {
                    "id": test_rid,
                    "name": "pre_existing",
                    "resource_type": "js",
                    "url": test_url,
                    "source_class": "Test",
                    "module": "test",
                    "package": "test-lib",
                    "version": "2.0.0",
                    "cdn_host": "jsdelivr",
                    "inherited": False,
                    "inherited_from": None,
                }
            ],
            "by_class": {},
        }

        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        filename = f"{test_rid}_npm_test-lib_at_2.0.0_alreadyhere.js"
        cached_file = cache_dir / filename
        cached_file.write_bytes(b"pre existing content")

        import folium.release_audit._offline as off_mod
        with patch.object(off_mod, "urlopen") as mock_urlopen:
            report = download_resources(mini_manifest, tmp_path)

        assert not mock_urlopen.called, "Should not re-download cached file"
        assert report["summary"]["cached"] == 1
        assert report["summary"]["downloaded"] == 0


class TestDownloadFromFile:
    def test_requires_valid_manifest(self, tmp_path):
        bad_manifest = tmp_path / "bad.json"
        bad_manifest.write_text("{\"not\": \"a real manifest\"}")

        with pytest.raises(ValueError, match="Manifest validation failed"):
            download_from_file(bad_manifest, tmp_path / "out")

    def test_file_must_exist(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            download_from_file(tmp_path / "does_not_exist.json", tmp_path / "out")
