"""Token blacklist ORM model for logout/revocation."""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, Index
from ..database import Base


class TokenBlacklist(Base):
    __tablename__ = "token_blacklist"

    id = Column(Integer, primary_key=True, autoincrement=True)
    jti = Column(String(64), unique=True, nullable=False)
    invalidated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    expires_at = Column(DateTime, nullable=False)

    __table_args__ = (
        Index("ix_token_blacklist_jti", "jti"),
    )
