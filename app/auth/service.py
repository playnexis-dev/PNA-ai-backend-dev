import base64
import asyncio
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
import hashlib
import hmac
import json
import logging
import secrets
import smtplib
import ssl
import time
from urllib.parse import urlencode
from urllib.parse import urlparse

from fastapi import HTTPException
from postgrest.exceptions import APIError
from supabase_auth.errors import AuthApiError

from app.auth.schemas import SignupRole, UserRole
from app.core.config import settings
from app.core.supabase import get_supabase_admin_client, get_supabase_client, supabase
from app.owner.schemas import OwnerRegister
from app.owner.service import create_owner
from app.player.schemas import PlayerRegister
from app.player.service import create_player

logger = logging.getLogger(__name__)

GOOGLE_ACCOUNT_NOT_REGISTERED_CODE = "account_not_registered"
GOOGLE_ACCOUNT_NOT_REGISTERED_MESSAGE = (
    "This Google account is not registered with PLAYNEXIS."
)

_GOOGLE_OAUTH_TICKETS: dict[str, dict] = {}
_GOOGLE_OAUTH_STATE_TTL_SECONDS = 600
_PHONE_OTP_STORE: dict[str, dict] = {}
_PHONE_OTP_TTL_SECONDS = 300
_VERIFICATION_RESEND_COOLDOWNS: dict[str, float] = {}
_VERIFICATION_RESEND_COOLDOWN_SECONDS = 60
_VERIFICATION_PROVIDER_RATE_LIMIT_SECONDS = 60 * 60


