# NANOLAB GLP AI - MASTER ARCHITECTURE & BUSINESS RULES (v1.0)

## 1. PROJE ÖZETİ VE AMACI
Bu proje, Nanolab Edirne GLP Test Tesisi için yapay zeka destekli bir operasyonel planlama, çakışma yönetimi ve kapasite optimizasyon sistemidir. Sistem, GLP (İyi Laboratuvar Uygulamaları) kurallarına katı bir şekilde uymak zorundadır. Yapay zeka hiçbir zaman biyolojik saatleri kaydıramaz, veri uyduramaz ve kendi kendine GLP kararı veremez.

## 2. TEKNOLOJİ YIĞINI (TECH STACK)
*   **Backend:** Python 3.10+, FastAPI, SQLAlchemy, Pydantic (REST API)
*   **Frontend:** React, Tailwind CSS, Vite (Yönetici ve Personel Dashboard)
*   **Veritabanı:** PostgreSQL
*   **AI Entegrasyonu:** OpenAI API (veya Local LLM) - Yalnızca PDF veri okuma ve taslak takvim önerme işlemleri için.

## 3. KLASÖR MİMARİSİ (MONOREPO)
```text
/nanolab-glp-ai
├── /backend
│   ├── /app
│   │   ├── main.py
│   │   ├── /api (Router'lar)
│   │   ├── /models (SQLAlchemy Modelleri)
│   │   ├── /schemas (Pydantic Şemaları)
│   │   ├── /services (Çakışma Motoru ve AI Servisleri)
│   │   └── /utils (PDF OCR, Saat hesaplamaları)
│   └── requirements.txt
├── /frontend
│   ├── /src
│   │   ├── /components (UI Bileşenleri)
│   │   ├── /pages (Dashboard, Planlama, Personel)
│   │   └── /services (API çağrıları)
│   ├── package.json
│   └── tailwind.config.js
├── MIMARI.md
└── docker-compose.yml (Opsiyonel, DB için)