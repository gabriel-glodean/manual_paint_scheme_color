import re
from collections_extended import RangeMap

from typing import Tuple, Any

Color = Tuple[int, int, int]


def parse_color_ranges(s: str) -> RangeMap:
    pattern = r"#([0-9A-Fa-f]{6})\s*\((\d+)\s*-\s*(\d+)\)"
    ranges = RangeMap()
    for  hex_color, gray_min, gray_max in re.findall(pattern, s):
        hc = hex_color.lstrip("#")
        r = int(hc[0:2], 16)
        g = int(hc[2:4], 16)
        b = int(hc[4:6], 16)
        ranges.set((b, g, r), int(gray_min), int(gray_max))
    return ranges

def lookup_with_default(range_map: Any, key: int, default: Color) -> Color:
    return range_map.get(key, default)

def parse_page_list(s: str) -> set[int]:
    return set(int(item)-1  for item in  s.split(",") if item.isdecimal())