import cv2
class PageFilter:
    def __init__(self, considered_pages: set) -> None:
        self.considered_pages = considered_pages

    def consider_page(self, page: int) -> bool:
        return len(self.considered_pages) == 0 or page in self.considered_pages

    def filter_page(self, page: int, values: cv2.typing.MatLike ) -> bool:
        return self.consider_page(page)
