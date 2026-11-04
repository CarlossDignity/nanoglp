from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, text

from app.config import settings
from app.database import engine, Base, SessionLocal
import app.models  # Modellerin Base.metadata'ya kaydolması için import edilir
from app.seed import seed_default_equipment
from app.services.templates import ensure_default_calibrations
from app.models.role_permission import ensure_default_role_permissions
from app.api.v1.api import api_router
from app.api.v1.planning import router as planning_router
from app.api.v1.endpoints import auth as auth_endpoints
from app.api.v1.endpoints import health as health_endpoints
from app.api.v1.endpoints import samples as samples_endpoints
from app.api.v1.endpoints import users as users_endpoints
from app.services.sample_service import seed_sample_tracking

FRONTEND_DIST_DIR = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


def _migrate_faz84_yigit_and_cleanups(db) -> None:
    """FAZ 8.4: 'yigit' hesabını SYSADMIN olarak garantiye alır ve yalnızca açıkça is_historical_demo olarak işaretli demo kayıtları temizler."""
    from app.models.user import User, UserRole
    from app.models.study import Study
    from app.models.study_step import StudyStep
    from app.models.conflict import Conflict
    from app.models.sample import SampleRecord

    yigit = db.query(User).filter(User.username == "yigit").first()
    if yigit is not None:
        yigit.role = UserRole.SYSADMIN
        yigit.department = "Sistem Yönetimi"
        yigit.is_active = True
        db.commit()

    sample_codes = {s.study_code for s in db.query(SampleRecord).all() if s.study_code}
    if len(sample_codes) >= 88:
        bogus_studies = [
            st for st in db.query(Study).all()
            if st.study_code not in sample_codes
            and isinstance(getattr(st, "dossier_metadata", None), dict)
            and st.dossier_metadata.get("is_historical_demo") is True
        ]
        if bogus_studies:
            for bst in bogus_studies:
                db.query(Conflict).filter(
                    (Conflict.study_id == bst.id) | (Conflict.related_study_id == bst.id)
                ).delete(synchronize_session=False)
                for st_step in db.query(StudyStep).filter(StudyStep.study_id == bst.id).all():
                    st_step.assignees = []
                    db.delete(st_step)
                db.delete(bst)
            db.commit()


def _ensure_sqlite_columns() -> None:
    """Mevcut SQLite tablolarına FAZ 6.1–7.2'de eklenen yeni sütunları veri silmeden ekler ve varsayılanları tamamlar."""
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
                        "WHERE (dossier_key IS NULL OR dossier_key = '') AND original_filename LIKE 'IMG_20261027_%'"
                    )
                )
                conn.execute(
                    text(
                        "UPDATE documents SET dossier_key = 'DOSSIER-REF-ARCHIVE', "
                        "dossier_label = 'Referans Standartlar ve Arşiv Belgeleri' "
                        "WHERE (dossier_key IS NULL OR dossier_key = '' OR dossier_key = 'DOSSIER-ELISA-2026') "
                        "AND original_filename NOT LIKE 'IMG_20261027_%'"
                    )
                )
        db = SessionLocal()
        try:
            seed_default_equipment(db)
            ensure_default_calibrations(db)
            ensure_default_role_permissions(db)
            seed_sample_tracking(db)
            _migrate_faz84_yigit_and_cleanups(db)
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


def create_app(is_production: bool | None = None) -> FastAPI:
    prod = settings.is_production if is_production is None else bool(is_production)
    application = FastAPI(
        title=settings.APP_NAME,
        description="Nanolab Edirne GLP Test Tesisi için Yapay Zeka Destekli Operasyonel Planlama ve Çakışma Yönetim Sistemi API",
        version="1.0.0",
        lifespan=lifespan,
        docs_url=None if prod else "/docs",
        redoc_url=None if prod else "/redoc",
        openapi_url=None if prod else "/openapi.json",
    )

    # CORS Yapılandırması (Frontend entegrasyonu için)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # FAZ 10: Kurumsal HTTP Güvenlik Başlıkları (Security Headers Middleware)
    @application.middleware("http")
    async def add_security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

    # API Router dahil et
    application.include_router(api_router, prefix=settings.API_V1_STR)
    application.include_router(planning_router, prefix=settings.API_V1_STR)
    # /api/... kısa yolları (/api/v1/... ile aynı güvenlik ve işlevsellik)
    application.include_router(auth_endpoints.router, prefix="/api", include_in_schema=False)
    application.include_router(health_endpoints.router, prefix="/api", include_in_schema=False)
    application.include_router(samples_endpoints.router, prefix="/api", include_in_schema=False)
    application.include_router(users_endpoints.router, prefix="/api", include_in_schema=False)

    # FAZ 10: Tek Port Canlı Ortam Sunumu (FastAPI + frontend/dist Statik & SPA Yönlendirmesi)
    assets_dir = FRONTEND_DIST_DIR / "assets"
    if assets_dir.is_dir():
        application.mount("/assets", StaticFiles(directory=str(assets_dir)), name="frontend-assets")

    @application.get("/api/info", include_in_schema=False)
    def api_info():
        return {
            "message": "Nanolab Edirne GLP Test Tesisi API Servisi Aktif",
            "docs_url": None if prod else "/docs",
            "health_check": f"{settings.API_V1_STR}/health",
        }

    @application.get("/", include_in_schema=False)
    def root(request: Request):
        index_file = FRONTEND_DIST_DIR / "index.html"
        accept = (request.headers.get("accept") or "").lower()
        if index_file.is_file() and "application/json" not in accept:
            return FileResponse(str(index_file))
        return {
            "message": "Nanolab Edirne GLP Test Tesisi API Servisi Aktif",
            "docs_url": None if prod else "/docs",
            "health_check": f"{settings.API_V1_STR}/health",
        }

    @application.get("/{full_path:path}", include_in_schema=False)
    def serve_spa(full_path: str):
        norm = full_path.strip("/")
        if norm.startswith("api/") or norm == "api" or norm in ("docs", "redoc", "openapi.json"):
            raise HTTPException(status_code=404, detail="Uç nokta bulunamadı.")
        if FRONTEND_DIST_DIR.is_dir():
            candidate = (FRONTEND_DIST_DIR / norm).resolve()
            if str(candidate).startswith(str(FRONTEND_DIST_DIR.resolve())) and candidate.is_file():
                return FileResponse(str(candidate))
            index_file = FRONTEND_DIST_DIR / "index.html"
            if index_file.is_file():
                return FileResponse(str(index_file))
        raise HTTPException(status_code=404, detail="Sayfa bulunamadı.")

    return application


app = create_app()
