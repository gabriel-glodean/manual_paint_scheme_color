import os
from typing import Optional, Iterator, Tuple, Any, List
import boto3
import numpy as np
from pathlib import Path

from logic import log_exec_time


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
        except Exception:
            raise
        if not ok:
            raise RuntimeError("cv2.imencode failed to encode image as WEBP")
        data = buf.tobytes()
        key = self._full_key(name)
        try:
            self.s3.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType="image/webp")
        except Exception:
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
                resp = self.s3.get_object(Bucket=self.bucket, Key=key)
                data = resp["Body"].read()
                arr = np.frombuffer(data, np.uint8)
                img = cv2.imdecode(arr, cv2.IMREAD_UNCHANGED)
                if img is None:
                    raise RuntimeError(f"cv2.imdecode failed for S3 key: {key}")
                yield Path(key).name, img

    def sub_repo(self, sub_prefix: str) -> "S3ImageFileRepo":
        new_prefix = f"{self.prefix}/{sub_prefix}" if self.prefix else sub_prefix
        return S3ImageFileRepo(self.bucket, new_prefix)

    @log_exec_time
    def store_images(self, imgs: list, name: str) -> List[str]:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        paths = [None] * len(imgs)
        def upload(idx_img):
            idx, img = idx_img
            img_name = f"{Path(name).stem}_{idx:03d}.webp"
            try:
                result = self.store_image(img, img_name)
                return idx, result
            except Exception:
                return idx, None
        with ThreadPoolExecutor() as executor:
            futures = [executor.submit(upload, (idx, img)) for idx, img in enumerate(imgs)]
            for future in as_completed(futures):
                idx, path = future.result()
                paths[idx] = path
        return [str(p) for p in paths if p is not None]

    def get_image(self, name: str) -> Any:
        """
        Retrieve an image by filename from the S3 bucket/prefix.
        Raises FileNotFoundError if the image does not exist or cannot be read.
        Accepts either a plain filename (relative, no path traversal) or an s3://bucket/key URI.
        """
        try:
            import cv2
        except Exception as exc:
            raise RuntimeError("S3ImageFileRepo requires opencv-python (cv2)") from exc
        # Accept s3://bucket/key or just filename
        if name.startswith("s3://"):
            # Parse s3://bucket/key without regex
            uri = name[5:]  # remove 's3://'
            slash_idx = uri.find("/")
            if slash_idx == -1 or slash_idx == len(uri) - 1:
                raise ValueError(f"Invalid S3 URI: {name}")
            bucket = uri[:slash_idx]
            key = uri[slash_idx+1:]
        else:
            # Only allow filename, no path traversal
            if Path(name).name != name:
                raise ValueError("name must be a filename without path components")
            bucket = self.bucket
            key = self._full_key(name)
        try:
            resp = self.s3.get_object(Bucket=bucket, Key=key)
        except self.s3.exceptions.NoSuchKey:
            raise FileNotFoundError(f"Image not found in S3: {bucket}/{key}")
        except Exception as exc:
            raise RuntimeError(f"Failed to fetch image from S3: {bucket}/{key}") from exc
        data = resp["Body"].read()
        arr = np.frombuffer(data, np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_UNCHANGED)
        if img is None:
            raise RuntimeError(f"cv2.imdecode failed to read image from S3: {bucket}/{key}")
        return img

