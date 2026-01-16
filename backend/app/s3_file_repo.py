import os
from typing import Optional, Iterator, Tuple, Any, List
import boto3
import numpy as np
from pathlib import Path

class S3ImageFileRepo:
    def __getstate__(self):
        state = self.__dict__.copy()
        state.pop("s3", None)
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        self.s3 = boto3.client("s3")

    def __init__(self, bucket: Optional[str] = None, prefix: str = ""):
        self.bucket = bucket or os.getenv("S3_BUCKET")
        if not self.bucket:
            raise ValueError("S3 bucket name must be provided via argument or S3_BUCKET env var.")
        self.prefix = prefix.strip("/")
        self.s3 = boto3.client("s3")

    def _full_key(self, key: str) -> str:
        if self.prefix:
            return f"{self.prefix}/{key}".lstrip("/")
        return key.lstrip("/")

    def store_image(self, img: Any, name: str) -> str:
        try:
            import cv2
        except Exception as exc:
            raise RuntimeError("S3ImageFileRepo requires opencv-python (cv2)") from exc
        if not name:
            raise ValueError("name must be a non-empty filename")
        if Path(name).name != name:
            raise ValueError("name must be a filename without path components")
        if not name.lower().endswith(".webp"):
            name = name + ".webp"
        try:
            ok, buf = cv2.imencode(".webp", img)
        except Exception as exc:
            print(f"[S3ImageFileRepo] cv2.imencode failed for {name}", exc)
            raise
        if not ok:
            print(f"[S3ImageFileRepo] cv2.imencode returned False for {name}")
            raise RuntimeError("cv2.imencode failed to encode image as WEBP")
        data = buf.tobytes()
        key = self._full_key(name)
        print(f"[S3ImageFileRepo] Attempting to store image to S3: bucket={self.bucket}, key={key}, size={len(data)}")
        try:
            self.s3.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType="image/webp")
            print(f"[S3ImageFileRepo] Successfully stored object to S3: {key}")
        except Exception as exc:
            print(f"[S3ImageFileRepo] S3 put_object failed for {key}: {exc}")
            raise
        return f"s3://{self.bucket}/{key}"

    def iter_images(self) -> Iterator[Tuple[str, Any]]:
        try:
            import cv2
        except Exception as exc:
            raise RuntimeError("S3ImageFileRepo requires opencv-python (cv2)") from exc
        prefix = self.prefix + "/" if self.prefix else ""
        paginator = self.s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if not key.lower().endswith(".webp"):
                    continue
                print(f"[S3ImageFileRepo] Downloading image from S3: {key}")
                resp = self.s3.get_object(Bucket=self.bucket, Key=key)
                data = resp["Body"].read()
                arr = np.frombuffer(data, np.uint8)
                img = cv2.imdecode(arr, cv2.IMREAD_UNCHANGED)
                if img is None:
                    raise RuntimeError(f"cv2.imdecode failed for S3 key: {key}")
                yield Path(key).name, img

    def sub_repo(self, sub_prefix: str) -> "S3ImageFileRepo":
        new_prefix = f"{self.prefix}/{sub_prefix}" if self.prefix else sub_prefix
        print(f"[S3ImageFileRepo] Creating sub_repo with prefix: {new_prefix}")
        return S3ImageFileRepo(self.bucket, new_prefix)

    def store_images(self, imgs: list, name: str) -> List[str]:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        paths = [None] * len(imgs)
        def upload(idx_img):
            idx, img = idx_img
            img_name = f"{Path(name).stem}_{idx:03d}.webp"
            print(f"[S3ImageFileRepo] Uploading image {img_name} (index {idx})")
            try:
                result = self.store_image(img, img_name)
                print(f"[S3ImageFileRepo] Uploaded image {img_name} (index {idx}) successfully: {result}")
                return idx, result
            except Exception as exc:
                print(f"[S3ImageFileRepo] Failed to upload image {img_name} (index {idx}): {exc}")
                return idx, None
        with ThreadPoolExecutor() as executor:
            futures = [executor.submit(upload, (idx, img)) for idx, img in enumerate(imgs)]
            for future in as_completed(futures):
                idx, path = future.result()
                paths[idx] = path
        failed = [i for i, p in enumerate(paths) if p is None]
        if failed:
            print(f"[S3ImageFileRepo] Failed to upload images at indices: {failed}")
        return [str(p) for p in paths if p is not None]
