import hmac
import json
import base64
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional, Union, Any

from backend.core.config import settings

# Try PyJWT first, fallback to native hmac-sha256 token if PyJWT is not installed
try:
    import jwt
    HAS_PYJWT = True
except ImportError:
    HAS_PYJWT = False


def hash_password(password: str) -> str:
    """Simple SHA-256 / salted hash for password storage."""
    salt = "industrial_safety_salt_"
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify plain text password against stored hash."""
    return hash_password(plain_password) == hashed_password


def _b64_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('utf-8')


def _b64_decode(data_str: str) -> bytes:
    padding = '=' * (4 - (len(data_str) % 4))
    return base64.urlsafe_b64decode(data_str + padding)


def create_access_token(subject: Union[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """Generate Access Token (PyJWT or fallback HMAC-SHA256)."""
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    exp_ts = int(expire.timestamp())
    payload = {"exp": exp_ts, "sub": str(subject)}

    if HAS_PYJWT:
        return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.ALGORITHM)
    else:
        header = {"alg": "HS256", "typ": "JWT"}
        header_b64 = _b64_encode(json.dumps(header).encode("utf-8"))
        payload_b64 = _b64_encode(json.dumps(payload).encode("utf-8"))
        msg = f"{header_b64}.{payload_b64}"
        sig = hmac.new(settings.JWT_SECRET.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).digest()
        sig_b64 = _b64_encode(sig)
        return f"{msg}.{sig_b64}"


def decode_token(token: str) -> Optional[dict]:
    """Decode and validate Access Token."""
    if HAS_PYJWT:
        try:
            return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.ALGORITHM])
        except Exception:
            return None
    else:
        try:
            parts = token.split(".")
            if len(parts) != 3:
                return None
            header_b64, payload_b64, sig_b64 = parts
            msg = f"{header_b64}.{payload_b64}"
            expected_sig = _b64_encode(hmac.new(settings.JWT_SECRET.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).digest())
            if not hmac.compare_digest(sig_b64, expected_sig):
                return None
            payload = json.loads(_b64_decode(payload_b64).decode("utf-8"))
            if "exp" in payload and payload["exp"] < int(datetime.now(timezone.utc).timestamp()):
                return None
            return payload
        except Exception:
            return None
