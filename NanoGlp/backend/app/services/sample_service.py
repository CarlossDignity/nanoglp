"""
FAZ 8.1 — Numune ve Çalışma Takip servisi.

* 11 adımlı numune iş akışı (dikey stepper) durum hesabı, rol bazlı yetkiler
* Excel (.xlsx / .csv) içe aktarma (sütun adlarını otomatik eşler)
* Numuneden otomatik taslak çalışma + takvim üretimi (kısıtlama ve kafes/cihaz kurallarıyla)
* Örnek veri tohumlama (GLP2026-072 / 031 / 076 / 073 / 026 ...)
"""
import copy
import csv
import io
import re
import unicodedata
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.sample import APPROVAL_ROLES, WORKFLOW_STEPS, SampleRecord
from app.models.study import Study, StudyStatus
from app.models.study_step import StepStatus, StudyStep
from app.models.user import User, UserRole
from app.utils.facility_time import facility_today
from app.services.capacity_service import get_auto_schedule_notice, next_business_day
from app.services.templates import DEFAULT_TEMPLATE_CODE, TEMPLATES, get_template, resolve_template_code

SUPER_ROLES = {"SYSADMIN", "ADMIN", "TFM"}
PLAN_ROLES = {"SYSADMIN", "ADMIN", "TFM", "STUDY_DIRECTOR", "PLANNING_COORDINATOR"}
TRM_ROLES = {"TRM_KABUL", "TRM_ACCEPTANCE"}
SAMPLE_ACCESS_ROLES = SUPER_ROLES | {"SALES", "TRM_KABUL", "TRM_ACCEPTANCE", "STUDY_DIRECTOR", "PLANNING_COORDINATOR", "QA", "EXECUTIVE"}

STATUS_LABELS = {
    "EXPECTED": "Beklenen",
    "PLANNED": "Planlanan",
    "ONGOING": "Devam eden",
    "COMPLETED": "Biten",
    "CANCELLED": "İptal",
}

SALES_FIELDS = (
    "requested_analysis", "test_item_name", "billing_company", "sponsor_name", "contacts",
    "quote_no", "sales_manager", "expected_arrival_date", "payment_status", "study_agreement_date",
)
TRM_FIELDS = (
    "sample_status", "test_item_code", "istanbul_arrival_date", "lab_arrival_date", "received_quantity",
    "lot_no", "expiry_date", "storage_condition", "sample_note",
    "manufacture_date", "extraction_polar_solvent", "extraction_non_polar_solvent",
    "animal_consumable_status", "animal_procurement_date",
)
PLANNING_FIELDS = ("template_code", "study_director_name", "glp_type", "test_laboratory")
DATE_FIELDS = {
    "expected_arrival_date", "istanbul_arrival_date", "lab_arrival_date", "planned_start", "planned_end",
    "animal_procurement_date", "experiment_start_date", "experiment_end_date", "draft_report_date",
    "final_report_date", "study_agreement_date",
}


def role_of(user: User) -> str:
    return user.role.value if hasattr(user.role, "value") else str(user.role)


# ---------------------------------------------------------------------------
# YETKİLER
# ---------------------------------------------------------------------------
def sample_permissions(user: User) -> Dict[str, Any]:
    """Rol bazlı numune ekranı yetkileri (kayıt düzenleme, planlama, belge yükleme, iş akışı)."""
    r = role_of(user)
    steps_allowed = [
        s["no"] for s in WORKFLOW_STEPS
        if s["kind"] in ("manual", "auto_or_manual") and (r in SUPER_ROLES or r in s["roles"])
    ]
    approvals = [k for k, v in APPROVAL_ROLES.items() if r in ("SYSADMIN", "ADMIN") or r in v["roles"]]
    return {
        "role": r,
        "can_edit_sales": r in SUPER_ROLES or r == "SALES",
        "can_edit_trm": r in SUPER_ROLES or r in TRM_ROLES,
        "can_plan": r in PLAN_ROLES,
        "can_import": r in SUPER_ROLES | {"SALES", "TRM_KABUL", "TRM_ACCEPTANCE", "STUDY_DIRECTOR", "PLANNING_COORDINATOR"},
        "can_delete": r in SUPER_ROLES,
        "can_upload_documents": r in SUPER_ROLES | {"SALES", "TRM_KABUL", "TRM_ACCEPTANCE", "STUDY_DIRECTOR", "PLANNING_COORDINATOR"},
        "can_assign_planning": r in PLAN_ROLES or r == "SALES",
        "workflow_steps": steps_allowed,
        "approval_roles": approvals,
    }


# ---------------------------------------------------------------------------
# YARDIMCILAR
# ---------------------------------------------------------------------------
def _ascii(s: Any) -> str:
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.replace("ı", "i").replace("İ", "I")


def norm_key(s: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _ascii(s).lower()).strip()


def parse_date_any(v: Any) -> Optional[date]:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = re.sub(r"\s+", " ", str(v)).strip()
    if not s or s == "-" or norm_key(s) in ("baslandi", "baslanmadi", "planning", "beklemede"):
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d.%m.%y", "%d %B %Y", "%d %B%Y", "%d %b %Y"):
        try:
            return datetime.strptime(s[:10] if fmt.startswith("%Y-") else s, fmt).date()
        except ValueError:
            continue
    return None


# FAZ 8.3: İntrakütanöz/İrritasyon kuralları Akut'tan ÖNCE gelmeli (çünkü "intrakutanoz" içinde "akut" alt dizisi vardır)
_TEMPLATE_PATTERNS = (
    (r"(6\s*ay|26\s*hafta|26\s*week|6\s*month|180\s*gun).*implant|implant.*(6\s*ay|26\s*hafta|26\s*week|6\s*month|180\s*gun)", "ISO_10993_6_IMP_26W"),
    (r"(3\s*ay|13\s*hafta|13\s*week|3\s*month|90\s*gun).*implant|implant.*(3\s*ay|13\s*hafta|13\s*week|3\s*month|90\s*gun)", "ISO_10993_6_IMP_13W"),
    (r"implant", "ISO_10993_6_IMP"),
    (r"pirojen|pyrogen|usp\s*151", "ISO_10993_11_PYRO"),
    (r"hemol", "ISO_10993_4_HEMO"),
    (r"subkronik|subchronic|(90\s*gun|13\s*hafta).*(toks|sistemik)|(toks|sistemik).*(90\s*gun|13\s*hafta)", "ISO_10993_11_SUBCHRONIC"),
    (r"subakut|subacute|(14\s*gun|28\s*gun).*(toks|sistemik)|(toks|sistemik).*(14\s*gun|28\s*gun)", "ISO_10993_11_SUBACUTE"),
    (r"intrakut|intracut|intradermal|irritasyon|irritation|reaktivite|reactivity|oral\s*mukoza|okuler|ocular", "ISO_10993_23_IC"),
    (r"sitotoks|cytotox|in\s*vitro", "ISO_10993_5_CYTO"),
    (r"sensiti|hassas|gpmt|maximi", "ISO_10993_10_SENS"),
    (r"sistemik|systemic|\b(akut|acute)\b|vivoacute", "ISO_10993_11_ACUTE"),
    (r"fiziksel|kimyasal|monogram|monograf|kalinti|tayin", "PHYS_CHEM_MONO"),
)


def infer_template_code(text: Optional[str]) -> Optional[str]:
    t = norm_key(text)
    for pattern, code in _TEMPLATE_PATTERNS:
        if re.search(pattern, t):
            return code
    return None


def find_study(db: Session, code: str) -> Optional[Study]:
    return db.query(Study).filter(Study.study_code == code).first()


def match_study_director(db: Session, name: Optional[str], include_inactive: bool = False) -> Optional[User]:
    q = db.query(User).filter(User.role == UserRole.STUDY_DIRECTOR, User.username != "yigit")
    if not include_inactive:
        q = q.filter(User.is_active == True)  # noqa: E712
    sds = [
        u for u in q.order_by(User.id).all()
        if (u.role.value if hasattr(u.role, "value") else str(u.role or "")).strip().upper() == "STUDY_DIRECTOR"
        and (u.username or "").strip().lower() != "yigit"
    ]
    if name:
        key = norm_key(name)
        for u in sds:
            if norm_key(u.full_name) == key:
                return u
        for u in sds:
            uk = norm_key(u.full_name)
            if key and (key in uk or uk in key):
                return u
        if "burcu" in key:
            for u in sds:
                if "burcu" in norm_key(u.full_name):
                    return u
    return None


def _wf(sample: SampleRecord) -> Dict[str, Any]:
    return dict(sample.workflow or {})


def _study_has_steps(db: Session, study: Optional[Study]) -> bool:
    if study is None:
        return False
    return (
        db.query(StudyStep).filter(StudyStep.study_id == study.id, StudyStep.status != StepStatus.CANCELLED).count() > 0
    )


def sync_dates_from_study(db: Session, sample: SampleRecord, study: Optional[Study]) -> None:
    """Çalışma takvimi oluşmuşsa numune satırındaki başlangıç/bitiş tarihlerini çalışma kaydından eşitler."""
    if study is not None and _study_has_steps(db, study):
        if study.acclimatization_start_date:
            sample.planned_start = study.acclimatization_start_date
        if study.target_end_date:
            sample.planned_end = study.target_end_date
        notice = get_auto_schedule_notice(study)
        sample.auto_schedule_notice = notice.get("text") if notice else None


# ---------------------------------------------------------------------------
# DURUM, İŞ AKIŞI VE GECİKME HESABI
# ---------------------------------------------------------------------------
def _approvals_done(state: Dict[str, Any]) -> bool:
    ap = state.get("approvals") or {}
    return all(k in ap for k in APPROVAL_ROLES)


REFERENCE_DATE = date(2026, 11, 3)  # Historical compatibility boundary, never the live clock.

# FAZ 9.3: Excel 4. Sekme (SPONSOR SÖZLŞ.-SPONSOR AGREEM.) firma sözleşme ve taahhüt tarihleri kataloğu
SPONSOR_AGREEMENT_CATALOG: Dict[str, Dict[str, Any]] = {
    "toxlab": {
        "agreement_date": date(2026, 7, 16),
        "person": "Pınar Erkekoğlu",
        "email": "pinartox@gmail.com",
        "items": (
            (("prp kit",), date(2026, 11, 10), None),
            (("prp syrnge", "prp syringe"), date(2026, 11, 10), None),
            (("fat processor",), date(2026, 11, 15), None),
            (("hydrogel",), date(2026, 11, 15), None),
        ),
    },
    "inovabella": {
        "agreement_date": date(2026, 7, 22),
        "person": "Fatma Sezer ŞENOL DENİZ",
        "email": "feseaser@gmail.com",
        "items": (
            (("inovaped",), date(2027, 1, 10), None),
        ),
    },
    "plastimed": {
        "agreement_date": date(2026, 6, 19),
        "person": "Cemre Nur EKİNLİ",
        "email": "cemre.ekinli@plasti-med.com.tr",
        "items": (
            (("bakteri viral", "hme filtre"), date(2026, 10, 28), None),
        ),
    },
    "elisa": {
        "agreement_date": date(2026, 6, 15),
        "person": "Nadir Akar",
        "email": "elisatibbi@gmail.com",
        "items": (
            (("caha",), date(2026, 12, 26), "İmplantasyon Hariç: 26.12.2026"),
            (("plla",), date(2026, 12, 26), "İmplantasyon Hariç: 26.12.2026"),
            (("ultra", "advanced"), date(2026, 10, 15), "İmplantasyon Hariç: 15.10.2026"),
            (("aqua",), date(2026, 10, 15), "İmplantasyon Hariç: 15.10.2026"),
            (("hpmc", "ophtalmic"), date(2026, 10, 30), "İmplantasyon Hariç: 30.10.2026"),
        ),
    },
    "merken": {
        "agreement_date": date(2026, 6, 15),
        "person": "Nadir Akar",
        "email": "elisatibbi@gmail.com",
        "items": (
            (("caha",), date(2026, 12, 26), "İmplantasyon Hariç: 26.12.2026"),
            (("plla",), date(2026, 12, 26), "İmplantasyon Hariç: 26.12.2026"),
            (("ultra", "advanced"), date(2026, 10, 15), "İmplantasyon Hariç: 15.10.2026"),
            (("aqua",), date(2026, 10, 15), "İmplantasyon Hariç: 15.10.2026"),
            (("hpmc", "ophtalmic"), date(2026, 10, 30), "İmplantasyon Hariç: 30.10.2026"),
        ),
    },
    "meditera": {
        "agreement_date": date(2026, 10, 2),
        "person": "Bora MALTEPE / Sinem KİRAZ",
        "email": "bora.maltepe@meditera.com.tr, sinem.kiraz@meditera.com.tr",
        "items": (
            (("povidon",), date(2026, 11, 10), None),
            (("chlorhexidal",), date(2026, 11, 10), None),
        ),
    },
    "medfors": {
        "agreement_date": date(2026, 8, 5),
        "person": "Barış ARSLAN",
        "email": "barisarslan@medforsfarma.com.tr",
        "items": (
            (("tetagil",), date(2026, 12, 13), None),
        ),
    },
    "alkan": {
        "agreement_date": date(2026, 5, 8),
        "person": "Tuna EROĞLU",
        "email": "tunaeroglu@forelli.com.tr",
        "items": (
            (("ayak giysisi",), date(2026, 12, 10), None),
        ),
    },
    "saniter": {
        "agreement_date": date(2026, 3, 17),
        "person": "Özge KOÇAK",
        "email": "ozge@incelermedikal.com",
        "items": (
            (("manson",), date(2026, 12, 10), None),
        ),
    },
    "forenscope": {
        "agreement_date": date(2026, 3, 17),
        "person": "Pelin Sayıtoğlu",
        "email": "pelinelifs.oglu@forenscope.com",
        "items": (
            (("forenscope", "fingerprint"), date(2026, 9, 30), None),
        ),
    },
    "disera": {
        "agreement_date": date(2026, 9, 15),
        "person": "Dilek BOSTANCIOĞLU",
        "email": "d.uzumcu@disera.com.tr",
        "items": (
            (("appearance", "citrate", "sodyum"), None, "Sarf malzeme bekleniyor"),
        ),
    },
}


