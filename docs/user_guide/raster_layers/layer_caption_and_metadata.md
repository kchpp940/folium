# Layer captions and metadata

Folium provides a unified `caption` parameter on the four raster-layer
classes — `ImageOverlay`, `VideoOverlay`, `TileLayer` and `FloatImage` —
so that you can attach rich, self-documenting metadata (title,
description, source, legend color bar, etc.) directly to each layer.

Instead of stacking a separate HTML info panel next to every layer,
folium registers all metadata into a **single Map-level control**.
When multiple layers are visible at the same time, their sections are
merged in registration order; when layers are toggled via
`LayerControl`, the corresponding metadata appears and disappears
automatically.

## Quick start

Pass any dictionary with the keys described in
[`folium.LayerMetadata`](../reference.rst#folium.LayerMetadata) to a
layer's `caption` argument:

```{code-cell} ipython3
import numpy as np
import folium
from folium.raster_layers import ImageOverlay

# Generate a synthetic heatmap array.
data = np.zeros((100, 200))
for y in range(100):
    for x in range(200):
        data[y, x] = np.exp(-0.5 * ((y - 50) / 20) ** 2 - 0.5 * ((x - 100) / 40) ** 2)

m = folium.Map([37, 0], zoom_start=2)

ImageOverlay(
    image=data,
    bounds=[[0, -60], [60, 60]],
    origin="lower",
    colormap=lambda x: (1, 0, 0, x),
    mercator_project=True,
    name="Synthetic heatmap",
    caption={
        "title": "Synthetic heatmap",
        "description": "A bivariate Gaussian test field.",
        "unit": "relative intensity",
        "resolution": "1.2 km",
        "source_url": "https://example.org/dataset",
        "source_text": "Example dataset",
        "updated_time": "2024-06-01",
        "copyright": "© 2024 Example Org",
        "legend": [
            {"label": "Low",    "color": "rgba(255,0,0,0.0)"},
            {"label": "Medium", "color": "rgba(255,0,0,0.5)"},
            {"label": "High",   "color": "rgba(255,0,0,1.0)"},
        ],
    },
).add_to(m)

folium.LayerControl().add_to(m)

m
```

After rendering, a single info panel appears in the bottom-right corner
showing the title, description, metadata row (unit / resolution / last
update), the source link, the legend color bar, and the copyright line.

## Supported layers

The `caption` parameter is accepted by:

| Layer class                                | Package / module         |
|--------------------------------------------|--------------------------|
| `folium.raster_layers.ImageOverlay`        | `folium.raster_layers`   |
| `folium.raster_layers.VideoOverlay`        | `folium.raster_layers`   |
| `folium.raster_layers.TileLayer`           | top-level `folium`       |
| `folium.plugins.FloatImage`                | `folium.plugins`         |

They all share the exact same specification documented in
[`folium.LayerMetadata`](../reference.rst#folium.LayerMetadata).

## Full metadata reference

Every key is optional; omit whatever is not relevant to your dataset.

| Key             | Type                    | Default       | Description |
|-----------------|-------------------------|---------------|-------------|
| `title`         | `str`                   | —             | Bold heading at the top of the section. |
| `description`   | `str`                   | —             | One-paragraph dataset description. |
| `unit`          | `str`                   | —             | Measurement unit, e.g. `"°C"`, `"m/s"`. |
| `resolution`    | `str`                   | —             | Spatial / temporal resolution. |
| `source_url`    | `str`                   | —             | Hyperlink to the original source. |
| `source_text`   | `str`                   | `source_url`  | Human-readable label for the link. |
| `updated_time`  | `str`                   | —             | Free-form last-updated string. |
| `copyright`     | `str`                   | —             | Small italic attribution at the bottom of the section. |
| `legend`        | `list[dict]`            | —             | Color bar. Each entry must have at least `"label"` and `"color"` keys. |
| `position`      | `str`                   | `bottomright` | Leaflet control position (`topleft`, `topright`, `bottomleft`, `bottomright`). |
| `collapsible`   | `bool`                  | `True`        | Whether the panel exposes a collapse toggle. |
| `collapsed`     | `bool`                  | `False`       | Whether the panel starts collapsed. |

```{warning}
The control-level keys **`position`**, **`collapsible`** and
**`collapsed`** are read only from the *first* caption-enabled layer
registered on a Map.  This is because folium creates exactly **one**
unified control per Map — a Map-level singleton.  Setting these keys on
a second or subsequent layer has no effect.
```

### Legend

Each entry in the `legend` list must contain (at least) the keys
`label` (string shown to the right of the color swatch) and `color`
(any valid CSS color — named color, `#rrggbb`, `rgba(r,g,b,a)`, etc.):

```python
caption = {
    "legend": [
        {"label": "Below 0°C",   "color": "#3498db"},
        {"label": "0 – 10°C",    "color": "#2ecc71"},
        {"label": "10 – 25°C",   "color": "#f39c12"},
        {"label": "Above 25°C",  "color": "#e74c3c"},
    ]
}
```

## Using `LayerMetadata` for type safety

For IDE autocompletion and type-checking you can import the
[`folium.LayerMetadata`](../reference.rst#folium.LayerMetadata)
TypedDict and pass it directly — it is treated identically to a plain
`dict` at runtime:

```{code-cell} ipython3
from folium import LayerMetadata, LegendItem

meta: LayerMetadata = {
    "title": "Sea-surface temperature",
    "unit": "°C",
    "legend": [
        LegendItem(label="Cold",  color="blue"),
        LegendItem(label="Warm",  color="red"),
    ],
}
```

`LegendItem` is itself a `TypedDict`; again, passing an inline `dict`
with matching keys is exactly equivalent.

## Multi-layer merging and LayerControl

When more than one caption-enabled layer is added to a Map, folium
collects every section in the order the layers were *first registered*
and merges them in a single panel, separated by thin horizontal rules.
Try toggling the two overlays on and off in the example below to see
the panel change dynamically:

```{code-cell} ipython3
import numpy as np
import folium
from folium.raster_layers import ImageOverlay

m = folium.Map([37, 0], zoom_start=2)

# Layer 1 — a red field in the northern hemisphere.
img1 = np.zeros((60, 120))
img1[20:40, 40:80] = 1.0
ImageOverlay(
    image=img1,
    bounds=[[0, -60], [60, 60]],
    colormap=lambda x: (1, 0, 0, x),
    mercator_project=True,
    name="Red blob (N. hemisphere)",
    caption={
        "title": "Red blob",
        "description": "A test patch over Europe.",
        "unit": "a.u.",
    },
).add_to(m)

# Layer 2 — a blue field in the southern hemisphere.
img2 = np.zeros((60, 120))
img2[20:40, 40:80] = 1.0
ImageOverlay(
    image=img2,
    bounds=[[-60, -60], [0, 60]],
    colormap=lambda x: (0, 0, 1, x),
    mercator_project=True,
    name="Blue blob (S. hemisphere)",
    caption={
        "title": "Blue blob",
        "description": "A test patch over the Southern Ocean.",
        "source_url": "https://example.org/blue",
    },
).add_to(m)

folium.LayerControl().add_to(m)
m
```

The wiring is automatic: each registered layer listens to its own
Leaflet `add` / `remove` events, so `LayerControl`, `FeatureGroup`, or
even programmatic `layer.addTo(map)` / `layer.remove()` calls all keep
the metadata panel perfectly in sync.

## `show=False` (hidden by default)

A layer added with `show=False` (or any other reason for which the
layer is initially off) will be registered but will **not** contribute
to the panel until the user enables it via `LayerControl`.  The
`show` flag from each layer's constructor is forwarded directly to the
Map-level registry as the *initial visibility* of that section.

```{code-cell} ipython3
import numpy as np
import folium
from folium.raster_layers import ImageOverlay

m = folium.Map([37, 0], zoom_start=2)

ImageOverlay(
    image=np.random.rand(60, 60),
    bounds=[[0, -60], [60, 60]],
    colormap=lambda x: (0, x, 1 - x, 0.9),
    mercator_project=True,
    name="Random overlay",
    show=False,                 # initially hidden …
    caption={
        "title": "Random overlay",
        "description": "Not visible until you toggle it on.",
    },
).add_to(m)

folium.LayerControl().add_to(m)
m
```

On load the panel stays empty (`No active layer metadata`). Enable the
layer and the caption appears; disable it again and it vanishes.

## `add_to()` vs. `map.add_child()`

You can attach a layer to the Map in either of the two idiomatic ways;
the caption system guarantees identical behaviour for both.

**Preferred idiom — `layer.add_to(map)`**:

```python
ImageOverlay(..., caption={...}).add_to(m)
```

**Alternative idiom — `map.add_child(layer)`**:

```python
layer = ImageOverlay(..., caption={...})
m.add_child(layer)
```

Both paths trigger registration.  Internally, folium uses two explicit,
safe hooks:

1. Overridden `add_to()` — fires registration immediately after the
   layer is attached.
2. Overridden `render()` — a fallback that fires just before the HTML
   is produced, catching layers that were added via `add_child()`.

You do **not** need to do anything special; the registry guarantees
that every caption attached to a layer that ends up in the render tree
is injected exactly once.

## Collapsible panel, default position, and custom defaults

The panel's layout is controlled by the three Map-level keys
(`position`, `collapsible`, `collapsed`) taken from the **first**
caption-enabled layer you add.  To change the default, just put the
desired settings on the layer that is registered first (often the base
`TileLayer`):

```{code-cell} ipython3
import folium
from folium import TileLayer, LayerControl

m = folium.Map([37, 0], zoom_start=2, tiles=None)

# A base map — registered first, so its caption layout wins.
TileLayer(
    tiles="CartoDB Voyager",
    name="Basemap",
    overlay=False,
    caption={
        "title": "CartoDB Voyager",
        "description": "Positron-style basemap tiles.",
        "position": "topright",       # → panel lives top-right
        "collapsible": True,          # → expose the toggle button
        "collapsed": True,            # → start collapsed to save space
        "copyright": "© CARTO",
    },
).add_to(m)

# A secondary tile set — position/collapsible/collapsed here are ignored.
TileLayer(
    tiles="OpenStreetMap",
    name="OpenStreetMap",
    overlay=False,
    show=False,
    caption={
        "title": "OpenStreetMap",
        "description": "Community-driven standard basemap.",
        "copyright": "© OpenStreetMap contributors",
    },
).add_to(m)

LayerControl().add_to(m)
m
```

## Validation

Internally, folium runs every `caption` dict through
[`folium.normalize_layer_metadata`](../reference.rst#folium.normalize_layer_metadata)
before registration.  This step:

* drops unrecognised keys;
* coerces `collapsible` / `collapsed` to strict `bool`;
* validates `position` against the four Leaflet-accepted values;
* validates that every item in `legend` has both `label` *and*
  `color`; raises `ValueError` otherwise;
* fills in the default values for any missing control-level keys.

This means that a mis-typed caption fails **early** at Python object
construction time, not silently in the browser.

```{code-cell} ipython3
---
tags: ["raises-exception"]
---
from folium.raster_layers import ImageOverlay, normalize_layer_metadata

# Missing 'color' key in a legend item → raises ValueError.
normalize_layer_metadata({
    "title": "Broken legend",
    "legend": [{"label": "Foo"}]
})
```

## Public API summary

| Symbol                                             | Kind         | Usage |
|----------------------------------------------------|--------------|-------|
| `folium.LayerMetadata`                             | `TypedDict`  | Describe a caption with type safety. |
| `folium.LegendItem`                                | `TypedDict`  | Describe a single color-bar entry. |
| `folium.normalize_layer_metadata(meta)`            | function     | Validate + fill defaults for a caption dict. |
| `ImageOverlay(..., caption=...)`                   | parameter    | Attach caption to an image layer. |
| `VideoOverlay(..., caption=...)`                   | parameter    | Attach caption to a video layer. |
| `TileLayer(..., caption=...)`                      | parameter    | Attach caption to a tile layer. |
| `folium.plugins.FloatImage(..., caption=...)`      | parameter    | Attach caption to a float image. |

```{warning}
The following names **appear in the source** but are internal
implementation details and are **not** covered by the public API
stability guarantee:

* `folium.elements.CaptionRegistry` — internal Map-level bookkeeper.
* `folium.elements.CaptionMixin` — internal mixin wired into raster
  layer classes.
* The `_CAPTION_CSS` / `_CAPTION_JS_TEMPLATE` module constants.

They may be renamed, moved, or removed in any future release.  Do not
import or subclass them from user code.
```
