"""Optional verified Google citizen sign-in; existing staff accounts stay password protected."""
import os
import secrets
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from backend.accounts import connect, effective_role, hash_password, normalize_email, token_hash

router = APIRouter(prefix='/auth',tags=['Google sign-in'])


def client_id():
    return os.getenv('GOOGLE_CLIENT_ID','').strip()


@router.get('/options')
def options():
    return {'google_client_id': client_id() or None}


@router.post('/google/challenge')
def challenge():
    if not client_id():
        raise HTTPException(503,'Google sign-in has not been configured')
    nonce = secrets.token_urlsafe(32)
    with connect() as db:
        now = int(time.time())
        db.execute('DELETE FROM google_challenges WHERE expires_at<=?',(now,))
        db.execute('INSERT INTO google_challenges VALUES(?,?)',(token_hash(nonce),now+300))
    return {'nonce':nonce}


def verify_google(credential, audience):
    try:
        from google.oauth2 import id_token
        from google.auth.transport.requests import Request
    except ImportError:
        raise HTTPException(503,'Install the API requirements to enable Google sign-in')
    # Google's library verifies signature, audience, expiry and issuer. Bound certificate fetch time.
    transport = Request()
    def fetch(*args,**kwargs):
        kwargs['timeout'] = 10
        return transport(*args,**kwargs)
    try:
        return id_token.verify_oauth2_token(credential,fetch,audience)
    except ValueError:
        raise HTTPException(401,'Google sign-in could not be verified')
    except Exception:
        raise HTTPException(503,'Google sign-in is temporarily unavailable')


class GoogleLogin(BaseModel):
    model_config = ConfigDict(extra='forbid')
    credential: str = Field(min_length=20,max_length=8192)


@router.post('/google')
def google_login(body: GoogleLogin):
    audience = client_id()
    if not audience:
        raise HTTPException(503,'Google sign-in has not been configured')
    claims = verify_google(body.credential,audience)
    if claims.get('aud') != audience or claims.get('iss') not in ('accounts.google.com','https://accounts.google.com') or claims.get('email_verified') is not True:
        raise HTTPException(401,'A verified Google identity for this app is required')
    subject = claims.get('sub')
    nonce = claims.get('nonce')
    if not isinstance(subject,str) or not 1 <= len(subject) <= 255 or not isinstance(nonce,str):
        raise HTTPException(401,'Google sign-in challenge is missing')
    if not isinstance(claims.get('email'),str):
        raise HTTPException(401,'Google identity does not include an email address')
    email = normalize_email(claims['email'])
    name = str(claims.get('name') or email.split('@')[0]).strip()[:100] or 'Citizen'
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        valid = db.execute('DELETE FROM google_challenges WHERE nonce_hash=? AND expires_at>? RETURNING nonce_hash',(token_hash(nonce),int(time.time()))).fetchone()
        if valid is None:
            raise HTTPException(401,'Google sign-in expired or was already used. Try again')
        user = db.execute('SELECT u.* FROM google_identities g JOIN users u ON u.id=g.user_id WHERE g.subject=?',(subject,)).fetchone()
        if user is None:
            # Never bind a Google claim to an existing staff/password account using email alone.
            if db.execute('SELECT 1 FROM users WHERE email=?',(email,)).fetchone():
                raise HTTPException(409,'This email already has an account. Use its password to sign in')
            cursor = db.execute("INSERT INTO users(name,email,password_hash,role) VALUES(?,?,?,'citizen')",(name,email,hash_password(secrets.token_urlsafe(64))))
            db.execute('INSERT INTO google_identities VALUES(?,?)',(subject,cursor.lastrowid))
            user = db.execute('SELECT * FROM users WHERE id=?',(cursor.lastrowid,)).fetchone()
        if effective_role(db,user) != 'citizen':
            raise HTTPException(403,'Staff accounts must use their password')
        token = secrets.token_urlsafe(32)
        db.execute('INSERT INTO sessions VALUES(?,?,?)',(token_hash(token),user['id'],int(time.time())+86400))
        return {'access_token':token,'token_type':'bearer','expires_in':86400,
                'user':{key:user[key] for key in ('id','name','email','role')}}
