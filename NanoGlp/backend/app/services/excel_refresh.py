"""Study Status refresh: source assertions and operational records have separate ownership."""

import copy
from datetime import date, datetime
from types import SimpleNamespace
from app.models.sample import SampleRecord
from app.models.study import Study, StudyStatus
from app.models.study_step import StudyStep, StepStatus
from app.models.audit_log import AuditLog
from app.models.user import User, UserRole

# These fields are shared facts. All other Excel fields belong to SampleRecord.
SHARED = {
    "sponsor_name": "sponsor_name",
    "test_item_name": "test_item_name",
    "lot_no": "test_item_batch",
    "expiry_date": "expiry_date",
    "manufacture_date": "manufacture_date",
    "storage_condition": "test_item_storage_condition",
    "requested_analysis": "test_type",
}
SCHEDULE = {
    "planned_start": "target_start_date",
    "planned_end": "target_end_date",
    "template_code": "template_code",
}


def json_value(v):
    return v.isoformat() if isinstance(v, (date, datetime)) else v


class SheetColumns:
    """Resolve the known workbook headers so deleting a column cannot shift its meaning."""

    def __init__(self, sheet, header_row, kind):
        from app.services.sample_service import (
            norm_key,
            _HEADER_LOOKUP,
            _clean_code,
            parse_date_any,
        )

        self.sheet = sheet
        self.max_row = sheet.max_row
        self.extras = {}
        headers = {}
        for c in range(1, sheet.max_column + 1):
            key = norm_key(sheet.cell(header_row, c).value)
            if key:
                if key in headers:
                    raise ValueError(f"{sheet.title}: yinelenen sütun: {key}")
                headers[key] = c
        canonical = HEADERS[kind]
        # Empty-header historical fixtures use the original layout. A named lot
        # extension alone does not turn them into a partially mapped workbook.
        mapped = any(key in headers for key in canonical.values())
        self.mapping = (
            {c: headers.get(key) for c, key in canonical.items()} if mapped else None
        )
        # The official GLP template has two unnamed note columns immediately
        # after Status. Do not treat named extension columns as notes.
        if mapped and kind == "glp" and self.mapping.get(25):
            for offset in (1, 2):
                col = self.mapping[25] + offset
                if not norm_key(sheet.cell(header_row, col).value):
                    self.mapping[25 + offset] = col
        code_col = (
            self.mapping.get(8 if kind == "glp" else 14)
            if mapped
            else (8 if kind == "glp" else 14)
        )
        if not code_col:
            raise ValueError(f"{sheet.title}: Çalışma Kodu sütunu eksik")
        extras = {}
        for key, c in headers.items():
            field = _HEADER_LOOKUP.get(key)
            if field in {
                "lot_no",
                "expiry_date",
                "storage_condition",
                "expected_arrival_date",
                "manufacture_date",
            }:
                extras[field] = c
            if key in ("termin", "termin tarihi", "deadline"):
                extras["final_report_date"] = c
        for r in range(header_row + 1, self.max_row + 1):
            code = _clean_code(sheet.cell(r, code_col).value, r - header_row)
            self.extras[code] = {
                f: (
                    parse_date_any(sheet.cell(r, c).value)
                    if f.endswith("_date")
                    and f not in ("expiry_date", "manufacture_date")
                    else (
                        str(sheet.cell(r, c).value).strip()
                        if sheet.cell(r, c).value is not None
                        else None
                    )
                )
                for f, c in extras.items()
            }

    def cell(self, r, c):
        col = self.mapping.get(c) if self.mapping is not None else c
        return self.sheet.cell(r, col) if col else SimpleNamespace(value=None)


