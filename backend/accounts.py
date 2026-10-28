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
    from backend.mongodb import users_collection
except ImportError:
    from database import connect, init_db
    from mongodb import users_collection


router = APIRouter(prefix="/auth", tags=["Accounts"])
bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    """Hash password using salted scrypt."""
    salt = secrets.token_hex(16)

    digest = hashlib.scrypt(
        password.encode(),
        salt=salt.encode(),
        n=16384,
        r=8,
        p=1
    ).hex()

    return f"{salt}:{digest}"


def verify_password(password: str, stored: str) -> bool:
    """Verify password against stored salt:digest."""
    try:
        salt, digest = stored.split(":")

        actual = hashlib.scrypt(
            password.encode(),
            salt=salt.encode(),
            n=16384,
            r=8,
            p=1
        ).hex()

        return hmac.compare_digest(actual, digest)

    except Exception:
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def normalize_email(email: str) -> str:
    email = email.strip().lower()

    if (
        len(email) > 254
        or email.count("@") != 1
        or any(c.isspace() for c in email)
    ):
        raise HTTPException(400, "Enter a valid email address")

    local, domain = email.split("@")

    if (
        not local
        or "." not in domain
        or domain.startswith(".")
        or domain.endswith(".")
    ):
        raise HTTPException(400, "Enter a valid email address")

    return email


class Registration(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(max_length=254)
    password: str = Field(min_length=10, max_length=128)
    role: str | None = None


class Login(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(min_length=1, max_length=128)


def create_user(
    name: str,
    email: str,
    password: str,
    role: str = "citizen"
):
    name = name.strip()

    if not name:
        raise HTTPException(400, "Name cannot be blank")

    email = normalize_email(email)

    if role not in ("citizen", "admin", "nigam"):
        role = "citizen"

    actual_role = "citizen" if role == "nigam" else role

    # Check MongoDB first
    mongo_existing = users_collection.find_one(
        {"email": email}
    )

    if mongo_existing:
        raise HTTPException(
            409,
            "Email is already registered"
        )

    # Keep SQLite user for compatibility with existing reports/issues
    with connect() as db:
        sqlite_existing = db.execute(
            "SELECT * FROM users WHERE email=?",
            (email,)
        ).fetchone()

        if sqlite_existing:
            raise HTTPException(
                409,
                "Email is already registered"
            )

        password_hash = hash_password(password)

        try:
            cursor = db.execute(
                """
                INSERT INTO users(
                    name,
                    email,
                    password_hash,
                    role
                )
                VALUES(?,?,?,?)
                """,
                (
                    name,
                    email,
                    password_hash,
                    actual_role
                )
            )

            legacy_id = cursor.lastrowid

            if role == "nigam":
                db.execute(
                    """
                    INSERT INTO municipal_accounts(user_id)
                    VALUES(?)
                    """,
                    (legacy_id,)
                )

        except sqlite3.IntegrityError:
            raise HTTPException(
                409,
                "Email is already registered"
            )

    # Create MongoDB user
    mongo_document = {
        "legacy_id": legacy_id,
        "name": name,
        "email": email,
        "password_hash": password_hash,
        "role": actual_role,
        "auth_provider": "local",
        "google_id": None,
        "is_active": True,
        "created_at": int(time.time()),
        "last_login": None
    }

    try:
        users_collection.insert_one(mongo_document)

    except Exception:
        # Roll back SQLite user if MongoDB insertion fails
        with connect() as db:
            db.execute(
                "DELETE FROM users WHERE id=?",
                (legacy_id,)
            )

        raise HTTPException(
            500,
            "Unable to create user in MongoDB"
        )

    return {
        "id": legacy_id,
        "name": name,
        "email": email,
        "role": role
    }


@router.post("/register", status_code=201)
def register(body: Registration):
    return create_user(
        body.name,
        body.email,
        body.password,
        role="citizen"
    )


@router.post("/login")
def login(body: Login):
    email = normalize_email(body.email)

    # First check MongoDB
    mongo_user = users_collection.find_one(
        {"email": email}
    )

    # If user exists only in old SQLite database,
    # migrate the user after successful password verification.
    if mongo_user is None:

        with connect() as db:
            sqlite_user = db.execute(
                "SELECT * FROM users WHERE email=?",
                (email,)
            ).fetchone()

        if sqlite_user:

            stored = sqlite_user["password_hash"]

            valid = verify_password(
                body.password,
                stored
            )

            if not valid:
                raise HTTPException(
                    401,
                    "Invalid email or password"
                )

            mongo_document = {
                "legacy_id": sqlite_user["id"],
                "name": sqlite_user["name"],
                "email": sqlite_user["email"],
                "password_hash": sqlite_user["password_hash"],
                "role": sqlite_user["role"],
                "auth_provider": "local",
                "google_id": None,
                "is_active": True,
                "created_at": int(time.time()),
                "last_login": int(time.time())
            }

            try:
                result = users_collection.insert_one(
                    mongo_document
                )

                mongo_user = users_collection.find_one(
                    {"_id": result.inserted_id}
                )

            except Exception:
                raise HTTPException(
                    500,
                    "Unable to migrate user to MongoDB"
                )

    # User does not exist anywhere
    if mongo_user is None:

        verify_password(
            body.password,
            "0" * 32 + ":" + "0" * 128
        )

        raise HTTPException(
            401,
            "Invalid email or password"
        )

    # Google-only account
    stored = mongo_user.get("password_hash")

    if not stored:
        raise HTTPException(
            401,
            "This account uses Google Sign-In"
        )

    # Verify password from MongoDB
    valid = verify_password(
        body.password,
        stored
    )

    if not valid:
        raise HTTPException(
            401,
            "Invalid email or password"
        )

    token = secrets.token_urlsafe(32)
    expires = int(time.time()) + 86400

    legacy_id = mongo_user.get("legacy_id")

    if legacy_id is None:
        raise HTTPException(
            500,
            "User account is missing legacy ID"
        )

    # Keep session in SQLite because the rest of the
    # existing application uses the SQLite user ID.
    with connect() as db:

        db.execute(
            "DELETE FROM sessions WHERE expires_at <= ?",
            (int(time.time()),)
        )

        db.execute(
            "INSERT INTO sessions VALUES(?,?,?)",
            (
                token_hash(token),
                legacy_id,
                expires
            )
        )

        role = effective_role(
            db,
            {
                "id": legacy_id,
                "role": mongo_user.get(
                    "role",
                    "citizen"
                )
            }
        )

    # Update last login in MongoDB
    users_collection.update_one(
        {"_id": mongo_user["_id"]},
        {
            "$set": {
                "last_login": int(time.time())
            }
        }
    )

    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": 86400,
        "user": {
            "id": legacy_id,
            "name": mongo_user["name"],
            "email": mongo_user["email"],
            "role": role
        }
    }


def effective_role(db, user):
    if user["role"] == "admin":
        return "admin"

    municipal = db.execute(
        """
        SELECT 1
        FROM municipal_accounts
        WHERE user_id=?
        """,
        (user["id"],)
    ).fetchone()

    return "nigam" if municipal else "citizen"


def current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer)
):
    if not credentials or not credentials.credentials:
        raise HTTPException(
            401,
            "Login required"
        )

    # Validate session using existing SQLite session system
    with connect() as db:

        row = db.execute(
            """
            SELECT
                s.user_id,
                s.expires_at
            FROM sessions s
            WHERE
                s.token_hash = ?
                AND s.expires_at > ?
            """,
            (
                token_hash(credentials.credentials),
                int(time.time())
            )
        ).fetchone()

    if row is None:
        raise HTTPException(
            401,
            "Login required or session expired"
        )

    # Get actual user data from MongoDB
    mongo_user = users_collection.find_one(
        {
            "legacy_id": row["user_id"]
        }
    )

    if mongo_user is None:
        raise HTTPException(
            401,
            "User account not found"
        )

    return {
        "id": row["user_id"],
        "name": mongo_user["name"],
        "email": mongo_user["email"],
        "role": mongo_user.get(
            "role",
            "citizen"
        )
    }


