"""Create or convert the first PLAYNEXIS Admin account.

Run only from a trusted machine:
    poetry run python scripts/bootstrap_admin.py --email admin@playnexis.com --name "PLAYNEXIS Admin"
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.supabase import (  # noqa: E402
    get_supabase_admin_client,
    is_supabase_admin_configured,
)


def auth_users(client):
    result = client.auth.admin.list_users(page=1, per_page=1000)
    return result if isinstance(result, list) else list(getattr(result, "users", None) or [])


def main():
    parser = argparse.ArgumentParser(description="Bootstrap the first PLAYNEXIS Admin")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", default="PLAYNEXIS Admin")
    args = parser.parse_args()

    if not is_supabase_admin_configured():
        raise SystemExit("SUPABASE_KEY must contain a Supabase Secret Key to bootstrap an Admin.")

    client = get_supabase_admin_client()
    active_admins = client.table("admins").select("user_id").eq("status", "active").execute().data or []
    if active_admins:
        raise SystemExit("An active Admin already exists. Use the Admin Users screen for additional Admins.")

    email = args.email.strip().lower()
    user = next((item for item in auth_users(client) if str(getattr(item, "email", "")).casefold() == email.casefold()), None)
    previous_role = None
    if user:
        user_id = str(user.id)
        role_row = client.table("user_roles").select("role").eq("user_id", user_id).maybe_single().execute().data
        previous_role = (role_row or {}).get("role")
        if previous_role not in (None, "player", "owner", "admin"):
            raise SystemExit("The existing account has an unsupported role.")
    else:
        invited = client.auth.admin.invite_user_by_email(
            email,
            {"redirect_to": "http://localhost:5173/auth/admin-invite/accept", "data": {"full_name": args.name}},
        )
        user = getattr(invited, "user", None)
        if not user:
            raise SystemExit("Supabase did not return the invited user.")
        user_id = str(user.id)

    client.table("user_roles").upsert({"user_id": user_id, "role": "admin"}, on_conflict="user_id").execute()
    client.table("admins").upsert({
        "user_id": user_id,
        "email": email,
        "full_name": args.name,
        "status": "active" if previous_role else "invited",
        "previous_role": previous_role if previous_role in ("player", "owner") else None,
    }, on_conflict="user_id").execute()
    print(f"Admin bootstrap complete for {email}.")
    if not previous_role:
        print("Open the Supabase invitation email to set the password and activate the account.")


if __name__ == "__main__":
    main()
