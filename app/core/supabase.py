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


def get_supabase_admin_client():
    service_key = settings.SUPABASE_SERVICE_ROLE_KEY or settings.SUPABASE_KEY
    return create_client(
        settings.SUPABASE_URL,
        service_key,
    )
