"""
Test _resources module: Resource descriptor, validation, registry, and audit.
"""

import pytest

from folium.plugins._resources import (
    AuditIssue,
    Resource,
    audit_all_resources,
    build_default_css,
    build_default_js,
    build_defaults,
    clear_registry,
    collect_plugin_resources,
    get_registry,
    register_resources,
    validate_resource,
    validate_resource_list,
)


class TestResourceDescriptor:
    def test_frozen(self):
        r = Resource(name="a", url="http://x", type="js")
        with pytest.raises(AttributeError):
            r.name = "b"

    def test_required_fields(self):
        with pytest.raises(TypeError):
            Resource()

    def test_defaults_optional(self):
        r = Resource(name="a", url="http://x", type="js")
        assert r.plugin is None
        assert r.package is None
        assert r.version is None
        assert r.kind is None
        assert r.order is None


class TestValidateResource:
    def test_valid_minimal(self):
        validate_resource(Resource(name="a", url="http://x", type="js"))

    def test_valid_full(self):
        validate_resource(
            Resource(
                name="a", url="http://x", type="css",
                plugin="P", package="pkg", version="1.0",
                kind="plugin", order=0,
            )
        )

    def test_empty_name(self):
        with pytest.raises(ValueError, match="non-empty"):
            validate_resource(Resource(name="", url="http://x", type="js"))

    def test_empty_url(self):
        with pytest.raises(ValueError, match="non-empty"):
            validate_resource(Resource(name="a", url="", type="js"))

    def test_bad_type(self):
        with pytest.raises(ValueError, match="'type' must be one of"):
            validate_resource(Resource(name="a", url="http://x", type="img"))

    def test_bad_kind(self):
        with pytest.raises(ValueError, match="'kind' must be one of"):
            validate_resource(
                Resource(name="a", url="http://x", type="js", kind="unknown")
            )

    def test_plugin_hint_mismatch(self):
        with pytest.raises(ValueError, match="claims plugin"):
            validate_resource(
                Resource(name="a", url="http://x", type="js", plugin="X"),
                plugin_hint="Y",
            )

    def test_order_not_int(self):
        with pytest.raises(TypeError, match="'order' must be int"):
            validate_resource(
                Resource(name="a", url="http://x", type="js", order=1.5)
            )

    def test_name_not_str(self):
        with pytest.raises(TypeError, match="must be str"):
            validate_resource(Resource(name=123, url="http://x", type="js"))

    def test_legacy_not_bool(self):
        with pytest.raises(TypeError, match="'legacy' must be bool"):
            r = Resource(name="a", url="http://x", type="js")
            object.__setattr__(r, "legacy", "yes")  # bypass frozen
            validate_resource(r)

    def test_legacy_default_false(self):
        r = Resource(name="a", url="http://x", type="js")
        assert r.legacy is False

    def test_legacy_reason_required_when_legacy_true(self):
        with pytest.raises(ValueError, match="legacy_reason.*required"):
            r = Resource(name="a", url="http://x", type="js")
            object.__setattr__(r, "legacy", True)
            object.__setattr__(r, "legacy_reason", None)
            validate_resource(r)

    def test_legacy_reason_empty_rejected(self):
        with pytest.raises(ValueError, match="legacy_reason.*non-empty"):
            r = Resource(name="a", url="http://x", type="js")
            object.__setattr__(r, "legacy", True)
            object.__setattr__(r, "legacy_reason", "")
            validate_resource(r)

    def test_legacy_reason_not_str_rejected(self):
        with pytest.raises(TypeError, match="legacy_reason.*must be str"):
            r = Resource(name="a", url="http://x", type="js")
            object.__setattr__(r, "legacy", True)
            object.__setattr__(r, "legacy_reason", 42)
            validate_resource(r)

    def test_legacy_reason_nonlegacy_accepts_none(self):
        validate_resource(Resource(name="a", url="http://x", type="js", legacy_reason=None))

    def test_legacy_reason_valid_string(self):
        r = Resource(name="a", url="http://x", type="js")
        object.__setattr__(r, "legacy", True)
        object.__setattr__(r, "legacy_reason", "historical name from copy-paste")
        validate_resource(r)


class TestValidateResourceList:
    def test_duplicate_name(self):
        with pytest.raises(ValueError, match="Duplicate resource name"):
            validate_resource_list([
                Resource(name="dup", url="http://a", type="js"),
                Resource(name="dup", url="http://b", type="js"),
            ])

    def test_duplicate_url_same_type(self):
        with pytest.raises(ValueError, match="same type \\+ URL"):
            validate_resource_list([
                Resource(name="a", url="http://same", type="js"),
                Resource(name="b", url="http://same", type="js"),
            ])

    def test_same_url_different_type_ok(self):
        validate_resource_list([
            Resource(name="a", url="http://same", type="js"),
            Resource(name="b", url="http://same", type="css"),
        ])

    def test_mixed_order(self):
        with pytest.raises(ValueError, match="Mixing explicit 'order'"):
            validate_resource_list([
                Resource(name="a", url="http://a", type="js", order=0),
                Resource(name="b", url="http://b", type="js"),
            ])

    def test_all_explicit_order_ok(self):
        validate_resource_list([
            Resource(name="a", url="http://a", type="js", order=2),
            Resource(name="b", url="http://b", type="js", order=1),
        ])

    def test_non_resource_entry(self):
        with pytest.raises(TypeError, match="expected Resource instance"):
            validate_resource_list(["not a resource"])


