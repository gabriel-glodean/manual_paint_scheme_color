import fitz
import concurrent.futures
import numpy as np
import cv2
import time

from .file_repo import ImageFileRepository
from .page_filter import PageFilter
from .utils import log_exec_time
from .vehicle_extractor import vehicle_to_images


# Helper: convert page -> cv2 image
@log_exec_time
def render_page_to_cv2(pdf_bytes, page_number, dpi=250):
    # Must open doc inside thread
    print(f"Rendering page {page_number+1}...")

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = doc.load_page(page_number)

    pix = page.get_pixmap(dpi=dpi)

    # Use a supported format for PyMuPDF, then convert to WEBP with OpenCV
    img_bytes = pix.tobytes("png")
    arr = np.frombuffer(img_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    # Return the decoded image (cv2 Mat), not the encoded WEBP buffer
    return img


# Helper for process pool: must be top-level for pickling
def process_page_worker(args):
    b, d, p, page_filter, out_repo = args
    rendered = render_page_to_cv2(b, p, d)
    if page_filter.filter_page(p, rendered):
       return p, vehicle_to_images(rendered, out_repo, p)
    return p, None


def process_pdf_in_parallel(pdf_bytes, out_repo: ImageFileRepository, page_filter: PageFilter, dpi=250):
    start_time = time.perf_counter()
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    n = doc.page_count
    elapsed = time.perf_counter() - start_time
    print(f"[timing] Processing {n} pages, page count taken {elapsed:.6f} seconds...")
    results = [None] * n
    # Prepare args for only pages that pass consider_page
    page_args = [(pdf_bytes, dpi, i, page_filter, out_repo) for i in range(n) if page_filter.consider_page(i)]

    rendered = 0
    start_time = time.perf_counter()
    # Use the global executor
    with concurrent.futures.ThreadPoolExecutor(max_workers=32) as executor:
        for page_number, img in executor.map(process_page_worker, page_args):
            if img is not None:
                results[page_number] = img
                rendered += 1
    elapsed = time.perf_counter() - start_time
    print(f"[timing] Rendered {rendered} pages in {elapsed:.6f} seconds...")
    return results