def _verification_record(user_id: str):
    response = (
        get_supabase_admin_client()
        .table("email_verifications")
        .select("*")
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    return response.data if response and response.data else None


def _upsert_verification_record(
    user_id: str,
    email: str,
    *,
    verified: bool | None = None,
    token_version: int | None = None,
    last_sent_at: str | None = None,
):
    client = get_supabase_admin_client()
    existing = _verification_record(user_id)
    payload = {
        "email": email.strip().lower(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if verified is not None:
        payload["verified_at"] = (
            datetime.now(timezone.utc).isoformat() if verified else None
        )
    if token_version is not None:
        payload["token_version"] = token_version
    if last_sent_at is not None:
        payload["last_sent_at"] = last_sent_at

    if existing:
        response = (
            client.table("email_verifications")
            .update(payload)
            .eq("user_id", user_id)
            .execute()
        )
    else:
        payload["user_id"] = user_id
        response = client.table("email_verifications").insert(payload).execute()

    return response.data[0] if response and response.data else {**(existing or {}), **payload}


def _email_verification_status(user, *, default_verified: bool | None = None):
    record = _verification_record(user.id)
    if record is not None:
        return bool(record.get("verified_at"))
    if default_verified is not None:
        verified = default_verified
    else:
        verified = bool(getattr(user, "email_confirmed_at", None))
    _upsert_verification_record(
        user.id,
        user.email or "",
        verified=verified,
    )
    return verified


def _create_email_verification_token(
    user_id: str,
    email: str,
    token_version: int,
):
    payload = {
        "user_id": user_id,
        "email": email.strip().lower(),
        "version": token_version,
        "created_at": time.time(),
        "nonce": secrets.token_urlsafe(12),
    }
    body = _base64_url_encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    )
    signature = _base64_url_encode(
        hmac.new(
            settings.JWT_SECRET_KEY.encode("utf-8"),
            body.encode("ascii"),
            hashlib.sha256,
        ).digest()
    )
    return f"{body}.{signature}"


def _read_email_verification_token(token: str):
    try:
        body, signature = token.split(".", 1)
        expected = _base64_url_encode(
            hmac.new(
                settings.JWT_SECRET_KEY.encode("utf-8"),
                body.encode("ascii"),
                hashlib.sha256,
            ).digest()
        )
        if not hmac.compare_digest(signature, expected):
            raise ValueError("signature")
        padded = body + "=" * (-len(body) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid verification link") from exc

    age = time.time() - float(payload.get("created_at", 0))
    if age > settings.EMAIL_VERIFICATION_TOKEN_TTL_SECONDS:
        raise HTTPException(
            status_code=400,
            detail="This verification link has expired. Request a new email.",
        )
    return payload


def _smtp_is_configured():
    return bool(settings.SMTP_HOST and settings.SMTP_FROM_EMAIL)


def _send_verification_message(email: str, verification_url: str):
    message = EmailMessage()
    message["Subject"] = "Verify your PLAYNEXIS email"
    message["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
    message["To"] = email
    message.set_content(
        "Verify your PLAYNEXIS email by opening this link:\n\n"
        f"{verification_url}\n\n"
        "If you did not create this account, you can ignore this email."
    )
    message.add_alternative(
        f"""
        <div style="font-family:Arial,sans-serif;max-width:560px;margin:auto;color:#17233b">
          <h1 style="color:#0057b8">PLAYNEXIS</h1>
          <h2>Verify your email</h2>
          <p>Confirm this email address to unlock bookings, reviews, contact details, and sensitive account actions.</p>
          <p style="margin:28px 0"><a href="{verification_url}" style="background:#0057b8;color:white;text-decoration:none;padding:12px 22px;border-radius:8px;font-weight:700">Verify email</a></p>
          <p style="color:#65758b;font-size:13px">This link expires in 24 hours. If you did not create this account, ignore this email.</p>
        </div>
        """,
        subtype="html",
    )

    context = ssl.create_default_context()
    if settings.SMTP_USE_SSL:
        with smtplib.SMTP_SSL(
            settings.SMTP_HOST,
            settings.SMTP_PORT,
            context=context,
            timeout=20,
        ) as server:
            if settings.SMTP_USERNAME:
                server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD or "")
            server.send_message(message)
        return

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20) as server:
        if settings.SMTP_USE_TLS:
            server.starttls(context=context)
        if settings.SMTP_USERNAME:
            server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD or "")
        server.send_message(message)


async def _send_application_verification_email(user_id: str, email: str):
    if not _smtp_is_configured():
        raise HTTPException(
            status_code=503,
            detail="Verification email delivery is not configured yet.",
        )

    record = _verification_record(user_id) or _upsert_verification_record(
        user_id,
        email,
        verified=False,
    )
    if record.get("verified_at"):
        return {"message": "Email is already verified", "resend_available_in_seconds": 0}

    last_sent_at = record.get("last_sent_at")
    if last_sent_at:
        sent_at = datetime.fromisoformat(str(last_sent_at).replace("Z", "+00:00"))
        wait = _VERIFICATION_RESEND_COOLDOWN_SECONDS - int(
            (datetime.now(timezone.utc) - sent_at).total_seconds()
        )
        if wait > 0:
            raise HTTPException(
                status_code=429,
                detail=f"A verification email was already sent. Try again in {wait} seconds.",
                headers={"Retry-After": str(wait)},
            )

    version = int(record.get("token_version") or 1) + 1
    token = _create_email_verification_token(user_id, email, version)
    verification_url = (
        f"{settings.FRONTEND_URL.rstrip('/')}/auth/verify-email?"
        f"{urlencode({'token': token})}"
    )
    try:
        await asyncio.to_thread(_send_verification_message, email, verification_url)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Could not send PLAYNEXIS verification email user_id=%s", user_id)
        raise HTTPException(
            status_code=502,
            detail="Verification email could not be sent. Please try again later.",
        ) from exc

    now = datetime.now(timezone.utc).isoformat()
    _upsert_verification_record(
        user_id,
        email,
        token_version=version,
        last_sent_at=now,
    )
    return {
        "message": "Verification email sent. Check your inbox and spam folder.",
        "resend_available_in_seconds": _VERIFICATION_RESEND_COOLDOWN_SECONDS,
    }


def _verification_email_key(email: str):
    return email.strip().lower()


def _start_verification_resend_cooldown(email: str):
    _VERIFICATION_RESEND_COOLDOWNS[_verification_email_key(email)] = (
        time.monotonic() + _VERIFICATION_RESEND_COOLDOWN_SECONDS
    )


def _verification_resend_wait_seconds(email: str):
    key = _verification_email_key(email)
    available_at = _VERIFICATION_RESEND_COOLDOWNS.get(key, 0)
    remaining = available_at - time.monotonic()
    if remaining <= 0:
        _VERIFICATION_RESEND_COOLDOWNS.pop(key, None)
        return 0
    return max(1, int(remaining + 0.999))


def _base64_url_encode(value: bytes):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _create_google_oauth_ticket(
    role: SignupRole | None,
    code_verifier: str,
    intent: str,
    frontend_url: str,
):
    payload = {
        "role": role,
        "intent": intent,
        "frontend_url": frontend_url,
        "code_verifier": code_verifier,
        "created_at": time.time(),
        "nonce": secrets.token_urlsafe(12),
    }
    body = _base64_url_encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    )
    signature = _base64_url_encode(
        hmac.new(
            settings.JWT_SECRET_KEY.encode("utf-8"),
            body.encode("ascii"),
            hashlib.sha256,
        ).digest()
    )

    return f"{body}.{signature}"


