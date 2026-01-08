import cv2
import pytesseract

from logic.page_filter import PageFilter
from logic.paint_detection import is_painting_page

def _ocr_page_image(img) -> str:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)

    # simple threshold often helps OCR on scans
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    ret =  pytesseract.image_to_string(bw, lang="eng")
    return ret

class OcrPageFilter(PageFilter):
    def __init__(self, considered_pages: set, threshold : int) -> None:
        super().__init__(considered_pages)
        self.threshold = threshold

    def filter_page(self, page: int, values: cv2.typing.MatLike ) -> bool:
        return self.consider_page(page) and (self.threshold < 0 or is_painting_page(values, _ocr_page_image, self.threshold))