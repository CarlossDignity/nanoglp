"""
GLP Çakışma Yönetimi ve Kural Doğrulama Motoru (Conflict Engine)

TEMEL GLP KURALLARI (MIMARI.md):
1. Biyolojik saatler (is_biological_fixed_time=True) hiçbir zaman kaydırılamaz.
2. Bir personele aynı saat diliminde birden fazla görev atanamaz.
3. Bir cihaz aynı saat diliminde birden fazla teste atanamaz.
4. Kalibrasyon tarihi geçmiş cihazlar teste tahsis edilemez.
5. Oda kapasitesi aşılamaz.
"""
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from app.models.study_step import StudyStep
from app.models.conflict import Conflict, ConflictType, ConflictSeverity


class ConflictEngine:
    def __init__(self, db: Session):
        self.db = db

    def check_study_conflicts(self, study_id: int) -> List[Conflict]:
        """Belirtilen çalışmanın tüm adımlarında GLP çakışmalarını denetler."""
        conflicts = []
        steps = self.db.query(StudyStep).filter(StudyStep.study_id == study_id).order_by(StudyStep.planned_start).all()
        
        # Biyolojik saat doğrulaması
        for step in steps:
            if step.is_biological_fixed_time and step.actual_start:
                time_diff = abs((step.actual_start - step.planned_start).total_seconds()) / 60.0
                if time_diff > step.biological_tolerance_minutes:
                    conflict = Conflict(
                        conflict_type=ConflictType.BIOLOGICAL_TIME_VIOLATION,
                        severity=ConflictSeverity.CRITICAL,
                        title=f"Biyolojik Saat İhlali: {step.step_name}",
                        description=(
                            f"Adım {step.step_order} için planlanan saat {step.planned_start}, "
                            f"gerçekleşen {step.actual_start}. Sapma ({time_diff:.1f} dk) izin verilen "
                            f"toleransı ({step.biological_tolerance_minutes} dk) aştı!"
                        ),
                        study_id=study_id,
                        step_id=step.id
                    )
                    conflicts.append(conflict)

        return conflicts
