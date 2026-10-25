"""Citizen and admin account management, password hashing, and expiring sessions."""
import argparse
import getpass
import hashlib
import hmac
import secrets
import sqlite3
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

try:
    from backend.database import connect, init_db
except ImportError:
    from database import connect, init_db

router = APIRouter(prefix="/auth", tags=["Accounts"])
bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    """Hash password using salted scrypt with standard parameters."""
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1).hex()
    return f"{salt}:{digest}"


def verify_password(password: str, stored: str) -> bool:
    """Verify password against stored salt:digest using constant-time comparison."""
    try:
        salt, digest = stored.split(":")
        actual = hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1).hex()
        return hmac.compare_digest(actual, digest)
    except Exception:
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def normalize_email(email: str) -> str:
    email = email.strip().lower()
    if len(email) > 254 or email.count("@") != 1 or any(c.isspace() for c in email):
        raise HTTPException(400, "Enter a valid email address")
    local, domain = email.split("@")
    if not local or "." not in domain or domain.startswith(".") or domain.endswith("."):
        raise HTTPException(400, "Enter a valid email address")
    return email


class Registration(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(max_length=254)
    password: str = Field(min_length=10, max_length=128)
    # Ignore any role submitted publicly to always register citizen
    role: str | None = None


class Login(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(min_length=1, max_length=128)


def create_user(name: str, email: str, password: str, role: str = "citizen"):
    name = name.strip()
    if not name:
        raise HTTPException(400, "Name cannot be blank")
    email = normalize_email(email)
    # Public registration MUST always create a citizen account
    if role not in ("citizen", "admin"):
        role = "citizen"
    with connect() as db:
        try:
            cursor = db.execute(
                "INSERT INTO users(name, email, password_hash, role) VALUES(?,?,?,?)",
                (name, email, hash_password(password), role)
            )
        except sqlite3.IntegrityError:
            raise HTTPException(409, "Email is already registered")
    return {"id": cursor.lastrowid, "name": name, "email": email, "role": role}


@router.post("/register", status_code=201)
def register(body: Registration):
    # Public registration always creates a citizen account
    return create_user(body.name, body.email, body.password, role="citizen")


@router.post("/login")
def login(body: Login):
    with connect() as db:
        user = db.execute("SELECT * FROM users WHERE email=?", (normalize_email(body.email),)).fetchone()
        # Run constant-time password check even for unknown accounts to prevent timing attacks
        stored = user["password_hash"] if user else "0" * 32 + ":" + "0" * 128
        valid = verify_password(body.password, stored)
        if not user or not valid:
            raise HTTPException(401, "Invalid email or password")

        token = secrets.token_urlsafe(32)
        expires = int(time.time()) + 86400  # 24 hours expiry
        # Clean expired sessions
        db.execute("DELETE FROM sessions WHERE expires_at <= ?", (int(time.time()),))
        db.execute("INSERT INTO sessions VALUES(?,?,?)", (token_hash(token), user["id"], expires))

    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": 86400,
        "user": {
            "id": user["id"],
            "name": user["name"],
            "email": user["email"],
            "role": user["role"]
        }
    }


def current_user(credentials: HTTPAuthorizationCredentials = Depends(bearer)):
    if not credentials or not credentials.credentials:
        raise HTTPException(401, "Login required")
    with connect() as db:
        row = db.execute(
            """SELECT u.id, u.name, u.email, u.role FROM users u
            JOIN sessions s ON s.user_id = u.id
            WHERE s.token_hash = ? AND s.expires_at > ?""",
            (token_hash(credentials.credentials), int(time.time()))
        ).fetchone()
    if row is None:
        raise HTTPException(401, "Login required or session expired")
    return dict(row)


def admin_user(user=Depends(current_user)):
    if user["role"] != "admin":
        raise HTTPException(403, "Admin account required")
    return user


@router.get("/me")
def me(user=Depends(current_user)):
    return user


@router.post("/logout", status_code=204)
def logout(user=Depends(current_user), credentials: HTTPAuthorizationCredentials = Depends(bearer)):
    if credentials and credentials.credentials:
        with connect() as db:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash(credentials.credentials),))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create a local NAGARSAATHI administrator")
    parser.add_argument("email", help="Administrator email address")
    parser.add_argument("--name", default="Administrator", help="Administrator name")
    args = parser.parse_args()
    init_db()
    password = getpass.getpass("Admin password (10–128 characters): ")
    if not 10 <= len(password) <= 128:
        parser.error("Password must contain 10–128 characters")
    admin = create_user(args.name, args.email, password, role="admin")
    print(f"Administrator successfully created: {admin['email']} (ID: {admin['id']})")
