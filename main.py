import sqlite3
import csv
import io
import uuid
import os
import json
from pathlib import Path

from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv
from openai import OpenAI

# ─── App Setup ───────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent

load_dotenv(BASE_DIR / ".env")

app = FastAPI(title="Gema-IL Data Manager")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

AI_URL = os.getenv("ai_url", "")
AI_MODEL = os.getenv("ai_model", "")
AI_KEY = os.getenv("ai_key", "")
ai_client = None
if AI_URL and AI_MODEL and AI_KEY:
    ai_client = OpenAI(base_url=AI_URL, api_key=AI_KEY)
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "data.db"


# ─── Database ────────────────────────────────────────────────────────────────


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS records (
            uid TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            nama_depan TEXT NOT NULL,
            nama_belakang TEXT NOT NULL DEFAULT '',
            email TEXT NOT NULL,
            email_utama TEXT NOT NULL DEFAULT '',
            tanggal_lahir TEXT NOT NULL,
            gender TEXT NOT NULL,
            password TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'antrian'
        )
    """)
    # Migration: add nama_depan/nama_belakang if upgrading from old schema
    try:
        conn.execute("ALTER TABLE records ADD COLUMN nama_depan TEXT NOT NULL DEFAULT ''")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE records ADD COLUMN nama_belakang TEXT NOT NULL DEFAULT ''")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE records ADD COLUMN email_utama TEXT NOT NULL DEFAULT ''")
    except Exception:
        pass
    # Migrate existing nama → nama_depan + nama_belakang
    # Check if old 'nama' column still exists
    cols = [c[1] for c in conn.execute("PRAGMA table_info(records)").fetchall()]
    if "nama" in cols:
        old_rows = conn.execute(
            "SELECT uid, nama FROM records WHERE nama_depan = '' AND nama IS NOT NULL AND nama != ''"
        ).fetchall()
        for row in old_rows:
            nama_depan, nama_belakang = split_name(row["nama"])
            conn.execute(
                "UPDATE records SET nama_depan = ?, nama_belakang = ? WHERE uid = ?",
                (nama_depan, nama_belakang, row["uid"]),
            )
    conn.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            username TEXT PRIMARY KEY,
            data TEXT NOT NULL DEFAULT '{}'
        )
    """)
    conn.commit()
    conn.close()


init_db()


# ─── Helpers ─────────────────────────────────────────────────────────────────


def strip_email(raw: str) -> str:
    """Strip domain from email, keep only the prefix before @."""
    return raw.strip().split("@")[0].lower()


def split_name(nama: str) -> tuple:
    """Split full name into (nama_depan, nama_belakang)."""
    parts = nama.strip().split(maxsplit=1)
    if len(parts) == 0:
        return ("", "")
    elif len(parts) == 1:
        return (parts[0], "")
    else:
        return (parts[0], parts[1])

def insert_records(username: str, rows: list[dict]) -> tuple[int, list]:
    """Insert multiple records into DB. Returns (count, skipped_reasons)."""
    conn = get_db()
    count = 0
    skipped = []
    for i, r in enumerate(rows):
        try:
            uid = str(uuid.uuid4())
            email = strip_email(r.get("email", ""))
            if not email:
                skipped.append(f"row {i}: email kosong → {r}")
                continue
            # Support both 'nama' (full name) and 'nama_depan'+'nama_belakang' columns
            if "nama_depan" in r and "nama_belakang" in r:
                nama_depan = (r.get("nama_depan") or "").strip()
                nama_belakang = (r.get("nama_belakang") or "").strip()
            else:
                nama_depan, nama_belakang = split_name(r.get("nama", ""))
            tanggal_lahir = (r.get("tanggal_lahir") or "").strip()
            gender = (r.get("gender") or "").strip().upper()
            password = (r.get("password") or "").strip()
            if not nama_depan:
                skipped.append(f"row {i}: nama_depan kosong → {r}")
                continue
            if not tanggal_lahir:
                skipped.append(f"row {i}: tanggal_lahir kosong → {r}")
                continue
            if gender not in ("P", "W"):
                skipped.append(f"row {i}: gender invalid '{gender}' → {r}")
                continue
            prev_changes = conn.total_changes
            email_utama = (r.get("email_utama") or "").strip()
            conn.execute(
                """INSERT OR IGNORE INTO records (uid, username, nama_depan, nama_belakang, email, email_utama, tanggal_lahir, gender, password, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'antrian')""",
                (uid, username, nama_depan, nama_belakang, email, email_utama, tanggal_lahir, gender, password),
            )
            if conn.total_changes > prev_changes:
                count += 1
                prev_changes = conn.total_changes
        except (ValueError, KeyError) as e:
            skipped.append(f"row {i}: exception {e} → {r}")
            continue
    conn.commit()
    conn.close()
    return count, skipped


