```{code-cell} ipython3
---
nbsphinx: hidden
---
import folium
```

# 事件绑定 (Event Binding)

Folium 提供了一套统一的事件绑定 API，让你可以通过 Python 参数声明 Leaflet 的交互事件（`click`、`mouseover`、`mouseout`、`dblclick` 等），无需手动注入 JavaScript。

## 快速参考

| 图层类型 | 参数名 | 绑定级别 | Leaflet 绑定方式 |
|----------|--------|----------|------------------|
| Circle, CircleMarker, Polygon, Polyline, Rectangle, RegularPolygonMarker, Marker | `events` | 图层本身（唯一级别） | `{layer}.on(event, handler)` |
| GeoJson | `feature_events` | **每个 feature** | `onEachFeature` 回调内 `layer.on({...})` |
| GeoJson | `layer_events` | **整个 GeoJson 图层** | `{geojson_layer}.on(event, handler)` |
| GeoJson | `events` | 每个 feature（`feature_events` 的别名，向后兼容） | 同上 |

## 普通矢量图层（Circle、Polygon 等）

对于 Circle、CircleMarker、Polygon、Polyline、Rectangle、Marker、RegularPolygonMarker 这类"单个对象"图层，使用 `events` 参数即可：

```{code-cell} ipython3
m = folium.Map(location=[45.5, -122.3], zoom_start=10)

folium.Circle(
    location=[45.5, -122.3],
    radius=1000,
    events={
        "click": "alert",          # 预定义动作：弹出事件信息
        "mouseover": "highlight",  # 预定义动作：高亮
        "mouseout": "reset_highlight",
    },
).add_to(m)

folium.Polygon(
    locations=[[45.51, -122.68], [37.77, -122.43], [34.04, -118.2]],
    events={
        "click": "zoom",           # 预定义动作：缩放到该图层
    },
).add_to(m)

m
```

## 三种事件处理器格式

`events`（以及 GeoJson 的 `feature_events` / `layer_events`）的值支持三种格式：

### 1. 全局 JS 函数名（字符串）

```{code-cell} ipython3
# 你的 HTML 中已定义的全局函数
events = {
    "click": "myApp.onCircleClick",
    "mouseover": "UI.highlightLayer",
}
```

### 2. 内联 JS 函数体

可以是字符串，也可以是 `folium.JsCode` 对象：

```{code-cell} ipython3
from folium import JsCode

events = {
    "click": "function(e) { console.log('clicked at', e.latlng); }",
    "dblclick": JsCode("function(e) { alert('Double clicked!'); }"),
}
```

### 3. 预定义动作

Folium 内置了几个常用动作，直接用名字即可：

| 动作名 | 效果 |
|--------|------|
| `"zoom"` | 将地图缩放到该图层 |
| `"alert"` | 弹出事件信息（`e` 对象 JSON） |
| `"log"` | 在浏览器控制台打印事件信息 |
| `"highlight"` | 将图层边框加粗为 5px 红色 |
| `"reset_highlight"` | 恢复 highlight 之前的样式 |
| `"open_popup"` | 打开该图层绑定的 Popup |
| `"close_popup"` | 关闭该图层绑定的 Popup |

可以通过 `folium.PREDEFINED_EVENT_ACTIONS` 查看所有预定义动作。

## GeoJson：两级事件绑定

GeoJson 比较特殊——它由**多个 feature 组成**，所以事件可以绑定到两个不同的级别：

### Feature 级事件（`feature_events`）

绑定到 GeoJson 中的**每一个 feature**（每个州、每个点等）。这是最常用的模式：

```{code-cell} ipython3
import json

geojson_data = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [-122.6, 45.5], [-122.2, 45.5],
                    [-122.2, 45.7], [-122.6, 45.7],
                    [-122.6, 45.5],
                ]],
            },
            "properties": {"name": "Portland Area"},
        },
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-122.6765, 45.5231]},
            "properties": {"name": "Portland"},
        },
    ],
}
```

```{code-cell} ipython3
m = folium.Map(location=[45.6, -122.4], zoom_start=9)

folium.GeoJson(
    geojson_data,
    feature_events={
        "click": "alert",        # 每一个 feature 被点击时都弹出其属性
        "mouseover": "highlight",
        "mouseout": "reset_highlight",
    },
).add_to(m)

m
```

### Layer 级事件（`layer_events`）

绑定到 GeoJson **图层整体**，而不是单个 feature。适合监听 `layeradd`、`layerremove` 这类图层生命周期事件：

