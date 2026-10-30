"""
GLP Biyolojik Saat ve Vardiya Hesaplama Yardımcıları
"""
from datetime import datetime, timedelta
from typing import Tuple


def calculate_biological_window(
    target_time: datetime,
    tolerance_minutes: int = 15
) -> Tuple[datetime, datetime]:
    """
    Belirli bir biyolojik işlem zamanı için kabul edilebilir minimum ve maksimum tolerans penceresini döner.
    """
    window_start = target_time - timedelta(minutes=tolerance_minutes)
    window_end = target_time + timedelta(minutes=tolerance_minutes)
    return window_start, window_end


def is_within_biological_window(
    actual_time: datetime,
    target_time: datetime,
    tolerance_minutes: int = 15
) -> bool:
    """İşlemin kabul edilebilir biyolojik zaman aralığında kalıp kalmadığını kontrol eder."""
    diff = abs((actual_time - target_time).total_seconds()) / 60.0
    return diff <= tolerance_minutes