class TestBuildDefaults:
    def test_js_and_css_split(self):
        resources = [
            Resource(name="a", url="http://a", type="js"),
            Resource(name="b", url="http://b", type="css"),
            Resource(name="c", url="http://c", type="js"),
        ]
        js, css = build_defaults(resources)
        assert js == [("a", "http://a"), ("c", "http://c")]
        assert css == [("b", "http://b")]

    def test_order_sorting(self):
        resources = [
            Resource(name="second", url="http://2", type="js", order=2),
            Resource(name="first", url="http://1", type="js", order=1),
        ]
        js, css = build_defaults(resources)
        assert js == [("first", "http://1"), ("second", "http://2")]

    def test_implicit_order_preserved(self):
        resources = [
            Resource(name="a", url="http://a", type="js"),
            Resource(name="b", url="http://b", type="js"),
        ]
        js, css = build_defaults(resources)
        assert js == [("a", "http://a"), ("b", "http://b")]


class TestRegistry:
    def setup_method(self):
        clear_registry()

    def test_register_and_get(self):
        res = [Resource(name="a", url="http://a", type="js")]
        register_resources("TestPlugin", res)
        reg = get_registry()
        assert "TestPlugin" in reg
        assert reg["TestPlugin"] == res

    def test_double_register_raises(self):
        res = [Resource(name="a", url="http://a", type="js")]
        register_resources("TestPlugin", res)
        with pytest.raises(ValueError, match="already registered"):
            register_resources("TestPlugin", res)

    def test_clear_registry(self):
        register_resources("X", [Resource(name="a", url="http://a", type="js")])
        clear_registry()
        assert get_registry() == {}

    def test_collect_plugin_resources(self):
        reg = collect_plugin_resources()
        assert "Fullscreen" in reg
        assert "MarkerCluster" in reg
        assert "HeatMapWithTime" in reg
        assert len(reg) > 10


