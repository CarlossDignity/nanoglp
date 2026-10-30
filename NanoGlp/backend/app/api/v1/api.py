from fastapi import APIRouter
from app.api.v1.endpoints import auth, documents, health, personnel, studies, equipment, users

api_router = APIRouter()

api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(health.router)
api_router.include_router(personnel.router)
api_router.include_router(studies.router)
api_router.include_router(equipment.router)
api_router.include_router(documents.router)
