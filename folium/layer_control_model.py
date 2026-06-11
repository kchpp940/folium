from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

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


class LayerControlModel:
    def __init__(self):
        self.entries: list[LayerEntry] = []

    @classmethod
    def from_map_children(cls, parent) -> LayerControlModel:
        model = cls()
        from folium.map import Layer as LayerCls

        for item in parent._children.values():
            if not isinstance(item, LayerCls) or not item.control:
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
                entry = self.find_entry(element)
                if entry is not None:
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

    def as_grouped_dicts(self) -> OrderedDict:
        groups: OrderedDict[str, OrderedDict[str, str]] = OrderedDict()
        for e in self.overlays:
            if e.group is None:
                continue
            grp = e.group
            if grp not in groups:
                groups[grp] = OrderedDict()
            groups[grp][e.label] = e.js_name
        return groups

    def normalize_tree(self, node, is_overlay: bool):
        if node is None:
            return None
        if isinstance(node, list):
            return [self.normalize_tree(item, is_overlay) for item in node]
        if not isinstance(node, dict):
            return node

        result = dict(node)
        layer_obj = result.get("layer")

        if layer_obj is not None:
            from folium.map import Layer as LayerCls

            if isinstance(layer_obj, LayerCls):
                overrides: dict = {
                    "is_overlay": is_overlay,
                }
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
                self.normalize_tree(child, is_overlay)
                for child in result["children"]
            ]

        return result