class TestAuditAllResources:
    def test_e001_cross_plugin_name_collision_different_urls(self):
        registry = {
            "PluginA": [Resource(name="dup", url="http://a", type="js")],
            "PluginB": [Resource(name="dup", url="http://b", type="js")],
        }
        issues = audit_all_resources(registry)
        e001 = [i for i in issues if i.code == "E001"]
        assert len(e001) == 1
        assert e001[0].severity == "error"
        assert "dup" in e001[0].message

    def test_e001_not_triggered_when_same_url(self):
        registry = {
            "PluginA": [Resource(name="dup", url="http://same", type="js")],
            "PluginB": [Resource(name="dup", url="http://same", type="js")],
        }
        issues = audit_all_resources(registry)
        e001 = [i for i in issues if i.code == "E001"]
        assert e001 == []

    def test_e002_package_version_skew(self):
        registry = {
            "PluginA": [
                Resource(
                    name="a", url="http://a", type="js",
                    package="moment", version="2.18.1",
                )
            ],
            "PluginB": [
                Resource(
                    name="b", url="http://b", type="js",
                    package="moment", version="2.29.0",
                )
            ],
        }
        issues = audit_all_resources(registry)
        e002 = [i for i in issues if i.code == "E002"]
        assert len(e002) == 1
        assert e002[0].severity == "error"
        assert "moment" in e002[0].message

    def test_w001_same_url_different_names(self):
        registry = {
            "PluginA": [Resource(name="a", url="http://same", type="js")],
            "PluginB": [Resource(name="b", url="http://same", type="js")],
        }
        issues = audit_all_resources(registry)
        w001 = [i for i in issues if i.code == "W001"]
        assert len(w001) == 1
        assert w001[0].severity == "warning"

    def test_w002_name_across_types(self):
        registry = {
            "PluginA": [Resource(name="x", url="http://js", type="js")],
            "PluginB": [Resource(name="x", url="http://css", type="css")],
        }
        issues = audit_all_resources(registry)
        w002 = [i for i in issues if i.code == "W002"]
        assert len(w002) == 1
        assert w002[0].severity == "warning"

    def test_w003_shared_name_same_url(self):
        registry = {
            "PluginA": [Resource(name="moment", url="http://moment.js", type="js")],
            "PluginB": [Resource(name="moment", url="http://moment.js", type="js")],
        }
        issues = audit_all_resources(registry)
        w003 = [i for i in issues if i.code == "W003"]
        assert len(w003) == 1
        assert w003[0].severity == "warning"
        assert "moment" in w003[0].message

    def _make_legacy_resource(self, name, url, rtype, reason):
        r = Resource(name=name, url=url, type=rtype)
        object.__setattr__(r, "legacy", True)
        object.__setattr__(r, "legacy_reason", reason)
        return r

    def test_w004_legacy_with_single_owner_demotes_to_warning(self):
        """BoatMarker (legacy+reason) vs MarkerCluster (owner, non-legacy): 1 non-legacy → W004."""
        registry = {
            "MarkerCluster": [Resource(name="markerclusterjs", url="http://cluster.js", type="js")],
            "BoatMarker": [
                self._make_legacy_resource(
                    "markerclusterjs", "http://boat.js", "js",
                    "historical copy-paste, keep for add_js_link compat",
                )
            ],
        }
        issues = audit_all_resources(registry)
        e001 = [i for i in issues if i.code == "E001"]
        w004 = [i for i in issues if i.code == "W004"]
        assert e001 == [], "Exactly 1 non-legacy owner with a legacy partner → W004, not E001"
        assert len(w004) == 1
        assert w004[0].severity == "warning"
        assert w004[0].details["non_legacy_count"] == 1

    def test_e001_third_party_new_conflict_still_errors(self):
        """BoatMarker (legacy) + MarkerCluster (owner) + UnrelatedPlugin (new misuse): 2 non-legacy → E001."""
        registry = {
            "MarkerCluster": [Resource(name="markerclusterjs", url="http://cluster.js", type="js")],
            "BoatMarker": [
                self._make_legacy_resource(
                    "markerclusterjs", "http://boat.js", "js",
                    "historical copy-paste, keep for add_js_link compat",
                )
            ],
            "UnrelatedPlugin": [Resource(name="markerclusterjs", url="http://other.js", type="js")],
        }
        issues = audit_all_resources(registry)
        e001 = [i for i in issues if i.code == "E001"]
        w004 = [i for i in issues if i.code == "W004"]
        assert w004 == [], "2 non-legacy participants → legacy allowlist must NOT cover"
        assert len(e001) == 1
        assert e001[0].severity == "error"
        assert e001[0].details["non_legacy_count"] == 2
        assert "UnrelatedPlugin" in e001[0].details["plugins"]

    def test_e001_persists_without_any_legacy(self):
        """No legacy flags at all, two plugins with different URLs → E001."""
        registry = {
            "PluginA": [Resource(name="same", url="http://one", type="js")],
            "PluginB": [Resource(name="same", url="http://two", type="js")],
        }
        issues = audit_all_resources(registry)
        e001 = [i for i in issues if i.code == "E001"]
        w004 = [i for i in issues if i.code == "W004"]
        assert len(e001) == 1
        assert e001[0].severity == "error"
        assert e001[0].details["non_legacy_count"] == 2
        assert w004 == []

    def test_e001_when_legacy_missing_reason(self):
        """If a legacy entry lacks a reason, the allowlist is invalid → E001."""
        r_legacy_no_reason = Resource(name="same", url="http://two", type="js")
        object.__setattr__(r_legacy_no_reason, "legacy", True)
        object.__setattr__(r_legacy_no_reason, "legacy_reason", None)
        registry = {
            "PluginA": [Resource(name="same", url="http://one", type="js")],
            "PluginB": [r_legacy_no_reason],
        }
        issues = audit_all_resources(registry)
        e001 = [i for i in issues if i.code == "E001"]
        w004 = [i for i in issues if i.code == "W004"]
        assert e001, (
            "A legacy entry without a reason should fail the all_reasoned "
            "check and stay as E001."
        )
        assert w004 == []

    def test_no_issues(self):
        registry = {
            "PluginA": [Resource(name="a", url="http://a", type="js")],
            "PluginB": [Resource(name="b", url="http://b", type="css")],
        }
        issues = audit_all_resources(registry)
        assert issues == []

    def test_same_name_different_type_not_e001(self):
        registry = {
            "PluginA": [Resource(name="x", url="http://js", type="js")],
            "PluginB": [Resource(name="x", url="http://css", type="css")],
        }
        issues = audit_all_resources(registry)
        e001 = [i for i in issues if i.code == "E001"]
        assert e001 == []

    def test_real_audit_no_errors(self):
        clear_registry()
        collect_plugin_resources()
        issues = audit_all_resources()
        errors = [i for i in issues if i.severity == "error"]
        assert errors == [], (
            f"Cross-plugin audit found errors: "
            f"{[i.message for i in errors]}"
        )


class TestAuditIssueDataclass:
    def test_frozen(self):
        issue = AuditIssue(severity="error", code="E001", message="test")
        with pytest.raises(AttributeError):
            issue.severity = "warning"

    def test_details_default(self):
        issue = AuditIssue(severity="warning", code="W001", message="test")
        assert issue.details == {}
