"""
Offline map example for the folium-resource CLI workflow.

Use this file as input to the CLI:

    # Step 1 – collect
    folium-resource collect examples/offline_map.py \
        --manifest resources/manifest.json \
        --dir resources/

    # Step 2 – download
    folium-resource download resources/manifest.json \
        --dir resources/ --retries 8

    # Step 3 – verify (optional)
    folium-resource verify resources/manifest.json --dir resources/

Then in your code:

    folium.set_resource_mode("manifest", manifest_path="resources/manifest.json")
    m = build_map()
    m.save("offline_report.html")
"""

import folium
from folium.plugins import Fullscreen, HeatMap


def build_map():
    m = folium.Map(location=[45.5, -122.7], zoom_start=10)
    Fullscreen().add_to(m)
    HeatMap([[45.5, -122.7, 1.0], [45.6, -122.8, 0.5]]).add_to(m)
    return m


if __name__ == "__main__":
    m = build_map()
    print(f"Map ready with location {m.location}")

