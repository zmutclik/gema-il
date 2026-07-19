from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from app.database import get_db
from app.helpers import strip_email, parse_tanggal

BASE_DIR = Path(__file__).parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter()


@router.get("/{username}/", response_class=HTMLResponse)
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


@router.get("/{username}/get/{uid}")
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

    tgl = parse_tanggal(row["tanggal_lahir"])

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
                "tanggal_lahir_d": tgl["d"],
                "tanggal_lahir_m": tgl["m"],
                "tanggal_lahir_mmm": tgl["mmm"],
                "tanggal_lahir_y": tgl["y"],
                "gender": row["gender"],
                "password": row["password"],
                "status": status,
            },
        }
    )


@router.get("/{username}/get-html/entry", response_class=HTMLResponse)
def get_entry_html(request: Request, username: str):
    """Ambil 1 data status 'entry' dan tampilkan sebagai halaman HTML."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM records WHERE username = ? AND status = 'entry' ORDER BY uid ASC LIMIT 1",
        (username,),
    ).fetchone()
    if not row:
        conn.close()
        return templates.TemplateResponse(
            request, "antrian.html",
            {"username": username, "nama": "", "fields": [], "error": "Tidak ada data dengan status entry."},
            status_code=404,
        )
    conn.close()

    tgl = parse_tanggal(row["tanggal_lahir"])
    nama = f"{row['nama_depan']} {row['nama_belakang']}".strip()
    field_data = [
        ("Nama Depan",    row["nama_depan"]),
        ("Nama Belakang", row["nama_belakang"]),
        ("Email Bapak",   row["email_utama"]),
        ("Email Anak",    row["email"]),
        ("Password",      row["password"]),
        ("FamilyLink",    "family link"),
        ("GoogleAkun",    "google akun"),
    ]
    fields = [(i, label, val, f"f{i}") for i, (label, val) in enumerate(field_data)]

    return templates.TemplateResponse(
        request, "antrian.html",
        {
            "username": username,
            "uid": row["uid"],
            "current_status": "entry",
            "nama": nama,
            "fields": fields,
            "error": None,
        },
    )

@router.get("/{username}/get-html/verivikasi", response_class=HTMLResponse)
def get_verivikasi_html(request: Request, username: str):
    """Ambil 1 data status 'verivikasi' dan tampilkan sebagai halaman HTML."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM records WHERE username = ? AND status = 'verivikasi' ORDER BY uid ASC LIMIT 1",
        (username,),
    ).fetchone()
    if not row:
        conn.close()
        return templates.TemplateResponse(
            request, "antrian.html",
            {"username": username, "nama": "", "fields": [], "error": "Tidak ada data dengan status verivikasi."},
            status_code=404,
        )
    conn.close()

    tgl = parse_tanggal(row["tanggal_lahir"])
    nama = f"{row['nama_depan']} {row['nama_belakang']}".strip()
    field_data = [
        ("Nama Depan",    row["nama_depan"]),
        ("Nama Belakang", row["nama_belakang"]),
        ("Email Bapak",   row["email_utama"]),
        ("Email Anak",    row["email"]),
        ("Password",      row["password"]),
        ("FamilyLink",    "family link"),
        ("GoogleAkun",    "google akun"),
    ]
    fields = [(i, label, val, f"f{i}") for i, (label, val) in enumerate(field_data)]

    return templates.TemplateResponse(
        request, "antrian.html",
        {
            "username": username,
            "uid": row["uid"],
            "current_status": "verivikasi",
            "nama": nama,
            "fields": fields,
            "error": None,
        },
    )

@router.get("/{username}/get-html/{uid}", response_class=HTMLResponse)
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
        if row["status"] == "antrian":
            conn.execute("UPDATE records SET status = 'entry' WHERE uid = ?", (row["uid"],))
            conn.commit()
        conn.close()

    tgl = parse_tanggal(row["tanggal_lahir"])
    nama = f"{row['nama_depan']} {row['nama_belakang']}".strip()
    field_data = [
        ("Nama Depan",    row["nama_depan"]),
        ("Nama Belakang", row["nama_belakang"]),
        ("Email Bapak",   row["email_utama"]),
        ("Email Anak",    row["email"]),
        ("Password",      row["password"]),
        ("FamilyLink",    "family link"),
        ("GoogleAkun",    "google akun"),
    ]
    fields = [(i, label, val, f"f{i}") for i, (label, val) in enumerate(field_data)]

    return templates.TemplateResponse(
        request, "antrian.html",
        {
            "username": username,
            "uid": row["uid"],
            "current_status": row["status"],
            "nama": nama,
            "fields": fields,
            "error": None,
        },
    )


@router.put("/{username}/edit/{uid}")
def edit_record(username: str, uid: str, body: dict):
    """Edit record by uid."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM records WHERE username = ? AND uid = ?",
        (username, uid),
    ).fetchone()
    if not row:
        conn.close()
        return JSONResponse(content={"message": "data tidak ditemukan"}, status_code=404)

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
        """UPDATE records SET nama_depan=?, nama_belakang=?, email=?, email_utama=?,
           tanggal_lahir=?, gender=?, password=?, status=?
           WHERE username=? AND uid=?""",
        (nama_depan, nama_belakang, email, email_utama, tanggal_lahir, gender, password, status, username, uid),
    )
    conn.commit()
    conn.close()

    return JSONResponse(content={"message": "data berhasil diupdate", "updated": True})


@router.delete("/{username}/clear")
def clear_data(username: str):
    """Hapus semua data milik username."""
    conn = get_db()
    cursor = conn.execute("DELETE FROM records WHERE username = ?", (username,))
    conn.commit()
    deleted = cursor.rowcount
    conn.close()
    return JSONResponse(content={"message": f"{deleted} data berhasil dihapus", "deleted": deleted})


@router.delete("/{username}/delete/{uid}")
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
        return JSONResponse(content={"message": "data tidak ditemukan"}, status_code=404)

    return JSONResponse(content={"message": "data berhasil dihapus", "deleted": True})


@router.get("/{username}/status/{status}/{uid}")
def update_status(username: str, uid: str, status: str, redirect: str = Query("")):
    """Update status record berdasarkan uid. Jika dipanggil dari browser (redirect=html), redirect ke get-html."""
    conn = get_db()
    cursor = conn.execute(
        "UPDATE records SET status = ? WHERE username = ? AND uid = ? AND status != ?",
        (status, username, uid, status),
    )
    conn.commit()
    updated = cursor.rowcount
    conn.close()

    if redirect == "html":
        return RedirectResponse(url=f"/{username}/get-html/{uid}", status_code=302)

    if updated == 0:
        return JSONResponse(
            content={"message": "data tidak ditemukan atau status sama", "updated": False},
            status_code=404,
        )

    return JSONResponse(
        content={"message": f"status uid {uid} diubah menjadi {status}", "updated": True}
    )
