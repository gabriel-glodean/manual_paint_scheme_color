import io
import os
import zipfile

from pydantic import BaseModel
from fastapi import UploadFile, File, Form, Depends, HTTPException, APIRouter, FastAPI, Body
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path


from logic import process_pdf, apply_color_mapping, ImageFileRepository
from logic.parsers import parse_page_list

def stream_files_as_zip(file_paths: list[str], s3_bucket: str = None):
    zip_io = io.BytesIO()
    with zipfile.ZipFile(zip_io, mode="w") as zf:
        #s3 = boto3.client("s3") if s3_bucket else None
        for file_path in file_paths:
            arc_name = os.path.basename(file_path)
            if s3_bucket and file_path.startswith("s3://"):
                # key = file_path.replace(f"s3://{s3_bucket}/", "")
                # obj =  s3.get_object(Bucket=s3_bucket, Key=key)
                # zf.writestr(arc_name, obj["Body"].read())
                raise NotImplementedError("S3 file streaming is not implemented yet.")
            else:
                with open(file_path, "rb") as f:
                    zf.writestr(arc_name, f.read())
    zip_io.seek(0)
    return StreamingResponse(
        zip_io,
        media_type="application/x-zip-compressed",
        headers={"Content-Disposition": "attachment; filename=files.zip"}
    )

def get_image_file_repo() -> ImageFileRepository:
    deployment = os.getenv("deployment", "local")
    if deployment == "local":
        from logic.file_repo import LocalImageFileRepo
        path = os.getenv("working_path", "output")
        return LocalImageFileRepo(Path(path))
    else:
        raise ValueError(f"Unsupported deployment type: {deployment}")

def create_page_filter(pages: str = Form(""), threshold: int = Form(3)):
    deployment = os.getenv("deployment", "local")
    pages_of_interest: set[int] = parse_page_list(pages)
    if deployment == "local":
         from local import OcrPageFilter
         return OcrPageFilter(pages_of_interest, threshold)
    from logic import PageFilter
    return PageFilter(pages_of_interest)

router = APIRouter(prefix="/api/v1/color_vehicles", tags=["color_vehicles"])

@router.post("/process_pdf")
async def api_process_pdf(
    pdf_file: UploadFile = File(...),
    clusters: int = Form(...),
    dpi: int = Form(...),
    image_repo = Depends(get_image_file_repo),
    page_filter = Depends(create_page_filter)
):
    try:
        contents = await pdf_file.read()
        preview_path, centroids, uuid_string = process_pdf(contents, clusters, dpi, image_repo, page_filter)
        return {
            "images": [preview_path],
            "centroids": centroids,
            "session": uuid_string
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

class DownloadImagesRequest(BaseModel):
    images: list[str]

@router.post("/download_images")
def download_images(request: DownloadImagesRequest = Body(...)):
    return stream_files_as_zip(request.images, os.getenv("s3_bucket", None))

@router.post("/apply_color_mapping")
async def api_apply_color_mapping(
    clusters: int = Form(...),
    colors: str = Form(...),
    session: str = Form(...),
    image_repo = Depends(get_image_file_repo)
):
    try:
        extracted_repo = image_repo.sub_repo(session).sub_repo("vehicles")
        color_repo = image_repo.sub_repo(session).sub_repo("colorized")
        return { "images": apply_color_mapping(clusters, colors, extracted_repo, color_repo) }
    except Exception as exc:
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
