import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "data.db"


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
    # Migration: add columns if upgrading from old schema
    for col_def in [
        "ALTER TABLE records ADD COLUMN nama_depan TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE records ADD COLUMN nama_belakang TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE records ADD COLUMN email_utama TEXT NOT NULL DEFAULT ''",
    ]:
        try:
            conn.execute(col_def)
        except Exception:
            pass

    # Migrate existing nama → nama_depan + nama_belakang
    cols = [c[1] for c in conn.execute("PRAGMA table_info(records)").fetchall()]
    if "nama" in cols:
        old_rows = conn.execute(
            "SELECT uid, nama FROM records WHERE nama_depan = '' AND nama IS NOT NULL AND nama != ''"
        ).fetchall()
        for row in old_rows:
            from app.helpers import split_name
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
