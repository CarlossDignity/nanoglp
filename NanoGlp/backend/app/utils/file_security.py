"""
FAZ 10 — Dosya Yükleme Güvenliği (Path Traversal, Boyut Sınırı, Uzantı Beyaz Listesi ve Magic Bytes Doğrulaması).
"""
import os
import re
from typing import Iterable, Tuple

from fastapi import HTTPException, status

ALLOWED_UPLOAD_EXTENSIONS = {"pdf", "xlsx", "xls", "csv", "png", "jpg", "jpeg", "txt"}

FORBIDDEN_EXECUTABLE_EXTENSIONS = {
    "exe", "sh", "bat", "cmd", "php", "js", "jsp", "asp", "aspx",
    "dll", "so", "msi", "ps1", "vbs", "scr", "com", "pif", "jar",
    "py", "rb", "pl", "cgi", "hta", "wsf",
}

EXECUTABLE_MAGIC_SIGNATURES = (
    (b"MZ", "Windows PE (.exe/.dll) çalıştırılabilir ikili dosya"),
    (b"\x7fELF", "Linux ELF çalıştırılabilir ikili dosya"),
    (b"#!", "Kabuk betiği (Shell Script)"),
    (b"<?php", "PHP betik dosyası"),
)


def sanitize_filename(raw_filename: str) -> str:
    """
    Dosya adındaki Path Traversal ('..', '/', '\\', null byte) karakterlerini denetler,
    os.path.basename ve güvenli karakter filtresiyle temizler.
    """
    if not raw_filename or not raw_filename.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Dosya adı eksik.")

    if "\x00" in raw_filename or ".." in raw_filename.replace("\\", "/").split("/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Güvenlik İhlali: Dosya adında geçersiz yol geçişi (Path Traversal '..') tespit edildi.",
        )

    # os.path.basename + Windows/Unix ayırıcı temizliği
    base = os.path.basename(raw_filename.replace("\\", "/")).strip()
    if not base or base in (".", "..") or ".." in base:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Güvenlik İhlali: Geçersiz dosya adı.",
        )

    # Yalnızca güvenli karakterlere izin ver
    cleaned = re.sub(r"[^A-Za-z0-9_.\-\sğüşıöçĞÜŞİÖÇ()]", "_", base).strip(" .")
    if not cleaned or "." not in cleaned:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Geçersiz dosya adı veya uzantısı eksik.",
        )
    return cleaned


def validate_and_sanitize_upload(
    raw_filename: str,
    content: bytes,
    allowed_extensions: Iterable[str] = ALLOWED_UPLOAD_EXTENSIONS,
    max_mb: int = 25,
) -> Tuple[str, str]:
    """
    Dosya adını, boyutunu (<= 25 MB), uzantısını ve dosya başlığını (magic bytes) doğrular.
    Geçerliyse (temiz_dosya_adi, uzanti) döner; aksi halde uygun HTTPException (400 / 413 / 415) fırlatır.
    """
    max_bytes = max_mb * 1024 * 1024
    if content is None or len(content) == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Dosya boş.")
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Dosya boyutu {max_mb} MB sınırını aşıyor.",
        )

    clean_name = sanitize_filename(raw_filename)
    ext = clean_name.rsplit(".", 1)[-1].lower()
    allowed_set = {e.lower().lstrip(".") for e in allowed_extensions}

    if ext in FORBIDDEN_EXECUTABLE_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Güvenlik İhlali: Çalıştırılabilir veya betik dosyası ('.{ext}') yüklenemez.",
        )

    if ext not in allowed_set:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Desteklenmeyen dosya türü '.{ext}'. İzin verilenler: {', '.join(sorted(allowed_set)).upper()}.",
        )

    # 1. Her uzantıda zararlı/çalıştırılabilir başlık (magic bytes) kontrolü
    head = content[:512]
    for sig, desc in EXECUTABLE_MAGIC_SIGNATURES:
        if head.startswith(sig):
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=f"Güvenlik İhlali: Dosya içeriği '{desc}' imzası taşıyor; sahte uzantılı dosya reddedildi.",
            )
    head_lower = head.lower()
    if b"<script" in head_lower or b"<?php" in head_lower:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Güvenlik İhlali: Dosya içeriğinde çalıştırılabilir betik (script/php) tespit edildi.",
        )

    # 2. Uzantıya özgü Magic Bytes doğrulaması
    if ext == "pdf":
        if not content[:1024].startswith(b"%PDF-") and b"%PDF-" not in content[:1024]:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Güvenlik İhlali: Geçersiz PDF dosya başlığı ('%PDF-' magic bytes bulunamadı).",
            )
    elif ext == "xlsx":
        if not content.startswith(b"PK\x03\x04"):
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Güvenlik İhlali: Geçersiz Excel (.xlsx) dosya başlığı ('PK' ZIP/OOXML imzası bulunamadı).",
            )
    elif ext == "xls":
        if not (content.startswith(b"\xd0\xcf\x11\xe0") or content.startswith(b"PK\x03\x04")):
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Güvenlik İhlali: Geçersiz Excel (.xls) dosya başlığı.",
            )
    elif ext == "png":
        if not content.startswith(b"\x89PNG\r\n\x1a\n"):
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Güvenlik İhlali: Geçersiz PNG görüntü başlığı.",
            )
    elif ext in ("jpg", "jpeg"):
        if not content.startswith(b"\xff\xd8\xff"):
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Güvenlik İhlali: Geçersiz JPEG görüntü başlığı.",
            )
    elif ext in ("txt", "csv"):
        if b"\x00" in content[:4096]:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Güvenlik İhlali: Metin/CSV dosyası ikili (binary) veri içeremez.",
            )

    return clean_name, ext
