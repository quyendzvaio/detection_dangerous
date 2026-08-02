from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from backend.models.db.user import User
from backend.models.schemas.auth import UserRegister, UserLogin
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
        user = User(
            gmail=user_in.gmail,
            password_hash=hash_password(user_in.password),
            role="USER",
            is_active=True
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
        token = create_access_token(subject=user.id)
        return token


auth_service = AuthService()
