# PlayNexis Backend

FastAPI backend for PLAYNEXIS auth, profiles, arena management, slots, bookings, notifications, reviews, and Supabase integration.

## Requirements

- Python 3.13
- Poetry 2.x, recommended
- Supabase project credentials
- Optional: Node/npm only if you want to use the local Supabase CLI package in `package.json`

## Setup With Poetry

```powershell
cd backend
poetry install --no-root
Copy-Item .env.example .env
```

Update `.env` with the real Supabase values.

Run the API:

```powershell
poetry run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

## Setup With Pip

```powershell
cd backend
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

Update `.env` with the real Supabase values.

Run the API:

```powershell
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

## Environment Variables

- `SUPABASE_URL`: Supabase project URL.
- `SUPABASE_KEY`: Supabase anon key.
- `SUPABASE_SERVICE_ROLE_KEY`: Supabase service-role key, required for admin operations like seeding users and some owner/player sync flows.
- `JWT_SECRET_KEY`: Local application secret.
- `FRONTEND_URL`: Frontend origin, usually `http://localhost:5173`.
- `BACKEND_URL`: Backend origin, usually `http://127.0.0.1:8000`.
- `ARENA_MEDIA_BUCKET`: Supabase Storage bucket for arena photos/videos. Current expected value is `Arena Media`.
- `DATABASE_URL`: Optional for normal app runtime. Use it only for direct database scripts/features.

## Create Or Repair Supabase Tables

The app does not auto-create tables on startup. Run the manual script when a new Supabase project needs the required schema:

```powershell
poetry run python scripts/check_create_supabase_tables.py --database-url "postgresql://USER:PASSWORD@HOST:PORT/postgres" --force
```

Use the Supabase Transaction pooler connection string for local Windows machines if the direct database host does not resolve.

## Seed Demo Data

After tables exist and `.env` has Supabase credentials:

```powershell
poetry run python scripts/seed_demo_data.py
```

## Validation

```powershell
poetry check
poetry run python -m compileall app scripts
```
