"""
Common resource descriptor infrastructure for Folium plugins.

This module provides a unified way to declare external JavaScript and CSS
resources for plugins, replacing the ad-hoc default_js / default_css tuple
lists with a structured Resource descriptor that captures package name,
version, dependency kind, and explicit ordering.

Benefits:
- Single, ordered list of all resources (JS + CSS interleaved as needed)
- Structured metadata: plugin, package, version, kind instead of URL guessing
- Centralised validation: type check, duplicate names, consistency
- Cross-plugin audit: global name conflicts, package version skew, URL drift
- Easier version upgrades, offline packaging and resource coverage
- Backward compatibility with JSCSSMixin through build_defaults()

"""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass, field
from typing import Any, Literal, Optional

from folium.elements import JSCSSMixin


VALID_TYPES: frozenset[str] = frozenset({"js", "css"})
VALID_KINDS: frozenset[str] = frozenset({"plugin", "dependency"})
REQUIRED_FIELDS: tuple[str, ...] = ("name", "url", "type")


@dataclass(frozen=True)
class Resource:
    """
    Structured descriptor for an external JavaScript or CSS resource.

    All fields except the core (name, url, type) are optional but strongly
    encouraged; they make it possible to enumerate dependencies, upgrade
    versions in one place, and build offline bundles without URL scraping.

    Parameters
    ----------
    name : str
        Unique identifier for the resource, used as the child name when
        added to a Figure's header.  Must be unique *within* a plugin.
    url : str
        URL of the resource (CDN address, local path, or data URI).
    type : Literal["js", "css"]
        Resource type: "js" for JavaScript, "css" for stylesheet.
    plugin : str, optional
        Name of the Folium plugin that owns this resource (e.g. "Fullscreen",
        "HeatMap").  Used for diagnostics and offline-bundle grouping.
    package : str, optional
        Upstream npm / package name that ships the resource
        (e.g. "leaflet.fullscreen", "@geoman-io/leaflet-geoman-free").
        Helps look up release notes / security advisories.
    version : str, optional
        Upstream package version string (e.g. "3.0.0", "1.1.0").
        When coupled with `package`, this is the single source of truth for
        version upgrades – no regex-ing URLs any more.
    kind : Literal["plugin", "dependency"], optional
        Whether this resource is the *main* plugin asset ("plugin") or a
        third-party dependency pulled in by it ("dependency").
        Example: `leaflet.timedimension` is the plugin, while `moment` and
        `iso8601-js-period` are dependencies.
    order : int, optional
        Explicit load priority / sort key.  Lower numbers load first.
        When omitted the list position (insertion order) is used instead.
        Useful when two interdependent plugins must load relative to each
        other even though they live in different files.
    """

    name: str
    url: str
    type: Literal["js", "css"]
    plugin: Optional[str] = None
    package: Optional[str] = None
    version: Optional[str] = None
    kind: Optional[Literal["plugin", "dependency"]] = None
    order: Optional[int] = None


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def validate_resource(r: Resource, *, plugin_hint: Optional[str] = None) -> None:
    """
    Validate a single Resource descriptor.

    Raises
    ------
    TypeError
        If a field has the wrong Python type.
    ValueError
        If a field value is semantically invalid (e.g. empty name, unknown
        `type` / `kind` string, plugin mismatch).
    """
    # -- required field types ------------------------------------------------
    for fld in REQUIRED_FIELDS:
        val = getattr(r, fld)
        if not isinstance(val, str):
            raise TypeError(
                f"Resource field '{fld}' must be str, got {type(val).__name__} "
                f"({val!r})."
            )
        if not val:
            raise ValueError(f"Resource field '{fld}' must be non-empty.")

    # -- enum-style values ---------------------------------------------------
    if r.type not in VALID_TYPES:
        raise ValueError(
            f"Resource '{r.name}': 'type' must be one of {sorted(VALID_TYPES)}, "
            f"got {r.type!r}."
        )
    if r.kind is not None and r.kind not in VALID_KINDS:
        raise ValueError(
            f"Resource '{r.name}': 'kind' must be one of {sorted(VALID_KINDS)} "
            f"or None, got {r.kind!r}."
        )

    # -- plugin consistency check (useful when `plugin_hint` is provided) ---
    if plugin_hint is not None and r.plugin is not None and r.plugin != plugin_hint:
        raise ValueError(
            f"Resource '{r.name}' claims plugin={r.plugin!r} but is declared "
            f"inside the {plugin_hint!r} plugin module."
        )

    # -- order, if provided, must be int ------------------------------------
    if r.order is not None and not isinstance(r.order, int):
        raise TypeError(
            f"Resource '{r.name}': 'order' must be int or None, got "
            f"{type(r.order).__name__}."
        )


