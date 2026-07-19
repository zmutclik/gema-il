from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response, FileResponse

BASE_DIR = Path(__file__).parent.parent.parent

router = APIRouter()


@router.get("/template")
def download_template():
    """Download template CSV file."""
    template_path = BASE_DIR / "template.csv"
    return FileResponse(
        path=str(template_path),
        filename="template.csv",
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=template.csv"},
    )


@router.get("/favicon.ico")
def favicon():
    return Response(status_code=204)


@router.get("/")
def root():
    return JSONResponse(content={"app": "GemaIL Data Manager"})
