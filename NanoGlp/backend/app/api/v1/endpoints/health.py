from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database import get_db

router = APIRouter()


@router.get("/health", tags=["Sistem"])
def health_check(db: Session = Depends(get_db)):
    db_status = "connected"
    try:
        db.execute(text("SELECT 1"))
    except Exception as e:
        db_status = f"unhealthy: {str(e)}"

    return {
        "status": "online",
        "system": "Nanolab Edirne GLP AI Operasyonel Planlama",
        "phase": "Faz 1 - Altyapı ve Veritabanı",
        "database": db_status
    }
