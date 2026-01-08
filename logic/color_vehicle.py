from typing import Tuple, List
import cv2
import numpy as np
import time
import uuid

from collections_extended import RangeMap

from cv2.typing import MatLike

from .file_repo import ImageFileRepository
from .parsers import parse_color_ranges, lookup_with_default
from .pdf_processing import process_pdf_in_parallel
from .page_filter import PageFilter



# -------------------------------------------------------------
# FUNCTION: Extract first vehicle from PDF (placeholder)
# -------------------------------------------------------------

Color = Tuple[int, int, int]

def process_pdf(pdf_file, k, dpi, out_repo: ImageFileRepository, page_filter: PageFilter) -> Tuple[str | None, List[int], str]:
    uuid_string = str(uuid.uuid4())
    preview_path, centroids =  _extract_first_vehicle(pdf_file, k, dpi, page_filter, out_repo.sub_repo(uuid_string))
    return preview_path, sorted(centroids), uuid_string

def _extract_first_vehicle(pdf_bytes, cluster_count: int, dpi: int, page_filter: PageFilter, out_repo: ImageFileRepository):
    items =  process_pdf_in_parallel(pdf_bytes, out_repo, page_filter, dpi)
    first = next((item for item in items if item is not None), None)
    start_time = time.perf_counter()
    if first is None:
        print("Could not find any painting page.")
        return None, []
    ret = _cluster_vehicle(first, cluster_count, out_repo)
    elapsed = time.perf_counter() - start_time
    print(f"Clustering time: {elapsed:.6f} seconds")
    return ret

# -------------------------------------------------------------
# FUNCTION: Cluster pixels and return centroid image + cluster data
# -------------------------------------------------------------
def _kmeans_1d_weighted(levels: np.ndarray, weights: np.ndarray, cluster_count: int, max_iter: int = 50, tol: float = 1e-3):
    """
    Weighted 1D kmeans on `levels` with `weights`. Returns centroids (float).
    """
    if cluster_count <= 0:
        raise ValueError("K must be >= 1")
    # initialize centroids by weighted quantiles
    cum = np.cumsum(weights)
    if cum[-1] == 0:
        return np.linspace(levels.min(), levels.max(), cluster_count)
    quantiles = (np.linspace(0, 1, cluster_count + 2)[1:-1] * cum[-1])
    centroids = np.interp(quantiles, cum, levels).astype(np.float64)

    for _ in range(max_iter):
        # assign each level to nearest centroid
        d = np.abs(levels[:, None] - centroids[None, :])  # (M, K)
        labels = np.argmin(d, axis=1)
        # compute weighted sums per cluster
        weighted_sums = np.bincount(labels, weights=levels * weights, minlength=cluster_count)
        weight_sums = np.bincount(labels, weights=weights, minlength=cluster_count)
        # handle empty clusters by reassigning to the largest remaining weight level
        new_centroids = centroids.copy()
        nonempty = weight_sums > 0
        new_centroids[nonempty] = weighted_sums[nonempty] / weight_sums[nonempty]
        if not nonempty.all():
            # pick levels with the largest weight that are not already used as centroids
            unused = np.where(~nonempty)[0]
            used_levels = set(np.round(new_centroids[nonempty]).astype(int).tolist())
            sorted_idx = np.argsort(-weights)  # descending by weight
            pick_iter = iter(sorted_idx)
            for u in unused:
                # find next heavy level not already used
                while True:
                    try:
                        cand = next(pick_iter)
                    except StopIteration:
                        break
                    if int(levels[cand]) not in used_levels:
                        used_levels.add(int(levels[cand]))
                        new_centroids[u] = float(levels[cand])
                        break
        shift = np.max(np.abs(new_centroids - centroids))
        centroids = new_centroids
        if shift <= tol:
            break
    return centroids

