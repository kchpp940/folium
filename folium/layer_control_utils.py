"""
Shared utilities for LayerControl, GroupedLayerControl and TreeLayerControl.

This module provides unified layer collection, sorting, grouping and
tree-building logic so that the three controls share the same ordering
rules.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import TYPE_CHECKING, Any, Optional, Union

if TYPE_CHECKING:
    from folium.map import Layer


_INF = float("inf")


def _stable_sort_key(layer: Layer, insertion_idx: int) -> tuple:
    """Return a sort key for a layer.

    Sorting rule:
      1. ``control_order`` ascending (None treated as +inf so unspecified
         layers appear after explicitly-numbered ones).
      2. ``insertion_idx`` ascending – preserves the original addition
         order for ties, giving deterministic output.
    """
    order = layer.control_order
    return (
        _INF if order is None else order,
        insertion_idx,
    )


def collect_layers(
    parent: Any,
    include_ungrouped: bool = True,
    only_overlay: Optional[bool] = None,
) -> list[Layer]:
    """Collect all :class:`Layer` children of ``parent`` that are eligible
    to appear in a layer control.

    Parameters
    ----------
    parent :
        Usually a :class:`folium.Map`.  All direct children are inspected.
    include_ungrouped : bool, default True
        If False, only layers with ``control_group`` set are returned.
    only_overlay : bool, optional
        - True  → only overlay layers (``overlay=True``)
        - False → only base layers (``overlay=False``)
        - None  → both (default)
    """
    from folium.map import Layer

    collected: list[Layer] = []
    insertion_idx = 0
    for child in parent._children.values():
        if not isinstance(child, Layer):
            continue
        if not child.control:
            continue
        if only_overlay is not None and child.overlay != only_overlay:
            continue
        if not include_ungrouped and child.control_group is None:
            continue
        # Stash the insertion index so we can use it for stable sorting.
        # We attach it to the object only temporarily via a private slot;
        # to avoid mutating the caller's objects we simply keep parallel
        # state inside the returned list by sorting here.
        child._lc_insertion_idx = getattr(child, "_lc_insertion_idx", insertion_idx)
        insertion_idx += 1
        collected.append(child)
    return collected


def sort_layers(layers: list[Layer]) -> list[Layer]:
    """Return a new list of layers sorted by the unified rule.

    See :func:`_stable_sort_key`.
    """
    def key(layer: Layer) -> tuple:
        idx = getattr(layer, "_lc_insertion_idx", 0)
        return _stable_sort_key(layer, idx)

    return sorted(layers, key=key)


def deduplicate_layer_names(layers: list[Layer]) -> list[Layer]:
    """Resolve duplicate ``layer_name`` values by appending `` (2)``,
    `` (3)`` … so that every label is unique.

    Modifies ``layer_name`` on the affected objects in-place and returns
    the (same) list for convenience.
    """
    seen: dict[str, int] = {}
    for layer in layers:
        name = layer.layer_name
        if name in seen:
            seen[name] += 1
            layer.layer_name = f"{name} ({seen[name]})"
        else:
            seen[name] = 1
    return layers


def flat_layers_for_control(
    parent: Any,
    only_overlay: Optional[bool] = None,
    dedupe_names: bool = True,
) -> list[Layer]:
    """Convenience: collect + sort + (optionally) dedupe.

    Used by the plain :class:`LayerControl`.
    """
    layers = collect_layers(parent, include_ungrouped=True, only_overlay=only_overlay)
    layers = sort_layers(layers)
    if dedupe_names:
        deduplicate_layer_names(layers)
    return layers


# ---------------------------------------------------------------------------
# Grouped-layer helpers (used by GroupedLayerControl)
# ---------------------------------------------------------------------------


def _min_order_of(layers: list[Layer]) -> float:
    orders = [
        _INF if l.control_order is None else l.control_order for l in layers
    ]
    return min(orders) if orders else _INF


def build_grouped_overlays(
    layers: list[Layer],
    explicit_groups: Optional[dict[str, list[Layer]]] = None,
) -> "OrderedDict[str, OrderedDict[str, Layer]]":
    """Build the ``grouped_overlays`` dict consumed by
    :class:`~folium.plugins.GroupedLayerControl`.

    Parameters
    ----------
    layers :
        Flat list of overlay layers (already sorted is fine, but not
        required – we sort here per group as well).
    explicit_groups : dict, optional
        Pre-declared groups (``{group_name: [layers]}``).  These take
        precedence and are emitted in the order they are declared;
        layers that also carry ``control_group`` are still placed into
        the explicit group when the names match.

    Returns
    -------
    OrderedDict[str, OrderedDict[str, Layer]]
        Outer key = group label, inner key = layer label, value = layer.
    """
    from folium.map import Layer  # noqa: F401 (re-import for type clarity)

    # 1. Collect every layer into a mutable per-group mapping.
    per_group: dict[str, list[Layer]] = OrderedDict()

    if explicit_groups:
        for group_name, group_layers in explicit_groups.items():
            per_group.setdefault(group_name, [])
            for layer in group_layers:
                if layer not in per_group[group_name]:
                    per_group[group_name].append(layer)

    # 2. Honour each layer's own control_group.
    for layer in layers:
        if layer.control_group is None:
            continue
        group_name = layer.control_group[0]  # grouped control only uses 1st level
        per_group.setdefault(group_name, [])
        if layer not in per_group[group_name]:
            per_group[group_name].append(layer)

    # 3. Drop empty groups, sort each group's layers, dedupe names.
    result: "OrderedDict[str, OrderedDict[str, Layer]]" = OrderedDict()
    all_so_far: list[Layer] = []
    for group_name, group_layers in per_group.items():
        if not group_layers:
            continue
        group_sorted = sort_layers(group_layers)
        deduplicate_layer_names(group_sorted)

        inner: "OrderedDict[str, Layer]" = OrderedDict()
        for layer in group_sorted:
            inner[layer.layer_name] = layer
            all_so_far.append(layer)
        result[group_name] = inner

    # 4. Determine group ordering: first the user-declared order
    #    (preserved above), then the remaining groups sorted by their
    #    minimum layer control_order, then by first-seen position.
    explicit_order = list(explicit_groups.keys()) if explicit_groups else []
    remaining = [g for g in result.keys() if g not in explicit_order]
    remaining_groups_with_key = [
        (
            _min_order_of(list(result[g].values())),
            next(iter(result[g].values()))._lc_insertion_idx
            if result[g] else 0,
            g,
        )
        for g in remaining
    ]
    remaining_groups_with_key.sort()
    final_order = explicit_order + [g for _, _, g in remaining_groups_with_key]

    ordered_result: "OrderedDict[str, OrderedDict[str, Layer]]" = OrderedDict()
    for g in final_order:
        if g in result:
            ordered_result[g] = result[g]
    return ordered_result


# ---------------------------------------------------------------------------
# Tree helpers (used by TreeLayerControl)
# ---------------------------------------------------------------------------


class _TreeNode:
    """Intermediate representation for building a tree dict."""

    def __init__(self, label: str):
        self.label = label
        self.children: dict[str, "_TreeNode"] = OrderedDict()
        self.layer: Optional[Layer] = None
        self.collapsed: bool = False
        self.select_all: Any = False
        self.control_order: float = _INF
        self.insertion_idx: int = 0
        self.disabled: bool = False


def _ensure_path(root: _TreeNode, path: list[str]) -> _TreeNode:
    node = root
    for part in path:
        if part not in node.children:
            node.children[part] = _TreeNode(part)
        node = node.children[part]
    return node


def build_tree(
    layers: list[Layer],
    explicit_tree: Optional[Union[dict, list]] = None,
) -> Union[dict, list]:
    """Construct a ``TreeLayerControl``-compatible tree dict/list from the
    given layers, honouring each layer's ``control_group`` (multi-level),
    ``control_order``, ``control_collapsed`` and ``control_disabled``.

    Parameters
    ----------
    layers :
        Flat list of layers.
    explicit_tree : dict or list, optional
        A user-supplied skeleton in the same format accepted by
        ``TreeLayerControl``.  We fill in / merge the layers that carry
        a matching ``control_group``.  Branches without layers are kept
        as-is.

    Returns
    -------
    dict or list
        A structure ready to be serialised into the Leaflet tree plugin.
    """
    root = _TreeNode("__root__")

    # 1. Create intermediate nodes from layers' control_group and attach layers.
    for layer in layers:
        path = list(layer.control_group) if layer.control_group else []
        parent = _ensure_path(root, path) if path else root
        parent.layer = layer
        parent.collapsed = bool(layer.control_collapsed)
        parent.disabled = bool(layer.control_disabled)
        if layer.control_order is not None:
            parent.control_order = layer.control_order
        parent.insertion_idx = getattr(layer, "_lc_insertion_idx", 0)

    # 2. Merge user-supplied skeleton.
    if explicit_tree:
        _merge_explicit_tree(root, explicit_tree)

    # 3. Sort children recursively.
    _sort_tree_children(root)

    # 4. Convert to the plugin's dict/list format.
    result = [_tree_node_to_dict(c) for c in root.children.values()]
    if len(result) == 1:
        return result[0]
    return result


def _merge_explicit_tree(root: _TreeNode, explicit: Union[dict, list]) -> None:
    """Merge a user-provided explicit tree into ``root``.

    This preserves user-declared ``selectAllCheckbox``, ``collapsed``,
    ``radioGroup``, ``name``, etc. while still pulling in layer objects
    from the flat layer list where labels coincide.
    """
    if isinstance(explicit, list):
        for item in explicit:
            _merge_explicit_tree(root, item)
        return

    if not isinstance(explicit, dict):
        return

    label = explicit.get("label")
    if not label:
        return

    if label not in root.children:
        root.children[label] = _TreeNode(label)
    node = root.children[label]

    # Carry over user-declared attributes.
    if "collapsed" in explicit:
        node.collapsed = bool(explicit["collapsed"])
    if "selectAllCheckbox" in explicit:
        node.select_all = explicit["selectAllCheckbox"]
    # The user may already have given a layer.
    if "layer" in explicit and node.layer is None:
        node.layer = explicit["layer"]
    # Remember explicit declaration order so explicit branches come first.
    node.insertion_idx = -1

    children = explicit.get("children")
    if children:
        _merge_explicit_tree(node, children)


def _sort_tree_children(node: _TreeNode) -> None:
    """Recursively sort the children of ``node``."""
    if not node.children:
        return
    items = list(node.children.items())
    items.sort(
        key=lambda kv: (
            kv[1].insertion_idx if kv[1].insertion_idx < 0 else (
                _INF if kv[1].control_order is None else kv[1].control_order
            ),
            kv[1].insertion_idx,
        )
    )
    node.children = OrderedDict(items)
    for child in node.children.values():
        _sort_tree_children(child)


def _tree_node_to_dict(node: _TreeNode) -> dict:
    d: dict[str, Any] = {"label": node.label}
    if node.layer is not None:
        d["layer"] = node.layer
    if node.collapsed:
        d["collapsed"] = True
    if node.select_all is not False:
        d["selectAllCheckbox"] = node.select_all
    if node.disabled:
        # The tree plugin does not natively support "disabled"; we carry
        # the flag so downstream rendering (or a user's custom hook) can
        # honour it.  It is stripped out before serialising.
        d["_disabled"] = True
    if node.children:
        d["children"] = [_tree_node_to_dict(c) for c in node.children.values()]
    return d


def strip_tree_plugin_flags(tree: Any) -> Any:
    """Return a copy of ``tree`` with private flags removed so the JSON
    encoder only emits keys the Leaflet tree plugin understands.
    """
    if isinstance(tree, list):
        return [strip_tree_plugin_flags(x) for x in tree]
    if isinstance(tree, dict):
        return {
            k: strip_tree_plugin_flags(v)
            for k, v in tree.items()
            if not k.startswith("_")
        }
    return tree