# ─── HTML Templates → lihat folder templates/ ────────────────────────────────

# ─── Routes ──────────────────────────────────────────────────────────────────


@app.get("/template")
def download_template():
    """Download template CSV file."""
    from fastapi.responses import FileResponse
    template_path = BASE_DIR / "template.csv"
    return FileResponse(
        path=str(template_path),
        filename="template.csv",
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=template.csv"},
    )


@app.get("/{username}/", response_class=HTMLResponse)
def list_data(
    request: Request,
    username: str,
    status: str = Query(""),
    gender: str = Query(""),
):
    """Tampilkan tabel semua data dengan filter opsional."""
    conn = get_db()
    conditions = ["username = ?"]
    params: list = [username]

    if status:
        conditions.append("status = ?")
        params.append(status)
    if gender:
        conditions.append("gender = ?")
        params.append(gender.upper())

    where = " AND ".join(conditions)
    rows = conn.execute(
        f"SELECT * FROM records WHERE {where} ORDER BY uid DESC", params
    ).fetchall()
    total = conn.execute(
        f"SELECT COUNT(*) FROM records WHERE {where}", params
    ).fetchone()[0]
    conn.close()

    rows_dict = [dict(r) for r in rows]
    return templates.TemplateResponse(
        request,
        "table.html",
        {
            "username": username,
            "rows": rows_dict,
            "total": total,
            "sel_status": status,
            "sel_gender": gender.upper(),
        },
    )


@app.get("/{username}/get/{uid}")
def get_one_antrian(username: str, uid: str):
    status = "entry"
    conn = get_db()
    if uid == "new":
        """Ambil 1 data status 'antrian', ubah jadi 'entry'. Return JSON."""
        row = conn.execute(
            "SELECT * FROM records WHERE username = ? AND status = 'antrian' ORDER BY uid ASC LIMIT 1",
            (username,),
        ).fetchone()

        if not row:
            conn.close()
            return JSONResponse(
                content={"message": "tidak ada antrian", "data": None}, status_code=404
            )

        conn.execute("UPDATE records SET status = 'entry' WHERE uid = ?", (row["uid"],))
        conn.commit()
        conn.close()
    elif uid in ("entry", "verivikasi", "sukses", "gagal"):
        """Ambil 1 data by status, ubah status jadi 'entry'."""
        row = conn.execute(
            "SELECT * FROM records WHERE username = ? AND status = ? ORDER BY uid ASC LIMIT 1",
            (username, uid),
        ).fetchone()

        if not row:
            conn.close()
            return JSONResponse(
                content={"message": f"tidak ada data dengan status '{uid}'", "data": None}, status_code=404
            )
        conn.execute("UPDATE records SET status = 'entry' WHERE uid = ?", (row["uid"],))
        conn.commit()
        conn.close()
    else:
        """Ambil 1 data by uid, ubah status jadi 'entry'."""
        row = conn.execute(
            "SELECT * FROM records WHERE username = ? AND uid = ?", (username, uid)
        ).fetchone()

        if not row:
            conn.close()
            return JSONResponse(
                content={"message": "data tidak ditemukan", "data": None}, status_code=404
            )
        status = row["status"]
        conn.execute("UPDATE records SET status = 'entry' WHERE uid = ?", (row["uid"],))
        conn.commit()
        conn.close()

    BULAN_ID = [
        "", "januari", "februari", "maret", "april", "mei", "juni",
        "juli", "agustus", "september", "oktober", "november", "desember"
    ]

    tgl_str = row["tanggal_lahir"]  # expected format: YYYY-MM-DD
    try:
        parts = tgl_str.split("-")
        tgl_y = int(parts[0])
        tgl_m = int(parts[1])
        tgl_d = int(parts[2])
        tgl_mmm = BULAN_ID[tgl_m]
    except Exception:
        tgl_y = tgl_m = tgl_d = 0
        tgl_mmm = ""

    return JSONResponse(
        content={
            "message": "data diambil dan status diubah menjadi entry",
            "data": {
                "uid": row["uid"],
                "nama_depan": row["nama_depan"],
                "nama_belakang": row["nama_belakang"],
                "nama": f"{row['nama_depan']} {row['nama_belakang']}".strip(),
                "email": row["email"],
                "email_utama": row["email_utama"],
                "tanggal_lahir": row["tanggal_lahir"],
                "tanggal_lahir_d": tgl_d,
                "tanggal_lahir_m": tgl_m,
                "tanggal_lahir_mmm": tgl_mmm,
                "tanggal_lahir_y": tgl_y,
                "gender": row["gender"],
                "password": row["password"],
                "status": status,
            },
        }
    )


