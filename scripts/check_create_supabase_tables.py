import argparse
import asyncio
import hashlib
import sys
from pathlib import Path
from urllib.parse import urlparse

try:
    import asyncpg
except ImportError:
    print("asyncpg is not installed. Run this script with the backend virtualenv Python.")
    print(r"Example: .venv\Scripts\python.exe scripts\check_create_supabase_tables.py")
    sys.exit(1)

ROOT_DIR = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = ROOT_DIR / "supabase" / "migrations"
MIGRATION_LOCK_KEY = "playnexis_manual_schema_bootstrap"

# This script is intentionally independent from the backend app/.env.
# Pass --database-url when you need to run it locally; do not commit DB passwords.
DEFAULT_DATABASE_URL = ""

REQUIRED_TABLES = (
    "user_roles",
    "players",
    "owners",
    "admins",
    "admin_audit_logs",
    "profile_phone_registry",
    "arenas",
    "turfs",
    "arena_slots",
    "arena_maintenance_windows",
    "bookings",
    "payments",
    "reviews",
    "notifications",
    "analytics_events",
    "site_counters",
    "arena_contact_events",
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Check and create missing PlayNexis Supabase tables manually."
    )
    parser.add_argument(
        "--database-url",
        help="Optional Postgres connection string override.",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Only check required tables. Do not run migrations.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Run idempotent migrations even if all required tables already exist.",
    )
    return parser.parse_args()


def load_database_url(args) -> str:
    database_url = args.database_url or DEFAULT_DATABASE_URL
    if not database_url:
        raise RuntimeError(
            "Database URL is missing. Pass --database-url with your Supabase Transaction pooler URL.\n"
            "Recommended for local Windows: use Supabase Transaction pooler URL."
        )

    if "[YOUR-PASSWORD]" in database_url or "<YOUR_DB_PASSWORD>" in database_url:
        raise RuntimeError(
            "DATABASE_URL still contains a password placeholder. Add the real Supabase DB password."
        )

    database_url = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    database_url = database_url.replace("postgresql+psycopg2://", "postgresql://", 1)
    return database_url


def migration_files() -> list[Path]:
    if not MIGRATIONS_DIR.exists():
        raise RuntimeError(f"Migrations folder not found: {MIGRATIONS_DIR}")

    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        raise RuntimeError(f"No SQL migration files found in: {MIGRATIONS_DIR}")

    return files


def has_always_run_schema_patches(files: list[Path]) -> bool:
    return any(file.name.startswith(("202608010001", "202608040001")) for file in files)


async def connect(database_url: str):
    return await asyncpg.connect(database_url, statement_cache_size=0)


async def get_required_table_status(connection):
    rows = await connection.fetch(
        """
        select table_name
        from information_schema.tables
        where table_schema = 'public'
          and table_name = any($1::text[])
        order by table_name
        """,
        list(REQUIRED_TABLES),
    )
    existing = [row["table_name"] for row in rows]
    missing = [table for table in REQUIRED_TABLES if table not in existing]
    return existing, missing


async def apply_migrations(connection, files: list[Path]):
    _, missing_before = await get_required_table_status(connection)
    missing_set = set(missing_before)

    async with connection.transaction():
        await connection.execute(
            "select pg_advisory_xact_lock(hashtext($1::text))",
            MIGRATION_LOCK_KEY,
        )
        await connection.execute(
            """
            create table if not exists public.schema_migrations (
                filename text primary key,
                checksum text not null,
                applied_at timestamptz not null default now()
            )
            """
        )

        for file in files:
            if not should_run_migration(file, missing_set):
                print(f"Skipping migration already covered by existing tables: {file.name}")
                continue

            sql = file.read_text(encoding="utf-8")
            checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
            print(f"Running migration: {file.name}")
            await connection.execute(sql)
            await connection.execute(
                """
                insert into public.schema_migrations (filename, checksum)
                values ($1, $2)
                on conflict (filename) do update
                set checksum = excluded.checksum,
                    applied_at = now()
                """,
                file.name,
                checksum,
            )


def should_run_migration(file: Path, missing_tables: set[str]) -> bool:
    name = file.name
    if name.startswith(("202608010001", "202608040001")):
        return True

    if name.startswith("202607190001"):
        return bool({"turfs", "arena_maintenance_windows"} & missing_tables)

    if name.startswith("20260609"):
        return bool({
            "arenas",
            "arena_slots",
            "bookings",
            "payments",
            "reviews",
            "notifications",
            "analytics_events",
        } & missing_tables)

    if name.startswith("20260528") or name.startswith("20260601"):
        return bool({"user_roles", "players", "owners", "profile_phone_registry"} & missing_tables)

    return True


def print_connection_hint(database_url: str):
    parsed = urlparse(database_url)
    print("Connection target:")
    print(f"  host: {parsed.hostname}")
    print(f"  port: {parsed.port}")
    print(f"  database: {parsed.path.lstrip('/')}")
    print(f"  username: {parsed.username}")


def is_direct_supabase_db_url(database_url: str):
    parsed = urlparse(database_url)
    hostname = parsed.hostname or ""
    return hostname.startswith("db.") and hostname.endswith(".supabase.co")


def pooler_hint(database_url: str):
    parsed = urlparse(database_url)
    hostname = parsed.hostname or ""
    project_ref = ""
    if hostname.startswith("db.") and hostname.endswith(".supabase.co"):
        project_ref = hostname.removeprefix("db.").removesuffix(".supabase.co")

    if not project_ref:
        return (
            "Use Supabase Dashboard -> Project Settings -> Database -> Connection string -> "
            "Transaction pooler."
        )

    return (
        "Use Supabase Dashboard -> Project Settings -> Database -> Connection string -> "
        "Transaction pooler.\n"
        f"For this project, the pooler username should usually be postgres.{project_ref} "
        "and the port should usually be 6543."
    )


async def main():
    args = parse_args()
    database_url = load_database_url(args)
    print_connection_hint(database_url)

    try:
        connection = await connect(database_url)
    except Exception as exc:
        hint = pooler_hint(database_url) if is_direct_supabase_db_url(database_url) else (
            "Check the host, port, username, password, and network connection."
        )
        raise RuntimeError(
            "Could not connect to Supabase Postgres. "
            "If you are using db.<project>.supabase.co locally and DNS/connectivity fails, "
            "replace DEFAULT_DATABASE_URL in this script with the Supabase Transaction pooler connection string.\n"
            f"{hint}\n"
            f"Original error: {exc}"
        ) from exc

    try:
        existing, missing = await get_required_table_status(connection)
        print("\nExisting required tables:")
        print("  " + (", ".join(existing) if existing else "none"))
        print("\nMissing required tables:")
        print("  " + (", ".join(missing) if missing else "none"))

        if args.check_only:
            return 1 if missing else 0

        files = migration_files()

        if not missing and not args.force and not has_always_run_schema_patches(files):
            print("\nAll required tables already exist. No migration needed.")
            return 0

        print("\nCreating/fixing schema using idempotent migrations...")
        await apply_migrations(connection, files)

        existing_after, missing_after = await get_required_table_status(connection)
        print("\nExisting required tables after migration:")
        print("  " + (", ".join(existing_after) if existing_after else "none"))

        if missing_after:
            print("\nStill missing required tables:")
            print("  " + ", ".join(missing_after))
            return 1

        print("\nSchema is ready. All required tables exist.")
        return 0
    finally:
        await connection.close()


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
    except Exception as exc:
        print(f"\nERROR: {exc}")
        exit_code = 1

    sys.exit(exit_code)
