import cv2
import numpy as np
from typing import List, Tuple

from .utils import log_exec_time
from .file_repo import ImageFileRepository


@log_exec_time
def vehicle_to_images(page_bytes, out_repo: ImageFileRepository,  page: int) -> str:
    roi, roi_box = find_inner_roi(page_bytes, margin=10)
    vehicles = extract_vehicles_inside_roi(roi, min_area_ratio=0.01)

    print("Found", len(vehicles), "vehicle-like regions inside the box.")

    ret = out_repo.sub_repo("roi").store_image(roi,f"roi_pg{page}.webp")
    vehicles_repo = out_repo.sub_repo("vehicles")
    vehicles_repo.store_images(vehicles,f"vehicles_pg{page}")
    return ret


def find_inner_roi(img, margin: int = 10) -> Tuple[np.ndarray, Tuple[int,int,int,int]]:
    h, w = img.shape[:2]

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)

    bw = cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        51, 5
    )

    contours, _ = cv2.findContours(bw, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if not contours:
        return img, (0, 0, w, h)

    # Biggest external contour – usually the frame
    frame_cnt = max(contours, key=cv2.contourArea)
    x, y, cw, ch = cv2.boundingRect(frame_cnt)

    # Crop slightly inside the frame to get rid of the line itself
    x_in = max(x + margin, 0)
    y_in = max(y + margin, 0)
    x2_in = min(x + cw - margin, w)
    y2_in = min(y + ch - margin, h)

    roi = img[y_in:y2_in, x_in:x2_in]
    return roi, (x_in, y_in, x2_in - x_in,y2_in-y_in)

def extract_vehicles_inside_roi(
    roi: np.ndarray,
    min_area_ratio: float = 0.01,
    debug: bool = False,
    denoise: str = "nlmeans",  # "none", "gaussian", or "nlmeans"
) -> List[np.ndarray]:
    """
    Extract vehicle crops and return them row-wise:
    - group candidates into horizontal 'rows' by y proximity,
    - sort rows top-to-bottom,
    - within each row sort items left-to-right.
    Filtering rules retained to skip frame-like / overly-large contours.
    denoise: 'none' (no denoising), 'gaussian' (fast, default), 'nlmeans' (slow, original)
    """
    h, w = roi.shape[:2]
    page_area = h * w

    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    if denoise == "none":
        denoised = gray
    elif denoise == "gaussian":
        denoised = cv2.GaussianBlur(gray, (3, 3), 0)
    elif denoise == "nlmeans":
        denoised = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)
    else:
        raise ValueError(f"Unknown denoise method: {denoise}")

    bw = cv2.adaptiveThreshold(
        denoised, 255,
        cv2.ADAPTIVE_THRESH_MEAN_C,
        cv2.THRESH_BINARY_INV,
        31, 5
    )

    kernel: np.ndarray = np.ones((5, 5), np.uint8)
    bw = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, kernel, iterations=2)
    bw = cv2.dilate(bw, kernel, iterations=1)

    contours, _ = cv2.findContours(bw, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        if debug:
            print("[debug] no contours found")
        return []

    contours_sorted = sorted(contours, key=cv2.contourArea, reverse=True)
    frame_candidate = contours_sorted[0]
    fx, fy, fw, fh = cv2.boundingRect(frame_candidate)
    frame_rect_area = fw * fh

    margin = 5
    touches_left   = fx <= margin
    touches_top    = fy <= margin
    touches_right  = (fx + fw) >= (w - margin)
    touches_bottom = (fy + fh) >= (h - margin)

    peri = cv2.arcLength(frame_candidate, True)
    approx = cv2.approxPolyDP(frame_candidate, 0.02 * peri, True)
    is_quad = (len(approx) == 4) and cv2.isContourConvex(approx)

    frame_aspect = (fw / fh) if fh != 0 else 0.0
    roi_aspect = (w / h) if h != 0 else 0.0
    aspect_ok = abs(frame_aspect - roi_aspect) < 0.35

    is_frame_like = (
        (frame_rect_area > 0.6 * page_area and touches_left and touches_top and touches_right and touches_bottom)
        or (frame_rect_area > 0.5 * page_area and is_quad and aspect_ok)
    )

    # thresholds
    max_area_ratio = 0.5
    bbox_full_thresh = 0.9
    border_margin = 3
    near_full_area_thresh = 0.98

    # collect candidates with bbox info for robust grouping
    candidates = []
    for i, cnt in enumerate(contours_sorted):
        if i == 0 and is_frame_like:
            if debug:
                print("[debug] skipping frame candidate")
            continue

        area = cv2.contourArea(cnt)
        if area < page_area * min_area_ratio:
            continue

        vx, vy, vw, vh = cv2.boundingRect(cnt)

        if vw >= w * bbox_full_thresh or vh >= h * bbox_full_thresh:
            continue

        if area >= page_area * near_full_area_thresh:
            continue

        if vx <= border_margin or vy <= border_margin or (vx + vw) >= (w - border_margin) or (vy + vh) >= (h - border_margin):
            continue

        if area > page_area * max_area_ratio:
            peri_c = cv2.arcLength(cnt, True)
            approx_c = cv2.approxPolyDP(cnt, 0.02 * peri_c, True)
            is_rect_like = (len(approx_c) == 4) and cv2.isContourConvex(approx_c)
            if is_rect_like:
                continue

        if vw == w and vh == h:
            continue

        crop = roi[vy : vy + vh, vx : vx + vw]
        if crop.shape == roi.shape and np.array_equal(crop, roi):
            continue

        if (vw * vh) >= page_area * near_full_area_thresh:
            continue

        cx = vx + vw / 2.0
        cy = vy + vh / 2.0
        candidates.append({"cx": cx, "cy": cy, "x": vx, "y": vy, "vw": vw, "vh": vh, "area": area, "crop": crop})

    if not candidates:
        if debug:
            print("[debug] no candidates after filtering")
        return []

    # determine a sensible y-gap to separate rows:
    heights = np.array([c["vh"] for c in candidates], dtype=float)
    median_h = float(np.median(heights)) if heights.size else 0.0
    row_gap = max(10.0, median_h * 0.8, h * 0.04)  # pixels

    # sort by cy then group into rows by proximity using running mean
    candidates.sort(key=lambda c: c["cy"])
    rows = []
    for c in candidates:
        if not rows:
            rows.append([c])
            continue
        row = rows[-1]
        mean_cy = float(np.mean([it["cy"] for it in row]))
        if abs(c["cy"] - mean_cy) <= row_gap:
            row.append(c)
        else:
            rows.append([c])

    # sort rows by their mean y (top-to-bottom) and items inside by x ascending (left-to-right)
    for row in rows:
        row.sort(key=lambda it: it["cx"])
    rows.sort(key=lambda r: float(np.mean([it["cy"] for it in r])))

    # flatten into final ordered list (row by row)
    ordered_crops: List[np.ndarray] = []
    for row in rows:
        for it in row:
            ordered_crops.append(it["crop"])

    if debug:
        print(f"[debug] rows={len(rows)}, total_items={len(ordered_crops)}, row_gap={row_gap:.1f}")

    return ordered_crops