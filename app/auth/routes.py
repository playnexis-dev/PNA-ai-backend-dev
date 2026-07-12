import logging
from urllib.parse import urlencode

from fastapi import (
    APIRouter,
    HTTPException,
    Query,
    Header,
    Request,
)
from fastapi.responses import RedirectResponse

from app.auth.schemas import (
    LoginRequest,
    SignupRequest,
    UserRole,
    OAuthCompleteRequest,
    PhoneOtpSendRequest,
    PhoneOtpVerifyRequest,
)
from app.auth.service import (
    complete_google_code,
    consume_google_ticket,
    get_default_frontend_url,
    get_frontend_url_from_oauth_ticket,
    get_google_oauth_url,
    login_user,
    signup_user,
    complete_oauth_profile,
    send_phone_otp,
    verify_phone_otp,
)
from app.core.config import settings

logger = logging.getLogger(__name__)


def _frontend_callback_url(
    params: dict[str, str],
    frontend_url: str | None = None,
):
    base_url = frontend_url or settings.FRONTEND_URL
    return f"{base_url}/auth/callback?{urlencode(params)}"

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
)

@router.post("/oauth-complete")
async def oauth_complete(
    payload: OAuthCompleteRequest,
    authorization: str = Header(None),
):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Missing authorization token",
        )

    token = authorization.replace("Bearer ", "")

    try:
        return await complete_oauth_profile(token, payload)
    except HTTPException as exc:
        logger.warning(
            "OAuth profile completion failed role=%s detail=%s",
            payload.role,
            exc.detail,
        )
        raise


@router.post("/phone-otp/send")
async def phone_otp_send(
    payload: PhoneOtpSendRequest,
    authorization: str = Header(None),
):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing authorization token")

    token = authorization.replace("Bearer ", "")
    return await send_phone_otp(token, payload.role, payload.phone)


@router.post("/phone-otp/verify")
async def phone_otp_verify(
    payload: PhoneOtpVerifyRequest,
    authorization: str = Header(None),
):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing authorization token")

    token = authorization.replace("Bearer ", "")
    return await verify_phone_otp(token, payload.role, payload.phone, payload.code)

@router.post("/signup")
async def signup(
    payload: SignupRequest,
):
    try:
        return await signup_user(
            payload.email,
            payload.password,
            payload.role,
            payload.full_name,
            payload.phone,
            payload.company_name,
        )

    except HTTPException:
        raise

    except Exception:
        logger.exception(
            "Signup failed for email=%s role=%s",
            payload.email,
            payload.role,
        )

        raise HTTPException(
            status_code=500,
            detail="Signup failed",
        )


@router.post("/login")
async def login(
    payload: LoginRequest,
):
    try:
        return await login_user(
            payload.email,
            payload.password,
            payload.role,
        )

    except HTTPException:
        raise

    except Exception:
        logger.exception(
            "Login failed for email=%s role=%s",
            payload.email,
            payload.role,
        )

        raise HTTPException(
            status_code=500,
            detail="Login failed",
        )


