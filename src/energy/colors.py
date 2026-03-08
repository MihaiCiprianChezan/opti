from dataclasses import dataclass


class CustomColors(type):
    def __getattribute__(cls, name):
        value = super().__getattribute__(name)
        if isinstance(value, Color):
            return value.as_dict
        return value


@dataclass
class Color:
    """
    Represents a color using RGBA (Red, Green, Blue, Alpha) components.

    This class provides a way to store and manipulate color information,
    including its red, green, blue, and alpha channel values. The alpha
    channel has a default value of 92. Additionally, the class offers
    a property to retrieve this color data in dictionary form.

    Attributes:
        r (int): The red component of the color.
        g (int): The green component of the color.
        b (int): The blue component of the color.
        a (int): The alpha component of the color, with a default value of 92.
    """

    r: int
    g: int
    b: int
    a: int = 92  # Default alpha value

    @property
    def as_dict(self):
        return {"color": (self.r, self.g, self.b, self.a)}


class Colors(metaclass=CustomColors):
    # Basic colors
    red = Color(255, 0, 0, 92)
    blue = Color(0, 10, 255, 92)
    green = Color(0, 255, 0, 92)
    yellow = Color(220, 220, 0, 92)
    bright_yellow = Color(255, 255, 100)
    magenta = Color(255, 0, 255, 92)
    grey = Color(100, 100, 100, 92)
    orange = Color(200, 100, 0, 92)
    brown = Color(255, 100, 50, 92)
    pink = Color(255, 200, 100, 92)
    cyan = Color(0, 255, 255, 92)
    lime = Color(125, 255, 0, 92)
    purple = Color(115, 0, 255, 92)
    turquoise = Color(0, 255, 255, 92)
    dark_grey = Color(50, 50, 50, 100)
    light_grey = Color(200, 200, 200, 92)
    transparent = Color(0, 0, 0, 0)

    # Semantic colors - direct references to basic colors
    hello = yellow
    generating = magenta
    speaking = cyan
    operating_text = yellow
    initial = transparent
    profanity = red
    uncertain = orange
    paused = light_grey
    translate = blue
