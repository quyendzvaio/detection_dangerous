from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from backend.core.deps import get_db, get_current_user
from backend.models.db.user import User
from backend.models.schemas.auth import UserRegister, UserLogin, TokenResponse, UserOut
from backend.services.auth_service import auth_service

router = APIRouter()


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(user_in: UserRegister, db: Session = Depends(get_db)):
    """Đăng ký tài khoản người dùng mới."""
    user = auth_service.register_user(db, user_in)
    return user


@router.post("/login", response_model=TokenResponse)
def login(login_in: UserLogin, db: Session = Depends(get_db)):
    """Đăng nhập lấy JWT access token."""
    token = auth_service.authenticate_user(db, login_in)
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserOut)
def get_me(current_user: User = Depends(get_current_user)):
    """Lấy thông tin tài khoản hiện tại."""
    return current_user
