"""SaaS control-plane entities.

The customer-host user/auth tables remain separate in the existing local
application. These entities are authenticated by device credentials and are
safe to use from an outbound edge connection.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from backend.db.session import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_key = Column(String(100), nullable=False, unique=True, index=True)
    name = Column(String(150), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    devices = relationship("EdgeDevice", back_populates="tenant", cascade="all, delete-orphan")
    streams = relationship("Stream", back_populates="tenant", cascade="all, delete-orphan")


class EdgeDevice(Base):
    __tablename__ = "edge_devices"
    __table_args__ = (UniqueConstraint("tenant_id", "device_key", name="uq_edge_device_tenant_key"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    device_key = Column(String(100), nullable=False)
    name = Column(String(150), nullable=False)
    status = Column(String(20), nullable=False, default="OFFLINE")
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    agent_version = Column(String(50), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    tenant = relationship("Tenant", back_populates="devices")
    credentials = relationship("DeviceCredential", back_populates="device", cascade="all, delete-orphan")


class DeviceCredential(Base):
    __tablename__ = "device_credentials"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(Integer, ForeignKey("edge_devices.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    label = Column(String(100), nullable=False, default="default")
    is_active = Column(Boolean, nullable=False, default=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)

    device = relationship("EdgeDevice", back_populates="credentials")


class Stream(Base):
    __tablename__ = "streams"
    __table_args__ = (UniqueConstraint("tenant_id", "path", name="uq_stream_tenant_path"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    device_id = Column(Integer, ForeignKey("edge_devices.id", ondelete="CASCADE"), nullable=False, index=True)
    camera_key = Column(String(100), nullable=False)
    path = Column(String(255), nullable=False)
    protocol = Column(String(20), nullable=False, default="RTSP")
    status = Column(String(20), nullable=False, default="OFFLINE")
    last_frame_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    tenant = relationship("Tenant", back_populates="streams")


class CameraProfile(Base):
    __tablename__ = "camera_profiles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(150), nullable=False)
    revision = Column(Integer, nullable=False, default=1)
    model_toggles = Column(JSON, nullable=False, default=lambda: {"zone": True, "fall": True, "ppe": False})
    operational_config = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)


class ModelAssignment(Base):
    __tablename__ = "model_assignments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    profile_id = Column(Integer, ForeignKey("camera_profiles.id", ondelete="CASCADE"), nullable=False, index=True)
    model_name = Column(String(100), nullable=False)
    model_version = Column(String(100), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class EventDelivery(Base):
    __tablename__ = "event_deliveries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    device_id = Column(Integer, ForeignKey("edge_devices.id", ondelete="CASCADE"), nullable=False, index=True)
    camera_key = Column(String(100), nullable=False)
    idempotency_key = Column(String(150), nullable=False, unique=True, index=True)
    topic = Column(String(255), nullable=False)
    payload = Column(JSON, nullable=False)
    published = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=True)

