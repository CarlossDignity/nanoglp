from datetime import datetime
from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import relationship
from app.database import Base


class Document(Base):
    """
    FAZ 6 & 6.1: Yüklenen GLP belgesi (Sponsor Sözleşmesi, TIIS, CoA, Hayvan Menşei, FM.083 vb.)
    ve GPT-4o Vision OCR + Yapılandırılmış Veri Çıkarım sonucu.

    GLP: Orijinal dosya değiştirilmeden saklanır (SHA-256 ile bütünlük doğrulanabilir).
    """
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    original_filename = Column(String(255), nullable=False)
    stored_filename = Column(String(255), nullable=False)
    content_type = Column(String(100), nullable=True)
    size_bytes = Column(Integer, nullable=False)
    sha256 = Column(String(64), nullable=False, index=True)

    # FAZ 6.2: Çalışma Paketi (Dossier) İzolasyonu
    dossier_key = Column(String(100), nullable=True, index=True, default="DOSSIER-ELISA-2026")
    dossier_label = Column(String(255), nullable=True, default="ELISA TIBBI GEREÇLER — GLP2026-024/026/031/034")

    # Belge kategorisi: CONTRACT_ORDER | TIIS_FORM | COA_CERTIFICATE | ANIMAL_ORIGIN_CERT | FM083_ACCLIMATIZATION | SD_ASSIGNMENT | OTHER
    doc_category = Column(String(60), nullable=True, index=True)
    doc_category_label = Column(String(120), nullable=True)
    primary_study_code = Column(String(100), nullable=True, index=True)
    study_codes = Column(JSON, nullable=True)

    # PARSED | NEEDS_REVIEW | FAILED
    status = Column(String(30), nullable=False, default="PARSED")
    extraction_method = Column(String(30), nullable=True)   # PDF_VISION | XLSX | TEXT
    ai_model = Column(String(100), nullable=True)
    extracted_data = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)

    uploaded_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    uploaded_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    uploaded_by = relationship("User")