def classify_animal_consumable_status(raw_status: Optional[str]) -> Dict[str, Any]:
    """FAZ 9.3: Excel 16. sütun (Hayvan/Sarf Malzeme Yeterlilik Durumu) rozet ve karantina analizi."""
    k = norm_key(raw_status)
    if not k or k == "-":
        return {
            "code": None,
            "badge": None,
            "requires_quarantine": False,
            "quarantine_days": 0,
        }
    if "sarf" in k and "bekleniyor" in k:
        return {
            "code": "CONSUMABLES_PENDING",
            "badge": "⚠️ Sarf Malzeme Bekleniyor",
            "requires_quarantine": False,
            "quarantine_days": 0,
        }
    if "karantina" in k:
        return {
            "code": "QUARANTINE",
            "badge": "Karantina (+7g)",
            "requires_quarantine": True,
            "quarantine_days": 7,
        }
    if "tekrar" in k:
        return {
            "code": "ANIMAL_REUSE",
            "badge": "Tekrar Kullanım (Vet/HADYEK)",
            "requires_quarantine": False,
            "quarantine_days": 0,
        }
    return {
        "code": "AVAILABLE",
        "badge": None,
        "requires_quarantine": False,
        "quarantine_days": 0,
    }


def resolve_sponsor_agreement_info(sample: SampleRecord) -> Dict[str, Any]:
    """FAZ 9.3: Sponsor sözleşmesi tarihi ve müşteri taahhüt (planlanan gönderim) tarihini çözümler."""
    wf = dict(sample.workflow or {})
    stored_contract = wf.get("_contract") or {}
    ag_date = sample.study_agreement_date or parse_date_any(stored_contract.get("agreement_date"))
    commit_date = parse_date_any(stored_contract.get("commitment_date"))
    commit_note = stored_contract.get("commitment_note")
    person = stored_contract.get("person")
    email = stored_contract.get("email")

    fk = None
    for cand in (sample.billing_company, sample.sponsor_name):
        c_fk = _wf_firm_cat(cand)
        if c_fk in SPONSOR_AGREEMENT_CATALOG:
            fk = c_fk
            break
    if fk is None:
        item_k = norm_key(sample.test_item_name)
        if "merken" in item_k:
            fk = "elisa"
        elif "forenscope" in item_k:
            fk = "forenscope"

    if fk and fk in SPONSOR_AGREEMENT_CATALOG:
        cat = SPONSOR_AGREEMENT_CATALOG[fk]
        if ag_date is None:
            ag_date = cat.get("agreement_date")
        if not person:
            person = cat.get("person")
        if not email:
            email = cat.get("email")
        item_k = norm_key(sample.test_item_name)
        for tokens, dt, note in cat.get("items", ()):
            if any(tok in item_k for tok in tokens):
                if commit_date is None and dt is not None:
                    commit_date = dt
                if not commit_note and note:
                    commit_note = note
                break
        if commit_date is None and commit_note is None and len(cat.get("items", ())) == 1:
            _, dt, note = cat["items"][0]
            commit_date = dt
            commit_note = note

    return {
        "agreement_date": ag_date,
        "commitment_date": commit_date,
        "commitment_note": commit_note,
        "person": person,
        "email": email,
    }


def compute_next_study_codes(db: Session) -> Dict[str, str]:
    """
    FAZ 9.3: Gerçek sıralı GLP2026-001..082 ve NGLP-2026-001..011 serilerine göre
    sıradaki boş çalışma kodunu hesaplar (> 150 olan test kalıntılarını yoksayar).
    """
    glp_max = 82
    nglp_max = 11
    all_codes: List[str] = [r.study_code for r in db.query(SampleRecord.study_code).all() if r.study_code]
    all_codes.extend(r.study_code for r in db.query(Study.study_code).all() if r.study_code)
    for raw in all_codes:
        c = str(raw).strip().upper()
        if c.startswith("GLP2026-"):
            tail = c.split("GLP2026-", 1)[1]
            m = re.match(r"^(\d{1,3})$", tail)
            if m:
                n = int(m.group(1))
                if 1 <= n <= 150 and n > glp_max:
                    glp_max = n
        elif "NGLP" in c and "2026" in c:
            after_yr = c.split("2026", 1)[1]
            for m_num in re.findall(r"\d{1,3}", after_yr):
                n = int(m_num)
                if 1 <= n <= 150 and n > nglp_max:
                    nglp_max = n
    return {
        "next_glp_code": f"GLP2026-{glp_max + 1:03d}",
        "next_non_glp_code": f"NGLP-2026-{nglp_max + 1:03d}",
    }


def build_stepper(
    sample: SampleRecord, study: Optional[Study], has_schedule: bool, perms: Dict[str, Any],
    today: Optional[date] = None,
) -> List[Dict[str, Any]]:
    today = today or facility_today()
    wf = _wf(sample)
    start, end = sample.planned_start, sample.planned_end
    anim_info = classify_animal_consumable_status(sample.animal_consumable_status)
    q_days = anim_info["quarantine_days"]
    out: List[Dict[str, Any]] = []
    for sd in WORKFLOW_STEPS:
        no, st = sd["no"], wf.get(str(sd["no"]), {})
        done, done_at, done_by, due = False, st.get("done_at"), st.get("done_by"), None
        marker = st.get("marker")
        abroad = bool(st.get("abroad") or marker == "yurt dışı")
        extra: Dict[str, Any] = {}
        if marker:
            extra["marker"] = marker
        if abroad:
            extra["abroad"] = True
        if no == 3:
            done = bool(st.get("done") or marker == "+")
            extra["order_defaults"] = {"order_date": today.isoformat(), "estimated_delivery_days": 15}
            extra["animal_order"] = st if st.get("animal_tracking") is True else None
            if st.get("animal_tracking"):
                done = bool(st.get("received_date"))
                extra["animal_status"] = ("Kabul Edildi" if done else "Sipariş Verildi — Teslim Bekleniyor" if st.get("order_date") else "Sipariş Bekleniyor")
        elif no == 4:
            if sample.lab_arrival_date:
                done, done_at, done_by = True, sample.lab_arrival_date.isoformat(), "TRM Kabul"
                due = sample.lab_arrival_date
            else:
                done = bool(st.get("done") or marker == "+")
                due = sample.expected_arrival_date
        elif no == 5:
            done = bool(has_schedule or st.get("done") or marker == "+")
            due = start
            done_by = done_by or ("Sistem (otomatik takvim)" if has_schedule else None)
        elif no == 6 or no == 11:
            ap = st.get("approvals") or {}
            done = bool(_approvals_done(st) or st.get("done") or marker == "+")
            extra["approvals"] = [
                {
                    "key": k,
                    "label": v["label"],
                    "full": v["full"],
                    "signed": k in ap,
                    "by": (ap.get(k) or {}).get("by"),
                    "at": (ap.get(k) or {}).get("at"),
                    "can_sign": k in perms["approval_roles"],
                }
                for k, v in APPROVAL_ROLES.items()
            ]
            if no == 11 and end:
                due = sample.final_report_date or (end + timedelta(days=7 + q_days))
            if no == 6:
                due = start
        elif no == 7:
            due = start
            if marker == "+":
                done = True
            elif marker == "-" and (sample.stored_status or "").upper() in ("EXPECTED", "PLANNED"):
                done = False
            else:
                done = bool((start and start <= today and (sample.stored_status or "").upper() not in ("EXPECTED", "PLANNED")) or st.get("done"))
            done_at = done_at or (start.isoformat() if done and start else None)
        elif no == 8:
            due = end
            if marker == "+":
                done = True
            elif marker == "-" and (sample.stored_status or "").upper() in ("EXPECTED", "PLANNED"):
                done = False
            else:
                done = bool((end and end <= today and (sample.stored_status or "").upper() not in ("EXPECTED", "PLANNED")) or st.get("done"))
            done_at = done_at or (end.isoformat() if done and end else None)
        elif no == 9:
            due = sample.draft_report_date or ((end + timedelta(days=3 + q_days)) if end else None)
            done = bool(st.get("done") or marker == "+")
        elif no == 10:
            done = bool(st.get("done") or marker == "+")
            if sample.payment_status:
                extra["payment_status"] = sample.payment_status
        else:
            done = bool(st.get("done") or marker == "+")
        if st.get("source") == "excel":
            done_at, done_by = st.get("done_at"), st.get("done_by")
            extra["source"] = "excel"
        out.append(
            {
                "no": no,
                "title": sd["title"],
                "owner": sd["owner"],
                "kind": sd["kind"],
                "done": done,
                "done_at": done_at,
                "done_by": done_by,
                "due_date": due.isoformat() if due else None,
                "overdue": bool((not done) and (not abroad) and due and due < today and no in (9, 11)),
                "can_edit": no in perms["workflow_steps"] and sd["kind"] in ("manual", "auto_or_manual")
                and not (no == 4 and bool(sample.lab_arrival_date)),
                **extra,
            }
        )
    current_set = False
    for s in out:
        if s.get("abroad"):
            s["state"] = "abroad"
        elif s["done"]:
            s["state"] = "done"
        elif not current_set:
            s["state"] = "current"
            current_set = True
        else:
            s["state"] = "pending"
    return out


def effective_status(sample: SampleRecord, stepper: List[Dict[str, Any]], today: Optional[date] = None) -> str:
    today = today or facility_today()
    stored = (sample.stored_status or "").upper()
    if stored == "CANCELLED":
        return "CANCELLED"
    final_done = next((s["done"] for s in stepper if s["no"] == 11), False)
    if final_done or stored == "COMPLETED":
        return "COMPLETED"
    # FAZ 8.3: Excel'den gelen resmi durum (raw_status_text) mevcutsa EXPECTED / PLANNED / ONGOING ayrımını koru
    if sample.raw_status_text:
        if stored in ("EXPECTED", "PLANNED", "ONGOING", "COMPLETED"):
            return stored
    if stored == "EXPECTED" and not sample.lab_arrival_date and not (sample.sample_status or "").lower().startswith("kabul"):
        return "EXPECTED"
    if stored == "ONGOING" or (sample.planned_start and sample.planned_start <= today):
        return "ONGOING"
    if sample.planned_start or stored == "PLANNED" or sample.lab_arrival_date or (sample.sample_status or "").lower().startswith("kabul"):
        return "PLANNED"
    return "EXPECTED"


