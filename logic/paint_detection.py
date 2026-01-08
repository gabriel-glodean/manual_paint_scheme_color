import re
from typing import Callable, Any

PAINT_PATTERNS = [
    r"RLM ?\d+",
    r"FS ?\d+",
    r"XF-\d\d?",
    r"X-\d\d?",
    r"H-\d\d\d?",
    r"C-\d\d\d?",
    r"RAL ?\d+",
]

PAINT_KEYWORDS = [
    "paint",
    "color",
    "colour"
    "painting",
    "scheme",
    "camouflage",
    "marking",
    "decal",
    "decals",
    "stencil",
    "regiment",
    "division",
    "unknown",
    "rgt",
    "div"
]

def find_paint_codes(text: str) -> set[str]:
    codes = set()
    for pattern in PAINT_PATTERNS:
        for m in re.findall(pattern, text, flags=re.IGNORECASE):
            code = m.upper().replace("  ", " ").strip()
            codes.add(code)
    return codes

def count_paint_keywords(text: str) -> int:
    tl = text.lower()
    return sum(1 if tl.count(k) > 0 else 0   for k in PAINT_KEYWORDS)


def score_painting_page(text:str) -> dict:
    """
    Returns a dict with:
      - text
      - codes
      - keyword_count
      - score
    """
    codes = find_paint_codes(text)
    kw_count = count_paint_keywords(text)

    # simple scoring: each paint code is strong evidence
    score = len(codes) + kw_count

    return {
        "text": text,
        "codes": codes,
        "keyword_count": kw_count,
        "score": score,
    }

def is_painting_page(img, transformer: Callable[[Any], str], score_threshold: int = 5) -> bool :
    """
    Check if a page is a likely painting guide
    """
    info = score_painting_page(transformer(img))
    return  info["score"] >= score_threshold