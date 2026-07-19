import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.database import get_db

router = APIRouter()


@router.get("/{username}/settings")
def get_settings(username: str):
    """Ambil settings form generate milik username."""
    conn = get_db()
    row = conn.execute("SELECT data FROM settings WHERE username = ?", (username,)).fetchone()
    conn.close()
    if not row:
        return JSONResponse(content={})
    try:
        return JSONResponse(content=json.loads(row["data"]))
    except Exception:
        return JSONResponse(content={})


@router.post("/{username}/settings")
async def save_settings(username: str, request: Request):
    """Simpan settings form generate milik username."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(content={"message": "Invalid JSON"}, status_code=400)

    conn = get_db()
    conn.execute(
        "INSERT INTO settings (username, data) VALUES (?, ?) ON CONFLICT(username) DO UPDATE SET data = excluded.data",
        (username, json.dumps(body)),
    )
    conn.commit()
    conn.close()
    return JSONResponse(content={"message": "ok"})