@app.get("/{username}/get-html/{uid}", response_class=HTMLResponse)
def get_antrian_html(request: Request, username: str, uid: str):
    """Ambil 1 data antrian dan tampilkan sebagai halaman HTML yang bisa dicopy."""
    conn = get_db()
    if uid == "new":
        row = conn.execute(
            "SELECT * FROM records WHERE username = ? AND status = 'antrian' ORDER BY uid ASC LIMIT 1",
            (username,),
        ).fetchone()
        if not row:
            conn.close()
            return templates.TemplateResponse(
                request, "antrian.html",
                {"username": username, "nama": "", "fields": [], "error": "Tidak ada data dengan status antrian."},
                status_code=404,
            )
        conn.execute("UPDATE records SET status = 'entry' WHERE uid = ?", (row["uid"],))
        conn.commit()
        conn.close()
        return RedirectResponse(url=f"/{username}/get-html/{row['uid']}", status_code=302)
    else:
        row = conn.execute(
            "SELECT * FROM records WHERE username = ? AND uid = ?", (username, uid)
        ).fetchone()
        if not row:
            conn.close()
            return templates.TemplateResponse(
                request, "antrian.html",
                {"username": username, "nama": "", "fields": [], "table_plain": "", "error": "Data tidak ditemukan."},
                status_code=404,
            )
        conn.execute("UPDATE records SET status = 'entry' WHERE uid = ?", (row["uid"],))
        conn.commit()
        conn.close()

    BULAN_ID = ["", "januari", "februari", "maret", "april", "mei", "juni",
                "juli", "agustus", "september", "oktober", "november", "desember"]
    tgl_str = row["tanggal_lahir"]
    try:
        parts = tgl_str.split("-")
        tgl_y, tgl_m, tgl_d = int(parts[0]), int(parts[1]), int(parts[2])
        tgl_mmm = BULAN_ID[tgl_m]
    except Exception:
        tgl_y = tgl_m = tgl_d = 0
        tgl_mmm = ""

    nama = f"{row['nama_depan']} {row['nama_belakang']}".strip()
    field_data = [
        ("Nama Depan",    row["nama_depan"]),
        ("Nama Belakang", row["nama_belakang"]),
        ("Email Bapak",   row["email_utama"]),
        ("Email Anak",         row["email"]),
        ("Password",      row["password"]),
        ("FamilyLink",      'family link'),
        ("GoogleAkun",      'google akun'),
    ]
    fields = [(i, label, val, f"f{i}") for i, (label, val) in enumerate(field_data)]

    return templates.TemplateResponse(
        request, "antrian.html",
        {
            "username": username,
            "nama": nama,
            "fields": fields,
            "error": None,
        },
    )