def _cluster_vehicle(img: np.ndarray | None, cluster_count: int,  out_repo: ImageFileRepository) -> Tuple[str, list[int]]:
    """
    Fast clustering using weighted 1D kmeans on the 256 gray levels (no sklearn).
    Returns (`../output/clustered_preview.png`, centroid_gray_list).
    """
    if img is None:
        raise ValueError("cluster_vehicle received None for `img`")
    img = np.asarray(img)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # histogram of grayscale values (0..255)
    counts = np.bincount(gray.ravel(), minlength=256).astype(np.float64)
    total = counts.sum()
    if total == 0:
        raise ValueError("Empty image in cluster_vehicle")

    n_unique = int(np.count_nonzero(counts))
    n_clusters = min(cluster_count, n_unique) if n_unique > 0 else 1

    levels = np.arange(256, dtype=np.float64)  # 0..255
    centroids = _kmeans_1d_weighted(levels, counts, n_clusters, max_iter=100, tol=1e-2)
    # ensure centroids are in 0..255 and as uint8
    centroids = np.clip(np.round(centroids), 0, 255).astype(np.uint8)

    # map each level to nearest centroid
    d = np.abs(levels[:, None] - centroids[None, :])  # (256, n_clusters)
    labels_levels = np.argmin(d, axis=1)  # for each level 0..255 -> cluster index
    lut = centroids[labels_levels]  # map level -> centroid_gray

    mapped_gray = lut[gray]  # vectorized mapping
    out = np.dstack([mapped_gray, mapped_gray, mapped_gray]).astype(np.uint8)

    # preserve black/white regions
    out[gray < 50] = (0, 0, 0)
    out[gray > 245] = (255, 255, 255)

    return  out_repo.store_image(out, "clustered_preview.png"), centroids.tolist()

# -------------------------------------------------------------
# FUNCTION: Apply final color mapping
# -------------------------------------------------------------
def apply_color_mapping(cluster_count: int, colors: str, in_repo: ImageFileRepository, out_repo: ImageFileRepository) -> List[MatLike]:
    color_ranges: RangeMap = parse_color_ranges(colors)
    paths = []
    for name, img in in_repo.iter_images():
        out = _apply_color_to_image(cluster_count, color_ranges, img)
        paths.append(out_repo.store_image(out, name))
    return paths


def _apply_color_to_image(cluster_count: int, color_ranges: RangeMap,
                          img: MatLike) -> MatLike:
    img = np.asarray(img)
    gray: np.ndarray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # histogram and cluster on 256 gray levels using the weighted 1D kmeans already in this file
    counts = np.bincount(gray.ravel(), minlength=256).astype(np.float64)
    total = counts.sum()
    if total == 0:
        raise ValueError("Empty image in apply_color_mapping")

    n_unique = int(np.count_nonzero(counts))
    n_clusters = min(cluster_count, n_unique) if n_unique > 0 else 1

    levels = np.arange(256, dtype=np.float64)
    centroids = _kmeans_1d_weighted(levels, counts, n_clusters, max_iter=100, tol=1e-2)
    centroids = np.clip(np.round(centroids), 0, 255).astype(np.uint8)

    # map each original gray level (0..255) to its centroid index
    d = np.abs(levels[:, None] - centroids[None, :])  # (256, n_clusters)
    labels_levels = np.argmin(d, axis=1)  # for each level -> cluster index

    # Build a final RGB LUT for every input gray level by looking up the centroid gray in color_ranges
    final_rgb = np.zeros((256, 3), dtype=np.uint8)
    for lvl in range(256):
        cent_g = int(centroids[labels_levels[lvl]])
        default_val = (cent_g, cent_g, cent_g)
        raw_val = lookup_with_default(color_ranges, cent_g, default_val)
        final_rgb[lvl] = (int(raw_val[0]), int(raw_val[1]), int(raw_val[2]))

    # Apply LUT vectorized and preserve black/white regions
    out = final_rgb[gray]  # shape (h, w, 3)
    out = out.copy()
    out[gray < 50] = (0, 0, 0)
    out[gray > 245] = (255, 255, 255)
    return out

