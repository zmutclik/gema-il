import uuid

BULAN_ID = [
    "", "januari", "februari", "maret", "april", "mei", "juni",
    "juli", "agustus", "september", "oktober", "november", "desember"
]


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


def parse_tanggal(tgl_str: str) -> dict:
    """Parse tanggal lahir string YYYY-MM-DD → dict dengan d, m, mmm, y."""
    try:
        parts = tgl_str.split("-")
        tgl_y = int(parts[0])
        tgl_m = int(parts[1])
        tgl_d = int(parts[2])
        tgl_mmm = BULAN_ID[tgl_m]
    except Exception:
        tgl_y = tgl_m = tgl_d = 0
        tgl_mmm = ""
    return {"d": tgl_d, "m": tgl_m, "mmm": tgl_mmm, "y": tgl_y}


def insert_records(username: str, rows: list[dict]) -> tuple[int, list]:
    """Insert multiple records into DB. Returns (count, skipped_reasons)."""
    from app.database import get_db
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
                """INSERT OR IGNORE INTO records
                   (uid, username, nama_depan, nama_belakang, email, email_utama, tanggal_lahir, gender, password, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'antrian')""",
                (uid, username, nama_depan, nama_belakang, email, email_utama, tanggal_lahir, gender, password),
            )
            if conn.total_changes > prev_changes:
                count += 1
        except (ValueError, KeyError) as e:
            skipped.append(f"row {i}: exception {e} → {r}")
            continue
    conn.commit()
    conn.close()
    return count, skipped
