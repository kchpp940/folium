"""
Folium Public API Policy.

This module is a pure data declaration file that defines the public API
boundary rules. It contains NO audit logic — only policy data consumed by
:mod:`folium._audit.api_audit`.

Policy Sections
---------------
AUDITED_MODULES
    Set of module paths that are in scope for API boundary auditing.
    Only modules listed here are checked by the API audit.

INIT_REEXPORT_MODULES
    Subset of AUDITED_MODULES whose public names MUST be re-exported
    through the top-level ``folium.__init__``. These are the core modules
    that users should be able to access via ``folium.ClassName``.

INTERNAL_NAMES
    Names that are internal implementation details and MUST NOT appear
    in any module's ``__all__``. These are often base classes, mixins,
    or helper functions that happen to be defined at module level but
    are not part of the public contract.

COMPAT_ALIASES
    Names that exist purely for backward compatibility. They are re-exports
    of classes that have moved or been renamed. These are explicitly
    enumerated so they can be tracked and eventually deprecated.

EXPERIMENTAL_NAMES
    Names marked as experimental / unstable. They appear in ``__all__``
    but should trigger warnings if audited in a release branch. This
    list is empty by default.

FORBIDDEN_TOPLEVEL_MODULES
    Basenames of .py files that must NOT exist directly under the
    ``folium/`` package root (i.e. ``folium/<name>.py``) unless they
    start with an underscore. This prevents audit/tooling modules from
    accidentally becoming part of the public API surface. The legacy
    shims (api_audit, api_policy, release_audit) are grandfathered in
    but must re-export from ``folium._audit`` and must not be
    duplicated by new non-underscore modules.

Notes
-----
This file is the single source of truth for API boundary questions.
When adding new public classes or refactoring internal implementation,
update the relevant section here rather than modifying audit logic.
"""

from __future__ import annotations

from typing import Final


__all__: list[str] = []


AUDITED_MODULES: Final[set[str]] = {
    "folium",
    "folium.map",
    "folium.features",
    "folium.raster_layers",
    "folium.vector_layers",
    "folium.elements",
    "folium.folium",
    "folium.utilities",
    "folium.plugins",
}


INIT_REEXPORT_MODULES: Final[set[str]] = {
    "folium.map",
    "folium.features",
    "folium.raster_layers",
    "folium.vector_layers",
}


INTERNAL_NAMES: Final[dict[str, set[str]]] = {
    "folium.map": {
        "classproperty",
        "Class",
        "Evented",
        "Layer",
    },
    "folium.features": {
        "GeoJsonStyleMapper",
        "GeoJsonDetail",
        "TypeStyleMapping",
    },
    "folium.vector_layers": {
        "path_options",
        "BaseMultiLocation",
    },
    "folium.elements": {
        "leaflet_method",
        "JSCSSMixin",
        "EventHandler",
        "ElementAddToElement",
        "IncludeStatement",
        "MethodCall",
        "CssLink",
        "JavascriptLink",
    },
    "folium.folium": {
        "GlobalSwitches",
    },
    "folium.utilities": {
        "_validate_locations_basics",
        "_is_url",
        "if_pandas_df_convert_to_numpy",
        "parse_font_size",
        "escape_double_quotes",
        "get_and_assert_figure_root",
    },
}


COMPAT_ALIASES: Final[dict[str, dict[str, str]]] = {
}


EXPERIMENTAL_NAMES: Final[dict[str, set[str]]] = {
}


FORBIDDEN_TOPLEVEL_MODULES: Final[set[str]] = {
    "api_audit",
    "api_policy",
    "release_audit",
}
