import base64
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import logging
import secrets
import time
from urllib.parse import urlencode
from urllib.parse import urlparse

from fastapi import HTTPException
from postgrest.exceptions import APIError
from supabase_auth.errors import AuthApiError

from app.auth.schemas import UserRole
from app.core.config import settings
from app.core.supabase import get_supabase_admin_client, get_supabase_client, supabase
from app.owner.schemas import OwnerRegister
from app.owner.service import create_owner
from app.player.schemas import PlayerRegister
from app.player.service import create_player

logger = logging.getLogger(__name__)

_GOOGLE_OAUTH_TICKETS: dict[str, dict] = {}
_GOOGLE_OAUTH_STATE_TTL_SECONDS = 600
_PHONE_OTP_STORE: dict[str, dict] = {}
_PHONE_OTP_TTL_SECONDS = 300


def _base64_url_encode(value: bytes):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _create_google_oauth_ticket(
    role: UserRole | None,
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

    if existing_role in ("player", "owner") and existing_role != fallback_role:
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
    if role not in ("player", "owner"):
        raise HTTPException(status_code=403, detail="Account setup is incomplete")

    return role


def _build_auth_response(
    user,
    session,
    role: UserRole,
    profile=None,
    needs_profile_completion: bool = False,
    needs_phone_verification: bool = False,
):
    response = {
        "message": "Authentication successful",
        "user": {
            "id": user.id,
            "email": user.email,
            "role": role,
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


async def _ensure_profile_for_role(
    user,
    role: UserRole,
    access_token: str,
):
    client = get_supabase_client(access_token)
    table = "players" if role == "player" else "owners"
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
    table = "players" if role == "player" else "owners"
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


async def signup_user(
    email: str,
    password: str,
    role: UserRole,
    full_name: str,
    phone: str | None,
    company_name: str | None,
):
    clean_phone = _sanitize_phone(phone)

    try:
        response = supabase.auth.sign_up(
            {
                "email": email,
                "password": password,
            }
        )
    except AuthApiError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    if not response.user:
        raise HTTPException(
            status_code=400,
            detail="Signup failed",
        )

    if not response.session:
        raise HTTPException(
            status_code=400,
            detail="Signup requires an active auth session to create a profile",
        )

    final_role = _ensure_role_for_user(
        response.user.id,
        role,
        response.session.access_token,
    )

    profile = await _create_profile_for_role(
        response.user.id,
        response.user.email or email,
        final_role,
        full_name,
        clean_phone,
        company_name,
        response.session.access_token,
    )

    auth_response = _build_auth_response(
        response.user,
        response.session,
        final_role,
        profile,
    )
    auth_response["message"] = "Signup successful"

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

    needs_profile_completion = not (profile or {}).get("phone")

    auth_response = _build_auth_response(
        response.user,
        response.session,
        final_role,
        profile,
        needs_profile_completion=needs_profile_completion,
    )
    auth_response["message"] = "Login successful"

    return auth_response


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
    role: UserRole | None,
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
    access_token: str,
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

    return {
        "message": "Google login successful",
        "user": {
            "id": user_response.user.id,
            "email": user_response.user.email,
            "role": final_role,
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
    else:
        requested_role = oauth_state["role"]
        stored_role = _get_role_for_user(
            response.user.id,
            response.session.access_token,
        )
        if stored_role in ("player", "owner"):
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

    phone_value = (profile or {}).get("phone")
    needs_profile_completion = not phone_value or not str(phone_value).strip()

    auth_response = _build_auth_response(
        response.user,
        response.session,
        final_role,
        profile,
        needs_profile_completion=needs_profile_completion,
        needs_phone_verification=False,
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
