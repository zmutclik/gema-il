import sqlite3
import csv
import io
import uuid
from pathlib import Path

from fastapi import FastAPI, Request, UploadFile, File, Query
from fastapi.responses import HTMLResponse, JSONResponse

# ─── App Setup ───────────────────────────────────────────────────────────────

app = FastAPI(title="Gema-IL Data Manager")

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "data.db"


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
            nama TEXT NOT NULL,
            email TEXT NOT NULL,
            tanggal_lahir TEXT NOT NULL,
            gender TEXT NOT NULL,
            password TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'antrian'
        )
    """)
    conn.commit()
    conn.close()


init_db()


# ─── Helpers ─────────────────────────────────────────────────────────────────


def strip_email(raw: str) -> str:
    """Strip domain from email, keep only the prefix before @."""
    return raw.strip().split("@")[0].lower()


def insert_records(username: str, rows: list[dict]) -> int:
    """Insert multiple records into DB. Returns count of inserted rows."""
    conn = get_db()
    count = 0
    for r in rows:
        try:
            uid = str(uuid.uuid4())
            email = strip_email(r.get("email", ""))
            if not email:
                continue
            nama = r.get("nama", "").strip()
            tanggal_lahir = r.get("tanggal_lahir", "").strip()
            gender = r.get("gender", "").strip().upper()
            password = r.get("password", "").strip()
            if not nama or not tanggal_lahir or gender not in ("P", "W"):
                continue
            prev_changes = conn.total_changes
            conn.execute(
                """INSERT OR IGNORE INTO records (uid, username, nama, email, tanggal_lahir, gender, password, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'antrian')""",
                (uid, username, nama, email, tanggal_lahir, gender, password),
            )
            if conn.total_changes > prev_changes:
                count += 1
                prev_changes = conn.total_changes
        except (ValueError, KeyError):
            continue
    conn.commit()
    conn.close()
    return count


# ─── HTML Templates (pure Python string formatting) ─────────────────────────


def render_table_page(username: str, rows, total: int, sel_status: str = "", sel_gender: str = "") -> str:
    """Render the data table page as HTML."""

    def sel(opt, val):
        return 'selected' if opt == val else ''

    # Build table rows
    row_html = ""
    if rows:
        for r in rows:
            row_html += f"""<tr>
                    <td>{r['nama']}</td>
                    <td>{r['email']}</td>
                    <td>{r['tanggal_lahir']}</td>
                    <td>{r['gender']}</td>
                    <td>{r['password']}</td>
                    <td><span class="badge badge-{r['status']}">{r['status']}</span></td>
                    <td>
                        <button class="btn-edit" onclick="openEdit('{r['uid']}','{r['nama']}','{r['email']}','{r['tanggal_lahir']}','{r['gender']}','{r['password']}')" title="Edit">✏️</button>
                        <a href="/{username}/status/sukses/{r['uid']}" style="color:#28a745;text-decoration:none;" title="Sukses">✅</a>
                        <a href="/{username}/status/gagal/{r['uid']}" style="color:#dc3545;text-decoration:none;margin-left:6px;" title="Gagal">❌</a>
                    </td>
                </tr>"""
        table_section = f"""<table>
            <thead>
                <tr><th>Nama</th><th>Email</th><th>Tanggal Lahir</th><th>Gender</th><th>Password</th><th>Status</th><th>Aksi</th></tr>
            </thead>
            <tbody>{row_html}</tbody>
        </table>"""
    else:
        table_section = '<p class="empty">🚫 Tidak ada data.</p>'

    return f"""<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Data {username}</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: system-ui, sans-serif; background: #f5f5f5; padding: 20px; }}
        .container {{ max-width: 1100px; margin: 0 auto; }}
        h1 {{ color: #333; margin-bottom: 20px; }}
        .nav {{ display: flex; gap: 10px; margin-bottom: 20px; flex-wrap: wrap; }}
        .nav a {{ padding: 8px 16px; background: #4a90d9; color: #fff; text-decoration: none; border-radius: 6px; font-size: 14px; }}
        .nav a:hover {{ background: #357abd; }}
        .filters {{ display: flex; gap: 10px; margin-bottom: 20px; flex-wrap: wrap; align-items: center; }}
        .filters select, .filters button {{ padding: 8px 12px; border-radius: 6px; border: 1px solid #ccc; font-size: 14px; }}
        .filters button {{ background: #28a745; color: #fff; border: none; cursor: pointer; }}
        .filters button:hover {{ background: #218838; }}
        table {{ width: 100%; border-collapse: collapse; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
        th, td {{ padding: 12px 15px; text-align: left; border-bottom: 1px solid #ddd; }}
        th {{ background: #4a90d9; color: #fff; font-weight: 600; }}
        tr:hover {{ background: #f1f7ff; }}
        .badge {{ padding: 4px 10px; border-radius: 12px; font-size: 12px; font-weight: 600; }}
        .badge-antrian {{ background: #fff3cd; color: #856404; }}
        .badge-sukses {{ background: #d4edda; color: #155724; }}
        .badge-gagal {{ background: #f8d7da; color: #721c24; }}
        .empty {{ text-align: center; color: #888; padding: 40px; }}
        .count {{ color: #666; margin-bottom: 10px; font-size: 14px; }}
        .btn-edit {{ background: none; border: none; cursor: pointer; font-size: 14px; padding: 2px 6px; }}
        .btn-edit:hover {{ background: #e8e8e8; border-radius: 4px; }}
        .modal {{ display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); z-index: 1000; justify-content: center; align-items: center; }}
        .modal.active {{ display: flex; }}
        .modal-content {{ background: #fff; padding: 30px; border-radius: 12px; max-width: 500px; width: 90%; box-shadow: 0 4px 20px rgba(0,0,0,0.2); }}
        .modal-content h2 {{ margin-bottom: 20px; color: #333; }}
        .modal-content label {{ display: block; font-weight: 600; margin-bottom: 4px; margin-top: 12px; color: #333; font-size: 13px; }}
        .modal-content input, .modal-content select {{ width: 100%; padding: 8px 12px; border: 1px solid #ccc; border-radius: 6px; font-size: 14px; }}
        .modal-actions {{ display: flex; gap: 10px; margin-top: 20px; justify-content: flex-end; }}
        .modal-actions button {{ padding: 8px 20px; border-radius: 6px; border: none; cursor: pointer; font-size: 14px; }}
        .btn-save {{ background: #28a745; color: #fff; }}
        .btn-save:hover {{ background: #218838; }}
        .btn-cancel {{ background: #6c757d; color: #fff; }}
        .btn-cancel:hover {{ background: #5a6268; }}
        .toast {{ display: none; position: fixed; bottom: 20px; right: 20px; padding: 12px 20px; border-radius: 8px; color: #fff; font-size: 14px; z-index: 2000; }}
        .toast-ok {{ background: #28a745; }}
        .toast-err {{ background: #dc3545; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📋 Data User: {username}</h1>
        <div class="nav">
            <a href="/{username}/import">📥 Import CSV</a>
            <a href="/{username}/get">🎯 Ambil Antrian</a>
            <a href="/template" style="background:#6c757d;">📄 Download Template CSV</a>
            <button onclick="confirmClear()" style="padding:8px 16px;background:#dc3545;color:#fff;border:none;border-radius:6px;font-size:14px;cursor:pointer;">🗑️ Clear Data</button>
        </div>
        <form class="filters" method="get">
            <label>Status:</label>
            <select name="status">
                <option value="">Semua</option>
                <option value="antrian" {sel(sel_status, 'antrian')}>Antrian</option>
                <option value="sukses" {sel(sel_status, 'sukses')}>Sukses</option>
                <option value="gagal" {sel(sel_status, 'gagal')}>Gagal</option>
            </select>
            <label>Gender:</label>
            <select name="gender">
                <option value="">Semua</option>
                <option value="P" {sel(sel_gender, 'P')}>Pria</option>
                <option value="W" {sel(sel_gender, 'W')}>Wanita</option>
            </select>
            <button type="submit">🔍 Filter</button>
            <a href="/{username}/" style="padding:8px 12px;color:#dc3545;text-decoration:none;">Reset</a>
        </form>
        <p class="count">Total: {total} data</p>
        {table_section}
    </div>

    <!-- Confirm Clear Modal -->
    <div class="modal" id="clearModal">
        <div class="modal-content" style="max-width:400px;text-align:center;">
            <h2 style="color:#dc3545;">🗑️ Clear Data</h2>
            <p style="margin:16px 0;color:#555;">Hapus <strong>semua data</strong> milik user <strong>{username}</strong>?<br>Tindakan ini tidak dapat dibatalkan.</p>
            <div style="display:flex;gap:10px;justify-content:center;margin-top:20px;">
                <button class="btn-cancel" onclick="document.getElementById('clearModal').classList.remove('active')">Batal</button>
                <button class="btn-save" style="background:#dc3545;" onclick="doClear()">Ya, Hapus Semua</button>
            </div>
        </div>
    </div>

    <!-- Edit Modal -->
    <div class="modal" id="editModal">
        <div class="modal-content">
            <h2>✏️ Edit Data</h2>
            <form id="editForm">
                <input type="hidden" id="editUid" name="uid">
                <label>Nama</label>
                <input type="text" id="editNama" name="nama" required>
                <label>Email</label>
                <input type="text" id="editEmail" name="email" required>
                <label>Tanggal Lahir</label>
                <input type="text" id="editTgl" name="tanggal_lahir" placeholder="YYYY-MM-DD" required>
                <label>Gender</label>
                <select id="editGender" name="gender" required>
                    <option value="P">Pria</option>
                    <option value="W">Wanita</option>
                </select>
                <label>Password</label>
                <input type="text" id="editPassword" name="password" required>
                <div class="modal-actions">
                    <button type="button" class="btn-cancel" onclick="closeEdit()">Batal</button>
                    <button type="submit" class="btn-save">Simpan</button>
                </div>
            </form>
        </div>
    </div>

    <!-- Toast -->
    <div class="toast" id="toast"></div>

    <script>
        const username = "{username}";

        function openEdit(uid, nama, email, tgl, gender, pass) {{
            document.getElementById('editUid').value = uid;
            document.getElementById('editNama').value = nama;
            document.getElementById('editEmail').value = email;
            document.getElementById('editTgl').value = tgl;
            document.getElementById('editGender').value = gender;
            document.getElementById('editPassword').value = pass;
            document.getElementById('editModal').classList.add('active');
        }}

        function closeEdit() {{
            document.getElementById('editModal').classList.remove('active');
        }}

        function showToast(msg, ok) {{
            const t = document.getElementById('toast');
            t.textContent = msg;
            t.className = 'toast ' + (ok ? 'toast-ok' : 'toast-err');
            t.style.display = 'block';
            setTimeout(function() {{ t.style.display = 'none'; }}, 3000);
        }}

        document.getElementById('editForm').addEventListener('submit', async function(e) {{
            e.preventDefault();
            const uid = document.getElementById('editUid').value;
            const body = {{
                nama: document.getElementById('editNama').value,
                email: document.getElementById('editEmail').value,
                tanggal_lahir: document.getElementById('editTgl').value,
                gender: document.getElementById('editGender').value,
                password: document.getElementById('editPassword').value,
            }};
            try {{
                const resp = await fetch('/' + username + '/edit/' + uid, {{
                    method: 'PUT',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify(body)
                }});
                const data = await resp.json();
                if (resp.ok) {{
                    showToast('✅ Data berhasil diupdate!', true);
                    closeEdit();
                    setTimeout(() => location.reload(), 600);
                }} else {{
                    showToast('❌ ' + (data.message || 'Gagal update'), false);
                }}
            }} catch(err) {{
                showToast('❌ Gagal terhubung ke server', false);
            }}
        }});

        // Close modal on outside click
        document.getElementById('editModal').addEventListener('click', function(e) {{
            if (e.target === this) closeEdit();
        }});
        document.getElementById('clearModal').addEventListener('click', function(e) {{
            if (e.target === this) this.classList.remove('active');
        }});

        function confirmClear() {{
            document.getElementById('clearModal').classList.add('active');
        }}

        async function doClear() {{
            document.getElementById('clearModal').classList.remove('active');
            try {{
                const resp = await fetch('/' + username + '/clear', {{ method: 'DELETE' }});
                const data = await resp.json();
                if (resp.ok) {{
                    showToast('🗑️ ' + data.message, true);
                    setTimeout(() => location.reload(), 800);
                }} else {{
                    showToast('❌ ' + (data.message || 'Gagal menghapus'), false);
                }}
            }} catch(err) {{
                showToast('❌ Gagal terhubung ke server', false);
            }}
        }}
    </script>
</body>
</html>"""


def render_import_page(username: str, message: str = "", msg_type: str = "") -> str:
    """Render the CSV import form page."""
    msg_html = f'<div class="msg msg-{msg_type}">{message}</div>' if message else ""
    return f"""<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Import CSV - {username}</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: system-ui, sans-serif; background: #f5f5f5; padding: 20px; }}
        .container {{ max-width: 600px; margin: 60px auto; background: #fff; padding: 30px; border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,0.1); }}
        h1 {{ margin-bottom: 10px; color: #333; }}
        p {{ color: #666; margin-bottom: 20px; font-size: 14px; }}
        .back {{ display: inline-block; margin-bottom: 20px; color: #4a90d9; text-decoration: none; font-size: 14px; }}
        label {{ display: block; font-weight: 600; margin-bottom: 8px; color: #333; }}
        input[type="file"] {{ display: block; margin-bottom: 16px; }}
        button {{ padding: 10px 24px; background: #4a90d9; color: #fff; border: none; border-radius: 6px; cursor: pointer; font-size: 14px; }}
        button:hover {{ background: #357abd; }}
        .note {{ margin-top: 16px; padding: 12px; background: #fff3cd; border-radius: 6px; font-size: 13px; color: #856404; }}
        .msg {{ margin-bottom: 16px; padding: 10px; border-radius: 6px; font-size: 14px; }}
        .msg-ok {{ background: #d4edda; color: #155724; }}
        .msg-err {{ background: #f8d7da; color: #721c24; }}
        .prompt-box {{ margin-top: 20px; padding: 16px; background: #f0f4ff; border: 1px solid #c5d3f0; border-radius: 8px; font-size: 13px; color: #2c3e6b; }}
        .prompt-box h3 {{ margin-bottom: 10px; font-size: 14px; color: #1a2a5e; }}
        .prompt-box pre {{ background: #e8edf8; border-radius: 6px; padding: 12px; white-space: pre-wrap; word-break: break-word; font-family: monospace; font-size: 12px; line-height: 1.6; color: #1a1a2e; margin-top: 8px; }}
        .copy-btn {{ margin-top: 10px; padding: 6px 14px; background: #4a90d9; color: #fff; border: none; border-radius: 5px; cursor: pointer; font-size: 12px; }}
        .copy-btn:hover {{ background: #357abd; }}
    </style>
</head>
<body>
    <div class="container">
        <a class="back" href="/{username}/">← Kembali ke tabel</a>
        <h1>📥 Import CSV</h1>
        <p>Upload file CSV dengan kolom: <strong>nama, email, tanggal_lahir, gender, password</strong></p>
        <p><a href="/template" style="color:#4a90d9;">📄 Download Template CSV</a></p>
        {msg_html}
        <form method="post" enctype="multipart/form-data">
            <label for="file">Pilih file CSV:</label>
            <input type="file" id="file" name="file" accept=".csv" required>
            <button type="submit">Upload & Import</button>
        </form>

        <div class="prompt-box">
            <h3>🤖 Prompt AI untuk Generate 100 Data CSV</h3>
            <p>Gunakan prompt berikut di ChatGPT / Gemini / Copilot untuk membuat data CSV secara otomatis:</p>
            <pre id="aiPrompt">Buatkan file CSV dengan 100 data random menggunakan kolom berikut:

- nama → nama lengkap Indonesia (nama depan + belakang)
- email → kombinasi nama depan + nama belakang + angka random, semua pakai @gmail.com
- tanggal_lahir → format YYYY-MM-DD, umur random antara 4 sampai 11 tahun
- gender → P atau W
- password → semua disamakan dengan nilai GANTIPASSWORD

Simpan sebagai file CSV dan tampilkan 5 baris pertama sebagai preview.</pre>
            <button class="copy-btn" onclick="copyPrompt()">📋 Salin Prompt</button>
        </div>
    </div>

    <script>
        function copyPrompt() {{
            const text = document.getElementById('aiPrompt').innerText;
            navigator.clipboard.writeText(text).then(function() {{
                const btn = document.querySelector('.copy-btn');
                btn.textContent = '✅ Tersalin!';
                setTimeout(function() {{ btn.textContent = '📋 Salin Prompt'; }}, 2000);
            }}).catch(function() {{
                alert('Gagal menyalin. Silakan salin manual.');
            }});
        }}
    </script>
</body>
</html>"""


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

    html = render_table_page(username, rows, total, status, gender.upper())
    return HTMLResponse(content=html)


@app.get("/{username}/get")
def get_one_antrian(username: str):
    """Ambil 1 data status 'antrian', langsung ubah jadi 'sukses'. Return JSON."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM records WHERE username = ? AND status = 'antrian' ORDER BY uid ASC LIMIT 1",
        (username,),
    ).fetchone()

    if not row:
        conn.close()
        return JSONResponse(
            content={"message": "tidak ada antrian", "data": None}, status_code=404
        )

    conn.execute("UPDATE records SET status = 'sukses' WHERE uid = ?", (row["uid"],))
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
            "message": "data diambil dan status diubah menjadi sukses",
            "data": {
                "uid": row["uid"],
                "nama": row["nama"],
                "email": row["email"],
                "tanggal_lahir": row["tanggal_lahir"],
                "tanggal_lahir_d": tgl_d,
                "tanggal_lahir_m": tgl_m,
                "tanggal_lahir_mmm": tgl_mmm,
                "tanggal_lahir_y": tgl_y,
                "gender": row["gender"],
                "password": row["password"],
                "status": "sukses",
            },
        }
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

    nama = body.get("nama", "").strip()
    email_raw = body.get("email", "").strip()
    tanggal_lahir = body.get("tanggal_lahir", "").strip()
    gender = body.get("gender", "").strip().upper()
    password = body.get("password", "").strip()

    if not nama or not email_raw or not tanggal_lahir or gender not in ("P", "W"):
        conn.close()
        return JSONResponse(
            content={"message": "data tidak valid (semua field wajib diisi, gender P/W)"},
            status_code=400,
        )

    email = strip_email(email_raw)
    conn.execute(
        """UPDATE records SET nama=?, email=?, tanggal_lahir=?, gender=?, password=?
           WHERE username=? AND uid=?""",
        (nama, email, tanggal_lahir, gender, password, username, uid),
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


@app.get("/{username}/status/sukses/{uid}")
def update_status_sukses(username: str, uid: str):
    """Update status record menjadi 'sukses' berdasarkan uid."""
    conn = get_db()
    cursor = conn.execute(
        "UPDATE records SET status = 'sukses' WHERE username = ? AND uid = ? AND status != 'sukses'",
        (username, uid),
    )
    conn.commit()
    updated = cursor.rowcount
    conn.close()

    if updated == 0:
        return JSONResponse(
            content={"message": "data tidak ditemukan atau sudah sukses", "updated": False},
            status_code=404,
        )

    return JSONResponse(
        content={"message": f"status uid {uid} diubah menjadi sukses", "updated": True}
    )


@app.get("/{username}/status/gagal/{uid}")
def update_status_gagal(username: str, uid: str):
    """Update status record menjadi 'gagal' berdasarkan uid."""
    conn = get_db()
    cursor = conn.execute(
        "UPDATE records SET status = 'gagal' WHERE username = ? AND uid = ? AND status != 'gagal'",
        (username, uid),
    )
    conn.commit()
    updated = cursor.rowcount
    conn.close()

    if updated == 0:
        return JSONResponse(
            content={"message": "data tidak ditemukan atau sudah gagal", "updated": False},
            status_code=404,
        )

    return JSONResponse(
        content={"message": f"status uid {uid} diubah menjadi gagal", "updated": True}
    )


@app.get("/{username}/import", response_class=HTMLResponse)
def import_page(request: Request, username: str):
    """Tampilkan halaman form upload CSV."""
    return HTMLResponse(content=render_import_page(username))


@app.post("/{username}/import", response_class=HTMLResponse)
async def import_csv(request: Request, username: str, file: UploadFile = File(...)):
    """Proses upload CSV dan insert ke database."""
    message = ""
    msg_type = "err"

    if not file.filename or not file.filename.lower().endswith(".csv"):
        message = "❌ File harus berformat CSV."
    else:
        try:
            content = await file.read()
            text = content.decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(text))

            if not reader.fieldnames:
                message = "❌ CSV kosong atau header tidak valid."
            else:
                rows = list(reader)
                count = insert_records(username, rows)
                if count > 0:
                    message = f"✅ Berhasil mengimport {count} data ke user '{username}'."
                    msg_type = "ok"
                else:
                    message = "⚠️ Tidak ada data valid yang diimport. Periksa format CSV."
        except Exception as e:
            message = f"❌ Gagal memproses file: {str(e)}"

    return HTMLResponse(content=render_import_page(username, message, msg_type))


# ─── Root ─────────────────────────────────────────────────────────────────────


@app.get("/")
def root():
    return JSONResponse(
        content={
            "app": "Gema-IL Data Manager",
            # "usage": "Akses /{username}/ untuk melihat data user tersebut.",
            # "endpoints": {
            #     "GET /{username}/": "Tabel data + filter (?status=, ?gender=)",
            #     "GET /{username}/get": "Ambil 1 antrian → sukses",
            #     "GET /{username}/status/sukses/{email}": "Update status ke sukses",
            #     "GET /{username}/status/gagal/{email}": "Update status ke gagal",
            #     "GET /{username}/import": "Form upload CSV",
            #     "POST /{username}/import": "Proses upload CSV",
            # },
        }
    )
