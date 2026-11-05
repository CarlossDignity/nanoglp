"""Facility wall clock: the existing Europe/Istanbul (UTC+03:00) standard.

Read on demand, never at import/startup. UTC audit timestamps remain separate.
"""
from datetime import date, datetime, timedelta, timezone

FACILITY_TZ = timezone(timedelta(hours=3))


def facility_now() -> datetime:
    return datetime.now(FACILITY_TZ).replace(tzinfo=None)


def facility_today() -> date:
    return facility_now().date()
