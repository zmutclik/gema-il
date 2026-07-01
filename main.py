import sqlite3
import csv
import io
import uuid
import os
import json
from pathlib import Path

from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse
from dotenv import load_dotenv
from openai import OpenAI

# ─── App Setup ───────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent

load_dotenv(BASE_DIR / ".env")

app = FastAPI(title="Gema-IL Data Manager")

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
            conn.execute(
                """INSERT OR IGNORE INTO records (uid, username, nama_depan, nama_belakang, email, tanggal_lahir, gender, password, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'antrian')""",
                (uid, username, nama_depan, nama_belakang, email, tanggal_lahir, gender, password),
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
                    <td>{r['nama_depan']}</td>
                    <td>{r['nama_belakang']}</td>
                    <td>{r['email']}</td>
                    <td>{r['tanggal_lahir']}</td>
                    <td>{r['gender']}</td>
                    <td>{r['password']}</td>
                    <td><span class="badge badge-{r['status']}">{r['status']}</span></td>
                    <td>
                        <button class="btn-edit" onclick="openEdit('{r['uid']}','{r['nama_depan']}','{r['nama_belakang']}','{r['email']}','{r['tanggal_lahir']}','{r['gender']}','{r['password']}')" title="Edit">✏️</button>
                        <a href="/{username}/status/sukses/{r['uid']}" style="color:#28a745;text-decoration:none;" title="Sukses">✅</a>
                        <a href="/{username}/status/gagal/{r['uid']}" style="color:#dc3545;text-decoration:none;margin-left:6px;" title="Gagal">❌</a>
                    </td>
                </tr>"""
        table_section = f"""<table>
            <thead>
                <tr><th>Nama Depan</th><th>Nama Belakang</th><th>Email</th><th>Tanggal Lahir</th><th>Gender</th><th>Password</th><th>Status</th><th>Aksi</th></tr>
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
            <a href="/{username}/generate">🤖 Generate Data</a>
            <a href="/{username}/get">🎯 Ambil Antrian</a>
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
                <label>Nama Depan</label>
                <input type="text" id="editNamaDepan" name="nama_depan" required>
                <label>Nama Belakang</label>
                <input type="text" id="editNamaBelakang" name="nama_belakang">
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

        function openEdit(uid, nama_depan, nama_belakang, email, tgl, gender, pass) {{
            document.getElementById('editUid').value = uid;
            document.getElementById('editNamaDepan').value = nama_depan;
            document.getElementById('editNamaBelakang').value = nama_belakang;
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
                nama_depan: document.getElementById('editNamaDepan').value,
                nama_belakang: document.getElementById('editNamaBelakang').value,
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


def render_generate_page(username: str, message: str = "", msg_type: str = "") -> str:
    """Render the AI Generate data page."""
    msg_html = f'<div class="msg msg-{msg_type}">{message}</div>' if message else ""
    return f"""<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Generate Data - {username}</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: system-ui, sans-serif; background: #f5f5f5; padding: 20px; }}
        .container {{ max-width: 600px; margin: 60px auto; background: #fff; padding: 30px; border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,0.1); }}
        h1 {{ margin-bottom: 10px; color: #333; }}
        p {{ color: #666; margin-bottom: 20px; font-size: 14px; }}
        .back {{ display: inline-block; margin-bottom: 20px; color: #4a90d9; text-decoration: none; font-size: 14px; }}
        label {{ display: block; font-weight: 600; margin-bottom: 8px; color: #333; }}
        input[type="number"], input[type="password"] {{ width: 100%; padding: 10px 14px; border: 1px solid #ccc; border-radius: 6px; font-size: 14px; margin-bottom: 16px; }}
        button {{ padding: 10px 24px; background: #4a90d9; color: #fff; border: none; border-radius: 6px; cursor: pointer; font-size: 14px; }}
        button:hover {{ background: #357abd; }}
        .msg {{ margin-bottom: 16px; padding: 10px; border-radius: 6px; font-size: 14px; }}
        .msg-ok {{ background: #d4edda; color: #155724; }}
        .msg-err {{ background: #f8d7da; color: #721c24; }}
        .msg-info {{ background: #cce5ff; color: #004085; }}
        .loading {{ display: none; text-align: center; margin: 20px 0; }}
        .loading.active {{ display: block; }}
        .spinner {{ border: 4px solid #f3f3f3; border-top: 4px solid #4a90d9; border-radius: 50%; width: 40px; height: 40px; animation: spin 1s linear infinite; margin: 0 auto 10px; }}
        @keyframes spin {{ 0% {{ transform: rotate(0deg); }} 100% {{ transform: rotate(360deg); }} }}

        /* Modal Styles */
        .modal-overlay {{ display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); z-index: 1000; justify-content: center; align-items: center; }}
        .modal-overlay.active {{ display: flex; }}
        .modal-box {{ background: #fff; padding: 30px; border-radius: 12px; max-width: 420px; width: 90%; box-shadow: 0 4px 20px rgba(0,0,0,0.2); text-align: center; }}
        .modal-box h2 {{ margin-bottom: 12px; color: #333; font-size: 20px; }}
        .modal-box p {{ color: #666; margin-bottom: 20px; font-size: 14px; }}
        .modal-box label {{ text-align: left; display: block; font-weight: 600; margin-bottom: 6px; color: #333; font-size: 13px; }}
        .modal-box input {{ width: 100%; padding: 10px 14px; border: 1px solid #ccc; border-radius: 6px; font-size: 14px; margin-bottom: 14px; }}
        .modal-actions {{ display: flex; gap: 10px; justify-content: center; }}
        .btn-generate {{ background: #28a745; color: #fff; padding: 10px 24px; border: none; border-radius: 6px; cursor: pointer; font-size: 14px; }}
        .btn-generate:hover {{ background: #218838; }}
        .btn-cancel {{ background: #6c757d; color: #fff; padding: 10px 24px; border: none; border-radius: 6px; cursor: pointer; font-size: 14px; }}
        .btn-cancel:hover {{ background: #5a6268; }}
        .btn-generate:disabled {{ background: #88c999; cursor: not-allowed; }}
    </style>
</head>
<body>
    <div class="container">
        <a class="back" href="/{username}/">← Kembali ke tabel</a>
        <h1>🤖 Generate Data dengan AI</h1>
        <p>Generate data random menggunakan AI langsung ke database.</p>
        {msg_html}

        <button onclick="openGenerateModal()" style="background:#28a745;padding:12px 28px;font-size:15px;">🤖 Generate Data</button>

        <div class="loading" id="loading">
            <div class="spinner"></div>
            <p style="color:#666;">AI sedang membuat data... mohon tunggu.</p>
        </div>
    </div>

    <!-- Generate Modal -->
    <div class="modal-overlay" id="generateModal">
        <div class="modal-box">
            <h2>🤖 Generate Data</h2>
            <p>Masukkan jumlah data yang ingin dibuat (max 100).</p>
            <label for="genCount">Jumlah Data:</label>
            <input type="number" id="genCount" min="1" max="100" value="10" placeholder="1-100">
            <label for="genPassword">Password:</label>
            <input type="text" id="genPassword" placeholder="Masukkan password">
            <label for="genPrefix">Prefix Email (opsional):</label>
            <input type="text" id="genPrefix" placeholder="Contoh: user → user123@gmail.com">
            <div class="modal-actions">
                <button class="btn-cancel" onclick="closeGenerateModal()">Batal</button>
                <button class="btn-generate" id="btnGenerate" onclick="doGenerate()">🤖 Generate</button>
            </div>
        </div>
    </div>

    <script>
        function openGenerateModal() {{
            document.getElementById('generateModal').classList.add('active');
            document.getElementById('genCount').value = 10;
            document.getElementById('genPassword').value = '';
            document.getElementById('genPrefix').value = '';
        }}

        function closeGenerateModal() {{
            document.getElementById('generateModal').classList.remove('active');
        }}

        document.getElementById('generateModal').addEventListener('click', function(e) {{
            if (e.target === this) closeGenerateModal();
        }});

        async function doGenerate() {{
            const count = parseInt(document.getElementById('genCount').value);
            const password = document.getElementById('genPassword').value.trim();
            const prefix = document.getElementById('genPrefix').value.trim();

            if (!count || count < 1 || count > 100) {{
                alert('Jumlah data harus antara 1 - 100.');
                return;
            }}

            if (!password) {{
                alert('Password wajib diisi.');
                return;
            }}

            closeGenerateModal();
            document.getElementById('loading').classList.add('active');
            const btn = document.querySelector('.container > button');
            btn.disabled = true;

            try {{
                const resp = await fetch('/{username}/generate', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ count: count, password: password, prefix: prefix }})
                }});
                const data = await resp.json();

                if (resp.ok) {{
                    const msgDiv = document.querySelector('.msg');
                    if (msgDiv) msgDiv.remove();
                    const newMsg = document.createElement('div');
                    newMsg.className = 'msg msg-ok';
                    newMsg.textContent = '✅ ' + data.message;
                    document.querySelector('.container').insertBefore(newMsg, document.querySelector('.container > button'));
                    setTimeout(function() {{ location.href = '/{username}/'; }}, 2000);
                }} else {{
                    const msgDiv = document.querySelector('.msg');
                    if (msgDiv) msgDiv.remove();
                    const newMsg = document.createElement('div');
                    newMsg.className = 'msg msg-err';
                    newMsg.textContent = '❌ ' + (data.message || 'Gagal generate');
                    document.querySelector('.container').insertBefore(newMsg, document.querySelector('.container > button'));
                }}
            }} catch(err) {{
                const msgDiv = document.querySelector('.msg');
                if (msgDiv) msgDiv.remove();
                const newMsg = document.createElement('div');
                newMsg.className = 'msg msg-err';
                newMsg.textContent = '❌ Gagal terhubung ke server atau AI.';
                document.querySelector('.container').insertBefore(newMsg, document.querySelector('.container > button'));
            }} finally {{
                document.getElementById('loading').classList.remove('active');
                btn.disabled = false;
            }}
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
                "nama_depan": row["nama_depan"],
                "nama_belakang": row["nama_belakang"],
                "nama": f"{row['nama_depan']} {row['nama_belakang']}".strip(),
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

    nama_depan = body.get("nama_depan", "").strip()
    nama_belakang = body.get("nama_belakang", "").strip()
    email_raw = body.get("email", "").strip()
    tanggal_lahir = body.get("tanggal_lahir", "").strip()
    gender = body.get("gender", "").strip().upper()
    password = body.get("password", "").strip()

    if not nama_depan or not email_raw or not tanggal_lahir or gender not in ("P", "W"):
        conn.close()
        return JSONResponse(
            content={"message": "data tidak valid (semua field wajib diisi, gender P/W)"},
            status_code=400,
        )

    email = strip_email(email_raw)
    conn.execute(
        """UPDATE records SET nama_depan=?, nama_belakang=?, email=?, tanggal_lahir=?, gender=?, password=?
           WHERE username=? AND uid=?""",
        (nama_depan, nama_belakang, email, tanggal_lahir, gender, password, username, uid),
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


@app.get("/{username}/generate", response_class=HTMLResponse)
def generate_page(request: Request, username: str):
    """Tampilkan halaman generate data dengan AI."""
    return HTMLResponse(content=render_generate_page(username))


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

    if not isinstance(count, int) or count < 1 or count > 100:
        return JSONResponse(content={"message": "Jumlah data harus antara 1 - 100."}, status_code=400)

    if not password:
        return JSONResponse(content={"message": "Password wajib diisi."}, status_code=400)

    if ai_client is None:
        return JSONResponse(content={"message": "AI belum dikonfigurasi. Cek .env (ai_url, ai_model)."}, status_code=500)

    if prefix:
        email_rule = f"email → '{prefix}' + nama_depan + 1 angka random + sedikit nama_belakang + angka random 2 sampai 4 digit + '@gmail.com'. Contoh: {prefix}budi2san23@gmail.com atau {prefix}sari1pur891@gmail.com."
    else:
        email_rule = "email → kombinasi nama_depan + 1 angka random + nama_belakang + 4 angka random sampai 5 angka random, semua pakai @gmail.com, lowercase"

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

    print(f"[DEBUG] Prompt to AI ({len(prompt)} chars):")
    print(prompt[:1000])
    
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
    print(f"[DEBUG] Raw AI response ({len(csv_text)} chars):")
    print(csv_text[:1000])
    print("---END RAW---")

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
