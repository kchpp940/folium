"""
Common resource descriptor infrastructure for Folium plugins.

This module provides a unified way to declare external JavaScript and CSS
resources for plugins, replacing the ad-hoc default_js / default_css tuple
lists with a structured Resource descriptor.

Benefits:
- Single, ordered list of all resources (JS + CSS interleaved as needed)
- Explicit type annotation for each resource (js / css)
- Easier version upgrades and offline packaging
- Backward compatibility with JSCSSMixin through build_defaults()

"""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Resource:
    """
    Descriptor for an external JavaScript or CSS resource.

    Parameters
    ----------
    name : str
        Unique identifier for the resource. Used as the child name when
        added to a Figure's header.
    url : str
        URL of the resource (CDN address or local path).
    type : Literal["js", "css"]
        Resource type: "js" for JavaScript, "css" for stylesheet.
    """

    name: str
    url: str
    type: Literal["js", "css"]


def build_default_js(resources: list[Resource]) -> list[tuple[str, str]]:
    """
    Extract JavaScript resources as (name, url) tuples, preserving order.

    Parameters
    ----------
    resources : list[Resource]
        Ordered list of resource descriptors.

    Returns
    -------
    list[tuple[str, str]]
        List of (name, url) tuples for JavaScript resources, in the same
        relative order as they appear in the input list.
    """
    return [(r.name, r.url) for r in resources if r.type == "js"]


def build_default_css(resources: list[Resource]) -> list[tuple[str, str]]:
    """
    Extract CSS resources as (name, url) tuples, preserving order.

    Parameters
    ----------
    resources : list[Resource]
        Ordered list of resource descriptors.

    Returns
    -------
    list[tuple[str, str]]
        List of (name, url) tuples for CSS resources, in the same relative
        order as they appear in the input list.
    """
    return [(r.name, r.url) for r in resources if r.type == "css"]


def build_defaults(
    resources: list[Resource],
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """
    Convert a list of Resource descriptors to JSCSSMixin-compatible tuple lists.

    The relative ordering of resources within each type is preserved exactly
    as it appears in the input list.

    Parameters
    ----------
    resources : list[Resource]
        Ordered list of resource descriptors.

    Returns
    -------
    tuple[list[tuple[str, str]], list[tuple[str, str]]]
        A (default_js, default_css) pair where each is a list of
        (name, url) tuples compatible with JSCSSMixin.

    Examples
    --------
    >>> resources = [
    ...     Resource("lib.js", "https://example.com/lib.js", "js"),
    ...     Resource("style.css", "https://example.com/style.css", "css"),
    ...     Resource("app.js", "https://example.com/app.js", "js"),
    ... ]
    >>> default_js, default_css = build_defaults(resources)
    >>> default_js
    [('lib.js', 'https://example.com/lib.js'), ('app.js', 'https://example.com/app.js')]
    >>> default_css
    [('style.css', 'https://example.com/style.css')]
    """
    return build_default_js(resources), build_default_css(resources)
