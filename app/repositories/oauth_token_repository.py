"""Repository for OAuthTokenModel."""

from sqlalchemy.orm import Session

from app.models.oauth_token_model import OAuthTokenModel


class OAuthTokenRepository:
    """Repository untuk operasi CRUD tabel oauth_tokens."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, platform: str, account_id: str | None = None) -> OAuthTokenModel | None:
        """Ambil token berdasarkan platform dan opsional account_id.

        Bila account_id None, ambil token pertama yang terdaftar untuk platform tersebut.
        """
        query = self.db.query(OAuthTokenModel).filter(OAuthTokenModel.platform == platform)
        if account_id is not None:
            query = query.filter(OAuthTokenModel.account_id == account_id)
        return query.first()

    def upsert(self, record: OAuthTokenModel) -> OAuthTokenModel:
        """Simpan atau perbarui record token berdasarkan pasangan (platform, account_id)."""
        existing = self.get(record.platform, record.account_id)
        if existing:
            existing.access_token_encrypted = record.access_token_encrypted
            existing.refresh_token_encrypted = record.refresh_token_encrypted
            existing.issued_at = record.issued_at
            existing.expires_at = record.expires_at
            if record.expiry_estimated is not None:
                existing.expiry_estimated = record.expiry_estimated
            existing.last_refreshed_at = record.last_refreshed_at
            existing.last_validated_at = record.last_validated_at
            if record.status is not None:
                existing.status = record.status
            existing.last_error = record.last_error
            existing.seed_fingerprint = record.seed_fingerprint
            self.db.commit()
            self.db.refresh(existing)
            return existing

        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    def save(self, record: OAuthTokenModel) -> OAuthTokenModel:
        """Commit dan refresh record token."""
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    def list_all(self) -> list[OAuthTokenModel]:
        """Ambil seluruh record token diurutkan per platform dan account_id."""
        return (
            self.db.query(OAuthTokenModel)
            .order_by(OAuthTokenModel.platform, OAuthTokenModel.account_id)
            .all()
        )
