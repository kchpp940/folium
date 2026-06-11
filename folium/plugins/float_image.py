from typing import Optional, Union

from branca.element import MacroElement

from folium.elements import CaptionMixin, LayerMetadata
from folium.template import Template


class FloatImage(CaptionMixin, MacroElement):
    """Adds a floating image in HTML canvas on top of the map.

    Parameters
    ----------
    image: str
        Url to image location. Can also be an inline image using a data URI
        or a local file using `file://`.
    bottom: int, default 75
        Vertical position from the bottom, as a percentage of screen height.
    left: int, default 75
        Horizontal position from the left, as a percentage of screen width.
    caption: dict or LayerMetadata, optional
        Metadata and legend caption for the float image.
        See folium.raster_layers.ImageOverlay for the full list of supported keys.
        Parameter accepts both LayerMetadata TypedDict or plain dict.
    **kwargs
        Additional keyword arguments are applied as CSS properties.
        For example: `width='300px'`.

    """

    _template = Template("""
            {% macro header(this,kwargs) %}
                <style>
                    #{{this.get_name()}} {
                        position: absolute;
                        bottom: {{this.bottom}}%;
                        left: {{this.left}}%;
                        {%- for property, value in this.css.items() %}
                          {{ property }}: {{ value }};
                        {%- endfor %}
                        }
                </style>
            {% endmacro %}

            {% macro html(this,kwargs) %}
            <img id="{{this.get_name()}}" alt="float_image"
                 src="{{ this.image }}"
                 style="z-index: 999999">
            </img>
            {% endmacro %}
            """)

    def __init__(
        self,
        image,
        bottom=75,
        left=75,
        caption: Optional[Union[LayerMetadata, dict]] = None,
        **kwargs,
    ):
        super().__init__()
        self._name = "FloatImage"
        self.image = image
        self.bottom = bottom
        self.left = left
        self.css = kwargs
        self._init_caption(caption, show=True)