def apply_refresh(db, records, markers, user, auto_schedule, **counts):
    from app.services import sample_service as ss

    codes = {}
    errors = []
    for rec in records:
        code = rec["study_code"]
        if code in codes:
            errors.append(
                f'{code}: yinelenen/çelişen çalışma kodu (sıra {codes[code]}, {rec["serial_no"]})'
            )
        codes[code] = rec["serial_no"]
    if errors:
        return dict(
            created=0,
            updated=0,
            unchanged=0,
            failed=len(errors),
            review_required=0,
            skipped=len(records),
            errors=errors,
            changes=[],
            reviews=[],
            total_rows=len(records),
            auto_scheduled=0,
            **counts,
        )
    # Do not create/modify personnel before the file has passed validation.
    ss.ensure_excel_personnel_users(db)
    samples = {}
    studies = {}
    for model, target in ((SampleRecord, samples), (Study, studies)):
        for row in db.query(model).all():
            key = ss._clean_code(row.study_code, 0)
            if key in target:
                raise ValueError(f"{key}: birden fazla mevcut kayıt eşleşiyor")
            target[key] = row
    result = dict(
        created=0,
        updated=0,
        unchanged=0,
        failed=0,
        review_required=0,
        skipped=0,
        errors=[],
        changes=[],
        reviews=[],
        total_rows=len(records),
        auto_scheduled=0,
        scheduling=[],
        newly_completed_steps=0,
        workflow_matched=len(markers),
        **counts,
    )
    for rec in records:
        rec = {k: (None if v == "-" else v) for k, v in rec.items()}
        code = rec["study_code"]
        sample = samples.get(code)
        study = studies.get(code)
        new = sample is None
        if new:
            sample = SampleRecord(study_code=code)
            db.add(sample)
        steps = (
            db.query(StudyStep).filter(StudyStep.study_id == study.id).all()
            if study
            else []
        )
        signed = any(
            isinstance(v, dict) and (v.get("approvals") or v.get("done_at"))
            for k, v in (sample.workflow or {}).items()
            if k.isdigit()
        )
        protected = bool(
            signed
            or (
                study
                and (
                    study.status != StudyStatus.DRAFT
                    or study.protocol_approved_at
                    or (study.dossier_metadata or {}).get("biological_revisions")
                    or any(
                        s.actual_start
                        or s.actual_end
                        or s.actual_reference_time
                        or s.status != StepStatus.PENDING
                        for s in steps
                    )
                )
            )
        )
        workflow = copy.deepcopy(sample.workflow or {})
        previous = workflow.get("_excel_source", {})
        incoming = {k: json_value(v) for k, v in rec.items() if k != "study_code"}
        differences = []
        reviews = []
        changed_fields = set()

        def report(field, old, value, reason=None, target="SampleRecord"):
            entry = dict(
                study_code=code,
                field=field,
                old_value=json_value(old),
                excel_value=json_value(value),
                target=target,
            )
            if reason:
                reviews.append(dict(entry, reason=reason))
            else:
                differences.append(entry)

        for field, value in rec.items():
            if field == "study_code":
                continue
            old = getattr(sample, field)
            if value in (None, "", []):
                if old not in (None, "", []):
                    report(field, old, value, "Boş veya eksik değer korunuyor")
                continue
            if field in ("stored_status", "sample_status") and not new:
                if field == "stored_status" and old != value:
                    report(
                        field, old, value, "Excel durumu ile operasyonel durum farklı"
                    )
                continue
            if protected and field in (*SCHEDULE, "study_director_name"):
                if old != value:
                    report(
                        field,
                        old,
                        value,
                        "Onaylı/başlamış plan korunuyor; Excel kaynak bilgisi saklandı",
                    )
                continue
            # Compare the last source too: scheduler-derived dates must not cause
            # repeated imports of the identical source to reset the plan.
            if not new and previous.get(field, object()) == json_value(value):
                continue
            if old != value:
                setattr(sample, field, value)
                changed_fields.add(field)
                report(field, old, value)
        if study is None:
            sd = ss.match_study_director(
                db, sample.study_director_name, include_inactive=True
            )
            if sd is None:
                sd = (
                    db.query(User)
                    .filter(
                        User.role == UserRole.STUDY_DIRECTOR, User.is_active == True
                    )
                    .order_by(User.id)
                    .first()
                )
            if sd is None:
                raise ValueError(f"{code}: çalışma yöneticisi bulunamadı")
            study = Study(
                study_code=code,
                title=sample.test_item_name or code,
                test_item_name=sample.test_item_name or "BELİRTİLMEDİ",
                study_director_id=sd.id,
                status=(
                    StudyStatus.COMPLETED
                    if rec["stored_status"] == "COMPLETED"
                    else (
                        StudyStatus.IN_PROGRESS
                        if rec["stored_status"] == "ONGOING"
                        else StudyStatus.DRAFT
                    )
                ),
                dossier_metadata={"historical_excel_import": True},
            )
            db.add(study)
            db.flush()
        for field, dest in SHARED.items():
            value = getattr(sample, field)
            if value not in (None, "", []) and getattr(study, dest) != value:
                report(field, getattr(study, dest), value, target="Study." + dest)
                setattr(study, dest, value)
        contact = (
            "; ".join(
                f"{c.get('name', '')} <{c.get('email', '')}>".replace(" <>", "")
                for c in (sample.contacts or [])
            )
            or None
        )
        if contact and study.sponsor_contact != contact:
            report(
                "contacts",
                study.sponsor_contact,
                contact,
                target="Study.sponsor_contact",
            )
            study.sponsor_contact = contact
        if not protected:
            if "study_director_name" in changed_fields:
                director = ss.match_study_director(
                    db, sample.study_director_name, include_inactive=True
                )
                if director:
                    study.study_director_id = director.id
                else:
                    report(
                        "study_director_name",
                        study.study_director_id,
                        sample.study_director_name,
                        "Çalışma yöneticisi eşleşmedi; mevcut atama korundu",
                        target="Study.study_director_id",
                    )
            for field, dest in SCHEDULE.items():
                if field in changed_fields and getattr(sample, field) is not None:
                    setattr(study, dest, getattr(sample, field))
            if "planned_start" in changed_fields:
                study.acclimatization_start_date = sample.planned_start
        operational = {
            "DRAFT": "PLANNED",
            "IN_PROGRESS": "ONGOING",
        }.get(study.status.value, study.status.value)
        if rec.get("raw_status_text") and rec["stored_status"] != operational:
            report(
                "status",
                study.status.value,
                rec["stored_status"],
                "Excel durumu operasyonel durumu değiştirmedi",
                target="Study.status",
            )
        if code in markers:
            imported = ss._build_workflow_from_markers(
                markers[code], None, None, None, None, None, None, None, None
            )
            # Keep application signatures verbatim; source markers are separate.
            incoming["workflow_markers"] = imported
            if new:
                workflow.update(imported)
        if incoming != previous:
            workflow["_excel_source"] = incoming
            sample.workflow = workflow
        if (
            auto_schedule
            and not protected
            and (new or bool(changed_fields & set(SCHEDULE)))
            and rec["stored_status"] in ("PLANNED", "EXPECTED")
        ):
            reason = "Yeni taslak" if new else "Taslak planlama girdileri değişti"
            ss.plan_sample(db, sample, user, preserve_status=True, existing_study=study)
            result["auto_scheduled"] += 1
            result["scheduling"].append(dict(study_code=code, reason=reason))
        if not new and incoming != previous and not differences:
            report(
                "excel_source",
                previous,
                incoming,
                target="SampleRecord.workflow._excel_source",
            )
        result["created" if new else "updated" if differences else "unchanged"] += 1
        result["changes"].extend(differences)
        result["reviews"].extend(reviews)
    result["review_required"] = len({r["study_code"] for r in result["reviews"]})
    if result["created"] or result["updated"]:
        db.add(
            AuditLog(
                user_id=user.id,
                entity_name="SampleRecord",
                entity_id=0,
                action="STUDY_STATUS_WORKBOOK_IMPORT",
                new_values=result,
                reason="Excel kaynak farkları; operasyonel kayıtlar korunarak güncelleme",
            )
        )
    db.flush()
    return result


