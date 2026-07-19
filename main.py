from fastapi import FastAPI

from app.database import init_db
from app.routes import data, generate, settings, misc

app = FastAPI(title="Gema-IL Data Manager")

# ─── Init DB ─────────────────────────────────────────────────────────────────
init_db()

# ─── Routers ─────────────────────────────────────────────────────────────────
app.include_router(misc.router)
app.include_router(data.router)
app.include_router(generate.router)
app.include_router(settings.router)
