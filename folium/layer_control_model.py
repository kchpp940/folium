from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional, Union

if TYPE_CHECKING:
    from folium.map import Layer


@dataclass
class LayerEntry:
    layer: Layer
    js_name: str
    label: str
    is_overlay: bool
    is_controlled: bool = True
    is_visible: bool = True
    sort_weight: int = 0
    group: Optional[str] = None
    is_disabled: bool = False
    is_collapsed: bool = False

    @property
    def group_path(self) -> list[str]:
        if not self.group:
            return []
        return [seg for seg in str(self.group).split("/") if seg]

    @property
    def top_level_group(self) -> Optional[str]:
        path = self.group_path
        return path[0] if path else None


class LayerControlModel:
    def __init__(self):
        self.entries: list[LayerEntry] = []

    @classmethod
    def from_map_children(cls, parent, exclude=None) -> LayerControlModel:
        model = cls()
        from folium.map import Layer as LayerCls

        exclude_set = set(exclude) if exclude else set()
        for item in parent._children.values():
            if not isinstance(item, LayerCls) or not item.control:
                continue
            if item in exclude_set:
                continue
            model.add_layer(item)
        return model

    def find_entry(self, layer: Layer) -> Optional[LayerEntry]:
        for entry in self.entries:
            if entry.layer is layer:
                return entry
        return None

    def ensure_layer(self, layer: Layer, **overrides) -> LayerEntry:
        existing = self.find_entry(layer)
        if existing is not None:
            for key, value in overrides.items():
                if value is not None:
                    setattr(existing, key, value)
            return existing
        return self.add_layer(layer, **overrides)

    def add_layer(self, layer: Layer, **overrides) -> LayerEntry:
        entry = LayerEntry(
            layer=layer,
            js_name=overrides.pop("js_name", layer.get_name()),
            label=overrides.pop("label", layer.layer_name),
            is_overlay=overrides.pop("is_overlay", layer.overlay),
            is_controlled=overrides.pop("is_controlled", layer.control),
            is_visible=overrides.pop("is_visible", layer.show),
            sort_weight=overrides.pop(
                "sort_weight", getattr(layer, "control_order", 0)
            ),
            group=overrides.pop("group", getattr(layer, "control_group", None)),
            is_disabled=overrides.pop(
                "is_disabled", getattr(layer, "control_disabled", False)
            ),
            is_collapsed=overrides.pop(
                "is_collapsed", getattr(layer, "control_collapsed", False)
            ),
        )
        self.entries.append(entry)
        return entry

    def apply_group_overrides(self, groups: dict) -> None:
        for group_name, sublist in groups.items():
            for element in sublist:
                entry = self.ensure_layer(element)
                entry.group = group_name

    def deduplicate(self) -> None:
        seen: dict[tuple[str, bool], LayerEntry] = {}
        for entry in self.entries:
            key = (entry.label, entry.is_overlay)
            seen[key] = entry
        self.entries = list(seen.values())

    def sort_by_weight(self) -> None:
        self.entries.sort(key=lambda e: e.sort_weight)

    @property
    def base_layers(self) -> list[LayerEntry]:
        return [e for e in self.entries if not e.is_overlay]

    @property
    def overlays(self) -> list[LayerEntry]:
        return [e for e in self.entries if e.is_overlay]

    @property
    def hidden_entries(self) -> list[LayerEntry]:
        return [e for e in self.entries if not e.is_visible or e.is_disabled]

    def as_flat_dicts(self) -> tuple[OrderedDict, OrderedDict]:
        base = OrderedDict()
        for e in self.base_layers:
            base[e.label] = e.js_name
        overlays = OrderedDict()
        for e in self.overlays:
            overlays[e.label] = e.js_name
        return base, overlays

    def as_grouped_dicts(
        self,
        explicit_groups: Optional[dict] = None,
        exclusive_groups: bool = True,
    ) -> tuple[OrderedDict[str, OrderedDict[str, str]], list[str]]:
        auto_groups: OrderedDict[str, OrderedDict[str, str]] = OrderedDict()
        auto_order: list[str] = []
        for e in self.overlays:
            top = e.top_level_group
            if top is None:
                continue
            if top not in auto_groups:
                auto_groups[top] = OrderedDict()
                auto_order.append(top)
            auto_groups[top][e.label] = e.js_name

        if not explicit_groups:
            return auto_groups, auto_order

        result: OrderedDict[str, OrderedDict[str, str]] = OrderedDict()
        seen_keys: set[str] = set()

        def _layer_jsname(element) -> str:
            entry = self.find_entry(element)
            return entry.js_name if entry else element.get_name()

        def _layer_label(element) -> str:
            entry = self.find_entry(element)
            return entry.label if entry else getattr(element, "layer_name", element.get_name())

        for gname, sublist in explicit_groups.items():
            if gname not in result:
                result[gname] = OrderedDict()
                seen_keys.add(gname)
            for element in sublist:
                entry = self.ensure_layer(element)
                entry.group = gname
                result[gname][_layer_label(element)] = _layer_jsname(element)

        for gname in auto_order:
            if gname in seen_keys:
                if gname not in result:
                    result[gname] = OrderedDict()
                for lbl, jsn in auto_groups[gname].items():
                    if lbl not in result[gname]:
                        result[gname][lbl] = jsn
            else:
                result[gname] = auto_groups[gname]
                seen_keys.add(gname)

        result_order = list(result.keys())
        if exclusive_groups:
            result_order = list(explicit_groups.keys()) + [
                k for k in result if k not in explicit_groups
            ]
            reordered: OrderedDict[str, OrderedDict[str, str]] = OrderedDict()
            for k in result_order:
                if k in result:
                    reordered[k] = result[k]
            result = reordered
        return result, result_order

    def build_tree_from_groups(self, is_overlay: bool) -> list[dict]:
        entries = self.overlays if is_overlay else self.base_layers
        entries = [e for e in entries if e.group_path]
        if not entries:
            return []

        root_children: list[dict] = []
        node_cache: dict[tuple, dict] = {}

        def get_or_create_node(path: list[str]) -> dict:
            key = tuple(path)
            if key in node_cache:
                return node_cache[key]
            if not path:
                raise ValueError("Empty path")
            if len(path) == 1:
                node = {"label": path[0]}
                root_children.append(node)
                node_cache[key] = node
                return node
            parent = get_or_create_node(path[:-1])
            child_list = parent.setdefault("children", [])
            existing = next(
                (n for n in child_list if n.get("label") == path[-1]), None
            )
            if existing is not None:
                node_cache[key] = existing
                return existing
            node = {"label": path[-1]}
            child_list.append(node)
            node_cache[key] = node
            return node

        for entry in entries:
            path = entry.group_path
            if len(path) == 1:
                container = root_children
            else:
                parent = get_or_create_node(path[:-1])
                container = parent.setdefault("children", [])
            leaf: dict[str, Any] = {"label": entry.label, "layer": entry.layer}
            if entry.is_collapsed:
                leaf["collapsed"] = True
            container.append(leaf)

        return root_children

    @staticmethod
    def prune_single_child_chains(nodes: list[dict]) -> list[dict]:
        def collapse(node: dict) -> None:
            children = node.get("children")
            if not children:
                return
            for child in children:
                collapse(child)
            while len(children) == 1 and "layer" not in children[0]:
                only = children[0]
                inner = only.get("children", [])
                if inner:
                    if node.get("label") and only.get("label"):
                        node["label"] = f"{node['label']} / {only['label']}"
                    node["children"] = inner
                    if only.get("collapsed") and not node.get("collapsed"):
                        node["collapsed"] = only["collapsed"]
                    children = inner
                else:
                    break

        result: list[dict] = [dict(n) for n in nodes]
        for i, n in enumerate(result):
            if "children" in n:
                result[i] = dict(n)
                result[i]["children"] = list(n["children"])
            collapse(result[i])
        return result

    @staticmethod
    def _merge_trees(base: list[dict], override: list[dict]) -> list[dict]:
        if not override:
            return list(base)

        def find_label(nodes: list[dict], label) -> Optional[dict]:
            if label is None:
                return None
            return next((n for n in nodes if n.get("label") == label), None)

        def merge_into(target_nodes: list[dict], override_node: dict) -> None:
            label = override_node.get("label")
            match = find_label(target_nodes, label) if label is not None else None
            if match is not None:
                for k, v in override_node.items():
                    if k == "children":
                        continue
                    match[k] = v
                if "children" in override_node:
                    match_children = match.setdefault("children", [])
                    for child in override_node["children"]:
                        merge_into(match_children, child)
            else:
                copied = dict(override_node)
                if "children" in copied:
                    copied["children"] = [dict(c) for c in copied["children"]]
                    for i, c in enumerate(copied["children"]):
                        if "children" in c:
                            copied["children"][i] = dict(c)
                            copied["children"][i]["children"] = list(c["children"])
                target_nodes.append(copied)
                if "children" in override_node:
                    last_idx = len(target_nodes) - 1
                    target_nodes[last_idx] = dict(target_nodes[last_idx])
                    fresh_children: list[dict] = []
                    for child in override_node["children"]:
                        merge_into(fresh_children, child)
                    target_nodes[last_idx]["children"] = fresh_children

        result: list[dict] = [dict(n) for n in base]
        for i, n in enumerate(result):
            if "children" in n:
                result[i] = dict(n)
                result[i]["children"] = list(n["children"])
        for node in override:
            merge_into(result, node)
        return result

    def normalize_tree(
        self,
        raw_tree: Union[dict, list, None],
        is_overlay: bool,
    ):
        auto_tree = self.build_tree_from_groups(is_overlay)

        if raw_tree is None:
            override_list: list[dict] = []
        elif isinstance(raw_tree, list):
            override_list = list(raw_tree)
        elif isinstance(raw_tree, dict):
            override_list = [raw_tree]
        else:
            override_list = []

        merged = LayerControlModel._merge_trees(auto_tree, override_list)
        merged = [self._resolve_layers(n, is_overlay) for n in merged]
        merged = LayerControlModel.prune_single_child_chains(merged)

        if not merged:
            return None
        if len(merged) == 1:
            return merged[0]
        return merged

    def _resolve_layers(self, node: dict, is_overlay: bool) -> dict:
        result = dict(node)
        layer_obj = result.get("layer")
        if layer_obj is not None:
            from folium.map import Layer as LayerCls

            if isinstance(layer_obj, LayerCls):
                overrides: dict = {"is_overlay": is_overlay}
                if "label" in result:
                    overrides["label"] = result["label"]
                if "collapsed" in result:
                    overrides["is_collapsed"] = result["collapsed"]
                entry = self.ensure_layer(layer_obj, **overrides)
                result["label"] = entry.label
                if entry.is_collapsed and "collapsed" not in result:
                    result["collapsed"] = True
        if "children" in result:
            result["children"] = [
                self._resolve_layers(child, is_overlay)
                for child in result["children"]
            ]
        return result


def collect_excluded_layers(parent) -> set:
    excluded: set = set()
    for item in parent._children.values():
        build_claim = getattr(item, "_build_model_and_claim", None)
        if callable(build_claim):
            try:
                claimed = build_claim(parent)
                excluded.update(claimed)
            except Exception:
                pass
    return excluded


def _collect_tree_layers(node, result: set) -> None:
    if node is None:
        return
    from folium.map import Layer as LayerCls

    if isinstance(node, dict):
        layer_obj = node.get("layer")
        if isinstance(layer_obj, LayerCls):
            result.add(layer_obj)
        for child in node.get("children", []):
            _collect_tree_layers(child, result)
    elif isinstance(node, list):
        for item in node:
            _collect_tree_layers(item, result)