def overdue_reasons(sample: SampleRecord, status: str, stepper: List[Dict[str, Any]], today: Optional[date] = None) -> List[str]:
    today = today or facility_today()
    reasons: List[str] = []
    if status in ("COMPLETED", "CANCELLED"):
        return reasons
    if status == "EXPECTED" and sample.expected_arrival_date and sample.expected_arrival_date < today:
        reasons.append(f"Beklenen numune geliş tarihi geçti ({sample.expected_arrival_date:%d.%m.%Y})")
    for s in stepper:
        if s["no"] == 9 and s["overdue"]:
            reasons.append(f"Taslak rapor gecikti (son tarih {date.fromisoformat(s['due_date']):%d.%m.%Y})")
        if s["no"] == 11 and s["overdue"]:
            reasons.append(f"Final rapor gecikti (son tarih {date.fromisoformat(s['due_date']):%d.%m.%Y})")
    return reasons


def serialize_sample(
    db: Session,
    s: SampleRecord,
    perms: Dict[str, Any],
    all_samples: Optional[List[SampleRecord]] = None,
    detailed: bool = True,
    sync_schedule_dates: bool = True,
    today: Optional[date] = None,
) -> Dict[str, Any]:
    today = today or facility_today()
    study = find_study(db, s.study_code)
    has_schedule = _study_has_steps(db, study)
    if has_schedule and sync_schedule_dates:
        sync_dates_from_study(db, s, study)
    stepper = build_stepper(s, study, has_schedule, perms, today=today)
    status = effective_status(s, stepper, today=today)
    reasons = overdue_reasons(s, status, stepper, today=today)
    end = s.planned_end

    # FAZ 9.3: Hayvan / Sarf durumu ve Karantina (+7g) TAT hesabı
    anim_info = classify_animal_consumable_status(s.animal_consumable_status)
    q_days = anim_info["quarantine_days"]
    tpl_code = resolve_template_code(s.template_code) or infer_template_code(s.requested_analysis) or DEFAULT_TEMPLATE_CODE
    tpl = TEMPLATES.get(tpl_code) or TEMPLATES[DEFAULT_TEMPLATE_CODE]
    effective_tat_days = tpl.tat_with_quarantine_days if anim_info["requires_quarantine"] else tpl.tat_without_quarantine_days

    draft_dt = s.draft_report_date or ((end + timedelta(days=3 + q_days)) if end else None)
    base_final = s.final_report_date or ((end + timedelta(days=7 + q_days)) if end else None)
    if status != "COMPLETED" and base_final and draft_dt and base_final < draft_dt:
        final_dt = draft_dt + timedelta(days=4)
    else:
        final_dt = base_final

    # FAZ 9.3: Devam Eden (ONGOING) çalışmalar için "Sahada Deneyde" (11) vs "Rapor / QA Aşamasında" (22) kırılımı
    ongoing_phase = None
    ongoing_phase_label = None
    if status == "ONGOING":
        if s.experiment_end_date and s.experiment_end_date < today:
            ongoing_phase = "IN_REPORTING_QA"
            ongoing_phase_label = "Rapor / QA Bekliyor"
        else:
            ongoing_phase = "IN_EXPERIMENT"
            ongoing_phase_label = "Deney Sürüyor"

    is_draft_report_overdue = bool(
        status == "ONGOING"
        and (s.glp_type or "GLP") == "GLP"
        and s.draft_report_date is not None
        and s.draft_report_date < today
    )

    # FAZ 9.3: Sponsor sözleşme ve müşteri taahhüt (planlanan gönderim) tarihi eşleştirmesi
    sp_info = resolve_sponsor_agreement_info(s)
    ag_dt = s.study_agreement_date or sp_info["agreement_date"]
    commit_dt = sp_info["commitment_date"]
    commit_note = sp_info["commitment_note"]
    is_contract_deadline_exceeded = bool(
        status not in ("COMPLETED", "CANCELLED")
        and commit_dt is not None
        and (
            (draft_dt is not None and draft_dt > commit_dt)
            or (final_dt is not None and final_dt > commit_dt)
            or (today > commit_dt)
        )
    )
    if is_contract_deadline_exceeded:
        msg = f"Sözleşme termini aşılıyor (Taahhüt: {commit_dt:%d.%m.%Y})"
        if msg not in reasons:
            reasons.append(msg)

    related: List[Dict[str, Any]] = []
    if s.test_item_code:
        pool = all_samples if all_samples is not None else db.query(SampleRecord).filter(
            SampleRecord.test_item_code == s.test_item_code
        ).all()
        for o in pool:
            if o.id != s.id and (o.test_item_code or "").strip().lower() == s.test_item_code.strip().lower():
                related.append({"id": o.id, "study_code": o.study_code, "requested_analysis": o.requested_analysis})
    sd_user = match_study_director(db, s.study_director_name, include_inactive=True)

    contacts_out = list(s.contacts or [])
    if not contacts_out and (sp_info["person"] or sp_info["email"]):
        contacts_out = [{"name": sp_info["person"] or "", "email": sp_info["email"] or ""}]

    data = {
        "id": s.id,
        "serial_no": s.serial_no,
        "glp_type": s.glp_type or "GLP",
        "test_laboratory": s.test_laboratory,
        "study_code": s.study_code,
        "template_code": s.template_code,
        "requested_analysis": s.requested_analysis,
        "test_item_name": s.test_item_name,
        "billing_company": s.billing_company,
        "sponsor_name": s.sponsor_name,
        "contacts": contacts_out,
        "quote_no": s.quote_no,
        "sales_manager": s.sales_manager,
        "study_agreement_date": ag_dt.isoformat() if ag_dt else None,
        "contract_commitment_date": commit_dt.isoformat() if commit_dt else None,
        "contract_commitment_note": commit_note,
        "is_contract_deadline_exceeded": is_contract_deadline_exceeded,
        "expected_arrival_date": s.expected_arrival_date.isoformat() if s.expected_arrival_date else None,
        "sample_status": s.sample_status,
        "test_item_code": s.test_item_code,
        "istanbul_arrival_date": s.istanbul_arrival_date.isoformat() if s.istanbul_arrival_date else None,
        "lab_arrival_date": s.lab_arrival_date.isoformat() if s.lab_arrival_date else None,
        "received_quantity": s.received_quantity,
        "animal_consumable_status": s.animal_consumable_status,
        "animal_status_code": anim_info["code"],
        "animal_status_badge": anim_info["badge"],
        "requires_quarantine": anim_info["requires_quarantine"],
        "quarantine_days": q_days,
        "effective_tat_days": effective_tat_days,
        "animal_procurement_date": s.animal_procurement_date.isoformat() if s.animal_procurement_date else None,
        "lot_no": s.lot_no,
        "expiry_date": s.expiry_date,
        "storage_condition": s.storage_condition,
        "sample_note": s.sample_note,
        "manufacture_date": s.manufacture_date,
        "extraction_polar_solvent": s.extraction_polar_solvent,
        "extraction_non_polar_solvent": s.extraction_non_polar_solvent,
        "extraction_polar": s.extraction_polar,
        "extraction_non_polar": s.extraction_non_polar,
        "document_autofill": s.document_autofill,
        "study_director_name": s.study_director_name,
        "study_director_id": sd_user.id if sd_user else None,
        "payment_status": s.payment_status,
        "raw_status_text": s.raw_status_text,
        "status": status,
        "status_label": STATUS_LABELS[status],
        "ongoing_phase": ongoing_phase,
        "ongoing_phase_label": ongoing_phase_label,
        "is_draft_report_overdue": is_draft_report_overdue,
        "scheduled": has_schedule,
        "study": (
            {"id": study.id, "status": study.status.value, "has_schedule": has_schedule} if study is not None else None
        ),
        "dates": {
            "start": s.planned_start.isoformat() if s.planned_start else None,
            "end": end.isoformat() if end else None,
            "experiment_start": s.experiment_start_date.isoformat() if s.experiment_start_date else None,
            "experiment_end": s.experiment_end_date.isoformat() if s.experiment_end_date else None,
            "draft_report": draft_dt.isoformat() if draft_dt else None,
            "final_report": final_dt.isoformat() if final_dt else None,
        },
        "auto_schedule_notice": s.auto_schedule_notice,
        "overdue_reasons": reasons,
        "is_overdue": bool(reasons),
        "related": related,
        "progress": sum(1 for st in stepper if st["done"]),
        "abroad_steps": sum(1 for st in stepper if st.get("abroad")),
    }
    if detailed:
        data["workflow"] = stepper
    else:
        data["workflow_progress"] = {
            "done": data["progress"],
            "total": len(stepper),
            "abroad": data["abroad_steps"],
        }
    return data


def build_summary(items: List[Dict[str, Any]], db: Optional[Session] = None) -> Dict[str, Any]:
    open_items = [i for i in items if i["status"] not in ("COMPLETED", "CANCELLED")]
    sd_counts: Dict[str, int] = {}
    for i in open_items:
        name = (i.get("study_director_name") or "").strip() or "Atanmamış"
        sd_counts[name] = sd_counts.get(name, 0) + 1
    burcu_lbl = "Burcu DİGER KULAKSIZ" if "Burcu DİGER KULAKSIZ" in sd_counts and "Burcu DİGER KULAK" not in sd_counts else "Burcu DİGER KULAK"
    preferred = ["Ezgi Nur AKIN", "Ayşe Özgür", burcu_lbl, "Atanmamış"]
    ordered = [{"name": n, "open_count": sd_counts.get(n, 0)} for n in preferred]
    ordered += [{"name": n, "open_count": c} for n, c in sd_counts.items() if n not in preferred]

    glp_max = 82
    nglp_max = 11
    for i in items:
        c = str(i.get("study_code") or "").strip().upper()
        if c.startswith("GLP2026-"):
            tail = c.split("GLP2026-", 1)[1]
            if re.match(r"^\d{1,3}$", tail):
                n = int(tail)
                if 1 <= n <= 150 and n > glp_max:
                    glp_max = n
        elif "NGLP" in c and "2026" in c:
            after_yr = c.split("2026", 1)[1]
            for m_num in re.findall(r"\d{1,3}", after_yr):
                n = int(m_num)
                if 1 <= n <= 150 and n > nglp_max:
                    nglp_max = n

    return {
        "expected": sum(1 for i in items if i["status"] == "EXPECTED"),
        "planned": sum(1 for i in items if i["status"] == "PLANNED"),
        "planned_unscheduled": sum(1 for i in items if i["status"] == "PLANNED" and not i["scheduled"]),
        "ongoing": sum(1 for i in items if i["status"] == "ONGOING"),
        "ongoing_in_experiment": sum(1 for i in items if i["status"] == "ONGOING" and i.get("ongoing_phase") == "IN_EXPERIMENT"),
        "ongoing_in_reporting": sum(1 for i in items if i["status"] == "ONGOING" and i.get("ongoing_phase") == "IN_REPORTING_QA"),
        "ongoing_overdue_draft": sum(1 for i in items if i.get("is_draft_report_overdue")),
        "consumables_pending": sum(1 for i in items if i.get("animal_status_code") == "CONSUMABLES_PENDING"),
        "quarantine_count": sum(1 for i in items if i.get("animal_status_code") == "QUARANTINE"),
        "animal_reuse_count": sum(1 for i in items if i.get("animal_status_code") == "ANIMAL_REUSE"),
        "contract_deadline_exceeded": sum(1 for i in items if i.get("is_contract_deadline_exceeded")),
        "completed": sum(1 for i in items if i["status"] == "COMPLETED"),
        "cancelled": sum(1 for i in items if i["status"] == "CANCELLED"),
        "overdue": sum(1 for i in items if i["is_overdue"]),
        "glp_count": sum(1 for i in items if (i.get("glp_type") or "GLP") == "GLP"),
        "non_glp_count": sum(1 for i in items if (i.get("glp_type") or "GLP") == "NON-GLP"),
        "total": len(items),
        "next_glp_code": f"GLP2026-{glp_max + 1:03d}",
        "next_non_glp_code": f"NGLP-2026-{nglp_max + 1:03d}",
        "by_study_director": ordered,
    }


