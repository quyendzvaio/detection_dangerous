from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from backend.db.session import Base


class EvidenceObject(Base):
    __tablename__ = "evidence_objects"
    __table_args__ = (
        UniqueConstraint("violation_id", "kind", name="uq_evidence_violation_kind"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    violation_id = Column(
        Integer, ForeignKey("violations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind = Column(String(20), nullable=False)
    object_key = Column(String(1024), nullable=False, unique=True)
    status = Column(String(20), nullable=False, default="PROCESSING")
    content_type = Column(String(100), nullable=False)
    size_bytes = Column(BigInteger, nullable=True)
    etag = Column(String(255), nullable=True)
    failure_reason = Column(String(1000), nullable=True)
    upload_expires_at = Column(DateTime(timezone=True), nullable=True)
    uploaded_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    violation = relationship("Violation", back_populates="evidence_objects")