def validate_resource_list(
    resources: list[Resource],
    *,
    plugin_hint: Optional[str] = None,
) -> None:
    """
    Validate a full list of Resource descriptors for a plugin.

    Checks performed on top of :func:`validate_resource`:
    - No duplicate `name` values (header children would overwrite each other)
    - No duplicate URLs for the same type (easy copy/paste mistakes)
    - If explicit `order` values are used they are pairwise comparable
      (no mix of None and int across entries that share the same list slot)

    Raises
    ------
    ValueError
        On any duplicate / ordering problem, with a message that points at
        the offending entries.
    """
    seen_names: dict[str, int] = {}
    seen_url_by_type: dict[tuple[str, str], int] = {}
    order_values: list[int | None] = []

    for i, r in enumerate(resources):
        if not isinstance(r, Resource):
            raise TypeError(
                f"resources[{i}]: expected Resource instance, got "
                f"{type(r).__name__} ({r!r})."
            )
        validate_resource(r, plugin_hint=plugin_hint)

        # unique name check
        if r.name in seen_names:
            prev = seen_names[r.name]
            raise ValueError(
                f"Duplicate resource name {r.name!r}: declared at index "
                f"{prev} and {i}.  Names must be unique within a plugin so "
                f"they can be individually overridden via add_js_link / "
                f"add_css_link."
            )
        seen_names[r.name] = i

        # same-type same-URL check (likely copy-paste error)
        key = (r.type, r.url)
        if key in seen_url_by_type:
            prev = seen_url_by_type[key]
            raise ValueError(
                f"Resource '{r.name}' at index {i} has the same type + URL "
                f"as resource at index {prev}: ({r.type}, {r.url}).  If this "
                f"is intentional give them different names; otherwise remove "
                f"the duplicate."
            )
        seen_url_by_type[key] = i

        order_values.append(r.order)

    # If *any* resource specifies an explicit order, *all* of them must.
    explicit_orders = [o for o in order_values if o is not None]
    if explicit_orders and len(explicit_orders) != len(order_values):
        raise ValueError(
            f"Mixing explicit 'order' values (indices "
            f"{[i for i, o in enumerate(order_values) if o is not None]}) "
            f"with implicit list-position ordering. Either set 'order' on "
            f"every Resource in the list, or leave it out entirely."
        )


# ---------------------------------------------------------------------------
# Conversion to JSCSSMixin tuple lists (backward compatibility)
# ---------------------------------------------------------------------------

def _sort_key(r: Resource, fallback_index: int) -> tuple[int, int]:
    """Return a sort key for a resource.

    Priority:
    1. explicit `order` field (if provided)
    2. original list position
    """
    primary = r.order if r.order is not None else fallback_index
    return (primary, fallback_index)


def build_default_js(
    resources: list[Resource],
    *,
    validate: bool = True,
    plugin_hint: Optional[str] = None,
) -> list[tuple[str, str]]:
    """
    Extract JavaScript resources as (name, url) tuples, preserving order.

    Parameters
    ----------
    resources : list[Resource]
        Ordered list of resource descriptors.
    validate : bool, default True
        Whether to run :func:`validate_resource_list` before extraction.
    plugin_hint : str, optional
        Passed through to the validator; mismatched `plugin` fields raise.

    Returns
    -------
    list[tuple[str, str]]
        List of (name, url) tuples for JavaScript resources, sorted by the
        (order, list-position) key.
    """
    if validate:
        validate_resource_list(resources, plugin_hint=plugin_hint)
    indexed = sorted(
        enumerate(resources), key=lambda pair: _sort_key(pair[1], pair[0])
    )
    return [(r.name, r.url) for _, r in indexed if r.type == "js"]


def build_default_css(
    resources: list[Resource],
    *,
    validate: bool = True,
    plugin_hint: Optional[str] = None,
) -> list[tuple[str, str]]:
    """
    Extract CSS resources as (name, url) tuples, preserving order.

    See :func:`build_default_js` for parameter docs.
    """
    if validate:
        validate_resource_list(resources, plugin_hint=plugin_hint)
    indexed = sorted(
        enumerate(resources), key=lambda pair: _sort_key(pair[1], pair[0])
    )
    return [(r.name, r.url) for _, r in indexed if r.type == "css"]


