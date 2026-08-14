from supabase import Client, create_client

from app.core.config import settings

supabase: Client = create_client(
    settings.SUPABASE_URL,
    settings.SUPABASE_KEY,
)


def get_supabase_client(access_token: str | None = None):
    client: Client = create_client(
        settings.SUPABASE_URL,
        settings.SUPABASE_KEY,
    )

    if access_token:
        client.postgrest.auth(access_token)

    return client


def get_supabase_admin_key() -> str | None:
    # Never promote publishable or legacy anon keys to Admin access.
    if settings.SUPABASE_KEY.startswith("sb_secret_"):
        return settings.SUPABASE_KEY

    return None


def is_supabase_admin_configured() -> bool:
    return get_supabase_admin_key() is not None


def get_supabase_admin_client():
    service_key = get_supabase_admin_key()
    if not service_key:
        raise RuntimeError("SUPABASE_KEY must contain a Supabase Secret Key for Admin operations")
    return create_client(
        settings.SUPABASE_URL,
        service_key,
    )