# ---------------------------------------------------------------------------
# ALAN GÜNCELLEME (ROL BAZLI)
# ---------------------------------------------------------------------------
def apply_field_updates(sample: SampleRecord, payload: Dict[str, Any], fields: Tuple[str, ...]) -> List[str]:
    changed: List[str] = []
    for f in fields:
        if f not in payload:
            continue
        val = payload[f]
        if f in DATE_FIELDS:
            val = parse_date_any(val)
        elif f == "contacts":
            val = [
                {"name": str(c.get("name") or "").strip(), "email": str(c.get("email") or "").strip()}
                for c in (val or []) if isinstance(c, dict) and (c.get("name") or c.get("email"))
            ]
        elif f == "template_code":
            val = resolve_template_code(val) if val else None
        elif isinstance(val, str):
            val = val.strip() or None
        if getattr(sample, f) != val:
            setattr(sample, f, val)
            changed.append(f)
    return changed


def sync_sample_shared_fields(db: Session, sample: SampleRecord, submitted_fields) -> List[str]:
    """Sync only submitted shared facts; never create a Study or touch its plan.

    Manual empty values explicitly clear nullable fields, unlike ambiguous blank
    Excel cells. A linked Study's mandatory product name cannot be cleared.
    The caller owns the transaction for this sample and all related records.
    """
    from app.services.excel_refresh import SHARED

    fields = set(submitted_fields) & (set(SHARED) | {"contacts"})
    if not fields:
        return []
    code = _clean_code(sample.study_code, 0)
    matches = [study for study in db.query(Study).all()
               if _clean_code(study.study_code, 0) == code] if code else []
    if len(matches) > 1:
        raise ValueError(f"{code}: birden fazla Study kaydı eşleşiyor; ortak alanlar güncellenemedi.")
    if not matches:
        return []
    study = matches[0]
    changed = []
    for source in sorted(fields):
        if source == "contacts":
            # Same representation used by the Excel refresh and plan_sample.
            value = "; ".join(
                f"{c.get('name', '')} <{c.get('email', '')}>".replace(" <>", "")
                for c in (sample.contacts or [])
            ) or None
            target = "sponsor_contact"
        else:
            value = getattr(sample, source)
            target = SHARED[source]
        if target == "test_item_name" and not value:
            raise ValueError(f"{code}: bağlı çalışmanın zorunlu test maddesi / ürün adı boşaltılamaz.")
        if getattr(study, target) != value:
            setattr(study, target, value)
            changed.append(target)
    return changed


# ---------------------------------------------------------------------------
# NUMUNEDEN OTOMATİK TASLAK ÇALIŞMA + TAKVİM
# ---------------------------------------------------------------------------
def default_start_for_sample(sample: SampleRecord) -> date:
    today = date.today()
    arrival = sample.lab_arrival_date or sample.expected_arrival_date or today
    return next_business_day(max(today + timedelta(days=1), arrival))


def plan_sample(
    db: Session,
    sample: SampleRecord,
    user: User,
    start_date: Optional[date] = None,
    preserve_status: bool = False,
    allow_non_draft: bool = False,
    existing_study: Optional[Study] = None,
) -> Dict[str, Any]:
    from app.services.scheduling_engine import ensure_no_execution_for_full_replan, schedule_new_study

    study = existing_study if existing_study is not None else find_study(db, sample.study_code)
    if study is not None:
        # Must precede field updates, the DRAFT override and the early commit.
        ensure_no_execution_for_full_replan(db, study)

    tpl_code = resolve_template_code(sample.template_code) or infer_template_code(sample.requested_analysis) or DEFAULT_TEMPLATE_CODE
    if tpl_code not in TEMPLATES:
        tpl_code = DEFAULT_TEMPLATE_CODE
    tpl = get_template(tpl_code, db=db)

    if study is not None and study.status != StudyStatus.DRAFT and not allow_non_draft:
        raise PermissionError(
            f"'{sample.study_code}' çalışması {study.status.value} durumundadır; onaylı çalışmaların takvimi "
            f"otomatik değiştirilmez. Takvimi Planlama ekranından görüntüleyebilirsiniz."
        )

    sd = match_study_director(db, sample.study_director_name)
    if sd is None:
        sd = (
            db.query(User).filter(User.role == UserRole.STUDY_DIRECTOR, User.is_active == True)  # noqa: E712
            .order_by(User.id).first()
        )
    if study is None and sd is None:
        raise ValueError("Sistemde aktif bir Çalışma Yöneticisi (STUDY_DIRECTOR) yok; önce kullanıcı tanımlayın.")

    contact_txt = "; ".join(
        f"{c.get('name', '')} <{c.get('email', '')}>".replace(" <>", "") for c in (sample.contacts or [])
    ) or None
    item_name = sample.test_item_name or "BELİRTİLMEDİ — SD tarafından girilecek"
    fields = dict(
        template_code=tpl.code,
        title=f"{tpl.standard} {tpl.title} — {item_name} ({sample.study_code})",
        test_type=sample.requested_analysis or tpl.title,
        guideline=tpl.standard,
        sponsor_name=sample.sponsor_name or sample.billing_company,
        sponsor_contact=contact_txt,
        test_item_name=item_name,
        test_item_batch=sample.lot_no,
        expiry_date=sample.expiry_date,
        manufacture_date=sample.manufacture_date,
        test_item_storage_condition=sample.storage_condition,
        extraction_polar=sample.extraction_polar,
        extraction_polar_solvent=sample.extraction_polar_solvent,
        extraction_non_polar=sample.extraction_non_polar,
        extraction_non_polar_solvent=sample.extraction_non_polar_solvent,
    )
    orig_study_status = study.status if study is not None else StudyStatus.DRAFT
    if study is None:
        study = Study(study_code=sample.study_code, study_director_id=sd.id, status=StudyStatus.DRAFT, **fields)
        db.add(study)
        db.flush()
        db.add(
            AuditLog(
                user_id=user.id, entity_name="Study", entity_id=study.id, action="CREATE",
                reason=f"{user.username}: Numune & Çalışma Takip ekranından '{sample.study_code}' DRAFT çalışması oluşturuldu.",
            )
        )
    else:
        for k, v in fields.items():
            if v not in (None, ""):
                setattr(study, k, v)
        if sd is not None and sample.study_director_name:
            study.study_director_id = sd.id
        if allow_non_draft and study.status != StudyStatus.DRAFT:
            study.status = StudyStatus.DRAFT
    db.commit()

    g0 = start_date or sample.planned_start or default_start_for_sample(sample)
    result = schedule_new_study(db, study.id, g0, template_code=tpl.code)

    db.refresh(study)
    if allow_non_draft and orig_study_status != StudyStatus.DRAFT:
        study.status = orig_study_status
    sample.template_code = tpl.code
    sample.planned_start = study.acclimatization_start_date
    sample.planned_end = study.target_end_date
    anim_meta = classify_animal_consumable_status(sample.animal_consumable_status)
    q_days = 7 if anim_meta["requires_quarantine"] else 0
    if not sample.draft_report_date and sample.planned_end:
        sample.draft_report_date = sample.planned_end + timedelta(days=3 + q_days)
    if not sample.final_report_date and sample.planned_end:
        base_final = sample.planned_end + timedelta(days=7 + q_days)
        if sample.draft_report_date and base_final < sample.draft_report_date + timedelta(days=4):
            base_final = sample.draft_report_date + timedelta(days=4)
        sample.final_report_date = base_final
    if not sample.study_director_name and study.study_director:
        sample.study_director_name = study.study_director.full_name
    if not preserve_status and not sample.raw_status_text and (sample.stored_status or "").upper() in ("", "EXPECTED"):
        sample.stored_status = "PLANNED"
    notice = result.get("auto_schedule_notice") or {}
    sample.auto_schedule_notice = notice.get("text") if notice else None
    db.add(
        AuditLog(
            user_id=user.id, entity_name="SampleRecord", entity_id=sample.id, action="SAMPLE_AUTO_SCHEDULE",
            new_values={
                "study_code": sample.study_code, "template": tpl.code,
                "day0": sample.planned_start.isoformat() if sample.planned_start else None,
                "end": sample.planned_end.isoformat() if sample.planned_end else None,
                "auto_shifted": bool(notice),
            },
            reason=f"{user.username}: '{sample.study_code}' numunesi için otomatik taslak takvim oluşturuldu.",
        )
    )
    db.commit()
    return {
        "study_id": study.id,
        "study_code": study.study_code,
        "start": sample.planned_start.isoformat() if sample.planned_start else None,
        "end": sample.planned_end.isoformat() if sample.planned_end else None,
        "status": result.get("status"),
        "total_conflicts": result.get("total_conflicts"),
        "critical_conflicts": result.get("critical_conflicts"),
        "warning_conflicts": result.get("warning_conflicts"),
        "auto_schedule_notice": result.get("auto_schedule_notice"),
        "capacity_info": result.get("capacity_info"),
    }


# ---------------------------------------------------------------------------
# EXCEL / CSV İÇE AKTARMA
# ---------------------------------------------------------------------------
_COLUMN_SYNONYMS: Dict[str, Tuple[str, ...]] = {
    "study_code": ("glp no", "glp", "glp kodu", "calisma kodu", "calisma no", "study code", "study no", "study", "glp calisma no"),
    "requested_analysis": ("talep edilen analiz", "analiz", "test", "test adi", "talep edilen test", "analiz adi"),
    "test_item_name": ("test maddesinin adi", "test maddesi", "test maddesi adi", "numune adi", "urun adi", "urun", "test item"),
    "billing_company": ("fatura edilecek firma", "fatura firma", "fatura edilecek firma unvani", "fatura unvani"),
    "sponsor_name": ("sponsor", "firma", "musteri", "sponsor firma", "firma unvani"),
    "contacts": ("ilgili kisiler", "ilgili kisi", "iletisim", "e posta", "email", "eposta", "mail", "yetkili"),
    "quote_no": ("teklif no", "teklif numarasi", "teklif", "quote no"),
    "sales_manager": ("satis yoneticisi", "satis temsilcisi", "satis sorumlusu", "satis"),
    "expected_arrival_date": ("beklenen gelis tarihi", "beklenen tarih", "beklenen numune gelis tarihi", "tahmini gelis"),
    "sample_status": ("numune durumu", "durum", "kabul durumu"),
    "test_item_code": ("test madde kodu", "test maddesi kodu", "ti no", "ti kodu", "ti", "trm kodu", "test item code"),
    "istanbul_arrival_date": ("istanbula gelis tarihi", "istanbul gelis tarihi", "istanbul gelis"),
    "lab_arrival_date": ("laboratuvara gelis tarihi", "laboratuvar gelis tarihi", "lab gelis tarihi", "lab gelis", "edirne gelis tarihi"),
    "received_quantity": ("teslim alinan miktar", "miktar", "adet", "teslim miktari"),
    "lot_no": ("lot", "lot no", "seri no", "lot seri no", "lot numarasi", "batch"),
    "expiry_date": ("skt", "son kullanma tarihi", "son kullanim tarihi", "expiry"),
    "storage_condition": ("saklama kosulu", "saklama kosullari", "saklama"),
    "sample_note": ("numune notu", "not", "notlar", "aciklama"),
    "study_director_name": ("calisma yoneticisi", "calisma direktoru", "cy", "sd", "study director"),
}
_HEADER_LOOKUP = {norm_key(s): field for field, syns in _COLUMN_SYNONYMS.items() for s in syns}
_HEADER_LOOKUP.update({norm_key(f): f for f in _COLUMN_SYNONYMS})


def _parse_contacts(raw: Any) -> List[Dict[str, str]]:
    if raw is None or str(raw).strip() == "":
        return []
    contacts: List[Dict[str, str]] = []
    for part in re.split(r"[;\n]+", str(raw)):
        part = part.strip()
        if not part:
            continue
        m = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", part)
        email = m.group(0) if m else ""
        name = re.sub(r"[<>(),]", " ", part.replace(email, "")).strip() if email else part
        contacts.append({"name": name, "email": email})
    return contacts