@router.get("/google")
async def google_auth(
    request: Request,
    role: UserRole | None = Query(default=None),
    intent: str = Query(default="login"),
    prompt: str | None = Query(default=None),
    frontend_url: str | None = Query(default=None),
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    oauth_ticket: str | None = Query(default=None),
    ticket: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
):
    origin_header = request.headers.get("origin")
    referer_header = request.headers.get("referer")
    inferred_frontend_url = None
    if origin_header:
        inferred_frontend_url = origin_header
    elif referer_header and "://" in referer_header:
        try:
            from urllib.parse import urlparse
            parsed_referer = urlparse(referer_header)
            if parsed_referer.scheme and parsed_referer.netloc:
                inferred_frontend_url = f"{parsed_referer.scheme}://{parsed_referer.netloc}"
        except Exception:
            inferred_frontend_url = None

    request_frontend_url = frontend_url or inferred_frontend_url
    resolved_frontend_url = frontend_url
    if oauth_ticket:
        try:
            resolved_frontend_url = get_frontend_url_from_oauth_ticket(oauth_ticket)
        except HTTPException:
            # Keep fallback behavior for malformed/expired tickets.
            resolved_frontend_url = request_frontend_url
    else:
        resolved_frontend_url = request_frontend_url

    logger.info(
        "Google auth request role=%s intent=%s frontend_url=%s has_code=%s has_state=%s has_oauth_ticket=%s has_ticket=%s error=%s error_description=%s",
        role,
        intent,
        resolved_frontend_url,
        bool(code),
        bool(state),
        bool(oauth_ticket),
        bool(ticket),
        error,
        error_description,
    )

    try:
        if ticket:
            logger.info("Consuming Google login ticket")
            return await consume_google_ticket(ticket)

        if error or error_description:
            logger.warning(
                "Google provider returned auth error error=%s error_description=%s",
                error,
                error_description,
            )
            return RedirectResponse(
                _frontend_callback_url({
                    "error": error_description or error or "Google login failed",
                }, resolved_frontend_url)
            )

        if code and oauth_ticket:
            logger.info("Completing Google code exchange")
            try:
                login_ticket = await complete_google_code(
                    code,
                    oauth_ticket,
                )
            except HTTPException as exc:
                logger.exception("Google code exchange failed")
                return RedirectResponse(
                    _frontend_callback_url({
                        "error": str(exc.detail),
                    }, resolved_frontend_url)
                )

            return RedirectResponse(
                _frontend_callback_url({
                    "ticket": login_ticket,
                }, resolved_frontend_url)
            )

        if code and state and not oauth_ticket:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Missing oauth_ticket in callback. "
                    "Start Google login again from this app."
                ),
            )

        if role:
            logger.info(
                "Starting Google auth role=%s intent=%s prompt=%s",
                role,
                intent,
                prompt,
            )
            response = await get_google_oauth_url(
                role,
                intent,
                prompt,
                frontend_url=request_frontend_url,
            )
            return RedirectResponse(response["url"])

        raise HTTPException(
            status_code=400,
            detail="Missing Google auth parameters",
        )

    except HTTPException:
        logger.exception("Google auth request failed with HTTPException")
        raise

    except Exception:
        logger.exception("Google auth request failed unexpectedly")

        raise HTTPException(
            status_code=500,
            detail="Google login failed",
        )


@router.get("/google/callback/{oauth_ticket}")
async def google_callback(
    oauth_ticket: str,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_code: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
):
    try:
        resolved_frontend_url = get_frontend_url_from_oauth_ticket(oauth_ticket)
    except HTTPException:
        resolved_frontend_url = get_default_frontend_url()

    logger.info(
        "Google callback request has_code=%s has_state=%s error=%s error_code=%s error_description=%s",
        bool(code),
        bool(state),
        error,
        error_code,
        error_description,
    )

    if error or error_code or error_description:
        return RedirectResponse(
            _frontend_callback_url({
                "error": error_description or error_code or error or "Google login failed",
            }, resolved_frontend_url)
        )

    if not code:
        return RedirectResponse(
            _frontend_callback_url({
                "error": "Google login failed. Please try again.",
            }, resolved_frontend_url)
        )

    try:
        login_ticket = await complete_google_code(code, oauth_ticket)
    except HTTPException as exc:
        logger.exception("Google callback code exchange failed")
        return RedirectResponse(
            _frontend_callback_url({
                "error": str(exc.detail),
            }, resolved_frontend_url)
        )
    except Exception:
        logger.exception("Google callback failed unexpectedly")
        return RedirectResponse(
            _frontend_callback_url({
                "error": "Google login could not be completed. Please try again.",
            }, resolved_frontend_url)
        )

    return RedirectResponse(
        _frontend_callback_url({
            "ticket": login_ticket,
        }, resolved_frontend_url)
    )
