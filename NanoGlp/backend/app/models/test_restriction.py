from datetime import datetime
from sqlalchemy import Boolean, Column, Date, DateTime, Integer, String, Text
from app.database import Base


class TestRestriction(Base):
    """
    FAZ 8.1 — Test Kısıtlama ve Uygunluk Takvimi (Blackout Period).

    "XXX testini XXX sebebinden dolayı ŞU TARİHE KADAR yapamayız" kaydı.
    template_code = 'ALL' ise tüm testler için geçerlidir.
    """

    __test__ = False  # pytest toplayıcısı bu sınıfı test sanmasın
    __tablename__ = "test_restrictions"

    id = Column(Integer, primary_key=True, index=True)
    template_code = Column(String(60), nullable=False, index=True, default="ALL")
    test_name = Column(String(255), nullable=False)
    restricted_from = Column(Date, nullable=False)
    restricted_until = Column(Date, nullable=False)
    reason = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_by = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