def read_tabular_file(filename: str, content: bytes) -> List[Dict[str, Any]]:
    """`.xlsx` (openpyxl) veya `.csv` dosyasından başlık satırını otomatik bulup sözlük listesi döner."""
    ext = (filename or "").lower().rsplit(".", 1)[-1]
    rows: List[List[Any]] = []
    if ext in ("xlsx", "xlsm"):
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(content), data_only=True, read_only=True)
        ws = wb.worksheets[0]
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        wb.close()
    elif ext in ("csv", "txt"):
        text = None
        for enc in ("utf-8-sig", "cp1254", "latin-1"):
            try:
                text = content.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        text = text or ""
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
        except csv.Error:
            class _Fallback(csv.excel):
                delimiter = ";" if text.count(";") > text.count(",") else ","

            dialect = _Fallback
        rows = [list(r) for r in csv.reader(io.StringIO(text), dialect)]
    else:
        raise ValueError("Yalnızca .xlsx veya .csv dosyaları içe aktarılabilir.")

    header_idx, header_map = None, {}
    for idx, row in enumerate(rows[:15]):
        mapping = {}
        for ci, cell in enumerate(row):
            field = _HEADER_LOOKUP.get(norm_key(cell))
            if field and field not in mapping.values():
                mapping[ci] = field
        if len(mapping) >= 2 and "study_code" in mapping.values():
            header_idx, header_map = idx, mapping
            break
    if header_idx is None:
        raise ValueError(
            "Başlık satırı tanınamadı. En az 'GLP No / Çalışma Kodu' sütunu ve bir veri sütunu içeren başlık satırı gerekir."
        )
    out = []
    for row in rows[header_idx + 1:]:
        rec = {field: (row[ci] if ci < len(row) else None) for ci, field in header_map.items()}
        if any(v not in (None, "") for v in rec.values()):
            out.append(rec)
    return out


def import_rows(db: Session, records: List[Dict[str, Any]], user: User) -> Dict[str, Any]:
    created = updated = skipped = 0
    errors: List[str] = []
    for n, rec in enumerate(records, start=1):
        code = str(rec.get("study_code") or "").strip().upper().replace(" ", "")
        if not code:
            skipped += 1
            errors.append(f"Satır {n}: çalışma kodu (GLP No) boş — atlandı.")
            continue
        sample = db.query(SampleRecord).filter(SampleRecord.study_code == code).first()
        is_new = sample is None
        if is_new:
            sample = SampleRecord(study_code=code, workflow={})
            db.add(sample)
        payload: Dict[str, Any] = {}
        for k, v in rec.items():
            if k == "study_code" or v is None or (isinstance(v, str) and not v.strip()):
                continue
            if k == "contacts":
                payload[k] = _parse_contacts(v)
            elif k in DATE_FIELDS:
                pd = parse_date_any(v)
                if pd is None:
                    errors.append(f"Satır {n} ({code}): '{k}' tarihi anlaşılamadı: {v!r}")
                    continue
                payload[k] = pd
            else:
                payload[k] = str(v).strip() if not isinstance(v, (int, float)) else str(v)
        if is_new or "template_code" not in payload:
            inferred = infer_template_code(payload.get("requested_analysis") or sample.requested_analysis)
            if inferred and not sample.template_code:
                payload["template_code"] = inferred
        apply_field_updates(sample, payload, SALES_FIELDS + TRM_FIELDS + PLANNING_FIELDS)
        if is_new:
            sample.stored_status = "PLANNED" if sample.lab_arrival_date else "EXPECTED"
            created += 1
        else:
            updated += 1
    db.add(
        AuditLog(
            user_id=user.id, entity_name="SampleRecord", entity_id=0, action="SAMPLE_EXCEL_IMPORT",
            new_values={"created": created, "updated": updated, "skipped": skipped},
            reason=f"{user.username}: Excel/CSV içe aktarma — {created} yeni, {updated} güncellenen, {skipped} atlanan kayıt.",
        )
    )
    db.commit()
    return {"created": created, "updated": updated, "skipped": skipped, "errors": errors[:50], "total_rows": len(records)}


# ---------------------------------------------------------------------------
# ÖRNEK VERİ TOHUMLAMA (yalnızca eksik kayıtlar eklenir; mevcutlara dokunulmaz)
# ---------------------------------------------------------------------------
SEED_USERS = (
    ("ayse.ozgur", "Ayşe Özgür", "STUDY_DIRECTOR"),
    ("burcu.diger", "Burcu DİGER KULAK", "STUDY_DIRECTOR"),
    ("ilknur.toklu", "İlknur Toklu", "SALES"),
    ("trm_kabul", "TRM Kabul", "TRM_KABUL"),
)

_MERKEN_COMMON = dict(
    test_item_name="MERKEN PLLA+HA",
    sponsor_name="MERKEN",
    billing_company="MERKEN",
    sales_manager="İlknur Toklu",
    test_item_code="TI-2026-0016",
    sample_status="Kabul edildi",
    istanbul_arrival_date=date(2026, 10, 26),
    lab_arrival_date=date(2026, 10, 28),
    received_quantity="30 adet / 30 pieces",
    stored_status="PLANNED",
)

SEED_SAMPLES: Tuple[Dict[str, Any], ...] = (
    dict(
        study_code="GLP2026-072", template_code="ISO_10993_6_IMP", requested_analysis="İmplantasyon Testi (Deri Altı) — ISO 10993-6",
        study_director_name="Ezgi Nur AKIN", workflow={"1": {"done": True, "done_by": "İlknur Toklu", "done_at": "2026-10-20"}},
        **_MERKEN_COMMON,
    ),
    dict(
        study_code="GLP2026-076", template_code="ISO_10993_5_CYTO", requested_analysis="In Vitro Sitotoksisite — ISO 10993-5",
        study_director_name="Ayşe Özgür", workflow={"1": {"done": True, "done_by": "İlknur Toklu", "done_at": "2026-10-20"}},
        **_MERKEN_COMMON,
    ),
    dict(
        study_code="GLP2026-073", template_code="ISO_10993_10_SENS", requested_analysis="Sensitizasyon Testi — ISO 10993-10",
        study_director_name="Burcu DİGER KULAK", workflow={"1": {"done": True, "done_by": "İlknur Toklu", "done_at": "2026-10-20"}},
        **_MERKEN_COMMON,
    ),
    dict(
        study_code="GLP2026-031", template_code="ISO_10993_10_SENS", requested_analysis="Sensitizasyon Testi — ISO 10993-10",
        test_item_name="Merken Aqua HA 90mg/3mL", sponsor_name="MERKEN", billing_company="MERKEN", sales_manager="İlknur Toklu",
        test_item_code="TI-2026-0009", sample_status="Kabul edildi", istanbul_arrival_date=date(2026, 10, 14),
        lab_arrival_date=date(2026, 10, 16), received_quantity="20 adet / 20 pieces", stored_status="ONGOING",
        planned_start=date(2026, 10, 26), planned_end=date(2026, 11, 4), study_director_name="Ezgi Nur AKIN",
        workflow={
            "1": {"done": True, "done_by": "İlknur Toklu", "done_at": "2026-10-05"},
            "2": {"done": True, "done_by": "Ezgi Nur AKIN", "done_at": "2026-10-12"},
            "3": {"done": True, "done_by": "Ezgi Nur AKIN", "done_at": "2026-10-19"},
            "6": {"approvals": {
                "CY": {"by": "Ezgi Nur AKIN", "at": "2026-10-22T10:00:00"},
                "KG": {"by": "Kalite Güvence Birimi", "at": "2026-10-22T14:00:00"},
                "TBY": {"by": "Emine ARMUTOĞLU", "at": "2026-10-23T09:30:00"},
            }},
        },
    ),
    dict(
        study_code="GLP2026-026", template_code="ISO_10993_23_IC", requested_analysis="İntrakütanöz Reaktivite Testi — ISO 10993-23",
        test_item_name="Hyaluronik Asit HA 30 mg/ml", sponsor_name="ELISA TIBBI GEREÇLER SAN A.Ş.",
        billing_company="ELISA TIBBI GEREÇLER SAN A.Ş.", sales_manager="İlknur Toklu", sample_status="Kabul edildi",
        lab_arrival_date=date(2026, 7, 24), stored_status="ONGOING", planned_start=date(2026, 7, 30), planned_end=date(2026, 8, 12),
        study_director_name="Ezgi Nur AKIN",
        workflow={
            "1": {"done": True, "done_by": "İlknur Toklu", "done_at": "2026-07-10"},
            "2": {"done": True, "done_by": "Ezgi Nur AKIN", "done_at": "2026-07-15"},
            "3": {"done": True, "done_by": "Ezgi Nur AKIN", "done_at": "2026-07-22"},
            "6": {"approvals": {
                "CY": {"by": "Ezgi Nur AKIN", "at": "2026-07-27T10:00:00"},
                "KG": {"by": "Kalite Güvence Birimi", "at": "2026-07-27T15:00:00"},
                "TBY": {"by": "Emine ARMUTOĞLU", "at": "2026-07-28T09:00:00"},
            }},
            "9": {"done": True, "done_by": "Ezgi Nur AKIN", "done_at": "2026-08-15"},
        },
    ),
    dict(
        study_code="GLP2026-078", template_code="ISO_10993_11_ACUTE", requested_analysis="Akut Sistemik Toksisite — ISO 10993-11",
        test_item_name="(Numune bekleniyor)", sales_manager="İlknur Toklu", sample_status="Bekleniyor",
        expected_arrival_date=date(2026, 11, 9), stored_status="EXPECTED", study_director_name=None, workflow={},
    ),
)


def seed_sample_tracking(db: Session) -> Dict[str, int]:
    """Numune takip örnek kullanıcılarını ve kayıtlarını (yoksa) ekler. Mevcut kayıtlara dokunmaz."""
    from app.models.role_permission import ensure_default_role_permissions
    from app.seed import DEFAULT_PASSWORD  # noqa: F401
    from app.utils.security import get_password_hash

    ensure_default_role_permissions(db)
    new_users = new_samples = 0
    hashed = None
    for username, full_name, role in SEED_USERS:
        if db.query(User).filter(User.username == username).first():
            continue
        hashed = hashed or get_password_hash("NanoLab2026!")
        db.add(
            User(
                username=username, full_name=full_name, role=role, is_active=True,
                max_daily_hours=9, qualifications=[], hashed_password=hashed,
            )
        )
        new_users += 1
    for rec in SEED_SAMPLES:
        if db.query(SampleRecord).filter(SampleRecord.study_code == rec["study_code"]).first():
            continue
        db.add(SampleRecord(contacts=[], **copy.deepcopy(rec)))
        new_samples += 1
    db.commit()
    return {"users": new_users, "samples": new_samples}


# ---------------------------------------------------------------------------
# FAZ 8.3 — STUDY STATUS LAST VERSION (2).XLSX TAM İÇE AKTARIM, PERSONEL & İŞ AKIŞI EŞLEŞTİRME
# ---------------------------------------------------------------------------
EXCEL_PERSONNEL_ACCOUNTS: Tuple[Tuple[str, str, str, bool], ...] = (
    # Study Directors (SD)
    ("ezgi.nur", "Ezgi Nur AKIN", "STUDY_DIRECTOR", True),
    ("ayse.ozgur", "Ayşe Özgür", "STUDY_DIRECTOR", True),
    ("burcu.diger", "Burcu DİGER KULAKSIZ", "STUDY_DIRECTOR", True),
    ("ceyla.abay", "Ceyla Abay", "STUDY_DIRECTOR", True),
    # Yiğit Babaoğlu işten ayrıldı: sadece geçmiş (Biten/Finished) çalışmalarda pasif kayıt olarak korunur;
    # aktif SYSADMIN "yigit" (Yiğit Kadir) hesabına kesinlikle dokunulmaz!
    ("yigit.babaoglu", "Yiğit Babaoğlu", "STUDY_DIRECTOR", False),
    # Üst Yönetim (GM / GMY)
    ("shivadasan.anoop", "Dr. Shivadasan Anoop", "EXECUTIVE", True),
    ("ozkan.bey", "Özkan Bey", "EXECUTIVE", True),
    # Satış Yöneticileri (SALES)
    ("ilknur.toklu", "İlknur Toklu", "SALES", True),
    ("aysenur.dural", "Ayşenur Dural", "SALES", True),
    ("tugrul.tuzlali", "Tuğrul Tuzlalı", "SALES", True),
    ("nil.discioglu", "Nil Dişçioğlu", "SALES", True),
    ("alp.soganci", "Alp Soğancı", "SALES", True),
    # TRM Kabul, QA ve TFM
    ("trm_kabul", "TRM Kabul", "TRM_KABUL", True),
    ("trm.acceptance", "TRM Acceptance", "TRM_ACCEPTANCE", True),
    ("selin.bolcan", "Selin Bolcan", "QA", True),
    ("emine.armutoglu", "Emine ARMUTOĞLU", "TFM", True),
)