def _read_google_oauth_ticket(oauth_ticket: str):
    try:
        body, signature = oauth_ticket.split(".", 1)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid Google login ticket. Please try again.",
        ) from exc

    expected_signature = _base64_url_encode(
        hmac.new(
            settings.JWT_SECRET_KEY.encode("utf-8"),
            body.encode("ascii"),
            hashlib.sha256,
        ).digest()
    )

    if not hmac.compare_digest(signature, expected_signature):
        raise HTTPException(
            status_code=400,
            detail="Invalid Google login ticket. Please try again.",
        )

    padded_body = body + "=" * (-len(body) % 4)
    payload = json.loads(
        base64.urlsafe_b64decode(padded_body.encode("ascii")).decode("utf-8")
    )

    if time.time() - float(payload["created_at"]) > _GOOGLE_OAUTH_STATE_TTL_SECONDS:
        raise HTTPException(
            status_code=400,
            detail="Google login session expired. Please try again.",
        )

    intent = payload.get("intent")
    role = payload.get("role")

    if intent not in ("signup", "login"):
        raise HTTPException(
            status_code=400,
            detail="Invalid Google login intent. Please try again.",
        )

    if role is not None and role not in ("player", "owner"):
        raise HTTPException(
            status_code=400,
            detail="Invalid Google login role. Please try again.",
        )

    if intent == "signup" and role is None:
        raise HTTPException(
            status_code=400,
            detail="Account type is required for Google signup.",
        )

    if intent == "signup" and role != "player":
        raise HTTPException(
            status_code=403,
            detail="Public Owner registration is not available.",
        )

    return payload


