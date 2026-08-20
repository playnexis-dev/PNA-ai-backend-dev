import logging

from supabase import Client, create_client

from app.core.config import settings

logger = logging.getLogger(__name__)


class _PublicSupabaseProxy:
    def __init__(self):
        self._client: Client | None = None

    def _ensure_client(self):
        if self._client is None:
            self._client = create_client(
                settings.SUPABASE_URL,
                get_supabase_public_key(),
            )
        return self._client

    def __getattr__(self, name):
        return getattr(self._ensure_client(), name)


def get_supabase_public_key(allow_legacy_fallback: bool = True) -> str:
    anon_key = settings.SUPABASE_ANON_KEY
    if anon_key:
        if anon_key.startswith("sb_anon_"):
            return anon_key
        if anon_key.startswith("sb_secret_"):
            raise RuntimeError(
                "SUPABASE_ANON_KEY is required for public email/password login. "
                "The configured Supabase key is a service role secret."
            )
        return anon_key

    legacy_key = settings.SUPABASE_KEY
    if legacy_key and allow_legacy_fallback:
        if legacy_key.startswith("sb_secret_"):
            logger.warning(
                "SUPABASE_ANON_KEY is not configured; using the server-side "
                "SUPABASE_KEY for authentication. Keep this key backend-only."
            )
        else:
            logger.warning(
                "SUPABASE_ANON_KEY is not configured; falling back to legacy "
                "SUPABASE_KEY."
            )
        return legacy_key

    raise RuntimeError(
        "Missing Supabase public key. Set SUPABASE_ANON_KEY in the environment."
    )


def get_supabase_admin_key() -> str | None:
    service_key = settings.SUPABASE_SERVICE_KEY or settings.SUPABASE_KEY
    if service_key and service_key.startswith("sb_secret_"):
        return service_key
    return None


supabase: Client = _PublicSupabaseProxy()


def get_supabase_client(access_token: str | None = None):
    client: Client = create_client(
        settings.SUPABASE_URL,
        get_supabase_public_key(),
    )

    if access_token:
        client.postgrest.auth(access_token)

    return client


def is_supabase_admin_configured() -> bool:
    return get_supabase_admin_key() is not None


def get_supabase_admin_client():
    service_key = get_supabase_admin_key()
    if not service_key:
        raise RuntimeError(
            "SUPABASE_SERVICE_KEY or a Supabase Secret Key must be configured for admin operations"
        )
    return create_client(
        settings.SUPABASE_URL,
        service_key,
    )