def admin_user(user=Depends(current_user)):
    if user["role"] != "admin":
        raise HTTPException(
            403,
            "Admin account required"
        )

    return user


@router.get("/me")
def me(user=Depends(current_user)):
    return user


@router.post("/logout", status_code=204)
def logout(
    user=Depends(current_user),
    credentials: HTTPAuthorizationCredentials = Depends(bearer)
):
    if credentials and credentials.credentials:

        with connect() as db:

            db.execute(
                """
                DELETE FROM sessions
                WHERE token_hash=?
                """,
                (
                    token_hash(
                        credentials.credentials
                    ),
                )
            )


if __name__ == "__main__":

    parser = argparse.ArgumentParser(
        description=(
            "Create a local NAGARSAATHA administrator"
        )
    )

    parser.add_argument(
        "email",
        help="Administrator email address"
    )

    parser.add_argument(
        "--name",
        default="Administrator",
        help="Administrator name"
    )

    parser.add_argument(
        "--role",
        choices=["admin", "nigam"],
        default="admin",
        help=(
            "Platform admin or municipal "
            "consolidated-issue account"
        )
    )

    args = parser.parse_args()

    init_db()

    password = getpass.getpass(
        "Admin password (10–128 characters): "
    )

    if not 10 <= len(password) <= 128:
        parser.error(
            "Password must contain 10–128 characters"
        )

    admin = create_user(
        args.name,
        args.email,
        password,
        role=args.role
    )

    print(
        f"{args.role} account successfully created: "
        f"{admin['email']} "
        f"(ID: {admin['id']})"
    )
