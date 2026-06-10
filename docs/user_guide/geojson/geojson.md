```{code-cell} ipython3
---
nbsphinx: hidden
---
import folium
```

## Using `GeoJson`

### Loading data

Let us load a GeoJSON file representing the US states.

```{code-cell} ipython3
import requests

geo_json_data = requests.get(
    "https://raw.githubusercontent.com/python-visualization/folium-example-data/main/us_states.json"
).json()
```

It is a classical GeoJSON `FeatureCollection` (see https://en.wikipedia.org/wiki/GeoJSON) of the form :

    {
        "type": "FeatureCollection",
        "features": [
            {
                "properties": {"name": "Alabama"},
                "id": "AL",
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[-87.359296, 35.00118], ...]]
                    }
                },
            {
                "properties": {"name": "Alaska"},
                "id": "AK",
                "type": "Feature",
                "geometry": {
                    "type": "MultiPolygon",
                    "coordinates": [[[[-131.602021, 55.117982], ... ]]]
                    }
                },
            ...
            ]
        }

A first way of drawing it on a map, is simply to use `folium.GeoJson` :

```{code-cell} ipython3
m = folium.Map([43, -100], zoom_start=4)

folium.GeoJson(geo_json_data).add_to(m)

m
```

Note that you can avoid loading the file on yourself,
by providing a (local) file path or a url.

```{code-cell} ipython3
m = folium.Map([43, -100], zoom_start=4)

url = "https://raw.githubusercontent.com/python-visualization/folium-example-data/main/us_states.json"

folium.GeoJson(url).add_to(m)

m
```

You can pass a geopandas object.

```{code-cell} ipython3
import geopandas

gdf = geopandas.read_file(url)

m = folium.Map([43, -100], zoom_start=4)

folium.GeoJson(
    gdf,
).add_to(m)

m
```

### Click on zoom

You can enable an option that if you click on a part of the geometry the map will zoom in to that.

Try it on the map below:

```{code-cell} ipython3
m = folium.Map([43, -100], zoom_start=4)

folium.GeoJson(geo_json_data, zoom_on_click=True).add_to(m)

m
```

### Styling

Now this is cool and simple, but we may be willing to choose the style of the data.

You can provide a function of the form `lambda feature: {}` that sets the style of each feature.

For possible options, see:

* For `Point` and `MultiPoint`, see https://leafletjs.com/reference.html#marker
* For other features, see https://leafletjs.com/reference.html#path and https://leafletjs.com/reference.html#polyline

```{code-cell} ipython3
m = folium.Map([43, -100], zoom_start=4)

folium.GeoJson(
    geo_json_data,
    style_function=lambda feature: {
        "fillColor": "#ffff00",
        "color": "black",
        "weight": 2,
        "dashArray": "5, 5",
    },
).add_to(m)

m
```

What's cool in providing a function, is that you can specify a style depending on the feature. For example, if you want to visualize in green all states whose name contains the letter 'E', just do:

```{code-cell} ipython3
m = folium.Map([43, -100], zoom_start=4)

folium.GeoJson(
    geo_json_data,
    style_function=lambda feature: {
        "fillColor": "green"
        if "e" in feature["properties"]["name"].lower()
        else "#ffff00",
        "color": "black",
        "weight": 2,
        "dashArray": "5, 5",
    },
).add_to(m)

m
```

Wow, this looks almost like a choropleth. To do one, we just need to compute a color for each state.

Let's imagine we want to draw a choropleth of unemployment in the US.

First, we may load the data:

```{code-cell} ipython3
import pandas

unemployment = pandas.read_csv(
    "https://raw.githubusercontent.com/python-visualization/folium-example-data/main/us_unemployment_oct_2012.csv"
)

unemployment.head(5)
```

Now we need to create a function that maps one value to a RGB color (of the form `#RRGGBB`).
For this, we'll use colormap tools from `folium.colormap`.

```{code-cell} ipython3
from branca.colormap import linear

colormap = linear.YlGn_09.scale(
    unemployment.Unemployment.min(), unemployment.Unemployment.max()
)

print(colormap(5.0))

colormap
```

We need also to convert the table into a dictionary, in order to map a feature to it's unemployment value.

```{code-cell} ipython3
unemployment_dict = unemployment.set_index("State")["Unemployment"]

unemployment_dict["AL"]
```

