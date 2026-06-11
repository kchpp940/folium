from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
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
            grp = e.group or ""
            if grp not in groups:
                groups[grp] = OrderedDict()
            groups[grp][e.label] = e.js_name
        return groups

    @staticmethod
    def normalize_tree(
        node, is_overlay: bool, model: Optional[LayerControlModel] = None
    ):
        if node is None:
            return None
        if isinstance(node, list):
            return [
                LayerControlModel.normalize_tree(item, is_overlay, model)
                for item in node
            ]
        if not isinstance(node, dict):
            return node

        result = dict(node)
        layer_obj = result.get("layer")

        if model is not None and layer_obj is not None:
            from folium.map import Layer as LayerCls

            if isinstance(layer_obj, LayerCls):
                overrides = {
                    "label": result.get("label", layer_obj.layer_name),
                    "is_overlay": is_overlay,
                }
                if "collapsed" in result:
                    overrides["is_collapsed"] = result["collapsed"]
                entry = model.add_layer(layer_obj, **overrides)
                result["label"] = entry.label
                if entry.is_collapsed and "collapsed" not in result:
                    result["collapsed"] = True

        if "children" in result:
            result["children"] = [
                LayerControlModel.normalize_tree(child, is_overlay, model)
                for child in result["children"]
            ]

        return result
