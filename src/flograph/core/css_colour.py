"""The colour written at a place in a stylesheet, and that colour written
back in the same notation — what the CSS tab's colour picker reads and
writes (ui/report/css_colour_pick.py).

Qt-free: a colour is (r, g, b, a) with each in 0..255.

A token only counts where a value goes. `#add` is a colour in
`color: #add` and an id in `#add { … }`; `red` is a colour in
`border: 1px solid red` and a class's tail in `.fg-red`. So a token is a
colour when the nearest of `{ } ; :` before it is a `:` and the nearest of
`{ } ;` after it is not a `{` — after a property name, and not in a
selector (`a:hover #add {` has a `:` behind it, but a `{` ahead).
"""
from __future__ import annotations

import colorsys
import re
from typing import NamedTuple, Optional

#: CSS's named colours (CSS Color 4), as #rrggbb.
NAMED = {
    "aliceblue": "f0f8ff", "antiquewhite": "faebd7", "aqua": "00ffff",
    "aquamarine": "7fffd4", "azure": "f0ffff", "beige": "f5f5dc",
    "bisque": "ffe4c4", "black": "000000", "blanchedalmond": "ffebcd",
    "blue": "0000ff", "blueviolet": "8a2be2", "brown": "a52a2a",
    "burlywood": "deb887", "cadetblue": "5f9ea0", "chartreuse": "7fff00",
    "chocolate": "d2691e", "coral": "ff7f50", "cornflowerblue": "6495ed",
    "cornsilk": "fff8dc", "crimson": "dc143c", "cyan": "00ffff",
    "darkblue": "00008b", "darkcyan": "008b8b", "darkgoldenrod": "b8860b",
    "darkgray": "a9a9a9", "darkgreen": "006400", "darkgrey": "a9a9a9",
    "darkkhaki": "bdb76b", "darkmagenta": "8b008b",
    "darkolivegreen": "556b2f", "darkorange": "ff8c00",
    "darkorchid": "9932cc", "darkred": "8b0000", "darksalmon": "e9967a",
    "darkseagreen": "8fbc8f", "darkslateblue": "483d8b",
    "darkslategray": "2f4f4f", "darkslategrey": "2f4f4f",
    "darkturquoise": "00ced1", "darkviolet": "9400d3",
    "deeppink": "ff1493", "deepskyblue": "00bfff", "dimgray": "696969",
    "dimgrey": "696969", "dodgerblue": "1e90ff", "firebrick": "b22222",
    "floralwhite": "fffaf0", "forestgreen": "228b22", "fuchsia": "ff00ff",
    "gainsboro": "dcdcdc", "ghostwhite": "f8f8ff", "gold": "ffd700",
    "goldenrod": "daa520", "gray": "808080", "green": "008000",
    "greenyellow": "adff2f", "grey": "808080", "honeydew": "f0fff0",
    "hotpink": "ff69b4", "indianred": "cd5c5c", "indigo": "4b0082",
    "ivory": "fffff0", "khaki": "f0e68c", "lavender": "e6e6fa",
    "lavenderblush": "fff0f5", "lawngreen": "7cfc00",
    "lemonchiffon": "fffacd", "lightblue": "add8e6", "lightcoral": "f08080",
    "lightcyan": "e0ffff", "lightgoldenrodyellow": "fafad2",
    "lightgray": "d3d3d3", "lightgreen": "90ee90", "lightgrey": "d3d3d3",
    "lightpink": "ffb6c1", "lightsalmon": "ffa07a",
    "lightseagreen": "20b2aa", "lightskyblue": "87cefa",
    "lightslategray": "778899", "lightslategrey": "778899",
    "lightsteelblue": "b0c4de", "lightyellow": "ffffe0", "lime": "00ff00",
    "limegreen": "32cd32", "linen": "faf0e6", "magenta": "ff00ff",
    "maroon": "800000", "mediumaquamarine": "66cdaa",
    "mediumblue": "0000cd", "mediumorchid": "ba55d3",
    "mediumpurple": "9370db", "mediumseagreen": "3cb371",
    "mediumslateblue": "7b68ee", "mediumspringgreen": "00fa9a",
    "mediumturquoise": "48d1cc", "mediumvioletred": "c71585",
    "midnightblue": "191970", "mintcream": "f5fffa", "mistyrose": "ffe4e1",
    "moccasin": "ffe4b5", "navajowhite": "ffdead", "navy": "000080",
    "oldlace": "fdf5e6", "olive": "808000", "olivedrab": "6b8e23",
    "orange": "ffa500", "orangered": "ff4500", "orchid": "da70d6",
    "palegoldenrod": "eee8aa", "palegreen": "98fb98",
    "paleturquoise": "afeeee", "palevioletred": "db7093",
    "papayawhip": "ffefd5", "peachpuff": "ffdab9", "peru": "cd853f",
    "pink": "ffc0cb", "plum": "dda0dd", "powderblue": "b0e0e6",
    "purple": "800080", "rebeccapurple": "663399", "red": "ff0000",
    "rosybrown": "bc8f8f", "royalblue": "4169e1", "saddlebrown": "8b4513",
    "salmon": "fa8072", "sandybrown": "f4a460", "seagreen": "2e8b57",
    "seashell": "fff5ee", "sienna": "a0522d", "silver": "c0c0c0",
    "skyblue": "87ceeb", "slateblue": "6a5acd", "slategray": "708090",
    "slategrey": "708090", "snow": "fffafa", "springgreen": "00ff7f",
    "steelblue": "4682b4", "tan": "d2b48c", "teal": "008080",
    "thistle": "d8bfd8", "tomato": "ff6347", "turquoise": "40e0d0",
    "violet": "ee82ee", "wheat": "f5deb3", "white": "ffffff",
    "whitesmoke": "f5f5f5", "yellow": "ffff00", "yellowgreen": "9acd32",
}

