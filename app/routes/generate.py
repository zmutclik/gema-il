import csv
import io
import random
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.helpers import insert_records
from app.config import ai_client, AI_MODEL

BASE_DIR = Path(__file__).parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter()

EXPECTED_HEADER = "nama_depan,nama_belakang,email,tanggal_lahir,gender,password"
EXPECTED_COLS = ["nama_depan", "nama_belakang", "email", "tanggal_lahir", "gender", "password"]


@router.get("/{username}/generate", response_class=HTMLResponse)
def generate_page(request: Request, username: str):
    """Tampilkan halaman generate data dengan AI."""
    return templates.TemplateResponse(
        request,
        "generate.html",
        {"username": username, "message": "", "msg_type": ""},
    )


@router.post("/{username}/generate")
async def generate_data(request: Request, username: str):
    """Generate data via AI — expects JSON body: {count, password, prefix, email_utama}."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(content={"message": "Invalid JSON body"}, status_code=400)

    count = body.get("count", 10)
    password = body.get("password", "").strip()
    prefix = body.get("prefix", "").strip()
    email_utama_raw = body.get("email_utama", "").strip()

    if not isinstance(count, int) or count < 1 or count > 100:
        return JSONResponse(content={"message": "Jumlah data harus antara 1 - 100."}, status_code=400)

    if not password:
        return JSONResponse(content={"message": "Password wajib diisi."}, status_code=400)

    if ai_client is None:
        return JSONResponse(
            content={"message": "AI belum dikonfigurasi. Cek .env (ai_url, ai_model)."},
            status_code=500,
        )

    # Parse email_utama domains
    email_domains = []
    if email_utama_raw:
        for part in email_utama_raw.replace("\n", ",").split(","):
            domain = part.strip().lower()
            if domain:
                if not domain.startswith("@"):
                    domain = "@" + domain
                email_domains.append(domain)

    if prefix:
        email_rule = (
            f"email → '{prefix}' + nama_depan + 1 angka random + sedikit nama_belakang + angka random 2 sampai 4 digit + '@gmail.com'. "
            f"Contoh: {prefix}budi2san23@gmail.com atau {prefix}sari1pur891@gmail.com."
        )
    else:
        email_rule = (
            "email → kombinasi nama_depan + 1 angka random + nama_belakang + 4 angka tahun sesuai tanggal lahir, "
            "semua pakai @gmail.com, lowercase"
        )

    prompt = f"""Kamu adalah generator data CSV. Buatkan data CSV dengan {count} data random menggunakan kolom berikut:

- nama_depan → nama depan Indonesia (random, bervariasi)
- nama_belakang → nama belakang Indonesia (random, bervariasi)
- {email_rule}
- tanggal_lahir → format YYYY-MM-DD, umur random antara 4 sampai 11 tahun
- gender → P atau W (random)
- password → semuanya disamakan "{password}"

**PENTING**: Hanya tampilkan data CSV-nya saja, tanpa header kolom, tanpa pembuka seperti "berikut datanya", cukup data mentahnya saja.
Format: nama_depan,nama_belakang,email,tanggal_lahir,gender,password
satu baris per data."""

    try:
        response = ai_client.chat.completions.create(
            model=AI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.9,
            max_tokens=4000,
        )
        csv_text = response.choices[0].message.content.strip()
    except Exception as e:
        return JSONResponse(content={"message": f"AI error: {str(e)}"}, status_code=500)

    # Remove markdown code fences
    lines = csv_text.strip().split("\n")
    while lines and lines[0].strip().startswith("```"):
        lines.pop(0)
    while lines and lines[-1].strip() == "```":
        lines.pop()
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    csv_text = "\n".join(lines)

    # Robust header detection
    first_line = csv_text.split("\n")[0].strip() if csv_text else ""
    first_cols = [c.strip().lower() for c in first_line.split(",")]
    has_header = all(col in first_cols for col in EXPECTED_COLS) and len(first_cols) >= len(EXPECTED_COLS)

    raw_rows = []
    if has_header:
        reader = csv.DictReader(io.StringIO(csv_text))
        for r in reader:
            normalized = {k.strip().lower(): v.strip() for k, v in r.items() if v is not None}
            raw_rows.append({field: normalized.get(field, "") for field in EXPECTED_COLS})
    else:
        reader = csv.DictReader(io.StringIO(EXPECTED_HEADER + "\n" + csv_text))
        raw_rows = list(reader)

    if not raw_rows:
        return JSONResponse(
            content={
                "message": f"AI tidak menghasilkan data yang valid.\nRaw AI output:\n{csv_text[:500]}",
                "raw_preview": csv_text[:500],
            },
            status_code=500,
        )

    # Replace email domains with random email_utama domains if provided
    if email_domains:
        for r in raw_rows:
            email_local = r.get("email", "").split("@")[0]
            if email_local:
                r["email"] = email_local + random.choice(email_domains)
            r["email_utama"] = random.choice(email_domains).lstrip("@")

    inserted, skipped = insert_records(username, raw_rows)
    response_data = {
        "message": f"Berhasil generate & insert {inserted} dari {count} data.",
        "inserted": inserted,
        "requested": count,
    }
    if skipped:
        response_data["skipped"] = skipped[:5]
        response_data["message"] += f" {len(skipped)} di-skip (cek 'skipped' field)."

    return JSONResponse(content=response_data)