def build_defaults(
    resources: list[Resource],
    *,
    validate: bool = True,
    plugin_hint: Optional[str] = None,
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """
    Convert a list of Resource descriptors to JSCSSMixin-compatible tuple lists.

    This is a convenience wrapper around :func:`build_default_js` and
    :func:`build_default_css`.  Validation is run **once** here so the
    per-type helpers don't duplicate the work when `validate=True`.

    Parameters
    ----------
    resources : list[Resource]
        Ordered list of resource descriptors.
    validate : bool, default True
        Whether to run validation before extraction.
    plugin_hint : str, optional
        Expected plugin name; passed through to the validator.

    Returns
    -------
    tuple[list[tuple[str, str]], list[tuple[str, str]]]
        A ``(default_js, default_css)`` pair, each a list of ``(name, url)``
        tuples compatible with :class:`folium.elements.JSCSSMixin`.
    """
    if validate:
        validate_resource_list(resources, plugin_hint=plugin_hint)
    return (
        build_default_js(resources, validate=False),
        build_default_css(resources, validate=False),
    )


# ---------------------------------------------------------------------------
# Cross-plugin registry & audit
# ---------------------------------------------------------------------------

_registry: dict[str, list[Resource]] = {}


def register_resources(plugin_name: str, resources: list[Resource]) -> None:
    """Register a plugin's resource list in the global audit registry.

    This is called automatically when a plugin module is imported via
    :func:`collect_plugin_resources`.  It can also be called manually.

    Parameters
    ----------
    plugin_name : str
        Human-readable name of the plugin (e.g. ``"Fullscreen"``).
    resources : list[Resource]
        The plugin's declared resource list.

    Raises
    ------
    ValueError
        If the same ``plugin_name`` is registered twice.
    """
    if plugin_name in _registry:
        raise ValueError(
            f"Plugin {plugin_name!r} is already registered in the resource "
            f"registry.  Double-registration is usually a bug."
        )
    _registry[plugin_name] = list(resources)


def get_registry() -> dict[str, list[Resource]]:
    """Return a shallow copy of the global plugin resource registry."""
    return dict(_registry)


def clear_registry() -> None:
    """Clear the global registry (useful for test isolation)."""
    _registry.clear()


def collect_plugin_resources() -> dict[str, list[Resource]]:
    """Import every plugin submodule and collect ``resources`` from each.

    Scans ``folium.plugins`` for submodules, imports them, then inspects
    every class that inherits from :class:`~folium.elements.JSCSSMixin`
    for a ``resources`` class attribute.  Each discovered list is registered
    via :func:`register_resources`.

    Returns
    -------
    dict[str, list[Resource]]
        Mapping from plugin class name to its resource list.

    Notes
    -----
    Calling this function multiple times is safe only after
    :func:`clear_registry`; otherwise already-registered plugins will
    raise ``ValueError``.
    """
    import folium.plugins as pkg

    for importer, modname, ispkg in pkgutil.iter_modules(pkg.__path__):
        if modname.startswith("_"):
            continue
        importlib.import_module(f"folium.plugins.{modname}")

    for attr_name in sorted(dir(pkg)):
        if attr_name.startswith("_"):
            continue
        obj = getattr(pkg, attr_name)
        if not isinstance(obj, type):
            continue
        if not issubclass(obj, JSCSSMixin):
            continue
        res = getattr(obj, "resources", None)
        if res is None:
            continue
        if not all(isinstance(r, Resource) for r in res):
            continue
        register_resources(obj.__name__, res)

    return get_registry()


@dataclass(frozen=True)
class AuditIssue:
    """A single problem found during cross-plugin resource auditing."""

    severity: Literal["error", "warning"]
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


def audit_all_resources(
    registry: Optional[dict[str, list[Resource]]] = None,
) -> list[AuditIssue]:
    """Run cross-plugin validation on the global resource registry.

    Checks performed:

    1. **E001 — cross-plugin name collision with different URLs**: the same
       ``name + type`` pair is used by different plugins but with different
       URLs.  The second plugin to render will silently overwrite the first
       with a *different* script/stylesheet — a genuine bug.
    2. **E002 — same package, different versions**: a package name
       appears with two different ``version`` strings.  This is almost
       always a bug (e.g. one plugin pins ``moment@2.18.1`` while
       another pins ``moment@2.29.0``).
    3. **W001 — same URL, different names**: the same ``type + URL``
       pair is declared under two different ``name`` values.  This is
       legal but suspicious — it usually means two plugins embed the
       same library independently, and the duplicate will be loaded
       twice if both plugins are active.
    4. **W002 — name collision across types**: a ``name`` appears as
       both ``js`` and ``css`` in different plugins.  Not necessarily
       broken, but can confuse ``add_js_link`` / ``add_css_link``
       overrides.
    5. **W003 — shared resource name (same URL)**: the same ``name +
       type`` pair is used by multiple plugins *with the same URL*.
       This is safe — JSCSSMixin deduplicates by name — but the
       shared name should be documented so maintainers know why.

    Parameters
    ----------
    registry : dict[str, list[Resource]], optional
        Mapping from plugin name to resource list.  Defaults to the
        result of :func:`get_registry`.

    Returns
    -------
    list[AuditIssue]
        Issues sorted by ``(severity, code)``.  Callers can filter by
        ``severity="error"`` for hard failures.
    """
    if registry is None:
        registry = get_registry()

    issues: list[AuditIssue] = []

    name_type_to_plugins: dict[tuple[str, str], list[str]] = {}
    name_type_to_urls: dict[tuple[str, str], set[str]] = {}
    name_type_to_entries: dict[tuple[str, str], list[tuple[str, Resource]]] = {}
    name_to_types: dict[str, set[str]] = {}
    url_type_to_entries: dict[tuple[str, str], list[tuple[str, Resource]]] = {}
    package_to_versions: dict[str, set[str]] = {}

    for plugin_name, resources in registry.items():
        for r in resources:
            key_nt = (r.name, r.type)
            name_type_to_plugins.setdefault(key_nt, []).append(plugin_name)
            name_type_to_urls.setdefault(key_nt, set()).add(r.url)
            name_type_to_entries.setdefault(key_nt, []).append((plugin_name, r))

            name_to_types.setdefault(r.name, set()).add(r.type)

            key_ut = (r.url, r.type)
            url_type_to_entries.setdefault(key_ut, []).append((plugin_name, r))

            if r.package and r.version:
                package_to_versions.setdefault(r.package, set()).add(r.version)

    for (name, rtype), plugins in name_type_to_plugins.items():
        if len(plugins) < 2:
            continue
        urls = name_type_to_urls[(name, rtype)]
        if len(urls) > 1:
            issues.append(
                AuditIssue(
                    severity="error",
                    code="E001",
                    message=(
                        f"Resource name {name!r} (type={rtype!r}) is declared "
                        f"by multiple plugins {plugins} with DIFFERENT URLs "
                        f"{sorted(urls)}.  The second plugin to render will "
                        f"silently overwrite the first with a different script."
                    ),
                    details={"name": name, "type": rtype, "plugins": plugins, "urls": sorted(urls)},
                )
            )
        else:
            issues.append(
                AuditIssue(
                    severity="warning",
                    code="W003",
                    message=(
                        f"Resource name {name!r} (type={rtype!r}) is shared by "
                        f"multiple plugins {plugins} with the same URL.  This "
                        f"is safe (JSCSSMixin deduplicates by name) but the "
                        f"shared name should be documented."
                    ),
                    details={"name": name, "type": rtype, "plugins": plugins},
                )
            )

    for pkg_name, versions in package_to_versions.items():
        if len(versions) > 1:
            issues.append(
                AuditIssue(
                    severity="error",
                    code="E002",
                    message=(
                        f"Package {pkg_name!r} is used at multiple versions: "
                        f"{sorted(versions)}.  This usually indicates a "
                        f"version skew that should be resolved."
                    ),
                    details={"package": pkg_name, "versions": sorted(versions)},
                )
            )

    for (url, rtype), entries in url_type_to_entries.items():
        if len(entries) > 1:
            names = sorted({r.name for _, r in entries})
            if len(names) > 1:
                plugins = [p for p, _ in entries]
                issues.append(
                    AuditIssue(
                        severity="warning",
                        code="W001",
                        message=(
                            f"URL {url!r} (type={rtype!r}) is referenced by "
                            f"different names {names} across plugins "
                            f"{plugins}.  The same library may be loaded "
                            f"twice when both plugins are active."
                        ),
                        details={
                            "url": url,
                            "type": rtype,
                            "names": names,
                            "plugins": plugins,
                        },
                    )
                )

    for name, types in name_to_types.items():
        if len(types) > 1:
            issues.append(
                AuditIssue(
                    severity="warning",
                    code="W002",
                    message=(
                        f"Resource name {name!r} appears as both JS and CSS "
                        f"across plugins.  This can confuse add_js_link / "
                        f"add_css_link overrides."
                    ),
                    details={"name": name, "types": sorted(types)},
                )
            )

    issues.sort(key=lambda iss: (0 if iss.severity == "error" else 1, iss.code))
    return issues
