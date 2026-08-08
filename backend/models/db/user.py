from datetime import datetime, timezone

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from backend.db.session import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role = 'USER'", name="ck_users_role_user"),
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    gmail = Column(String(254), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(100), nullable=True)
    role = Column(String(20), nullable=False, default="USER")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    reviewed_violations = relationship("Violation", back_populates="reviewer")