Now we can do the choropleth.

```{code-cell} ipython3
m = folium.Map([43, -100], zoom_start=4)

folium.GeoJson(
    geo_json_data,
    name="unemployment",
    style_function=lambda feature: {
        "fillColor": colormap(unemployment_dict[feature["id"]]),
        "color": "black",
        "weight": 1,
        "dashArray": "5, 5",
        "fillOpacity": 0.9,
    },
).add_to(m)

folium.LayerControl().add_to(m)

m
```

Of course, if you can create and/or use a dictionary providing directly the good color. Thus, the finishing seems faster:

```{code-cell} ipython3
color_dict = {key: colormap(unemployment_dict[key]) for key in unemployment_dict.keys()}
```

```{code-cell} ipython3
m = folium.Map([43, -100], zoom_start=4)

folium.GeoJson(
    geo_json_data,
    style_function=lambda feature: {
        "fillColor": color_dict[feature["id"]],
        "color": "black",
        "weight": 1,
        "dashArray": "5, 5",
        "fillOpacity": 0.9,
    },
).add_to(m)
```

Note that adding a color legend may be a good idea.

```{code-cell} ipython3
colormap.caption = "Unemployment color scale"
colormap.add_to(m)

m
```

>
> **Caveat**
>
> When using `style_function` in a loop you may encounter Python's 'Late Binding Closure' gotcha!
> See https://docs.python-guide.org/writing/gotchas/#late-binding-closures for more info.
> There are a few ways around it from using a GeoPandas object instead,
> to "hacking" your `style_function` to force early closure, like:
> ```python
> for geom, my_style in zip(geoms, my_styles):
>     style = my_style
>     style_function = lambda x, style=style: style
>     folium.GeoJson(
>         data=geom,
>         style_function=style_function,
>     ).add_to(m)
> ```

### Highlight function

The `GeoJson` class provides a `highlight_function` argument, which works similarly
to `style_function`, but applies on mouse events. In the following example
the fill color will change when you hover your mouse over a feature.

```{code-cell} ipython3
m = folium.Map([43, -100], zoom_start=4)

folium.GeoJson(
    geo_json_data,
    highlight_function=lambda feature: {
        "fillColor": (
            "green" if "e" in feature["properties"]["name"].lower() else "#ffff00"
        ),
    },
).add_to(m)

m
```

#### Keep highlighted while popup is open

The `GeoJson` class provides a `popup_keep_highlighted` boolean argument.
Whenever a GeoJson layer is associated with a popup and a highlight function
is defined, this argument allows you to decide if the highlighting should remain
active while the popup is open.

```{code-cell} ipython3
m = folium.Map([43, -100], zoom_start=4)

popup = folium.GeoJsonPopup(fields=["name"])

folium.GeoJson(
    geo_json_data,
    highlight_function=lambda feature: {
        "fillColor": (
            "green" if "e" in feature["properties"]["name"].lower() else "#ffff00"
        ),
    },
    popup=popup,
    popup_keep_highlighted=True,
).add_to(m)

m
```

### 事件绑定 (Event Binding)

`GeoJson` 支持两级事件绑定，因为一个 GeoJson 图层可以包含多个 feature：

- **Feature 级**（`feature_events`）：事件绑定到每一个 feature，每个州/点/多边形各自响应点击、悬停等
- **Layer 级**（`layer_events`）：事件绑定到整个 GeoJson 图层，适合监听 `layeradd`、`layerremove` 等生命周期事件

示例：点击每个 feature 弹出它的属性信息，悬停时高亮：

```{code-cell} ipython3
m = folium.Map([43, -100], zoom_start=4)

folium.GeoJson(
    geo_json_data,
    feature_events={
        "click": "alert",
        "mouseover": "highlight",
        "mouseout": "reset_highlight",
    },
    layer_events={
        "layeradd": "log",
    },
).add_to(m)

m
```

> **向后兼容提示**：旧代码使用 `events` 参数（如 `events={"click": "alert"}`）仍然有效，它是 `feature_events` 的别名。为了代码语义更清晰，推荐使用显式的 `feature_events` / `layer_events`。不要同时传两者，否则会抛出 `ValueError`。

有关事件绑定的完整说明（支持的事件列表、处理器格式、与 `add_child(EventHandler)` 的关系等），请参见 [事件绑定](../features/event_binding.md) 文档。