@app.put("/{username}/edit/{uid}")
def edit_record(username: str, uid: str, body: dict):
    """Edit record (nama, email, tanggal_lahir, gender, password) by uid."""
    conn = get_db()
    # Check record exists and belongs to this user
    row = conn.execute(
        "SELECT * FROM records WHERE username = ? AND uid = ?",
        (username, uid),
    ).fetchone()
    if not row:
        conn.close()
        return JSONResponse(
            content={"message": "data tidak ditemukan"}, status_code=404
        )

    nama_depan = body.get("nama_depan", "").strip()
    nama_belakang = body.get("nama_belakang", "").strip()
    email_raw = body.get("email", "").strip()
    email_utama_raw = body.get("email_utama", "").strip()
    tanggal_lahir = body.get("tanggal_lahir", "").strip()
    gender = body.get("gender", "").strip().upper()
    password = body.get("password", "").strip()
    status = body.get("status", "").strip().lower()

    if not nama_depan or not email_raw or not tanggal_lahir or gender not in ("P", "W"):
        conn.close()
        return JSONResponse(
            content={"message": "data tidak valid (semua field wajib diisi, gender P/W)"},
            status_code=400,
        )

    if status not in ("antrian", "entry", "verivikasi", "sukses", "gagal"):
        conn.close()
        return JSONResponse(
            content={"message": "status tidak valid (antrian/entry/verivikasi/sukses/gagal)"},
            status_code=400,
        )

    email = strip_email(email_raw)
    email_utama = strip_email(email_utama_raw)
    conn.execute(
        """UPDATE records SET nama_depan=?, nama_belakang=?, email=?, email_utama=?, tanggal_lahir=?, gender=?, password=?, status=?
           WHERE username=? AND uid=?""",
        (nama_depan, nama_belakang, email, email_utama, tanggal_lahir, gender, password, status, username, uid),
    )
    conn.commit()
    conn.close()

    return JSONResponse(
        content={"message": "data berhasil diupdate", "updated": True}
    )


@app.delete("/{username}/clear")
def clear_data(username: str):
    """Hapus semua data milik username."""
    conn = get_db()
    cursor = conn.execute("DELETE FROM records WHERE username = ?", (username,))
    conn.commit()
    deleted = cursor.rowcount
    conn.close()
    return JSONResponse(
        content={"message": f"{deleted} data berhasil dihapus", "deleted": deleted}
    )

@app.delete("/{username}/delete/{uid}")
def delete_record(username: str, uid: str):
    """Hapus satu record berdasarkan uid."""
    conn = get_db()
    cursor = conn.execute(
        "DELETE FROM records WHERE username = ? AND uid = ?", (username, uid)
    )
    conn.commit()
    deleted = cursor.rowcount
    conn.close()

    if deleted == 0:
        return JSONResponse(
            content={"message": "data tidak ditemukan"}, status_code=404
        )

    return JSONResponse(
        content={"message": "data berhasil dihapus", "deleted": True}
    )

@app.get("/{username}/status/{status}/{uid}")
def update_status_sukses(username: str, uid: str, status: str):
    """Update status record berdasarkan uid."""
    conn = get_db()
    cursor = conn.execute(
        "UPDATE records SET status = ? WHERE username = ? AND uid = ? AND status != ?",
        (status, username, uid, status),
    )
    conn.commit()
    updated = cursor.rowcount
    conn.close()

    if updated == 0:
        return JSONResponse(
            content={"message": "data tidak ditemukan atau status sama", "updated": False},
            status_code=404,
        )

    return JSONResponse(
        content={"message": f"status uid {uid} diubah menjadi {status}", "updated": True}
    )



@app.get("/{username}/generate", response_class=HTMLResponse)
def generate_page(request: Request, username: str):
    """Tampilkan halaman generate data dengan AI."""
    return templates.TemplateResponse(
        request,
        "generate.html",
        {"username": username, "message": "", "msg_type": ""},
    )


