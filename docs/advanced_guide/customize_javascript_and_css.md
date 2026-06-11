# Customizing javascript or css resources

```{code-cell} ipython3
---
nbsphinx: hidden
---
import folium
```

## Adding javascript or css resources
Many leaflet resources require loading of custom css or javascript modules. This is handled in the `folium.elements.JSCSSMixin` class. Anything that inherits from this class can load custom resources.

You can use the methods `add_js_link` and `add_css_link` to ensure these resources are loaded into the map.

### Example 1: overriding the locations from where resources are loaded
One use case is to override the locations from where resources are loaded. This can be useful if you have to use a private CDN for your javascript and css resources, or if you want to use a different version.

```{code-cell}
m = folium.Map()
m.add_css_link(
    "bootstrap_css",
    "https://example.com/bootstrap/400.5.0/css/bootstrap.min.css"
)
```


### Example 2: loading additional javascript
A second use case is to load library modules that you can then use inside JsCode blocks. Continuing from the Realtime ISS example, see :doc:Realtime <user_guide/plugins/realtime>, we can modify this so that it uses the dayjs library to format the current date.

```{code-cell} ipython3
from folium.utilities import JsCode
from folium.plugins import Realtime

m = folium.Map()
on_each_feature = JsCode("""
function(f, l) {
    l.bindPopup(function() {
        return '<h5>' + dayjs.unix(f.properties.timestamp).format() + '</h5>';
    });
}
""")

source = JsCode("""
function(responseHandler, errorHandler) {
    var url = 'https://api.wheretheiss.at/v1/satellites/25544';

    fetch(url)
    .then((response) => {
        return response.json().then((data) => {
            var { id, timestamp, longitude, latitude } = data;

            return {
                'type': 'FeatureCollection',
                'features': [{
                    'type': 'Feature',
                    'geometry': {
                        'type': 'Point',
                        'coordinates': [longitude, latitude]
                    },
                    'properties': {
                        'id': id,
                        'timestamp': timestamp
                    }
                }]
            };
        })
    })
    .then(responseHandler)
    .catch(errorHandler);
}
""")

rt = Realtime(source,
              on_each_feature=on_each_feature,
              interval=1000)
rt.add_js_link("dayjs", "https://cdn.jsdelivr.net/npm/dayjs@1.11.10/dayjs.min.js")
rt.add_to(m)
m
```


# Offline / air-gapped resource loading

Folium supports four resource loading strategies, controlled by
`resource_mode` on `folium.Map` or globally with
`folium.set_resource_mode()`.  The choice of mode lets you trade off
convenience, build reproducibility, and strictness for offline and
audited environments.

## Resource modes

| Mode       | Network at render | Checksum | Failure behaviour |
|------------|-------------------|----------|-------------------|
| `cdn`      | ✅ yes            | none     | —                 |
| `inline`   | ✅ yes            | none     | fallback to CDN + warning |
| `local`    | ❌ no             | none     | fallback to CDN + warning |
| `manifest` | ❌ **strictly no** | **SHA-256** | **`RuntimeError`** |

`manifest` mode is the safest choice for offline reports, CI pipelines
and audited environments.  Resources are **downloaded once, up-front**,
their SHA-256 hashes are recorded in a JSON manifest, and HTML
generation never touches the network.  Any mismatch or missing file
aborts the render with a clear error.


## `manifest` mode workflow (recommended for offline/CI)

This is a three-step process.  The example shows both the **CLI** and
the **Python API** – use whichever fits your pipeline better.

### 1. Prepare your map

Save a Python file that defines your map.  The CLI looks for a
`build_map()` function or a variable named `m`:

```python
# my_map.py
import folium
from folium.plugins import Fullscreen, HeatMap

def build_map():
    m = folium.Map(location=[45.5, -122.7], zoom_start=10)
    Fullscreen().add_to(m)
    HeatMap([[45.5, -122.7, 1.0], [45.6, -122.8, 0.5]]).add_to(m)
    return m
```

### 2. Step 1 – collect resources

Enumerate every JS and CSS resource the map (and all its plugins) will
need:

**CLI:**
```bash
folium-resource collect my_map.py --manifest resources/manifest.json --dir resources/
```

**Python:**
```python
from my_map import build_map
import folium

m = build_map()
manifest = folium.collect_resources(m)
manifest.save("resources/manifest.json")
```

### 3. Step 2 – download resources

Download every resource into your cache directory and record their
SHA-256 hashes.  This is the only step that needs network access:

**CLI:**
```bash
folium-resource download resources/manifest.json --dir resources/ --retries 8
```

**Python:**
```python
manifest = folium.ResourceManifest.load("resources/manifest.json")
folium.download_manifest(manifest, "resources/", retries=8)
manifest.save("resources/manifest.json")  # now with sha256 checksums
```

### 4. Step 3 – render offline

At this point you can copy the `resources/` directory and
`manifest.json` to an air-gapped machine.  Rendering is 100% offline:

```python
from my_map import build_map
import folium

folium.set_resource_mode("manifest", manifest_path="resources/manifest.json")
m = build_map()
m.save("offline_report.html")
```

If any resource is missing or has been tampered with, you'll get a
`RuntimeError` – never a silent fallback to CDN.


## Verifying a resource cache

Before building in CI you can verify all files are present and their
checksums match:

**CLI:**
```bash
folium-resource verify resources/manifest.json --dir resources/ -v
```

**Python:**
```python
from folium.resource_manifest import resolve_from_manifest
manifest = folium.ResourceManifest.load("resources/manifest.json")
for entry in manifest:
    path = resolve_from_manifest(entry.name, manifest, "resources/")
    if path is None:
        raise RuntimeError(f"Missing or corrupt: {entry.name}")
```


## Per-resource overrides

Regardless of mode, you can override individual resources with
`folium.set_resource_override(name, path_or_url)`.  The value can be:

* an absolute or relative filesystem path → read from disk and inlined
* a `http://` or `https://` URL → load from that URL
* a `data:text/javascript;base64,...` or `data:text/css;base64,...` URI

```python
folium.set_resource_override("leaflet", "/internal/cdn/leaflet-1.9.3.js")
folium.set_resource_override("bootstrap_css", "data:text/css;base64,LyoqLy4uLg==")
```

Overrides take priority over every mode.  If an override is set but
points to a missing file, you get a warning and fall back to the
configured `resource_mode` strategy.


## `inline` mode (quick-and-dirty)

If you just want a self-contained HTML file and don't need reproducible
builds:

```python
folium.set_resource_mode("inline")
m = folium.Map()
# ... add plugins ...
m.save("self_contained.html")
```

Every resource is downloaded **at render time** and inlined into
`<script>`/`<style>` tags.  This can make `save()` slow, and it won't
work in air-gapped environments.


## `local` mode (simple local cache)

If you maintain a directory of JS/CSS files but don't need checksum
validation:

```python
folium.set_resource_mode("local", local_path="/path/to/cached/resources")
m = folium.Map()
m.save("report.html")
```

Files are looked up by filename (extracted from the original CDN URL).
If a file is missing, a warning is emitted and folium falls back to
CDN.  For strict behaviour use `manifest` mode instead.
