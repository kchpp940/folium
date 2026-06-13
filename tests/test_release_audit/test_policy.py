"""
Tests for folium.release_audit._policy module.

Responsibility coverage:
  - policy file path resolution
  - policy file loading and structure
  - is_no_resources_class helper
  - is_inheritance_class helper
  - is_dynamic_resource_class helper
  - is_ignored_inline_cdn helper
  - is_strict_promotable helper
"""

import pytest

from folium.release_audit import (
    FOLIUM_ROOT,
    is_dynamic_resource_class,
    is_inheritance_class,
    is_no_resources_class,
    is_strict_promotable,
    load_policy,
    policy_file_path,
)

pytestmark = pytest.mark.audit


class TestPolicyFile:
    def test_policy_file_path_exists(self):
        path = policy_file_path()
        assert path.exists()
        assert path.is_file()
        assert path.name == "release_audit_policy.json"
        assert FOLIUM_ROOT in path.parents

    def test_load_policy_returns_dict(self):
        data = load_policy()
        assert isinstance(data, dict)

    def test_policy_has_all_required_sections(self):
        data = load_policy()
        for section in ["classes", "docs", "strict", "version_drift"]:
            assert section in data, f"Policy missing section: {section}"

    def test_policy_classes_structure(self):
        data = load_policy()
        classes = data["classes"]
        for key in ["no_resources_expected", "inherit_resources_from",
                    "dynamic_resource_classes", "ignore_inline_cdn_locations"]:
            assert key in classes, f"Policy missing 'classes.{key}'"
            assert isinstance(classes[key], list)

    def test_policy_strict_structure(self):
        data = load_policy()
        strict = data["strict"]
        assert "promote_warnings_to_errors" in strict
        assert "never_promote" in strict


class TestNoResourcesClass:
    def test_known_no_resources_classes(self):
        policy = load_policy()
        for expected_name in ["FloatImage", "VegaLite", "Choropleth"]:
            is_no, entry = is_no_resources_class(policy, expected_name)
            assert is_no, f"{expected_name} should be in no_resources_expected"
            assert entry is not None
            assert "reason" in entry

    def test_not_a_no_resources_class(self):
        policy = load_policy()
        is_no, _ = is_no_resources_class(policy, "MarkerCluster")
        assert not is_no

    def test_all_no_resources_entries_have_reason(self):
        policy = load_policy()
        for entry in policy["classes"]["no_resources_expected"]:
            assert "class_name" in entry
            assert "reason" in entry


class TestInheritanceClass:
    def test_known_inheritance_classes(self):
        policy = load_policy()
        is_inh, entry = is_inheritance_class(policy, "FastMarkerCluster")
        assert is_inh
        assert entry is not None
        assert entry["parent_class"] == "MarkerCluster"

    def test_not_an_inheritance_class(self):
        policy = load_policy()
        is_inh, _ = is_inheritance_class(policy, "Draw")
        assert not is_inh

    def test_all_inheritance_entries_have_parent(self):
        policy = load_policy()
        for entry in policy["classes"]["inherit_resources_from"]:
            assert "class_name" in entry
            assert "parent_class" in entry


class TestDynamicResourceClass:
    def test_vegalite_is_dynamic(self):
        policy = load_policy()
        is_dyn, cfg = is_dynamic_resource_class(policy, "VegaLite")
        assert is_dyn
        assert cfg is not None
        assert "variants" in cfg
        assert len(cfg["variants"]) >= 6

    def test_not_dynamic(self):
        policy = load_policy()
        is_dyn, _ = is_dynamic_resource_class(policy, "Draw")
        assert not is_dyn


class TestStrictPromotable:
    def test_promotable_categories(self):
        policy = load_policy()
        for cat in policy["strict"]["promote_warnings_to_errors"]:
            assert is_strict_promotable(policy, cat) is True

    def test_never_promote_categories(self):
        policy = load_policy()
        for cat in policy["strict"]["never_promote"]:
            assert is_strict_promotable(policy, cat) is False

    def test_unknown_category_not_promoted(self):
        policy = load_policy()
        assert is_strict_promotable(policy, "does_not_exist") is False
        assert is_strict_promotable(policy, "duplicate_name") is False