# Exact normalized headers from the supported Study Status workbook template.
HEADERS = {
    "glp": {
        1: "sira no",
        2: "talep edilen analizler requested analyses",
        3: "test maddesinin adi name of the test item",
        4: "calisma yoneticisi study director",
        5: "fatura edilecek firma adi name of the company to be invoiced",
        6: "sponsor adi sponsor name",
        7: "ilgili kisiler isim ve mail authorized person name and e mail",
        8: "calisma kodu study code",
        9: "ilgili satis yoneticisi sales person",
        10: "teklif no offer no",
        11: "test maddesinin istanbul a gelis tarihi test item arrival date in istanbul",
        12: "test maddesinin laboratuvara gelis tarihi test item arrival date",
        13: "test madde kodu test item code",
        14: "testin yapilacagi laboratuvar laboratory where the test will be performed",
        15: "test maddesi miktari amount of test item",
        16: "hayvan sarf malzeme yeterlilik durumu animal consumable availability status",
        17: "hayvan temin tarihi procurement date",
        18: "planlanan calisma baslangic tarihi planned study start date",
        19: "test baslangic tarihi calisma takvimi experiment start date",
        20: "test bitis tarihi experiment end date",
        21: "taslak rapor teslim tarihi draft report submission date",
        22: "odeme durumu payment status",
        23: "final rapor gonderim tarihi mailin musteriye gonderildigi tarih final report submission date date the email was sent to the client",
        24: "calisma turu glp nonglp",
        25: "durum status",
    },
    "non_glp": {
        2: "firma adi company name",
        3: "yetkili isim ve mail authorized person name and e mail",
        4: "teklif no offer no",
        5: "satiscisi sales person",
        6: "proje adi project name",
        7: "icerik content",
        8: "analiz analyses",
        9: "test tesisi test facility",
        10: "calisma yoneticisi study director",
        11: "calisma sozlesmesi tarihi study agreement date",
        12: "test ogesi test item",
        13: "test ogesi miktari amount of test item",
        14: "calisma kodu study code",
        15: "test ogesi varis tarihi test item arrival date",
        16: "planlanan calisma baslangic tarihi planned study start date",
        17: "calisma baslangic tarihi study start date",
        18: "planlanan test baslangic tarihi planned experiment start date",
        19: "test baslangic tarihi experiment start date",
        20: "planlanan test bitis tarihi planned experiment end date",
        21: "test bitis tarihi experiment end date",
        22: "planlanan calisma bitis tarihi planned study end date",
        23: "calisma bitis tarihi study end date",
        24: "raporlama tarihi reporting date",
        25: "notlar notes",
        1: "sira no",
    },
}