@app.post("/{username}/generate")
async def generate_data(request: Request, username: str):
    """Generate data via AI — expects JSON body: {count, password}."""
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
        return JSONResponse(content={"message": "AI belum dikonfigurasi. Cek .env (ai_url, ai_model)."}, status_code=500)

    # Parse email_utama domains
    import random
    email_domains = []
    if email_utama_raw:
        # Split by comma or newline
        for part in email_utama_raw.replace("\n", ",").split(","):
            domain = part.strip().lower()
            if domain:
                # Ensure domain has @ prefix for easy appending
                if not domain.startswith("@"):
                    domain = "@" + domain
                email_domains.append(domain)

    if prefix:
        email_rule = f"email → '{prefix}' + nama_depan + 1 angka random + sedikit nama_belakang + angka random 2 sampai 4 digit + '@gmail.com'. Contoh: {prefix}budi2san23@gmail.com atau {prefix}sari1pur891@gmail.com."
    else:
        email_rule = "email → kombinasi nama_depan + 1 angka random + nama_belakang + 4 angka tahun sesuai tanggal lahir, semua pakai @gmail.com, lowercase"

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

    # print(f"[DEBUG] Prompt to AI ({len(prompt)} chars):")
    # print(prompt[:1000])
    
    try:
        response = ai_client.chat.completions.create(
            model=AI_MODEL,
            messages=[
                {"role": "user", "content": prompt}
            ],
            temperature=0.9,
            max_tokens=4000,
        )
        csv_text = response.choices[0].message.content.strip()
    except Exception as e:
        return JSONResponse(content={"message": f"AI error: {str(e)}"}, status_code=500)

    # Log raw AI response for debugging
    # print(f"[DEBUG] Raw AI response ({len(csv_text)} chars):")
    # print(csv_text[:1000])
    # print("---END RAW---")

    # Remove potential markdown code fences (more robust)
    csv_text = csv_text.strip()
    # Remove ```csv or ``` fences
    lines = csv_text.split("\n")
    # Remove leading fence line(s) that are only ``` or ```csv etc.
    while lines and lines[0].strip().startswith("```"):
        lines.pop(0)
    # Remove trailing fence line
    while lines and lines[-1].strip() == "```":
        lines.pop()
    # Also remove empty leading/trailing lines
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    csv_text = "\n".join(lines)

    # Robust header detection: check exact column names, not substring match
    EXPECTED_HEADER = "nama_depan,nama_belakang,email,tanggal_lahir,gender,password"
    EXPECTED_COLS = ["nama_depan", "nama_belakang", "email", "tanggal_lahir", "gender", "password"]

    first_line = csv_text.split("\n")[0].strip() if csv_text else ""
    first_cols = [c.strip().lower() for c in first_line.split(",")]

    # Header detection: ALL expected columns must appear in first row (exact match)
    has_header = all(col in first_cols for col in EXPECTED_COLS) and len(first_cols) >= len(EXPECTED_COLS)

    if has_header:
        # Parse with AI-provided header, but map to canonical names
        reader = csv.DictReader(io.StringIO(csv_text))
        raw_rows = list(reader)
        rows = []
        for r in raw_rows:
            normalized = {}
            for k, v in r.items():
                if v is not None:
                    normalized[k.strip().lower()] = v.strip()
            mapped = {field: normalized.get(field, "") for field in EXPECTED_COLS}
            rows.append(mapped)
    else:
        # AI returned data without header — prepend our own
        reader = csv.DictReader(io.StringIO(EXPECTED_HEADER + "\n" + csv_text))
        raw_rows = list(reader)
        rows = raw_rows

    if not rows or len(rows) == 0:
        return JSONResponse(content={"message": f"AI tidak menghasilkan data yang valid ({len(raw_rows) if 'raw_rows' in dir() else 0} baris).\nRaw AI output:\n{csv_text[:500]}", "raw_preview": csv_text[:500]}, status_code=500)

    # Replace email domains with random email_utama domains if provided
    if email_domains:
        for r in rows:
            email_local = r.get("email", "").split("@")[0]
            if email_local:
                r["email"] = email_local + random.choice(email_domains)
            # Also store the chosen domain in email_utama for reference
            r["email_utama"] = random.choice(email_domains).lstrip("@")

    inserted, skipped = insert_records(username, rows)
    response_data = {
        "message": f"Berhasil generate & insert {inserted} dari {count} data.",
        "inserted": inserted,
        "requested": count,
    }
    if skipped:
        response_data["skipped"] = skipped[:5]  # max 5 reasons to avoid huge response
        response_data["message"] += f" {len(skipped)} di-skip (cek 'skipped' field)."
    return JSONResponse(content=response_data)


# ─── Root ─────────────────────────────────────────────────────────────────────


@app.get("/{username}/settings")
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


@app.post("/{username}/settings")
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


@app.get("/favicon.ico")
def favicon():
    from fastapi.responses import Response
    return Response(status_code=204)


@app.get("/")
def root():
    return JSONResponse(
        content={
            "app": "GemaIL Data Manager"
        }
    )