```{code-cell} ipython3
m = folium.Map(location=[45.6, -122.4], zoom_start=9)

folium.GeoJson(
    geojson_data,
    layer_events={
        "layeradd": "log",       # 当 GeoJson 图层被添加到地图时
        "layerremove": "log",    # 当 GeoJson 图层被移除时
    },
).add_to(m)

m
```

### 同时使用两级事件

可以同时设置 `feature_events` 和 `layer_events`，互不干扰：

```{code-cell} ipython3
m = folium.Map(location=[45.6, -122.4], zoom_start=9)

folium.GeoJson(
    geojson_data,
    feature_events={
        "click": "function(e) { console.log(e.target.feature); }",
    },
    layer_events={
        "layeradd": "log",
    },
).add_to(m)

m
```

## 旧 `events` 参数的兼容性

在引入显式的 `feature_events` / `layer_events` 之前，GeoJson 使用 `events` 作为参数名，绑定到 feature 级。

这个用法**仍然可用**，`events` 是 `feature_events` 的向后兼容别名：

```{code-cell} ipython3
# 这行和 feature_events={"click": "alert"} 效果完全相同
folium.GeoJson(geojson_data, events={"click": "alert"})
```

> **注意**：不要同时传 `events` 和 `feature_events`，否则会抛出 `ValueError`。请二选一，推荐使用新名字 `feature_events`，语义更清晰。

## 与 `add_child(EventHandler(...))` 的关系

Folium 的旧 API 允许通过以下方式绑定事件：

```python
from folium.elements import EventHandler

circle = folium.Circle(location=[0, 0])
circle.add_child(EventHandler("click", "myHandler"))
```

现在这种方式**仍然有效**，但内部实现已经统一：`add_child(EventHandler)` 会被自动"吸收"到图层的 `_event_handlers` 字典中，与通过 `events={...}` 参数设置的事件走同一条渲染路径。

### 去重规则

如果同一事件名通过两种方式都被设置了，会保留**先设置的那个**，并发出 `UserWarning` 提示：

```{code-cell} ipython3
---
nbsphinx: hidden
---
import warnings
```

```{code-cell} ipython3
from folium.elements import EventHandler
from folium import JsCode

c = folium.Circle(
    location=[45.5, -122.3],
    radius=1000,
    events={"click": "alert"},   # 先通过 events= 设置
)

with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter("always")
    c.add_child(EventHandler("click", JsCode("function(e) { console.log(e); }")))
    # ⚠️ UserWarning: Event 'click' already set via `events` parameter. ...
    print("Warning message:", str(w[0].message))
```

结果：只绑定 `"alert"` 动作，`EventHandler` 中的 handler 被忽略。

## 程序化管理事件

除了通过构造函数参数，还可以在创建后动态增删事件：

```{code-cell} ipython3
c = folium.Circle(location=[0, 0], radius=100)

# 添加事件
c.set_event("click", "alert")
c.set_event("mouseover", "log")

# 查询
assert c.has_events() is True
assert c.get_event("click") is not None

# 移除单个
c.remove_event("mouseover")

# 清空所有
c.clear_events()
```

GeoJson 的 layer 级事件有对应的专用方法：

```{code-cell} ipython3
---
nbsphinx: hidden
---
geojson_layer = folium.GeoJson(geojson_data)
```

```python
geojson_layer.set_layer_event("layeradd", "log")
geojson_layer.has_layer_events()       # True
geojson_layer.get_layer_event("layeradd")
geojson_layer.remove_layer_event("layeradd")
geojson_layer.clear_layer_events()
```

## 支持的事件列表

Folium 默认支持以下 Leaflet 事件名：

- `click`, `dblclick`, `mousedown`, `mouseup`
- `mouseover`, `mouseout`, `mousemove`, `contextmenu`
- `focus`, `blur`, `preclick`
- `add`, `remove`
- `popupopen`, `popupclose`, `tooltipopen`, `tooltipclose`

如果传入不在列表中的事件名，会抛出 `ValueError`。可以用 `folium.validate_events()` 在运行前校验：

```{code-cell} ipython3
folium.validate_events({"click": "alert"})   # OK, no exception
```

```{code-cell} ipython3
---
nbsphinx: hidden
---
# Don't actually run the error case
```

```python
folium.validate_events({"custom_event": "alert"})
# ValueError: Unsupported event: 'custom_event'. Supported events: [...]
```
