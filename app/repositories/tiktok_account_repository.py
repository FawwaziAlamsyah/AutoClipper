"""Repository for TikTokAccountModel."""

from sqlalchemy.orm import Session

from app.models.tiktok_account_model import TikTokAccountModel


class TikTokAccountRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_first(self) -> TikTokAccountModel | None:
        """Ambil akun TikTok yang connect — app ini didesain untuk 1 akun personal,
        jadi cukup ambil yang pertama/satu-satunya, tidak perlu multi-akun.
        """
        return self.db.query(TikTokAccountModel).first()

    def get_by_open_id(self, open_id: str) -> TikTokAccountModel | None:
        return self.db.query(TikTokAccountModel).filter(TikTokAccountModel.open_id == open_id).first()

    def upsert(self, account: TikTokAccountModel) -> TikTokAccountModel:
        existing = self.get_by_open_id(account.open_id)
        if existing:
            existing.access_token_encrypted = account.access_token_encrypted
            existing.refresh_token_encrypted = account.refresh_token_encrypted
            existing.expires_at = account.expires_at
            self.db.commit()
            self.db.refresh(existing)
            return existing
        self.db.add(account)
        self.db.commit()
        self.db.refresh(account)
        return account
