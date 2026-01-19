import io
import os
import zipfile
import traceback

from pydantic import BaseModel
from fastapi import Depends, HTTPException, APIRouter, FastAPI, Body
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path

from logic import process_pdf, apply_color_mapping, ImageFileRepository, PdfRetriever
from logic.color_vehicle import cluster_vehicle
from logic.parsers import parse_page_list


def stream_files_as_zip(image_repo, file_paths: list[str]):
    zip_io = io.BytesIO()
    with zipfile.ZipFile(zip_io, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file_path in file_paths:
            arc_name = os.path.basename(file_path)
            try:
                data = image_repo.get_image_bytes(file_path)
                zf.writestr(arc_name, data)
            except Exception as exc:
                raise HTTPException(status_code=500, detail=f"Failed to fetch or add {file_path}: {exc}")
    zip_io.seek(0)
    return StreamingResponse(
        zip_io,
        media_type="application/x-zip-compressed",
        headers={"Content-Disposition": "attachment; filename=files.zip"}
    )

def get_image_file_repo() -> ImageFileRepository:
    deployment = os.getenv("deployment", "local").lower()
    print(f"[DEBUG] get_image_file_repo: deployment={deployment}")
    if deployment == "local":
        from logic.file_repo import LocalImageFileRepo
        path = os.getenv("working_path", "output")
        print(f"[DEBUG] Using LocalImageFileRepo with path={path}")
        return LocalImageFileRepo(Path(path))
    elif deployment == "aws":
        from aws.s3_file_repo import S3ImageFileRepo
        bucket = os.getenv("s3_output_bucket", None)
        if bucket:
            print(f"[DEBUG] Using S3ImageFileRepo with bucket={bucket}")
            return S3ImageFileRepo(bucket)
    print(f"[DEBUG] Unsupported deployment type: {deployment}")
    raise ValueError(f"Unsupported deployment type: {deployment}")

def pdf_retriever() -> PdfRetriever:
    deployment = os.getenv("deployment", "local").lower()
    print(f"[DEBUG] get_image_file_repo: deployment={deployment}")
    if deployment == "local":
        from logic.file_repo import LocalPdfRetriever
        print(f"[DEBUG] UsingLocalPdfRetriever")
        return LocalPdfRetriever(".")
    elif deployment == "aws":
        from aws.s3_file_repo import S3PdfRetriever
        bucket = os.getenv("s3_output_bucket", None)
        if bucket:
            print(f"[DEBUG] Using S3ImageFileRepo with bucket={bucket}")
            return S3PdfRetriever(bucket)
    print(f"[DEBUG] Unsupported deployment type: {deployment}")
    raise ValueError(f"Unsupported deployment type: {deployment}")

def create_page_filter(pages: str = "", threshold: int = 3):
    deployment = os.getenv("deployment", "local")
    print(f"[DEBUG] create_page_filter: deployment={deployment}, pages={pages}, threshold={threshold}")
    pages_of_interest: set[int] = parse_page_list(pages)
    if deployment == "local":
         from local import OcrPageFilter
         print(f"[DEBUG] Using OcrPageFilter with pages_of_interest={pages_of_interest}")
         return OcrPageFilter(pages_of_interest, threshold)
    from logic import PageFilter
    print(f"[DEBUG] Using logic.PageFilter with pages_of_interest={pages_of_interest}")
    return PageFilter(pages_of_interest)

router = APIRouter(prefix="/api/v1/color_vehicles", tags=["color_vehicles"])

class ProcessPdfRequest(BaseModel):
    pdf_path: str
    dpi: int
    pages: str = ""
    threshold: int = 3



@router.post("/process_pdf")
async def api_process_pdf(
    request: ProcessPdfRequest = Body(...),
    image_repo = Depends(get_image_file_repo),
    pdf_repo = Depends(pdf_retriever)
):
    try:
        print(f"[DEBUG] /process_pdf called with: {request}")
        print(f"[DEBUG] Attempting to load PDF from: {request.pdf_path}")
        contents = pdf_repo.get_pdf_bytes(request.pdf_path)
        print(f"[DEBUG] PDF loaded, size={len(contents)} bytes")
        page_filter = create_page_filter(request.pages, request.threshold)
        print(f"[DEBUG] Calling process_pdf with dpi={request.dpi}")
        roi_path, uuid_string = process_pdf(contents, request.dpi, image_repo, page_filter)
        print(f"[DEBUG] process_pdf returned roi_path={roi_path}, session={uuid_string}")
        return {
            "images": [roi_path],
            "session": uuid_string
        }
    except Exception as exc:
        print(f"[ERROR] Exception in /process_pdf: {exc}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc))

class PreviewImageRequest(BaseModel):
    image: str
    clusters: int
    session: str

@router.post("/preview_image")
def preview_image(request: PreviewImageRequest = Body(...), image_repo = Depends(get_image_file_repo)):
    print(f"[DEBUG] /preview_image called with image_path={request.image}")
    try:
        preview_path, centroids = cluster_vehicle(request.image, request.clusters,
                              image_repo.sub_repo(request.session).sub_repo("roi")
                                                  , image_repo.sub_repo(request.session))
        print(f"[DEBUG] cluster_vehicle returned: preview_path={preview_path}, centroids={centroids}")
        return {
            "images": [preview_path],
            "centroids": centroids,
        }
    except Exception as exc:
        print(f"[ERROR] Exception in /preview_image: {exc}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc))

class DownloadImagesRequest(BaseModel):
    images: list[str]
    session: str
    folder: str = ""

@router.post("/download_images")
def download_images(request: DownloadImagesRequest = Body(...), image_repo = Depends(get_image_file_repo)):
    print(f"[DEBUG] /download_images called with: {request}")
    try:
        repo = image_repo.sub_repo(request.session)
        if request.folder:
            repo = repo.sub_repo(request.folder)
            print(f"[DEBUG] Using sub-repo for folder: {request.folder}")

        response = stream_files_as_zip(repo, request.images)
        print(f"[DEBUG] stream_files_as_zip returned StreamingResponse")
        return response
    except Exception as exc:
        print(f"[ERROR] Exception in /download_images: {exc}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc))

class ApplyColorMappingRequest(BaseModel):
    clusters: int
    colors: str
    session: str

@router.post("/apply_color_mapping")
async def api_apply_color_mapping(
    request: ApplyColorMappingRequest = Body(...),
    image_repo = Depends(get_image_file_repo)
):
    try:
        print(f"[DEBUG] /apply_color_mapping called with: {request}")
        extracted_repo = image_repo.sub_repo(request.session).sub_repo("vehicles")
        color_repo = image_repo.sub_repo(request.session).sub_repo("colorized")
        print(f"[DEBUG] Calling apply_color_mapping with clusters={request.clusters}, colors={request.colors}")
        result = apply_color_mapping(request.clusters, request.colors, extracted_repo, color_repo)
        print(f"[DEBUG] apply_color_mapping returned: {result}")
        return { "images": result }
    except Exception as exc:
        print(f"[ERROR] Exception in /apply_color_mapping: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # You can restrict this to your frontend URL in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)
app.include_router(router)