def normalize_sales_manager(raw: Optional[str]) -> Optional[str]:
    if not raw or not str(raw).strip():
        return None
    s = str(raw).strip()
    k = norm_key(s)
    if "ilknur" in k:
        return "İlknur Toklu"
    if "aysenur" in k or "ayse nur" in k:
        return "Ayşenur Dural"
    if "tugrul" in k:
        return "Tuğrul Tuzlalı"
    if "nil" in k:
        return "Nil Dişçioğlu"
    if "alp" in k:
        return "Alp Soğancı"
    return s


def normalize_study_director_name(raw: Optional[str]) -> Optional[str]:
    if not raw or not str(raw).strip():
        return None
    s = str(raw).strip()
    k = norm_key(s)
    if "ezgi" in k:
        return "Ezgi Nur AKIN"
    if "ayse" in k:
        return "Ayşe Özgür"
    if "burcu" in k:
        return "Burcu DİGER KULAKSIZ"
    if "ceyla" in k:
        return "Ceyla Abay"
    if "yigit" in k:
        return "Yiğit Babaoğlu"
    return s


def ensure_excel_personnel_users(db: Session) -> Dict[str, Any]:
    """Excel'deki tüm personel için kullanıcı hesaplarını (varsayılan şifre NanoLab2026!) oluşturur/günceller."""
    from app.models.role_permission import ensure_default_role_permissions
    from app.utils.security import get_password_hash

    ensure_default_role_permissions(db)
    hashed = get_password_hash("NanoLab2026!")
    created: List[str] = []
    updated: List[str] = []
    for username, full_name, role, is_active in EXCEL_PERSONNEL_ACCOUNTS:
        u = db.query(User).filter(User.username == username).first()
        if u is None:
            u = User(
                username=username,
                full_name=full_name,
                role=role,
                is_active=is_active,
                max_daily_hours=9,
                qualifications=[],
                hashed_password=hashed,
            )
            db.add(u)
            created.append(username)
        else:
            changed = False
            if username == "burcu.diger" and u.full_name != "Burcu DİGER KULAKSIZ":
                u.full_name = "Burcu DİGER KULAKSIZ"
                changed = True
            if username == "yigit.babaoglu" and u.is_active != False:  # noqa: E712
                u.is_active = False
                changed = True
            if not u.hashed_password:
                u.hashed_password = hashed
                changed = True
            if changed:
                updated.append(username)
    db.commit()
    return {"created": created, "updated": updated}


def is_study_status_workbook(filename: str, content: bytes) -> bool:
    ext = (filename or "").lower().rsplit(".", 1)[-1]
    if ext not in ("xlsx", "xlsm"):
        return False
    try:
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(content), data_only=True, read_only=True)
        names = [norm_key(n) for n in wb.sheetnames]
        wb.close()
        return any("glp medikal" in n for n in names)
    except Exception:
        return False


def _wf_firm_cat(f: Any) -> str:
    k = norm_key(f)
    for token, cat in (
        ("db medikal", "db"),
        ("disera", "disera"),
        ("saniter", "saniter"),
        ("inceler", "saniter"),
        ("alkan", "alkan"),
        ("medfors", "medfors"),
        ("inovabella", "inovabella"),
        ("elisa", "elisa"),
        ("toxlab", "toxlab"),
        ("t lab", "toxlab"),
        ("plasti", "plastimed"),
        ("meditera", "meditera"),
        ("forenscope", "forenscope"),
        ("acto", "acto"),
        ("merken", "merken"),
        ("turkuaz", "turkuaz"),
        ("burak", "burak"),
        ("global", "global"),
        ("biomeks", "biomeks"),
        ("inter", "inter"),
        ("tria", "tria"),
        ("sonomed", "sonomed"),
        ("aksu", "aksu"),
        ("ortosem", "ortosem"),
    ):
        if token in k:
            return cat
    return k.split()[0] if k else ""


def _wf_test_cat(t: Any) -> str:
    k = norm_key(t)
    if "implant" in k:
        return "imp"
    if "sitotok" in k or "cytotox" in k:
        return "cyto"
    if "sensit" in k or "hassas" in k:
        return "sens"
    if "irrit" in k or "intrakut" in k or "intracut" in k or "intradermal" in k or "oral" in k or "okuler" in k or "ocular" in k:
        return "irr"
    if re.search(r"\b(akut|acute)\b|vivoacute|sistemik|systemic", k):
        return "acute"
    if "subakut" in k or "subacute" in k:
        return "subacute"
    if "subkronik" in k or "subchronic" in k:
        return "subchronic"
    if "pirojen" in k or "pyrogen" in k:
        return "pyro"
    if "hemol" in k:
        return "hemo"
    return k


def _marker_str(val: Any) -> str:
    s = str(val or "").strip()
    if not s:
        return "-"
    low = norm_key(s)
    if "yurt" in low:
        return "yurt dışı"
    if "+" in s:
        return "+"
    return "-"


def _build_workflow_from_markers(
    markers: List[str],
    sd_name: Optional[str],
    sales_name: Optional[str],
    agreement_dt: Optional[date],
    arrival_dt: Optional[date],
    start_dt: Optional[date],
    end_dt: Optional[date],
    draft_dt: Optional[date],
    final_dt: Optional[date],
) -> Dict[str, Any]:
    # Imported assertions are source information, never application signatures.
    return {str(i): {"done": m == "+", "marker": m, "source": "excel",
                     **({"abroad": True} if m == "yurt dışı" else {})}
            for i, m in enumerate(markers, 1)}


def _build_default_workflow_for_status(
    stored_status: str,
    sd_name: Optional[str],
    sales_name: Optional[str],
    agreement_dt: Optional[date],
    arrival_dt: Optional[date],
    start_dt: Optional[date],
    end_dt: Optional[date],
    draft_dt: Optional[date],
    final_dt: Optional[date],
    payment_status: Optional[str],
) -> Dict[str, Any]:
    paid = "yapildi" in norm_key(payment_status) and "yapilmadi" not in norm_key(payment_status)
    if stored_status == "COMPLETED":
        markers = ["+"] * 11
    elif stored_status == "ONGOING":
        markers = [
            "+", "+", "+", "+", "+", "+", "+",
            "+" if end_dt else "-",
            "+" if draft_dt else "-",
            "+" if paid else "-",
            "-",
        ]
    elif stored_status == "PLANNED":
        markers = [
            "+",
            "+",
            "-",
            "+" if arrival_dt else "-",
            "-", "-", "-", "-", "-",
            "+" if paid else "-",
            "-",
        ]
    else:
        markers = ["+", "-", "-", "-", "-", "-", "-", "-", "-", "+" if paid else "-", "-"]
    return _build_workflow_from_markers(
        markers, sd_name, sales_name, agreement_dt, arrival_dt, start_dt, end_dt, draft_dt, final_dt
    )


def _clean_code(raw: Any, sira_no: int) -> str:
    s = str(raw or "").strip()
    if norm_key(s) == "yurt disi":
        return f"GLP2026-YD{sira_no:02d}"
    return re.sub(r"\s+", "", s).upper()


