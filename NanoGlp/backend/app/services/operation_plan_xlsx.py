"""Read-only export of calendar tasks, clipped to facility-local calendar days."""

from datetime import date, datetime, time, timedelta
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy.orm import Session, selectinload

from app.models.study import Study, StudyStatus
from app.models.study_step import StudyStep, StepStatus

STUDY_LABELS = {
    "DRAFT": "TASLAK",
    "APPROVED": "Onaylı",
    "IN_PROGRESS": "Devam ediyor",
    "REPORTING": "Raporlama",
    "COMPLETED": "Tamamlandı",
    "CANCELLED": "İptal",
}
STEP_LABELS = {
    "PENDING": "Bekliyor",
    "IN_PROGRESS": "Devam ediyor",
    "COMPLETED": "Tamamlandı",
    "DELAYED": "Gecikti",
    "CANCELLED": "İptal",
}
HEADERS = [
    "Tarih",
    "Çalışma kodu",
    "Görev",
    "Çalışma günü",
    "Planlanan başlangıç",
    "Planlanan bitiş",
    "Güne düşen başlangıç",
    "Güne düşen bitiş",
    "Güne düşen süre (dk)",
    "Sorumlu personeller",
    "Çalışma durumu",
    "Görev durumu",
]


def export_operation_plan(
    db: Session, target_date: date, view: str, study_code: str | None = None
):
    start = (
        target_date - timedelta(days=target_date.weekday())
        if view == "weekly"
        else target_date
    )
    end = start + timedelta(days=7 if view == "weekly" else 1)
    period_start, period_end = datetime.combine(start, time.min), datetime.combine(
        end, time.min
    )
    # Same scope as /planning/calendar: include drafts, reporting and completed;
    # exclude cancelled studies/steps. No new historical visibility cutoff.
    # Query tasks, not personnel, so unassigned and multi-person tasks occur once.
    query = (
        db.query(StudyStep)
        .join(StudyStep.study)
        .options(selectinload(StudyStep.study), selectinload(StudyStep.assignees))
        .filter(
            Study.status != StudyStatus.CANCELLED,
            StudyStep.status != StepStatus.CANCELLED,
            StudyStep.planned_start < period_end,
            StudyStep.planned_end > period_start,
        )
        .order_by(StudyStep.planned_start, Study.study_code, StudyStep.id)
    )
    if study_code is not None:
        query = query.filter(Study.study_code == study_code)
    steps = query.all()

    wb = Workbook()
    ws = wb.active
    ws.title = "Operasyon Planı"
    meta = [
        f"{'Haftalık' if view == 'weekly' else 'Günlük'} Operasyon Planı",
        f"Dönem: {start.isoformat()} – {(end - timedelta(days=1)).isoformat()} (dahil)",
        f"Çalışma filtresi: {study_code if study_code is not None else 'Tüm çalışmalar'}",
        "Saatler: Europe/Istanbul (UTC+03:00). Yalnız planlanan saatler; gerçekleşmeler dahil değildir.",
        "Gece/hafta sınırını aşan görevler günlere bölünür; süre [başlangıç, bitiş) aralığına aittir.",
        "Süre personel görevinin planlanan süresidir; cihaz rezervasyonu eklenmez. İptal kayıtları dahil değildir.",
    ]
    for row, value in enumerate(meta, 1):
        ws.cell(row, 1, value)
        ws.merge_cells(
            start_row=row, start_column=1, end_row=row, end_column=len(HEADERS)
        )
    ws.append([])
    ws.append(HEADERS)
    day = start
    while day < end:
        day_start = datetime.combine(day, time.min)
        day_end = day_start + timedelta(days=1)
        for step in steps:
            clipped_start = max(step.planned_start, day_start)
            clipped_end = min(step.planned_end, day_end)
            if clipped_start >= clipped_end:
                continue
            study_status, step_status = step.study.status.value, step.status.value
            ws.append(
                [
                    day,
                    step.study.study_code,
                    step.step_name,
                    step.study_day,
                    step.planned_start,
                    step.planned_end,
                    clipped_start,
                    clipped_end,
                    int((clipped_end - clipped_start).total_seconds() // 60),
                    ", ".join(u.full_name for u in step.assignees) or "Atanmamış",
                    f"{STUDY_LABELS.get(study_status, 'Bilinmeyen')} ({study_status})",
                    f"{STEP_LABELS.get(step_status, 'Bilinmeyen')} ({step_status})",
                ]
            )
        day += timedelta(days=1)
    last_task_row = ws.max_row
    if last_task_row == 8:
        ws.cell(9, 1, "Seçilen dönemde ve kapsamda görev bulunmuyor.")
        ws.merge_cells(start_row=9, start_column=1, end_row=9, end_column=len(HEADERS))
    for row in ws:
        for cell in row:
            if isinstance(cell.value, str):
                # Treat user-provided codes/names as text, never Excel formulas.
                cell.data_type = "s"
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    ws["A1"].font = Font(size=16, bold=True, color="17365D")
    for cell in ws[8]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="17365D")
    for row in range(9, last_task_row + 1):
        ws.cell(row, 1).number_format = "dd.mm.yyyy"
        for col in range(5, 9):
            ws.cell(row, col).number_format = "dd.mm.yyyy hh:mm"
        if row % 2:
            for cell in ws[row]:
                cell.fill = PatternFill("solid", fgColor="F0F4F8")
    for col, width in enumerate([14, 23, 40, 14, 22, 22, 22, 22, 19, 40, 28, 28], 1):
        ws.column_dimensions[get_column_letter(col)].width = width
    ws.freeze_panes = "E9"
    ws.auto_filter.ref = f"A8:L{max(8, last_task_row)}"
    ws.print_title_rows = "1:8"
    ws.print_options.horizontalCentered = True
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A3
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    stream = BytesIO()
    wb.save(stream)
    stream.seek(0)
    return stream, f"operasyon-plani-{view}-{start.isoformat()}.xlsx"