def _normalize_frontend_url(frontend_url: str | None):
    default_url = settings.FRONTEND_URL
    if not frontend_url:
        return default_url

    parsed = urlparse(frontend_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return default_url

    normalized = f"{parsed.scheme}://{parsed.netloc}"
    return normalized


def get_frontend_url_from_oauth_ticket(oauth_ticket: str):
    payload = _read_google_oauth_ticket(oauth_ticket)
    frontend_url = payload.get("frontend_url")
    return _normalize_frontend_url(frontend_url)


def get_default_frontend_url():
    return _normalize_frontend_url(None)


def _remove_expired_oauth_states():
    now = time.time()
    expired_tickets = [
        ticket
        for ticket, payload in _GOOGLE_OAUTH_TICKETS.items()
        if now - float(payload["created_at"]) > _GOOGLE_OAUTH_STATE_TTL_SECONDS
    ]

    for ticket in expired_tickets:
        _GOOGLE_OAUTH_TICKETS.pop(ticket, None)


async def complete_oauth_profile(token: str, payload):
    user_response = supabase.auth.get_user(token)

    if not user_response.user:
        raise HTTPException(status_code=401, detail="Invalid token")

    auth_user = user_response.user

    user_id = auth_user.id
    email = auth_user.email
    stored_role = _require_role_for_user(user_id, token)
    if payload.role != stored_role:
        raise HTTPException(
            status_code=403,
            detail="Account role does not match the authenticated user",
        )

    metadata = auth_user.user_metadata or {}
    clean_phone = _sanitize_phone(payload.phone)

    full_name = (
        payload.full_name
        or metadata.get("full_name")
        or metadata.get("name")
        or email.split("@")[0]
    )

    avatar_url = metadata.get("avatar_url") or metadata.get("picture")
    admin_client = get_supabase_admin_client()

    if stored_role == "owner":
        existing = (
            admin_client.table("owners")
            .select("*")
            .eq("user_id", user_id)
            .execute()
        )

        owner_payload = {
            "user_id": user_id,
            "full_name": full_name,
            "email": email,
            "phone": clean_phone,
            "phone_verified": True,
        }
        if payload.company_name is not None:
            owner_payload["company_name"] = payload.company_name

        if existing.data:
            try:
                response = (
                    admin_client.table("owners")
                    .update(owner_payload)
                    .eq("user_id", user_id)
                    .execute()
                )
            except APIError as exc:
                raise _profile_completion_error(exc) from exc
        else:
            try:
                response = (
                    admin_client.table("owners")
                    .insert(owner_payload)
                    .execute()
                )
            except APIError as exc:
                raise _profile_completion_error(exc) from exc

        return {
            "role": "owner",
            "profile": response.data[0],
        }

    if stored_role == "player":
        existing = (
            admin_client.table("players")
            .select("*")
            .eq("user_id", user_id)
            .execute()
        )

        player_payload = {
            "user_id": user_id,
            "full_name": full_name,
            "email": email,
            "phone": clean_phone,
            "avatar_url": avatar_url,
            "phone_verified": True,
        }

        if existing.data:
            try:
                response = (
                    admin_client.table("players")
                    .update(player_payload)
                    .eq("user_id", user_id)
                    .execute()
                )
            except APIError as exc:
                raise _profile_completion_error(exc) from exc
        else:
            try:
                response = (
                    admin_client.table("players")
                    .insert(player_payload)
                    .execute()
                )
            except APIError as exc:
                raise _profile_completion_error(exc) from exc

        return {
            "role": "player",
            "profile": response.data[0],
        }

    raise HTTPException(status_code=400, detail="Invalid role")


def _profile_completion_error(exc: APIError):
    raw_detail = " ".join(
        str(part)
        for part in (
            getattr(exc, "message", None),
            getattr(exc, "details", None),
            getattr(exc, "hint", None),
            getattr(exc, "code", None),
        )
        if part
    )
    detail = raw_detail or "Failed to complete profile"
    lower_detail = detail.lower()

    if (
        "phone number is already used" in lower_detail
        or "phone_normalized" in lower_detail
        or "profile_phone_registry" in lower_detail
        or "duplicate key" in lower_detail
        or "unique constraint" in lower_detail
    ):
        detail = "Phone number is already used by another profile"
    return HTTPException(status_code=400, detail=detail)


def _auth_data_error(exc: APIError):
    detail = exc.message or "Authentication data could not be saved"
    lower_detail = detail.lower()

    if (
        "could not find the table" in lower_detail
        or "does not exist" in lower_detail
        or "schema cache" in lower_detail
        or "relation" in lower_detail
    ):
        detail = (
            "Database tables are missing in Supabase. "
            "Please run scripts/check_create_supabase_tables.py to create them."
        )

    return HTTPException(status_code=500, detail=detail)


def _get_role_for_user(
    user_id: str,
    access_token: str | None = None,
):
    client = get_supabase_client(access_token)

    logger.info("Reading user role user_id=%s", user_id)
    try:
        response = (
            client
            .table("user_roles")
            .select("role")
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
    except APIError as exc:
        raise _auth_data_error(exc) from exc

    if response and response.data:
        return response.data.get("role")

    return None


def _ensure_role_for_user(
    user_id: str,
    fallback_role: UserRole,
    access_token: str | None = None,
):
    client = get_supabase_client(access_token)
    existing_role = _get_role_for_user(user_id, access_token)

    if existing_role == fallback_role:
        logger.info(
            "Existing user role found user_id=%s role=%s",
            user_id,
            existing_role,
        )
        return existing_role

    if existing_role in ("player", "owner", "admin") and existing_role != fallback_role:
        raise HTTPException(
            status_code=409,
            detail=(
                f"This account is already registered as {existing_role}. "
                f"Please log in instead."
            ),
        )

    if existing_role is not None:
        raise HTTPException(status_code=403, detail="Account setup is incomplete")

    logger.info(
        "Creating user role user_id=%s role=%s",
        user_id,
        fallback_role,
    )
    try:
        response = (
            client
            .table("user_roles")
            .insert({
                "user_id": user_id,
                "role": fallback_role,
            })
            .execute()
        )
    except APIError as exc:
        raise _auth_data_error(exc) from exc

    if not response.data:
        raise HTTPException(
            status_code=500,
            detail="Failed to store user role",
        )

    return fallback_role


def _require_role_for_user(
    user_id: str,
    access_token: str | None = None,
):
    role = _get_role_for_user(user_id, access_token)
    if role not in ("player", "owner", "admin"):
        raise HTTPException(status_code=403, detail="Account setup is incomplete")

    return role


def _build_auth_response(
    user,
    session,
    role: UserRole,
    profile=None,
    needs_profile_completion: bool = False,
    needs_phone_verification: bool = False,
    email_verified: bool | None = None,
):
    resolved_email_verified = (
        _email_verification_status(user)
        if email_verified is None
        else email_verified
    )
    response = {
        "message": "Authentication successful",
        "user": {
            "id": user.id,
            "email": user.email,
            "role": role,
            "full_name": _get_google_full_name(user),
            "email_verified": resolved_email_verified,
        },
        "session": {
            "access_token": session.access_token if session else None,
            "refresh_token": session.refresh_token if session else None,
        },
    }

    if profile is not None:
        response["profile"] = profile

    response["needs_profile_completion"] = needs_profile_completion
    response["needs_phone_verification"] = needs_phone_verification
    response["email_verified"] = resolved_email_verified

    return response


def _get_user_metadata(user):
    metadata = getattr(user, "user_metadata", None)

    if metadata is None:
        metadata = getattr(user, "raw_user_meta_data", None)

    return metadata or {}


def _get_google_full_name(user):
    metadata = _get_user_metadata(user)

    return (
        metadata.get("full_name")
        or metadata.get("name")
        or metadata.get("display_name")
        or user.email.split("@", 1)[0]
    )


def _get_google_avatar_url(user):
    metadata = _get_user_metadata(user)

    return metadata.get("avatar_url") or metadata.get("picture")


async def _create_profile_for_role(
    user_id: str,
    email: str,
    role: UserRole,
    full_name: str,
    phone: str | None,
    company_name: str | None,
    access_token: str,
    avatar_url: str | None = None,
):
    if role == "player":
        return await create_player(
            PlayerRegister(
                user_id=user_id,
                full_name=full_name,
                email=email,
                phone=phone,
                avatar_url=avatar_url,
            ),
            access_token,
        )

    if role == "owner":
        return await create_owner(
            OwnerRegister(
                user_id=user_id,
                full_name=full_name,
                email=email,
                phone=phone,
                company_name=company_name,
            ),
            access_token,
        )

    raise HTTPException(status_code=403, detail="Admin profiles can only be created by an Admin")


async def _ensure_profile_for_role(
    user,
    role: UserRole,
    access_token: str,
):
    client = get_supabase_client(access_token)
    table = {"player": "players", "owner": "owners", "admin": "admins"}[role]
    try:
        existing_profile = (
            client
            .table(table)
            .select("*")
            .eq("user_id", user.id)
            .maybe_single()
            .execute()
        )
    except APIError as exc:
        raise _auth_data_error(exc) from exc

    if existing_profile and existing_profile.data:
        return existing_profile.data

    if role == "admin":
        return None

    try:
        return await _create_profile_for_role(
            user.id,
            user.email,
            role,
            _get_google_full_name(user),
            None,
            None,
            access_token,
            _get_google_avatar_url(user),
        )
    except APIError as exc:
        raise _auth_data_error(exc) from exc


def _get_profile_for_role(
    user_id: str,
    role: UserRole,
    access_token: str,
):
    client = get_supabase_client(access_token)
    table = {"player": "players", "owner": "owners", "admin": "admins"}[role]
    try:
        profile = (
            client
            .table(table)
            .select("*")
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
    except APIError as exc:
        raise _auth_data_error(exc) from exc

    if profile and profile.data:
        return profile.data

    return None


def _sanitize_phone(phone: str):
    trimmed = (phone or "").strip()
    if not trimmed:
        raise HTTPException(status_code=400, detail="Phone number is required")

    if len(trimmed) < 8 or len(trimmed) > 20:
        raise HTTPException(status_code=400, detail="Invalid phone number")

    allowed = set("+0123456789 -()")
    if any(ch not in allowed for ch in trimmed):
        raise HTTPException(status_code=400, detail="Invalid phone number")

    return trimmed


def _otp_hash(code: str):
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _get_current_user_from_token(token: str):
    user_response = supabase.auth.get_user(token)

    if not user_response.user:
        raise HTTPException(status_code=401, detail="Invalid token")

    return user_response.user


async def send_phone_otp(
    access_token: str,
    role: UserRole,
    phone: str,
):
    user = _get_current_user_from_token(access_token)
    clean_phone = _sanitize_phone(phone)
    code = f"{secrets.randbelow(900000) + 100000}"

    _PHONE_OTP_STORE[user.id] = {
        "phone": clean_phone,
        "role": role,
        "code_hash": _otp_hash(code),
        "expires_at": datetime.now(timezone.utc) + timedelta(seconds=_PHONE_OTP_TTL_SECONDS),
    }

    # TODO: integrate SMS gateway (Twilio/MSG91). For now, OTP is logged in backend.
    logger.warning("PHONE OTP for user_id=%s role=%s phone=%s code=%s", user.id, role, clean_phone, code)

    return {
        "message": "OTP sent successfully",
        "expires_in_seconds": _PHONE_OTP_TTL_SECONDS,
    }


async def verify_phone_otp(
    access_token: str,
    role: UserRole,
    phone: str,
    code: str,
):
    user = _get_current_user_from_token(access_token)
    clean_phone = _sanitize_phone(phone)
    otp_entry = _PHONE_OTP_STORE.get(user.id)

    if not otp_entry:
        raise HTTPException(status_code=400, detail="OTP not found. Please request a new OTP.")

    if otp_entry["role"] != role or otp_entry["phone"] != clean_phone:
        raise HTTPException(status_code=400, detail="OTP details mismatch. Please request a new OTP.")

    if datetime.now(timezone.utc) > otp_entry["expires_at"]:
        _PHONE_OTP_STORE.pop(user.id, None)
        raise HTTPException(status_code=400, detail="OTP expired. Please request a new OTP.")

    if _otp_hash(code.strip()) != otp_entry["code_hash"]:
        raise HTTPException(status_code=400, detail="Invalid OTP")

    _PHONE_OTP_STORE.pop(user.id, None)
    client = get_supabase_client(access_token)
    table = "players" if role == "player" else "owners"
    existing = (
        client
        .table(table)
        .select("*")
        .eq("user_id", user.id)
        .maybe_single()
        .execute()
    )

    payload = {
        "user_id": user.id,
        "full_name": _get_google_full_name(user),
        "email": user.email,
        "phone": clean_phone,
        "phone_verified": True,
    }

    if role == "player":
        payload["avatar_url"] = _get_google_avatar_url(user)

    try:
        if existing and existing.data:
            response = (
                client
                .table(table)
                .update(payload)
                .eq("user_id", user.id)
                .execute()
            )
        else:
            response = (
                client
                .table(table)
                .insert(payload)
                .execute()
            )
    except APIError as exc:
        if "phone_verified" not in (exc.message or ""):
            raise

        payload.pop("phone_verified", None)
        if existing and existing.data:
            response = (
                client
                .table(table)
                .update(payload)
                .eq("user_id", user.id)
                .execute()
            )
        else:
            response = (
                client
                .table(table)
                .insert(payload)
                .execute()
            )

    profile = response.data[0] if response and response.data else None
    return {"message": "Phone verified successfully", "profile": profile}


def _find_auth_user_by_email(email: str):
    normalized = email.strip().lower()
    admin = get_supabase_admin_client()
    page = 1
    while page <= 10:
        users = admin.auth.admin.list_users(page=page, per_page=1000) or []
        for user in users:
            if str(user.email or "").strip().lower() == normalized:
                return user
        if len(users) < 1000:
            break
        page += 1
    return None


def _confirm_auth_user_for_application_verification(user):
    response = get_supabase_admin_client().auth.admin.update_user_by_id(
        user.id,
        {"email_confirm": True},
    )
    return response.user or user


async def signup_user(
    email: str,
    password: str,
    role: UserRole,
    full_name: str,
    phone: str | None,
    company_name: str | None,
):
    if role != "player":
        raise HTTPException(
            status_code=403,
            detail="Public Owner registration is not available.",
        )

    clean_phone = _sanitize_phone(phone)
    admin = get_supabase_admin_client()
    try:
        created = admin.auth.admin.create_user(
            {
                "email": email,
                "password": password,
                "email_confirm": True,
                "user_metadata": {
                    "role": "player",
                    "full_name": full_name,
                    "phone": clean_phone,
                },
            }
        )
    except AuthApiError as exc:
        raise HTTPException(
            status_code=409 if "already" in str(exc).lower() else 400,
            detail=(
                "An account already exists for this email. Please log in instead."
                if "already" in str(exc).lower()
                else str(exc)
            ),
        ) from exc

    if not created.user:
        raise HTTPException(
            status_code=400,
            detail="Signup failed",
        )

    try:
        response = supabase.auth.sign_in_with_password(
            {"email": email, "password": password}
        )
    except AuthApiError as exc:
        admin.auth.admin.delete_user(created.user.id)
        raise HTTPException(status_code=500, detail="Could not start the new session") from exc

    if not response.user or not response.session:
        admin.auth.admin.delete_user(created.user.id)
        raise HTTPException(status_code=500, detail="Could not start the new session")

    access_token = response.session.access_token

    _upsert_verification_record(
        response.user.id,
        response.user.email or email,
        verified=False,
        token_version=1,
    )

    final_role = _ensure_role_for_user(
        response.user.id,
        role,
        access_token,
    )

    profile = await _create_profile_for_role(
        response.user.id,
        response.user.email or email,
        final_role,
        full_name,
        clean_phone,
        company_name,
        access_token,
    )

    auth_response = _build_auth_response(
        response.user,
        response.session,
        final_role,
        profile,
        email_verified=False,
    )
    auth_response["requires_email_verification"] = True
    auth_response["message"] = (
        "Account created. You can continue now and verify your email from the dashboard."
    )
    try:
        delivery = await _send_application_verification_email(
            response.user.id,
            response.user.email or email,
        )
        auth_response.update(delivery)
        auth_response["verification_email_sent"] = True
    except HTTPException as exc:
        logger.warning(
            "Account created without verification email user_id=%s detail=%s",
            response.user.id,
            exc.detail,
        )
        auth_response["verification_email_sent"] = False
        auth_response["resend_available_in_seconds"] = 0

    return auth_response


async def login_user(
    email: str,
    password: str,
):
    try:
        response = supabase.auth.sign_in_with_password(
            {
                "email": email,
                "password": password,
            }
        )
    except AuthApiError as exc:
        if getattr(exc, "code", None) == "email_not_confirmed":
            existing_user = _find_auth_user_by_email(email)
            if not existing_user:
                raise HTTPException(status_code=401, detail="Invalid credentials") from exc
            _confirm_auth_user_for_application_verification(existing_user)
            _upsert_verification_record(
                existing_user.id,
                existing_user.email or email,
                verified=False,
            )
            try:
                response = supabase.auth.sign_in_with_password(
                    {"email": email, "password": password}
                )
            except AuthApiError as retry_exc:
                raise HTTPException(status_code=401, detail="Invalid credentials") from retry_exc
        else:
            raise HTTPException(
                status_code=401,
                detail="Invalid credentials",
            ) from exc

    if not response.user:
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials",
        )

    if not response.session:
        raise HTTPException(
            status_code=401,
            detail="Missing active session",
        )

    final_role = _require_role_for_user(
        response.user.id,
        response.session.access_token,
    )

    profile = _get_profile_for_role(
        response.user.id,
        final_role,
        response.session.access_token,
    )
    if profile is None:
        raise HTTPException(status_code=403, detail="Account setup is incomplete")

    if final_role == "admin" and profile.get("status") != "active":
        raise HTTPException(status_code=403, detail="Admin account is not active")

    needs_profile_completion = final_role != "admin" and not (profile or {}).get("phone")

    auth_response = _build_auth_response(
        response.user,
        response.session,
        final_role,
        profile,
        needs_profile_completion=needs_profile_completion,
    )
    auth_response["message"] = "Login successful"
    auth_response["requires_email_verification"] = not auth_response["email_verified"]

    return auth_response


async def resend_signup_verification(email: str):
    user = _find_auth_user_by_email(email)
    if not user:
        return {
            "message": "If the account exists, a verification email will be sent.",
            "resend_available_in_seconds": _VERIFICATION_RESEND_COOLDOWN_SECONDS,
        }
    return await _send_application_verification_email(
        user.id,
        user.email or email,
    )


async def confirm_application_email(token: str):
    payload = _read_email_verification_token(token)
    record = _verification_record(str(payload.get("user_id") or ""))
    if not record:
        raise HTTPException(status_code=400, detail="Invalid verification link")
    if record.get("verified_at"):
        return {"message": "Email is already verified", "email_verified": True}
    if str(record.get("email") or "").lower() != str(payload.get("email") or "").lower():
        raise HTTPException(status_code=400, detail="Invalid verification link")
    if int(record.get("token_version") or 0) != int(payload.get("version") or -1):
        raise HTTPException(
            status_code=400,
            detail="This verification link is no longer valid. Request a new email.",
        )

    _upsert_verification_record(
        record["user_id"],
        record["email"],
        verified=True,
        token_version=int(record.get("token_version") or 1) + 1,
    )
    return {"message": "Email verified successfully", "email_verified": True}


async def refresh_user_session(refresh_token: str):
    try:
        response = supabase.auth.refresh_session(refresh_token)
    except AuthApiError as exc:
        raise HTTPException(
            status_code=401,
            detail="Session expired. Please log in again.",
        ) from exc

    if not response.session or not response.session.access_token:
        raise HTTPException(
            status_code=401,
            detail="Session expired. Please log in again.",
        )

    return {
        "session": {
            "access_token": response.session.access_token,
            "refresh_token": response.session.refresh_token or refresh_token,
        }
    }


async def get_google_oauth_url(
    role: SignupRole | None,
    intent: str = "login",
    prompt: str | None = None,
    frontend_url: str | None = None,
):
    _remove_expired_oauth_states()

    code_verifier = secrets.token_urlsafe(64)
    oauth_ticket = _create_google_oauth_ticket(
        role,
        code_verifier,
        intent,
        _normalize_frontend_url(frontend_url),
    )
    code_challenge = _base64_url_encode(
        hashlib.sha256(code_verifier.encode("ascii")).digest()
    )
    redirect_to = f"{settings.BACKEND_URL}/auth/google/callback/{oauth_ticket}"

    logger.info(
        "Created Google OAuth flow role=%s redirect_to=%s",
        role,
        redirect_to,
    )

    query_params = {
        "provider": "google",
        "redirect_to": redirect_to,
        "code_challenge": code_challenge,
        "code_challenge_method": "s256",
    }

    query_params["prompt"] = prompt or "select_account"

    query = urlencode(query_params)

    return {
        "url": f"{settings.SUPABASE_URL}/auth/v1/authorize?{query}",
    }


async def complete_google_session(
    access_token: str | None,
    refresh_token: str | None,
):
    user_response = supabase.auth.get_user(
        access_token,
    )

    if not user_response.user:
        raise HTTPException(
            status_code=401,
            detail="Invalid Google session",
        )

    final_role = _require_role_for_user(
        user_response.user.id,
        access_token,
    )
    _upsert_verification_record(
        user_response.user.id,
        user_response.user.email or "",
        verified=True,
    )

    return {
        "message": "Google login successful",
        "user": {
            "id": user_response.user.id,
            "email": user_response.user.email,
            "role": final_role,
            "email_verified": True,
        },
        "session": {
            "access_token": access_token,
            "refresh_token": refresh_token,
        },
    }


async def complete_google_code(
    code: str,
    oauth_ticket: str,
):
    _remove_expired_oauth_states()
    oauth_state = _read_google_oauth_ticket(oauth_ticket)
    redirect_to = f"{settings.BACKEND_URL}/auth/google/callback/{oauth_ticket}"

    logger.info(
        "Received Google code exchange request role=%s intent=%s code_length=%s",
        oauth_state.get("role"),
        oauth_state["intent"],
        len(code),
    )

    try:
        response = supabase.auth.exchange_code_for_session(
            {
                "auth_code": code,
                "code_verifier": oauth_state["code_verifier"],
                "redirect_to": redirect_to,
            }
        )
    except AuthApiError as exc:
        logger.exception(
            "Supabase rejected Google authorization code redirect_to=%s",
            redirect_to,
        )
        raise HTTPException(
            status_code=400,
            detail="Google login could not be completed. Please start again.",
        ) from exc
    except Exception:
        logger.exception(
            "Supabase failed to exchange Google authorization code redirect_to=%s",
            redirect_to,
        )
        raise

    if not response.user or not response.session:
        logger.error(
            "Supabase code exchange returned incomplete auth response has_user=%s has_session=%s",
            bool(response.user),
            bool(response.session),
        )
        raise HTTPException(
            status_code=401,
            detail="Invalid Google authorization code",
        )

    if oauth_state["intent"] == "login":
        stored_role = _get_role_for_user(
            response.user.id,
            response.session.access_token,
        )
        if stored_role is None:
            has_existing_profile = any(
                _get_profile_for_role(
                    response.user.id,
                    role,
                    response.session.access_token,
                )
                is not None
                for role in ("player", "owner", "admin")
            )
            if has_existing_profile:
                raise HTTPException(
                    status_code=403,
                    detail="Account setup is incomplete",
                )

            raise HTTPException(
                status_code=404,
                detail=GOOGLE_ACCOUNT_NOT_REGISTERED_MESSAGE,
            )

        if stored_role not in ("player", "owner", "admin"):
            raise HTTPException(status_code=403, detail="Account setup is incomplete")

        final_role = stored_role
        profile = _get_profile_for_role(
            response.user.id,
            final_role,
            response.session.access_token,
        )
        if profile is None:
            raise HTTPException(status_code=403, detail="Account setup is incomplete")
    else:
        requested_role = oauth_state["role"]
        stored_role = _get_role_for_user(
            response.user.id,
            response.session.access_token,
        )
        if stored_role in ("player", "owner", "admin"):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"This Google account is already registered as {stored_role}. "
                    "Please log in or use another Google account."
                ),
            )
        if stored_role is not None:
            raise HTTPException(status_code=403, detail="Account setup is incomplete")

        existing_profile = _get_profile_for_role(
            response.user.id,
            requested_role,
            response.session.access_token,
        )
        opposite_role = "owner" if requested_role == "player" else "player"
        opposite_profile = _get_profile_for_role(
            response.user.id,
            opposite_role,
            response.session.access_token,
        )
        if existing_profile or opposite_profile:
            raise HTTPException(
                status_code=409,
                detail=(
                    "This Google account already has a PLAYNEXIS profile. "
                    "Please log in or use another Google account."
                ),
            )

        final_role = _ensure_role_for_user(
            response.user.id,
            requested_role,
            response.session.access_token,
        )
        profile = await _ensure_profile_for_role(
            response.user,
            final_role,
            response.session.access_token,
        )

    if final_role == "admin" and (not profile or profile.get("status") != "active"):
        raise HTTPException(status_code=403, detail="Admin account is not active")

    _upsert_verification_record(
        response.user.id,
        response.user.email or "",
        verified=True,
    )

    phone_value = (profile or {}).get("phone")
    needs_profile_completion = final_role != "admin" and (
        not phone_value or not str(phone_value).strip()
    )

    auth_response = _build_auth_response(
        response.user,
        response.session,
        final_role,
        profile,
        needs_profile_completion=needs_profile_completion,
        needs_phone_verification=False,
        email_verified=True,
    )
    auth_response["message"] = "Google login successful"

    ticket = secrets.token_urlsafe(32)
    _GOOGLE_OAUTH_TICKETS[ticket] = {
        "created_at": time.time(),
        "response": auth_response,
    }

    logger.info(
        "Created Google login ticket user_id=%s role=%s",
        response.user.id,
        final_role,
    )

    return ticket


async def consume_google_ticket(ticket: str):
    _remove_expired_oauth_states()
    payload = _GOOGLE_OAUTH_TICKETS.pop(ticket, None)

    logger.info("Consuming Google login ticket ticket_found=%s", bool(payload))

    if not payload:
        raise HTTPException(
            status_code=400,
            detail="Google login ticket expired. Please try again.",
        )

    return payload["response"]
