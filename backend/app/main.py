import io
import os
import zipfile
import traceback

from pydantic import BaseModel
from fastapi import Depends, HTTPException, APIRouter, FastAPI, Body
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
import boto3

from logic import process_pdf, apply_color_mapping, ImageFileRepository
from logic.color_vehicle import cluster_vehicle
from logic.parsers import parse_page_list

def stream_files_as_zip(file_paths: list[str]):
    print(f"[DEBUG] stream_files_as_zip called with file_paths={file_paths}")
    deployment = os.getenv("deployment", "local")
    s3 = None
    if deployment == "aws":
        import boto3
        s3 = boto3.client("s3")
        print("[DEBUG] S3 client created for AWS deployment")
    else:
        print("[DEBUG] Not in AWS deployment, S3 client not created")
    zip_io = io.BytesIO()
    # Use ZIP_DEFLATED for compression
    with zipfile.ZipFile(zip_io, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file_path in file_paths:
            arc_name = os.path.basename(file_path)
            print(f"[DEBUG] Processing file_path={file_path}, arc_name={arc_name}")
            if file_path.startswith("s3://"):
                if not s3:
                    print(f"[ERROR] S3 URI provided but not in AWS deployment: {file_path}")
                    raise HTTPException(status_code=400, detail="S3 URIs are only supported in AWS deployment.")
                try:
                    _, _, bucket_and_key = file_path.partition("s3://")
                    bucket, key = bucket_and_key.split("/", 1)
                except Exception as exc:
                    print(f"[ERROR] Invalid S3 URI: {file_path}, error: {exc}")
                    raise HTTPException(status_code=400, detail=f"Invalid S3 URI: {file_path}")
                print(f"[DEBUG] Attempting to fetch from S3: bucket={bucket}, key={key}")
                try:
                    obj = s3.get_object(Bucket=bucket, Key=key)
                    data = obj["Body"].read()
                    print(f"[DEBUG] S3 fetch success: {key}, size={len(data)} bytes")
                    zf.writestr(arc_name, data)
                    print(f"[DEBUG] Added {arc_name} to zip from S3")
                except Exception as exc:
                    print(f"[ERROR] Failed to fetch or add {file_path} from S3: {exc}")
                    raise HTTPException(status_code=500, detail=f"Failed to fetch or add {file_path} from S3: {exc}")
            else:
                if deployment == "aws":
                    print(f"[ERROR] Only S3 URIs are supported in Lambda: {file_path}")
                    raise HTTPException(status_code=400, detail=f"Only S3 URIs are supported in Lambda: {file_path}")
                print(f"[DEBUG] Attempting to open local file: {file_path}")
                try:
                    with open(file_path, "rb") as f:
                        data = f.read()
                        print(f"[DEBUG] Local file read success: {file_path}, size={len(data)} bytes")
                        zf.writestr(arc_name, data)
                        print(f"[DEBUG] Added {arc_name} to zip from local file")
                except Exception as exc:
                    print(f"[ERROR] Failed to open or add {file_path} from local: {exc}")
                    raise HTTPException(status_code=500, detail=f"Failed to open or add {file_path} from local: {exc}")
    zip_io.seek(0)
    print(f"[DEBUG] Zip file created, size={zip_io.getbuffer().nbytes} bytes (compressed)")
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
    s3_pdf_path: str
    dpi: int
    pages: str = ""
    threshold: int = 3



@router.post("/process_pdf")
async def api_process_pdf(
    request: ProcessPdfRequest = Body(...),
    image_repo = Depends(get_image_file_repo)
):
    try:
        print(f"[DEBUG] /process_pdf called with: {request}")
        # Parse S3 path
        s3_path = request.s3_pdf_path
        if not s3_path.startswith("s3://"):
            print(f"[DEBUG] Invalid s3_pdf_path: {s3_path}")
            raise HTTPException(status_code=400, detail="s3_pdf_path must start with 's3://'")
        s3_parts = s3_path[5:].split('/', 1)
        if len(s3_parts) != 2:
            print(f"[DEBUG] Invalid s3_pdf_path format: {s3_path}")
            raise HTTPException(status_code=400, detail="Invalid s3_pdf_path format")
        bucket, key = s3_parts
        print(f"[DEBUG] Downloading PDF from S3 bucket={bucket}, key={key}")
        s3 = boto3.client("s3")
        try:
            pdf_obj = s3.get_object(Bucket=bucket, Key=key)
            contents = pdf_obj["Body"].read()
        except Exception as s3_exc:
            print(f"[ERROR] Exception while downloading PDF from S3: {s3_exc}")
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"S3 download error: {s3_exc}")
        print(f"[DEBUG] Downloaded PDF size: {len(contents)} bytes")
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
                              image_repo, image_repo.sub_repo(request.session))
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

@router.post("/download_images")
def download_images(request: DownloadImagesRequest = Body(...)):
    print(f"[DEBUG] /download_images called with: {request}")
    try:
        response = stream_files_as_zip(request.images)
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