def _clean_ti_code(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    s = re.sub(r"\s+", " ", str(raw)).strip()
    if not s or norm_key(s) in ("beklemede", "waiting", "pending", "-", "yok"):
        return None
    return s


def _map_status(raw_status: Optional[str], has_arrival: bool) -> str:
    k = norm_key(raw_status)
    if "biten" in k or "finished" in k or "completed" in k:
        return "COMPLETED"
    if "devem" in k or "devam" in k or "on going" in k or "ongoing" in k:
        return "ONGOING"
    if "planlanan" in k or "planning" in k or "planned" in k:
        return "PLANNED"
    if "beklenen" in k or "expected" in k:
        return "EXPECTED"
    return "PLANNED" if has_arrival else "EXPECTED"


def _import_study_status_workbook(
    db: Session,
    content: bytes,
    user: User,
    auto_schedule: bool = True,
    prune_non_excel: bool = True,
) -> Dict[str, Any]:
    """
    `Study Status last version (2).xlsx` çok sekmeli çalışma dosyasını (88 GLP + 5 Non-GLP + 47 Numune İş Akışı)
    tam olarak içe aktarır, personel hesaplarını tamamlar ve bekleyen/planlanan çalışmaları otomatik takvimler.
    """
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(content), data_only=True)

    ws_glp = next((wb[n] for n in wb.sheetnames if "glp medikal" in norm_key(n)), None)
    ws_nglp = next((wb[n] for n in wb.sheetnames if "non glp" in norm_key(n)), None)
    ws_wf = next((wb[n] for n in wb.sheetnames if "is akisi" in norm_key(n)), None)
    ws_sp = next((wb[n] for n in wb.sheetnames if "sponsor" in norm_key(n)), None)
    if ws_glp is None:
        wb.close()
        raise ValueError("'GLP Medikal' sekmesi bulunamadı.")

    from app.services.excel_refresh import SheetColumns
    ws_glp = SheetColumns(ws_glp, 7, "glp")
    if ws_nglp is not None:
        ws_nglp = SheetColumns(ws_nglp, 6, "non_glp")

    # 1) Sponsor sözleşme sekmesinden yedek iletişim / sözleşme tarihi sözlüğü
    sponsor_lookup: Dict[str, Dict[str, Any]] = {}
    if ws_sp is not None:
        for r in range(4, ws_sp.max_row + 1):
            firm = ws_sp.cell(r, 2).value
            sp_col = ws_sp.cell(r, 3).value
            if not firm and not sp_col:
                continue
            fk = _wf_firm_cat(firm or sp_col)
            person = ws_sp.cell(r, 5).value
            mail = ws_sp.cell(r, 6).value
            ag_date = parse_date_any(ws_sp.cell(r, 12).value)
            if fk and fk not in sponsor_lookup and (person or mail or ag_date):
                sponsor_lookup[fk] = {
                    "person": str(person).strip() if person else "",
                    "email": str(mail).strip() if mail else "",
                    "agreement_date": ag_date,
                }

    # 2) NUMUNE İŞ AKIŞI sekmesi (47 satır: R5..R51)
    # Sütunlar: Col 1=Firma Adı, Col 2=Numune/Test Adı, Col 3..7=Adım 1..5,
    # Col 8..10=Adım 6 (ÇY, KG, TBY), Col 11..14=Adım 7..10, Col 15..17=Adım 11 (ÇY, KG, TBY)
    wf_rows: List[Dict[str, Any]] = []
    if ws_wf is not None:
        for r in range(5, ws_wf.max_row + 1):
            firm = ws_wf.cell(r, 1).value
            test_name = ws_wf.cell(r, 2).value
            if not firm and not test_name:
                continue
            m1_5 = [_marker_str(ws_wf.cell(r, c).value) for c in range(3, 8)]
            m6 = _marker_str(ws_wf.cell(r, 8).value or ws_wf.cell(r, 9).value or ws_wf.cell(r, 10).value)
            m7_10 = [_marker_str(ws_wf.cell(r, c).value) for c in range(11, 15)]
            m11 = _marker_str(ws_wf.cell(r, 15).value or ws_wf.cell(r, 16).value or ws_wf.cell(r, 17).value)
            markers = m1_5 + [m6] + m7_10 + [m11]
            wf_rows.append(
                {
                    "row": r,
                    "firm": str(firm or "").strip(),
                    "test": str(test_name or "").strip(),
                    "firm_cat": _wf_firm_cat(firm),
                    "test_cat": _wf_test_cat(test_name),
                    "markers": markers,
                }
            )

    # 3) GLP Medikal sekmesi (satır 8..95 -> 88 GLP çalışması)
    glp_parsed: List[Dict[str, Any]] = []
    for r in range(8, ws_glp.max_row + 1):
        sira_raw = ws_glp.cell(r, 1).value
        if sira_raw is None or str(sira_raw).strip() == "":
            if not ws_glp.cell(r, 8).value:
                continue
            sira_raw = r - 7
        try:
            sira_no = int(float(str(sira_raw).strip()))
        except ValueError:
            continue
        raw_code = ws_glp.cell(r, 8).value
        study_code = _clean_code(raw_code, sira_no)
        if not study_code:
            raise ValueError(f"GLP Medikal satır {r}: çalışma kodu eksik")
        req_analysis = re.sub(r"\s+", " ", str(ws_glp.cell(r, 2).value or "")).strip() or None
        test_item = re.sub(r"\s+", " ", str(ws_glp.cell(r, 3).value or "")).strip() or None
        sd_name = normalize_study_director_name(ws_glp.cell(r, 4).value)
        billing = re.sub(r"\s+", " ", str(ws_glp.cell(r, 5).value or "")).strip() or None
        raw_sp = re.sub(r"\s+", " ", str(ws_glp.cell(r, 6).value or "")).strip()
        sponsor = raw_sp if (raw_sp and raw_sp != "-") else None
        person_mail_raw = str(ws_glp.cell(r, 7).value or "").strip()
        sales_mgr = normalize_sales_manager(ws_glp.cell(r, 9).value)
        quote_no = re.sub(r"\s+", " ", str(ws_glp.cell(r, 10).value or "")).strip() or None
        if quote_no == "-":
            quote_no = None
        ist_date = parse_date_any(ws_glp.cell(r, 11).value)
        lab_date = parse_date_any(ws_glp.cell(r, 12).value)
        ti_code = _clean_ti_code(ws_glp.cell(r, 13).value)
        lab_type = str(ws_glp.cell(r, 14).value or "").strip() or None
        qty_val = ws_glp.cell(r, 15).value
        qty_str = str(int(qty_val)) if isinstance(qty_val, float) and qty_val.is_integer() else (str(qty_val).strip() if qty_val is not None else None)
        if qty_str == "-":
            qty_str = None
        anim_status = re.sub(r"\s+", " ", str(ws_glp.cell(r, 16).value or "")).strip() or None
        if anim_status == "-":
            anim_status = None
        anim_date = parse_date_any(ws_glp.cell(r, 17).value)
        plan_st = parse_date_any(ws_glp.cell(r, 18).value)
        exp_st = parse_date_any(ws_glp.cell(r, 19).value)
        exp_end = parse_date_any(ws_glp.cell(r, 20).value)
        draft_dt = parse_date_any(ws_glp.cell(r, 21).value)
        pay_status = re.sub(r"\s+", " ", str(ws_glp.cell(r, 22).value or "")).strip() or None
        if pay_status == "-":
            pay_status = None
        final_dt = parse_date_any(ws_glp.cell(r, 23).value)
        raw_status = re.sub(r"\s+", " ", str(ws_glp.cell(r, 25).value or "")).strip() or None
        notes_parts = [
            re.sub(r"\s+", " ", str(ws_glp.cell(r, c).value or "")).strip()
            for c in (26, 27)
            if ws_glp.cell(r, c).value and str(ws_glp.cell(r, c).value).strip() != "-"
        ]
        note_col = " | ".join(notes_parts) if notes_parts else None
        if norm_key(raw_code) == "yurt disi":
            note_col = f"Yurt dışı çalışması ({note_col})" if note_col else "Yurt dışı çalışması (Excel çalışma kodu: yurt dışı)"

        fk = _wf_firm_cat(sponsor or billing)
        sp_fallback = sponsor_lookup.get(fk, {})
        ag_date = sp_fallback.get("agreement_date")
        if (not person_mail_raw or person_mail_raw == "-") and (sp_fallback.get("person") or sp_fallback.get("email")):
            person_mail_raw = f"{sp_fallback.get('person', '')} / {sp_fallback.get('email', '')}".strip(" /")

        contacts: List[Dict[str, str]] = []
        if person_mail_raw and person_mail_raw != "-":
            emails = re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]+", person_mail_raw)
            name_part = person_mail_raw.split("/")[0].strip() if "/" in person_mail_raw else re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "", person_mail_raw).strip()
            contacts.append({"name": name_part or (emails[0] if emails else person_mail_raw), "email": ", ".join(emails)})

        stored_status = _map_status(raw_status, bool(lab_date or ist_date))
        glp_parsed.append(
            {
                "serial_no": sira_no,
                "glp_type": "GLP",
                "study_code": study_code,
                "test_laboratory": lab_type,
                "requested_analysis": req_analysis,
                "test_item_name": test_item,
                "study_director_name": sd_name,
                "billing_company": billing,
                "sponsor_name": sponsor,
                "contacts": contacts,
                "sales_manager": sales_mgr,
                "quote_no": quote_no,
                "study_agreement_date": ag_date,
                "test_item_code": ti_code,
                "istanbul_arrival_date": ist_date,
                "lab_arrival_date": lab_date,
                "received_quantity": qty_str,
                "animal_consumable_status": anim_status,
                "animal_procurement_date": anim_date,
                "planned_start": plan_st or exp_st,
                "experiment_start_date": exp_st,
                "experiment_end_date": exp_end,
                "planned_end": exp_end,
                "draft_report_date": draft_dt,
                "payment_status": pay_status,
                "final_report_date": final_dt,
                "raw_status_text": raw_status,
                "sample_note": note_col,
                "stored_status": stored_status,
                "sample_status": "Bekleniyor" if stored_status == "EXPECTED" else "Kabul edildi",
                "template_code": (infer_template_code(req_analysis) or DEFAULT_TEMPLATE_CODE) if req_analysis else None,
            }
        )

    # 4) NUMUNE İŞ AKIŞI (47 satır) -> Sira 4..50 (47 çalışma) birebir eşleştirme
    sira_pool = sorted([row for row in glp_parsed if 4 <= row["serial_no"] <= 50], key=lambda x: x["serial_no"])
    used_codes = set()
    wf_by_code: Dict[str, List[str]] = {}
    for wr in wf_rows:
        matched = None
        for cand in sira_pool:
            if cand["study_code"] in used_codes:
                continue
            if wr["firm_cat"] in (_wf_firm_cat(cand["billing_company"]), _wf_firm_cat(cand["sponsor_name"])) and _wf_test_cat(cand["requested_analysis"]) == wr["test_cat"]:
                matched = cand
                break
        if matched is None:
            for cand in sira_pool:
                if cand["study_code"] not in used_codes and wr["firm_cat"] in (_wf_firm_cat(cand["billing_company"]), _wf_firm_cat(cand["sponsor_name"])):
                    matched = cand
                    break
        if matched is not None:
            used_codes.add(matched["study_code"])
            wf_by_code[matched["study_code"]] = wr["markers"]

    # 5) Fiziksel Kimyasal non-GLP sekmesi (satır 7..11 -> 5 Non-GLP çalışması)
    nglp_parsed: List[Dict[str, Any]] = []
    if ws_nglp is not None:
        for r in range(7, ws_nglp.max_row + 1):
            raw_code = ws_nglp.cell(r, 14).value
            if not raw_code or not str(raw_code).strip():
                continue
            sira_raw = ws_nglp.cell(r, 1).value
            try:
                sira_no = int(float(str(sira_raw).strip()))
            except Exception:
                sira_no = r - 6
            study_code = re.sub(r"\s+", "", str(raw_code)).upper()
            billing = re.sub(r"\s+", " ", str(ws_nglp.cell(r, 2).value or "")).strip() or None
            sponsor = billing
            person_mail_raw = str(ws_nglp.cell(r, 3).value or "").strip()
            quote_no = re.sub(r"\s+", " ", str(ws_nglp.cell(r, 4).value or "")).strip() or None
            sales_mgr = normalize_sales_manager(ws_nglp.cell(r, 5).value)
            proj_name = re.sub(r"\s+", " ", str(ws_nglp.cell(r, 6).value or "")).strip()
            anal_name = re.sub(r"\s+", " ", str(ws_nglp.cell(r, 8).value or "")).strip()
            req_analysis = f"{proj_name} — {anal_name}".strip(" —") or "FİZİKSEL-KİMYASAL Monogram Testler"
            lab_type = str(ws_nglp.cell(r, 9).value or "Edirne Lab").strip()
            sd_name = normalize_study_director_name(ws_nglp.cell(r, 10).value) or "Burcu DİGER KULAKSIZ"
            ag_date = parse_date_any(ws_nglp.cell(r, 11).value)
            test_item = re.sub(r"\s+", " ", str(ws_nglp.cell(r, 12).value or "")).strip() or None
            qty_val = ws_nglp.cell(r, 13).value
            qty_str = str(qty_val).strip() if qty_val is not None else None
            lab_date = parse_date_any(ws_nglp.cell(r, 15).value)
            plan_st = parse_date_any(ws_nglp.cell(r, 16).value) or parse_date_any(ws_nglp.cell(r, 18).value)
            exp_st = parse_date_any(ws_nglp.cell(r, 19).value) or parse_date_any(ws_nglp.cell(r, 17).value)
            exp_end = parse_date_any(ws_nglp.cell(r, 21).value) or parse_date_any(ws_nglp.cell(r, 20).value)
            draft_dt = None
            final_dt = parse_date_any(ws_nglp.cell(r, 24).value)
            col17_str = str(ws_nglp.cell(r, 17).value or "").strip()
            col23_str = str(ws_nglp.cell(r, 23).value or "").strip()
            note_col = re.sub(r"\s+", " ", str(ws_nglp.cell(r, 25).value or "")).strip() or None
            if "plan" in norm_key(col23_str) or "baslanmadi" in norm_key(col17_str):
                stored_status = "PLANNED"
                raw_status = "Planlanan/Planning"
            else:
                stored_status = "ONGOING"
                raw_status = "Devem eden/On going"
            contacts = []
            if person_mail_raw:
                emails = re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]+", person_mail_raw)
                name_part = re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "", person_mail_raw).strip()
                contacts.append({"name": name_part or (emails[0] if emails else person_mail_raw), "email": ", ".join(emails)})
            nglp_parsed.append(
                {
                    "serial_no": sira_no,
                    "glp_type": "NON-GLP",
                    "study_code": study_code,
                    "test_laboratory": lab_type,
                    "requested_analysis": req_analysis,
                    "test_item_name": test_item,
                    "study_director_name": sd_name,
                    "billing_company": billing,
                    "sponsor_name": sponsor,
                    "contacts": contacts,
                    "sales_manager": sales_mgr,
                    "quote_no": quote_no,
                    "study_agreement_date": ag_date,
                    "test_item_code": None,
                    "istanbul_arrival_date": lab_date,
                    "lab_arrival_date": lab_date,
                    "received_quantity": qty_str,
                    "animal_consumable_status": None,
                    "animal_procurement_date": None,
                    "planned_start": plan_st or exp_st,
                    "experiment_start_date": exp_st,
                    "experiment_end_date": exp_end,
                    "planned_end": exp_end,
                    "draft_report_date": draft_dt,
                    "payment_status": None,
                    "final_report_date": final_dt,
                    "raw_status_text": raw_status,
                    "sample_note": note_col,
                    "stored_status": stored_status,
                    "sample_status": "Kabul edildi" if lab_date else "Bekleniyor",
                    "template_code": "PHYS_CHEM_MONO",
                }
            )
    for sheet, records, start in ((ws_glp, glp_parsed, 8), (ws_nglp, nglp_parsed, 7)):
        if sheet is not None:
            for rec in records:
                rec.update(sheet.extras.get(rec["study_code"], {}))
    wb.close()

    all_parsed = glp_parsed + nglp_parsed
    from app.services.excel_refresh import apply_refresh
    return apply_refresh(db, all_parsed, wf_by_code, user, auto_schedule,
                         glp_count=len(glp_parsed), non_glp_count=len(nglp_parsed))


class _ExcelTransactionSession(Session):
    """Legacy planning helpers may flush, but only the import boundary commits."""
    def commit(self):
        self.flush()


def import_study_status_workbook(db, content, user, auto_schedule=True, prune_non_excel=False):
    # A separate identity map prevents helper commits from persisting partial rows.
    # rollback_only joins the caller's transaction without owning its connection.
    worker = _ExcelTransactionSession(bind=db.connection(), join_transaction_mode="rollback_only")
    try:
        actor = worker.get(User, user.id)
        result = _import_study_status_workbook(worker, content, actor, auto_schedule, False)
        worker.flush()
        db.commit()
        db.expire_all()
        return result
    except Exception:
        db.rollback()
        db.expire_all()
        raise
    finally:
        worker.close()


