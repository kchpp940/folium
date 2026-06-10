from branca.element import MacroElement

from folium.template import Template
from folium.utilities import image_to_url


class FloatImage(MacroElement):
    """Adds a floating image in HTML canvas on top of the map.

    Parameters
    ----------
    image: str, PathLike, or array-like object
        The image to display.

        * If string is a path to an image file and the file exists,
          its content will be converted and embedded.
        * If PathLike object, it will be treated as a file path and
          its content will be converted and embedded.
        * If string is a URL, it will be linked.
        * Otherwise a string will be assumed to be raw content and embedded.
        * If array-like, it will be converted to PNG base64 string and embedded.
    bottom: int, default 75
        Vertical position from the bottom, as a percentage of screen height.
    left: int, default 75
        Horizontal position from the left, as a percentage of screen width.
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
                 src="{{ this.url }}"
                 style="z-index: 999999">
            </img>
            {% endmacro %}
            """)

    def __init__(self, image, bottom=75, left=75, **kwargs):
        super().__init__()
        self._name = "FloatImage"
        self.url = image_to_url(image)
        self.bottom = bottom
        self.left = left
        self.css = kwargs
