from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from backend.models.db.user import User
from backend.models.schemas.auth import UserRegister, UserLogin
from backend.models.schemas.control_plane import TenantCreate
from backend.services.control_plane_service import create_tenant
from backend.core.security import (
    create_access_token,
    hash_password,
    password_hash_needs_upgrade,
    verify_password,
)


class AuthService:
    @staticmethod
    def register_user(db: Session, user_in: UserRegister) -> User:
        existing_user = db.query(User).filter(User.gmail == user_in.gmail).first()
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Gmail already registered"
            )
        # 1 user = 1 tenant: signup creates a dedicated tenant for the user.
        # tenant_key must match ^[a-z0-9][a-z0-9_-]*$ — normalize the email
        # localpart (dots/plus/upper) into a slug; uniqueness is guaranteed by
        # the unique gmail check above.
        import re

        localpart = user_in.gmail.split("@")[0].lower()
        slug = re.sub(r"[^a-z0-9_-]", "", localpart).strip("_-")
        if not slug:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Gmail localpart cannot be used as tenant key",
            )
        tenant = create_tenant(db, TenantCreate(tenant_key=slug, name=user_in.gmail))
        user = User(
            gmail=user_in.gmail,
            password_hash=hash_password(user_in.password),
            role="USER",
            is_active=True,
            tenant_id=tenant.id,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    @staticmethod
    def authenticate_user(db: Session, login_in: UserLogin) -> str:
        user = db.query(User).filter(User.gmail == login_in.gmail).first()
        if not user or not verify_password(login_in.password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect Gmail or password"
            )
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is inactive"
            )
        if password_hash_needs_upgrade(user.password_hash):
            user.password_hash = hash_password(login_in.password)
            db.commit()
        token = create_access_token(subject=user.id, tenant_id=user.tenant_id)
        return token


auth_service = AuthService()
