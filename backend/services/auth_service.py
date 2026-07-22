from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from backend.models.db.user import User
from backend.models.schemas.auth import UserRegister, UserLogin
from backend.core.security import hash_password, verify_password, create_access_token


class AuthService:
    @staticmethod
    def register_user(db: Session, user_in: UserRegister) -> User:
        existing_user = db.query(User).filter(User.username == user_in.username).first()
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already registered"
            )
        user = User(
            username=user_in.username,
            password_hash=hash_password(user_in.password),
            full_name=user_in.full_name,
            role=user_in.role or "operator",
            is_active=True
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    @staticmethod
    def authenticate_user(db: Session, login_in: UserLogin) -> str:
        user = db.query(User).filter(User.username == login_in.username).first()
        if not user or not verify_password(login_in.password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect username or password"
            )
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is inactive"
            )
        token = create_access_token(subject=user.id)
        return token


auth_service = AuthService()
