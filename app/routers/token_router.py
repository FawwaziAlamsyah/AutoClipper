"""Router untuk status dan pengelolaan OAuth token multi-platform."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.token_manager.setup import build_default_manager

router = APIRouter(prefix="/tokens", tags=["tokens"])


@router.get("/status")
def get_tokens_status(db: Session = Depends(get_db)) -> dict:
    """Ambil ringkasan status semua token yang tersimpan (tanpa token/secret mentah)."""
    manager = build_default_manager()
    return {"tokens": manager.get_status(db)}
