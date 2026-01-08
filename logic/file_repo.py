from typing import Protocol, Iterator, TYPE_CHECKING, Any, runtime_checkable, Tuple
from pathlib import Path

if TYPE_CHECKING:
    import cv2  # type: ignore
    MatLike = cv2.typing.MatLike  # type: ignore
else:
    MatLike = Any

@runtime_checkable
class ImageFileRepository(Protocol):
    def iter_images(self) -> Iterator[Tuple[str, MatLike]]:
        ...

    def store_image(self, img: MatLike, name: str) -> str:
        ...

    def sub_repo(self, name: str) -> "ImageFileRepository":
       ...

# Example concrete implementation (optional; requires opencv-python and numpy)
class LocalImageFileRepo:
    """Yield (filename, cv2 Mat) tuples for all PNG files in a given local directory.

    Usage:
        repo = LocalImageFileRepo("C:/path/to/dir")
        for name, mat in repo.iter_images():
            # name is the filename (e.g. "img01.png")
            # mat is a cv2-compatible MatLike (numpy array)
            ...
    """
    def __init__(self, directory):
        # accept str or os.PathLike
        self._dir = Path(directory)
        # create directory if it does not exist (do not raise)
        if not self._dir.exists():
            self._dir.mkdir(parents=True, exist_ok=True)

        # if the path exists but is not a directory, raise — this indicates a misconfiguration
        if not self._dir.is_dir():
            raise ValueError(f"Path is not a directory: {self._dir}")

        # collect PNG files (case-insensitive) in the directory (non-recursive)
        pngs = []
        for entry in self._dir.iterdir():
            if entry.is_file():
                if entry.suffix.lower() == ".png":
                    pngs.append(str(entry))
        # keep stable ordering
        self._paths = sorted(pngs)

    def iter_images(self) -> Iterator[Tuple[str, MatLike]]:
        try:
            import cv2
        except Exception as exc:
            raise RuntimeError("LocalImageFileRepo requires opencv-python (cv2)") from exc

        for path in self._paths:
            mat = cv2.imread(path, cv2.IMREAD_UNCHANGED)
            if mat is None:
                # provide a clear error including filename
                raise RuntimeError(f"cv2.imread failed to read image: {path}")
            yield Path(path).name, mat

    def store_image(self, img: MatLike, name: str) -> str:
        try:
            import cv2
        except Exception as exc:
            raise RuntimeError("LocalImageFileRepo requires opencv-python (cv2)") from exc

        if not name:
            raise ValueError("name must be a non-empty filename")
        # disallow path traversal / directories in the provided name
        if Path(name).name != name:
            raise ValueError("name must be a filename without path components")

        out_path = self._dir / name
        # default to PNG when no extension provided
        if not out_path.suffix:
            out_path = out_path.with_suffix(".png")

        # write the image directly with OpenCV (no temp files)
        str_path = str(out_path)
        ok = cv2.imwrite(str_path, img)
        print( f"Writing image to {str(out_path.resolve())}, success: {ok}")
        if not ok:
            raise RuntimeError(f"Failed to write path {out_path}")
        return str_path

    def sub_repo(self, name: str) -> "LocalImageFileRepo":
        if not name:
            raise ValueError("name must be a non-empty subdirectory name")
        # disallow path traversal / directories in the provided name
        if Path(name).name != name:
            raise ValueError("name must be a subdirectory name without path components")

        subdir = self._dir / name
        # create directory if it does not exist
        subdir.mkdir(parents=True, exist_ok=True)

        if not subdir.is_dir():
            raise ValueError(f"Subpath is not a directory: {subdir}")

        return LocalImageFileRepo(subdir)
