from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text
from app.config import settings
from app.database import engine, Base, SessionLocal
import app.models  # Modellerin Base.metadata'ya kaydolması için import edilir
from app.seed import seed_default_equipment
from app.api.v1.api import api_router
from app.api.v1.planning import router as planning_router


def _ensure_sqlite_columns() -> None:
    """Mevcut SQLite tablolarına FAZ 6.1 & 6.2'de eklenen yeni sütunları veri silmeden ekler ve varsayılanları tamamlar."""
    try:
        insp = inspect(engine)
        with engine.begin() as conn:
            for table in Base.metadata.sorted_tables:
                if not insp.has_table(table.name):
                    continue
                existing_cols = {c["name"] for c in insp.get_columns(table.name)}
                for col in table.columns:
                    if col.name not in existing_cols:
                        col_type = col.type.compile(dialect=engine.dialect)
                        conn.execute(text(f"ALTER TABLE {table.name} ADD COLUMN {col.name} {col_type}"))
            if insp.has_table("documents"):
                conn.execute(
                    text(
                        "UPDATE documents SET dossier_key = 'DOSSIER-ELISA-2026', "
                        "dossier_label = 'ELISA TIBBI GEREÇLER — GLP2026-024/026/031/034' "
                        "WHERE dossier_key IS NULL OR dossier_key = ''"
                    )
                )
        db = SessionLocal()
        try:
            seed_default_equipment(db)
        finally:
            db.close()
    except Exception:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Veritabanı tablolarını oluştur ve eksik sütunları tamamla
    Base.metadata.create_all(bind=engine)
    _ensure_sqlite_columns()
    yield


app = FastAPI(
    title=settings.APP_NAME,
    description="Nanolab Edirne GLP Test Tesisi için Yapay Zeka Destekli Operasyonel Planlama ve Çakışma Yönetim Sistemi API",
    version="1.0.0",
    lifespan=lifespan
)

# CORS Yapılandırması (Frontend entegrasyonu için)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API Router dahil et
app.include_router(api_router, prefix=settings.API_V1_STR)
app.include_router(planning_router, prefix=settings.API_V1_STR)


@app.get("/")
def root():
    return {
        "message": "Nanolab Edirne GLP Test Tesisi API Servisi Aktif",
        "docs_url": "/docs",
        "health_check": f"{settings.API_V1_STR}/health"
    }