def auto_schedule_excel_studies(
    db: Session,
    user: User,
    target_study_codes: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """
    FAZ 8.3 Adım 4:
    - `Planlanan/Planning` (14 GLP + 2 Non-GLP)
    - `Beklenen/Expected` (3 GLP: GLP2026-059, 057, 058 — `stored_status = 'EXPECTED'` korunur!)
    - `Devem eden/On going` olup bitiş tarihi / takvimi olmayan (`GLP2026-030` vb.)
    çalışmalar için takvim motorunu (`plan_sample`) çalıştırır.
    Excel'de `Planlanan Çalışma Başlangıç Tarihi` doluysa o tarihi, boşsa çakışmasız kademeli (staggered) Gün 0 tarihini atar.
    """
    samples = (
        db.query(SampleRecord)
        .order_by(SampleRecord.serial_no.asc().nullslast(), SampleRecord.study_code.asc())
        .all()
    )
    normalized_targets = {str(c).strip().upper() for c in target_study_codes if c} if target_study_codes is not None else None
    cursor_by_tpl: Dict[str, date] = {}
    base_cursor = next_business_day(max(date.today() + timedelta(days=2), date(2026, 11, 9)))
    results: List[Dict[str, Any]] = []

    for s in samples:
        if normalized_targets is not None and str(s.study_code or "").strip().upper() not in normalized_targets:
            continue
        st = (s.stored_status or "").upper()
        needs_schedule = False
        if st in ("PLANNED", "EXPECTED"):
            needs_schedule = True
        elif st == "ONGOING" and (s.planned_end is None or not _study_has_steps(db, find_study(db, s.study_code))):
            needs_schedule = True
        if not needs_schedule:
            continue

        tpl_code = resolve_template_code(s.template_code) or infer_template_code(s.requested_analysis) or DEFAULT_TEMPLATE_CODE
        if s.planned_start is not None:
            g0 = s.planned_start
        else:
            prev = cursor_by_tpl.get(tpl_code, base_cursor)
            if st == "EXPECTED":
                prev = max(prev, next_business_day(base_cursor + timedelta(days=10)))
            g0 = next_business_day(prev)
            cursor_by_tpl[tpl_code] = next_business_day(g0 + timedelta(days=2))

        try:
            plan = plan_sample(
                db,
                s,
                user,
                start_date=g0,
                preserve_status=True,
                allow_non_draft=(st == "ONGOING"),
            )
            results.append({"study_code": s.study_code, "ok": True, **plan})
        except Exception as exc:
            db.rollback()
            results.append({"study_code": s.study_code, "ok": False, "error": str(exc)})

    return {
        "scheduled": sum(1 for r in results if r["ok"]),
        "failed": sum(1 for r in results if not r["ok"]),
        "results": results,
    }


# ---------------------------------------------------------------------------
# FAZ 9.3 — SÖZLEŞME / TAAHHÜT TARİHLERİ, KARANTİNA (+7G), SAYAÇ & EXCEL (.XLSX) DIŞA AKTARIM
# ---------------------------------------------------------------------------
def sync_faz_9_3_sample_fields(db: Session) -> Dict[str, Any]:
    """
    FAZ 9.3 veri senkronizasyonu (hiçbir çalışma veya adım silinmez):
    1) SPONSOR SÖZLŞ.-SPONSOR AGREEM. sekmesindeki 10 firmanın sözleşme tarihi, iletişim bilgisi ve
       taahhüt (`Planlanan Gönderim Tarihi`) tarihlerini eşleştirir.
    2) Non-GLP çalışmalarda ayrı Taslak Rapor sütunu olmadığı için `draft_report_date = None` yapar.
    3) `Mevcut (Karantina)` olan Planlanan/Beklenen çalışmalarda (`+7g` karantina TAT farkı)
       `draft_report_date` ve `final_report_date` tarihlerini karantina süresini içerecek şekilde günceller.
    """
    pruned_test_codes: List[str] = []
    updated_contracts = 0
    updated_quarantine_dates = 0
    for s in db.query(SampleRecord).all():
        if (s.glp_type or "GLP").upper() != "GLP" and s.draft_report_date is not None and s.draft_report_date == s.final_report_date:
            s.draft_report_date = None

        sp_info = resolve_sponsor_agreement_info(s)
        if sp_info:
            if not s.study_agreement_date and sp_info.get("agreement_date"):
                s.study_agreement_date = sp_info["agreement_date"]
            if not s.contacts and (sp_info.get("person") or sp_info.get("email")):
                s.contacts = [{"name": sp_info.get("person") or "", "email": sp_info.get("email") or ""}]
            wf = copy.deepcopy(s.workflow or {})
            wf["_contract"] = {
                "agreement_date": (s.study_agreement_date or sp_info.get("agreement_date")).isoformat()
                if (s.study_agreement_date or sp_info.get("agreement_date"))
                else None,
                "commitment_date": sp_info["commitment_date"].isoformat() if sp_info.get("commitment_date") else None,
                "commitment_note": sp_info.get("commitment_note"),
            }
            s.workflow = wf
            updated_contracts += 1

        anim_meta = classify_animal_consumable_status(s.animal_consumable_status)
        end_ref = s.experiment_end_date or s.planned_end
        st_code = (s.stored_status or "").upper()
        if anim_meta["requires_quarantine"] and st_code in ("PLANNED", "EXPECTED") and end_ref:
            min_draft = end_ref + timedelta(days=10)
            min_final = end_ref + timedelta(days=14)
            if not s.draft_report_date or s.draft_report_date < min_draft:
                s.draft_report_date = min_draft
                updated_quarantine_dates += 1
            if not s.final_report_date or s.final_report_date < min_final:
                s.final_report_date = min_final
        elif s.draft_report_date and s.final_report_date and s.final_report_date < s.draft_report_date:
            s.final_report_date = s.draft_report_date + timedelta(days=4)

    db.commit()
    codes = compute_next_study_codes(db)
    return {
        "pruned_test_codes": pruned_test_codes,
        "updated_contracts": updated_contracts,
        "updated_quarantine_dates": updated_quarantine_dates,
        **codes,
    }


def export_samples_workbook_bytes(db: Session, perms: Dict[str, Any]) -> bytes:
    """
    Tüm çalışmaları (93 çalışma: 88 GLP + 5 Non-GLP) kurumsal başlıklar, renk kodlu durum hücreleri
    ve 11 Adımlı Numune İş Akışı özetiyle birlikte Excel (.xlsx) olarak dışa aktarır.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    samples = (
        db.query(SampleRecord)
        .order_by(
            SampleRecord.glp_type.asc(),
            SampleRecord.serial_no.asc().nullslast(),
            SampleRecord.study_code.asc(),
        )
        .all()
    )
    today = facility_today()
    rows = [serialize_sample(db, s, perms, today=today) for s in samples]

    wb = Workbook()
    ws = wb.active
    ws.title = "Çalışma Takip Listesi"

    headers = [
        "Sıra No",
        "GLP / Non-GLP Türü",
        "Çalışma Kodu",
        "TRM Kodu",
        "Talep Edilen Analiz",
        "Test Maddesi",
        "Sponsor",
        "Fatura Edilecek Firma",
        "Çalışma Yöneticisi (SD)",
        "Satış Yöneticisi",
        "Teklif No",
        "Sözleşme Tarihi",
        "Müşteri Taahhüt Tarihi",
        "Hayvan / Sarf Durumu",
        "Numune Geliş Tarihi",
        "Planlanan Başlangıç",
        "Deney Başlangıç",
        "Deney Bitiş",
        "Taslak Rapor Tarihi",
        "Final Rapor Tarihi",
        "Ödeme Durumu",
        "Genel Durum",
        "11 Adımlı İş Akışı Özeti",
    ]

    header_fill = PatternFill(start_color="0F172A", end_color="0F172A", fill_type="solid")
    header_font = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
    thin_border = Border(
        left=Side(style="thin", color="CBD5E1"),
        right=Side(style="thin", color="CBD5E1"),
        top=Side(style="thin", color="CBD5E1"),
        bottom=Side(style="thin", color="CBD5E1"),
    )

    status_fills = {
        "COMPLETED": PatternFill(start_color="DCFCE7", end_color="DCFCE7", fill_type="solid"),
        "ONGOING": PatternFill(start_color="FEF3C7", end_color="FEF3C7", fill_type="solid"),
        "PLANNED": PatternFill(start_color="DBEAFE", end_color="DBEAFE", fill_type="solid"),
        "EXPECTED": PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid"),
    }
    warn_fill = PatternFill(start_color="FEE2E2", end_color="FEE2E2", fill_type="solid")

    def _fmt_dt(iso_str: Optional[str]) -> str:
        if not iso_str:
            return "-"
        try:
            d = date.fromisoformat(str(iso_str)[:10])
            return d.strftime("%d.%m.%Y")
        except Exception:
            return str(iso_str)

    ws.append(headers)
    for col_idx in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = thin_border
    ws.row_dimensions[1].height = 28

    for r_idx, r in enumerate(rows, start=2):
        stepper = r.get("stepper") or []
        done_cnt = sum(1 for st in stepper if st.get("done"))
        wf_parts = [f"A{st['index']}:{'+' if st.get('done') else (st.get('marker') or '-')}" for st in stepper]
        wf_summary = f"{done_cnt}/11 Tamamlandı ({' '.join(wf_parts)})"

        status_lbl = r.get("status_label") or r.get("status") or "-"
        if r.get("status") == "ONGOING" and r.get("ongoing_phase_label"):
            status_lbl = f"{status_lbl} ({r['ongoing_phase_label']})"

        commit_txt = _fmt_dt(r.get("contract_commitment_date"))
        if r.get("is_contract_deadline_exceeded"):
            commit_txt = f"{commit_txt} (Sözleşme Termini Aşılıyor!)"

        anim_txt = r.get("animal_consumable_status") or "-"
        if r.get("requires_quarantine"):
            anim_txt = f"{anim_txt} (+7g Karantina TAT)"

        row_vals = [
            r.get("serial_no") or (r_idx - 1),
            r.get("glp_type") or "GLP",
            r.get("study_code") or "-",
            r.get("test_item_code") or "Beklemede",
            r.get("requested_analysis") or "-",
            r.get("test_item_name") or "-",
            r.get("sponsor_name") or "-",
            r.get("billing_company") or "-",
            r.get("study_director_name") or "-",
            r.get("sales_manager") or "-",
            r.get("quote_no") or "-",
            _fmt_dt(r.get("study_agreement_date")),
            commit_txt,
            anim_txt,
            _fmt_dt(r.get("lab_arrival_date") or r.get("istanbul_arrival_date") or r.get("expected_arrival_date")),
            _fmt_dt(r.get("planned_start")),
            _fmt_dt(r.get("experiment_start_date") or r.get("planned_start")),
            _fmt_dt(r.get("experiment_end_date") or r.get("planned_end")),
            _fmt_dt(r.get("draft_report_date")),
            _fmt_dt(r.get("final_report_date")),
            r.get("payment_status") or "-",
            status_lbl,
            wf_summary,
        ]
        ws.append(row_vals)
        ws.row_dimensions[r_idx].height = 21
        st_code = r.get("status") or "EXPECTED"
        for col_idx in range(1, len(headers) + 1):
            c = ws.cell(row=r_idx, column=col_idx)
            c.font = Font(name="Calibri", size=10)
            c.border = thin_border
            c.alignment = Alignment(vertical="center", wrap_text=(col_idx in (5, 6, 7, 8, 23)))
            if col_idx == 22 and st_code in status_fills:
                c.fill = status_fills[st_code]
                c.font = Font(name="Calibri", size=10, bold=True)
            elif col_idx == 13 and r.get("is_contract_deadline_exceeded"):
                c.fill = warn_fill
                c.font = Font(name="Calibri", size=10, bold=True, color="991B1B")
            elif col_idx == 14 and r.get("animal_status_code") == "CONSUMABLES_PENDING":
                c.fill = warn_fill
                c.font = Font(name="Calibri", size=10, bold=True, color="92400E")

    widths = [8, 14, 16, 15, 36, 28, 26, 26, 22, 18, 18, 15, 24, 26, 16, 16, 16, 16, 16, 16, 18, 28, 48]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "D2"

    buf = io.BytesIO()
    wb.save(buf)
    wb.close()
    return buf.getvalue()

