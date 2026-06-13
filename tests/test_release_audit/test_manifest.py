"""
Tests for folium.release_audit._manifest module.

Responsibility coverage:
  - MANIFEST_SCHEMA_VERSION constant
  - MANIFEST_JSON_SCHEMA (JSON Schema)
  - build_stable_manifest: from ClassResources to dict
  - generate_manifest: to JSON string
  - validate_manifest: structural + schema-version checks
  - manifest_json_schema: export function
"""

import json

import pytest

from folium.release_audit import (
    MANIFEST_SCHEMA_VERSION,
    build_stable_manifest,
    collect_all_resources,
    generate_manifest,
    manifest_json_schema,
    validate_manifest,
)

pytestmark = pytest.mark.audit


class TestSchemaVersion:
    def test_schema_version_format(self):
        parts = MANIFEST_SCHEMA_VERSION.split(".")
        assert len(parts) == 3
        assert all(p.isdigit() for p in parts)

    def test_schema_version_in_json_schema(self):
        schema = manifest_json_schema()
        assert schema.get("version") == MANIFEST_SCHEMA_VERSION


class TestManifestJsonSchema:
    def test_schema_has_required_structure(self):
        schema = manifest_json_schema()
        assert "$schema" in schema
        assert "$defs" in schema
        assert "ResourceEntry" in schema["$defs"]
        assert "ClassResources" in schema["$defs"]

    def test_resource_entry_required_fields(self):
        schema = manifest_json_schema()
        re_props = schema["$defs"]["ResourceEntry"]["properties"]
        for key in ["id", "name", "resource_type", "url"]:
            assert key in re_props, f"ResourceEntry missing property: {key}"

    def test_resource_type_enum(self):
        schema = manifest_json_schema()
        res_type = schema["$defs"]["ResourceEntry"]["properties"]["resource_type"]
        assert res_type["enum"] == ["js", "css"]


class TestBuildStableManifest:
    def test_manifest_has_all_required_top_level_fields(self):
        all_res = collect_all_resources()
        manifest = build_stable_manifest(all_res)

        for field in ["manifest_schema_version", "source_of_truth", "generated_at",
                      "folium_version", "resource_count", "resources", "by_class"]:
            assert field in manifest, f"Missing top-level field: {field}"

    def test_manifest_source_of_truth_constant(self):
        all_res = collect_all_resources()
        manifest = build_stable_manifest(all_res)
        assert manifest["source_of_truth"] == "default_js/default_css in Python source"

    def test_manifest_schema_version_matches_constant(self):
        all_res = collect_all_resources()
        manifest = build_stable_manifest(all_res)
        assert manifest["manifest_schema_version"] == MANIFEST_SCHEMA_VERSION

    def test_resource_count_matches_array(self):
        all_res = collect_all_resources()
        manifest = build_stable_manifest(all_res)
        assert manifest["resource_count"] == len(manifest["resources"])

    def test_every_resource_entry_has_required_fields(self):
        all_res = collect_all_resources()
        manifest = build_stable_manifest(all_res)
        required = ["id", "name", "resource_type", "url", "source_class", "module"]

        for idx, res in enumerate(manifest["resources"]):
            for field in required:
                assert field in res, f"resources[{idx}] missing field: {field}"
            assert res["resource_type"] in ("js", "css")
            assert res["url"].startswith(("http://", "https://"))
            assert len(res["id"]) == 12

    def test_by_class_structure(self):
        all_res = collect_all_resources()
        manifest = build_stable_manifest(all_res)

        for class_name, class_data in manifest["by_class"].items():
            assert "module" in class_data
            assert isinstance(class_data["js"], list)
            assert isinstance(class_data["css"], list)

    def test_by_class_references_are_valid_ids(self):
        all_res = collect_all_resources()
        manifest = build_stable_manifest(all_res)
        valid_ids = {r["id"] for r in manifest["resources"]}

        for class_name, class_data in manifest["by_class"].items():
            for rid in class_data["js"] + class_data["css"]:
                assert rid in valid_ids, (
                    f"Class {class_name} references unknown resource id {rid}"
                )

    def test_fastmarkercluster_inheritance_tracked(self):
        all_res = collect_all_resources()
        manifest = build_stable_manifest(all_res)
        fastmc = manifest["by_class"].get("FastMarkerCluster")
        assert fastmc is not None
        assert "inherited_resources" in fastmc
        if fastmc["js"]:
            for rid in fastmc["js"]:
                if rid in fastmc["inherited_resources"]:
                    res = next(r for r in manifest["resources"] if r["id"] == rid)
                    assert res["inherited"] is True
                    assert res["inherited_from"] == "MarkerCluster"
                    break


class TestGenerateManifest:
    def test_output_is_valid_json(self):
        all_res = collect_all_resources()
        json_str = generate_manifest(all_res, pretty=False)
        data = json.loads(json_str)
        assert data["manifest_schema_version"] == MANIFEST_SCHEMA_VERSION

    def test_pretty_format_has_newlines(self):
        all_res = collect_all_resources()
        pretty = generate_manifest(all_res, pretty=True)
        assert "\n" in pretty
        assert "  " in pretty


class TestValidateManifest:
    def test_valid_manifest_passes(self):
        all_res = collect_all_resources()
        manifest = build_stable_manifest(all_res)
        errors = validate_manifest(manifest)
        assert errors == []

    def test_missing_top_level_field_detected(self):
        all_res = collect_all_resources()
        manifest = build_stable_manifest(all_res)
        del manifest["resources"]
        errors = validate_manifest(manifest)
        assert len(errors) > 0
        assert any("resources" in e for e in errors)

    def test_major_version_mismatch_detected(self):
        all_res = collect_all_resources()
        manifest = build_stable_manifest(all_res)
        manifest["manifest_schema_version"] = "999.0.0"
        errors = validate_manifest(manifest)
        assert len(errors) > 0
        assert any("version" in e.lower() for e in errors)

    def test_bad_source_of_truth_detected(self):
        all_res = collect_all_resources()
        manifest = build_stable_manifest(all_res)
        manifest["source_of_truth"] = "some random manifest file"
        errors = validate_manifest(manifest)
        assert len(errors) > 0

    def test_resource_count_mismatch_detected(self):
        all_res = collect_all_resources()
        manifest = build_stable_manifest(all_res)
        manifest["resource_count"] = manifest["resource_count"] + 999
        errors = validate_manifest(manifest)
        assert len(errors) > 0

    def test_bad_resource_type_detected(self):
        all_res = collect_all_resources()
        manifest = build_stable_manifest(all_res)
        manifest["resources"][0]["resource_type"] = "exe"
        errors = validate_manifest(manifest)
        assert len(errors) > 0

    def test_resources_not_array_detected(self):
        all_res = collect_all_resources()
        manifest = build_stable_manifest(all_res)
        manifest["resources"] = "not_an_array"
        errors = validate_manifest(manifest)
        assert len(errors) > 0