_NUM = r"[+-]?(?:\d+\.?\d*|\.\d+)"
_TOKEN = re.compile(
    r"#[0-9a-fA-F]{3,8}\b"
    r"|\b(?:rgba?|hsla?)\(\s*[^()]*\)"
    r"|(?<![\w-])[a-zA-Z]+(?![\w-])")
_FUNC = re.compile(r"(rgba?|hsla?)\(\s*(.*?)\s*\)\Z", re.I | re.S)


class Colour(NamedTuple):
    start: int            # where the token starts in the text
    end: int              # and ends (exclusive)
    text: str             # the token as written
    rgba: tuple           # (r, g, b, a), 0..255


def colour_at(text: str, offset: int) -> Optional[Colour]:
    """The colour token `offset` is in (or at either end of), or None."""
    line_start = text.rfind("\n", 0, offset) + 1
    line_end = text.find("\n", offset)
    line_end = len(text) if line_end < 0 else line_end
    for match in _TOKEN.finditer(text, line_start, line_end):
        start, end = match.span()
        if start > offset:
            break
        if offset > end:
            continue
        rgba = parse(match.group(0))
        if rgba is not None and _in_value(text, start, end):
            return Colour(start, end, match.group(0), rgba)
    return None


def _in_value(text: str, start: int, end: int) -> bool:
    if _in_comment(text, start):
        return False
    back = max(text.rfind(c, 0, start) for c in "{};:")
    if back < 0 or text[back] != ":":
        return False
    ahead = [i for i in (text.find(c, end) for c in "{};") if i >= 0]
    return not ahead or text[min(ahead)] != "{"


def _in_comment(text: str, at: int) -> bool:
    return text.rfind("/*", 0, at) > text.rfind("*/", 0, at)


def parse(token: str) -> Optional[tuple]:
    """(r, g, b, a) for a CSS colour token, or None if it is not one."""
    token = token.strip()
    if token.startswith("#"):
        digits = token[1:]
        if len(digits) in (3, 4):
            digits = "".join(c * 2 for c in digits)
        if len(digits) not in (6, 8):
            return None
        try:
            values = [int(digits[i:i + 2], 16) for i in range(0, len(digits), 2)]
        except ValueError:
            return None
        return tuple(values + [255] * (4 - len(values)))
    named = NAMED.get(token.lower())
    if named is not None:
        return parse("#" + named)
    match = _FUNC.match(token)
    if match is None:
        return None
    kind = match.group(1).lower()
    parts = [p for p in re.split(r"[\s,/]+", match.group(2)) if p]
    if len(parts) not in (3, 4):
        return None
    try:
        alpha = _alpha(parts[3]) if len(parts) == 4 else 255
        if kind.startswith("rgb"):
            r, g, b = (_channel(p) for p in parts[:3])
        else:
            h = float(re.sub(r"deg\Z", "", parts[0], flags=re.I)) % 360
            s, light = (_percent(p) for p in parts[1:3])
            red, green, blue = colorsys.hls_to_rgb(h / 360, light, s)
            r, g, b = (round(v * 255) for v in (red, green, blue))
    except ValueError:
        return None
    return (r, g, b, alpha)


def _channel(part: str) -> int:
    if part.endswith("%"):
        return _clamp(round(float(part[:-1]) * 2.55))
    if not re.fullmatch(_NUM, part):
        raise ValueError(part)
    return _clamp(round(float(part)))


def _percent(part: str) -> float:
    if not part.endswith("%"):
        raise ValueError(part)
    return max(0.0, min(1.0, float(part[:-1]) / 100))


def _alpha(part: str) -> int:
    value = float(part[:-1]) / 100 if part.endswith("%") else float(part)
    return _clamp(round(value * 255))


def _clamp(value: int) -> int:
    return max(0, min(255, value))


def write_like(token: str, rgba: tuple) -> str:
    """`rgba` written the way `token` was. A hex stays hex in its own case
    (eight digits only when it has to carry transparency); `rgb()` and
    `hsl()` keep their function and their comma or space style — with
    commas a transparent colour is `rgba(r, g, b, a)`, without them
    `rgb(r g b / a)`; a named colour becomes hex, since a picked colour
    rarely has a name."""
    r, g, b, a = rgba
    match = _FUNC.match(token.strip())
    if match is None:
        out = f"#{r:02x}{g:02x}{b:02x}" + (f"{a:02x}" if a < 255 else "")
        return out.upper() if token[1:].isupper() else out
    kind = match.group(1).lower()[:3]
    if kind == "rgb":
        values = [str(r), str(g), str(b)]
    else:
        h, light, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
        values = [str(round(h * 360)), f"{round(s * 100)}%",
                  f"{round(light * 100)}%"]
    if "," in match.group(2):
        if a < 255:
            return f"{kind}a({', '.join(values + [_alpha_text(a)])})"
        return f"{kind}({', '.join(values)})"
    tail = f" / {_alpha_text(a)}" if a < 255 else ""
    return f"{kind}({' '.join(values)}{tail})"


def _alpha_text(a: int) -> str:
    return f"{a / 255:.2f}".rstrip("0").rstrip(".") or "0"
