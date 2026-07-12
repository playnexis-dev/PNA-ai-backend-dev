import sys
from pathlib import Path
from postgrest.exceptions import APIError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import settings
from app.core.supabase import get_supabase_admin_client

PLAYER_EMAIL = "player@test.com"
OWNER_EMAIL = "owner@test.com"
DEMO_PASSWORD = "Playnexis@123"

PLAYER_ID = "11111111-1111-4111-8111-111111111111"
OWNER_ID = "22222222-2222-4222-8222-222222222222"

ARENAS = [
    {
        "id": "33333333-3333-4333-8333-333333333331",
        "name": "City Football Arena",
        "sport": "Football",
        "description": "Premium 5-a-side turf with flood lights, parking, changing rooms, and refreshments.",
        "address": "Andheri West, Mumbai",
        "city": "Mumbai",
        "state": "Maharashtra",
        "country": "India",
        "latitude": 19.1136,
        "longitude": 72.8697,
        "base_price": 800,
        "price_unit": "hour",
        "status": "active",
        "is_active": True,
        "rating": 4.8,
        "review_count": 156,
        "amenities": ["Parking", "Flood Lights", "Changing Rooms", "Refreshments"],
        "images": ["/arena-football.jpg"],
        "metadata": {"distance": "0.8 km", "totalBookings": 156, "thisMonthRevenue": 18400},
    },
    {
        "id": "33333333-3333-4333-8333-333333333332",
        "name": "Pro Badminton Hub",
        "sport": "Badminton",
        "description": "Air-conditioned badminton courts with showers, WiFi, and pro-grade flooring.",
        "address": "Bandra East, Mumbai",
        "city": "Mumbai",
        "state": "Maharashtra",
        "country": "India",
        "latitude": 19.1146,
        "longitude": 72.8707,
        "base_price": 600,
        "price_unit": "hour",
        "status": "active",
        "is_active": True,
        "rating": 4.7,
        "review_count": 98,
        "amenities": ["AC", "Showers", "WiFi"],
        "images": ["/arena-badminton.jpg"],
        "metadata": {"distance": "1.2 km", "totalBookings": 98, "thisMonthRevenue": 11200},
    },
    {
        "id": "33333333-3333-4333-8333-333333333333",
        "name": "Premier Cricket Ground",
        "sport": "Cricket",
        "description": "Full cricket pitch with night lights, seating, and practice nets.",
        "address": "Powai, Mumbai",
        "city": "Mumbai",
        "state": "Maharashtra",
        "country": "India",
        "latitude": 19.1156,
        "longitude": 72.8717,
        "base_price": 1200,
        "price_unit": "hour",
        "status": "inactive",
        "is_active": False,
        "rating": 4.9,
        "review_count": 72,
        "amenities": ["Pitch", "Lights", "Seating"],
        "images": ["/arena-cricket.jpg"],
        "metadata": {"distance": "2.1 km", "totalBookings": 72, "thisMonthRevenue": 9400},
    },
    {
        "id": "33333333-3333-4333-8333-333333333334",
        "name": "Grand Tennis Club",
        "sport": "Tennis",
        "description": "Hard court tennis facility with coaching lanes and evening lighting.",
        "address": "Juhu, Mumbai",
        "city": "Mumbai",
        "state": "Maharashtra",
        "country": "India",
        "latitude": 19.1126,
        "longitude": 72.8687,
        "base_price": 900,
        "price_unit": "hour",
        "status": "active",
        "is_active": True,
        "rating": 4.6,
        "review_count": 64,
        "amenities": ["Hard Court", "AC"],
        "images": ["/arena-tennis.jpg"],
        "metadata": {"distance": "1.8 km", "totalBookings": 64, "thisMonthRevenue": 8600},
    },
]


def _upsert(client, table, payload, conflict):
    try:
        response = client.table(table).upsert(payload, on_conflict=conflict).execute()
    except APIError as exc:
        error_json = getattr(exc, "json", None)
        if callable(error_json):
            error_json = error_json()
        if not isinstance(error_json, dict):
            error_json = {}
        error_code = getattr(exc, "code", None) or error_json.get("code")
        if error_code != "42P10":
            raise

        existing = (
            client.table(table)
            .select("*")
            .eq(conflict, payload[conflict])
            .maybe_single()
            .execute()
        )
        if existing and existing.data:
            response = (
                client.table(table)
                .update(payload)
                .eq(conflict, payload[conflict])
                .execute()
            )
        else:
            response = client.table(table).insert(payload).execute()

    if not response.data:
        raise RuntimeError(f"Failed to seed {table}")
    return response.data[0]


def _list_auth_users(client):
    response = client.auth.admin.list_users()
    if hasattr(response, "users"):
        return response.users
    if isinstance(response, list):
        return response
    return getattr(response, "data", []) or []


def _find_auth_user(client, email):
    email = email.lower()
    for user in _list_auth_users(client):
        if (getattr(user, "email", "") or "").lower() == email:
            return user
        if isinstance(user, dict) and (user.get("email") or "").lower() == email:
            return user
    return None


def _user_id(user):
    if isinstance(user, dict):
        return user["id"]
    return user.id


def _ensure_auth_user(client, email, full_name, role):
    existing = _find_auth_user(client, email)
    if existing:
        user_id = _user_id(existing)
        try:
            client.auth.admin.update_user_by_id(
                user_id,
                {
                    "password": DEMO_PASSWORD,
                    "email_confirm": True,
                    "user_metadata": {"full_name": full_name, "role": role},
                },
            )
        except Exception:
            # Older Supabase projects may reject password updates for existing users.
            pass
        return user_id

    created = client.auth.admin.create_user(
        {
            "email": email,
            "password": DEMO_PASSWORD,
            "email_confirm": True,
            "user_metadata": {"full_name": full_name, "role": role},
        }
    )
    user = getattr(created, "user", None) or created
    return _user_id(user)


def seed():
    if not settings.SUPABASE_SERVICE_ROLE_KEY and not settings.SUPABASE_KEY.startswith("sb_secret_"):
        raise RuntimeError(
            "Set SUPABASE_SERVICE_ROLE_KEY in .env before seeding auth users."
        )

    client = get_supabase_admin_client()

    auth_player_id = _ensure_auth_user(client, PLAYER_EMAIL, "Aarav Player", "player")
    auth_owner_id = _ensure_auth_user(client, OWNER_EMAIL, "Nisha Owner", "owner")

    _upsert(client, "user_roles", {"user_id": auth_player_id, "role": "player"}, "user_id")
    _upsert(client, "user_roles", {"user_id": auth_owner_id, "role": "owner"}, "user_id")

    player = _upsert(
        client,
        "players",
        {
            "id": PLAYER_ID,
            "user_id": auth_player_id,
            "full_name": "Aarav Player",
            "email": PLAYER_EMAIL,
            "phone": "+91 90000 00001",
            "avatar_url": None,
            "phone_verified": True,
        },
        "user_id",
    )
    owner = _upsert(
        client,
        "owners",
        {
            "id": OWNER_ID,
            "user_id": auth_owner_id,
            "full_name": "Nisha Owner",
            "email": OWNER_EMAIL,
            "phone": "+91 90000 00002",
            "company_name": "PlayNexis Arena Partners",
            "phone_verified": True,
        },
        "user_id",
    )

    for arena in ARENAS:
        _upsert(client, "arenas", {**arena, "owner_id": owner["id"]}, "id")

    slots = [
        ("44444444-4444-4444-8444-444444444441", ARENAS[0]["id"], "2026-06-12", "19:00", "20:00", 840, 1, 1, "booked"),
        ("44444444-4444-4444-8444-444444444442", ARENAS[0]["id"], "2026-06-13", "18:00", "19:00", 800, 1, 0, "active"),
        ("44444444-4444-4444-8444-444444444443", ARENAS[1]["id"], "2026-06-14", "07:00", "08:00", 640, 1, 1, "booked"),
        ("44444444-4444-4444-8444-444444444444", ARENAS[1]["id"], "2026-06-15", "08:00", "09:00", 600, 1, 0, "active"),
        ("44444444-4444-4444-8444-444444444445", ARENAS[3]["id"], "2026-06-16", "06:00", "07:00", 940, 1, 0, "active"),
    ]
    for slot_id, arena_id, slot_date, start_time, end_time, price, capacity, booked_count, status in slots:
        _upsert(
            client,
            "arena_slots",
            {
                "id": slot_id,
                "arena_id": arena_id,
                "slot_date": slot_date,
                "start_time": start_time,
                "end_time": end_time,
                "price": price,
                "capacity": capacity,
                "booked_count": booked_count,
                "status": status,
            },
            "id",
        )

    bookings = [
        ("55555555-5555-4555-8555-555555555551", ARENAS[0]["id"], slots[0][0], "2026-06-12", "19:00", "20:00", "Football", "confirmed", "paid", 840, "PN-2024-7892"),
        ("55555555-5555-4555-8555-555555555552", ARENAS[1]["id"], slots[2][0], "2026-06-14", "07:00", "08:00", "Badminton", "confirmed", "paid", 640, "PN-2024-7901"),
        ("55555555-5555-4555-8555-555555555553", ARENAS[2]["id"], None, "2026-06-05", "09:00", "12:00", "Cricket", "completed", "paid", 3640, "PN-2024-7854"),
        ("55555555-5555-4555-8555-555555555554", ARENAS[3]["id"], None, "2026-06-04", "06:00", "07:00", "Tennis", "completed", "paid", 940, "PN-2024-7843"),
        ("55555555-5555-4555-8555-555555555555", ARENAS[0]["id"], None, "2026-06-06", "17:00", "18:00", "Football", "cancelled", "refunded", 840, "PN-2024-7867"),
    ]
    for booking_id, arena_id, slot_id, booking_date, start_time, end_time, sport, status, payment_status, amount, ref in bookings:
        _upsert(
            client,
            "bookings",
            {
                "id": booking_id,
                "player_id": player["id"],
                "owner_id": owner["id"],
                "arena_id": arena_id,
                "slot_id": slot_id,
                "booking_date": booking_date,
                "start_time": start_time,
                "end_time": end_time,
                "sport": sport,
                "status": status,
                "payment_status": payment_status,
                "total_amount": amount,
                "metadata": {"reference": ref},
            },
            "id",
        )
        if payment_status in ("paid", "refunded"):
            _upsert(
                client,
                "payments",
                {
                    "booking_id": booking_id,
                    "player_id": player["id"],
                    "amount": amount,
                    "currency": "INR",
                    "status": "refunded" if payment_status == "refunded" else "success",
                    "provider": "simulated",
                    "provider_reference": f"seed-{ref}",
                },
                "booking_id",
            )

    _upsert(
        client,
        "reviews",
        {
            "id": "66666666-6666-4666-8666-666666666661",
            "booking_id": bookings[2][0],
            "player_id": player["id"],
            "arena_id": ARENAS[2]["id"],
            "rating": 5,
            "comment": "Great pitch quality and smooth booking experience.",
        },
        "id",
    )

    notifications = [
        ("77777777-7777-4777-8777-777777777771", auth_player_id, "player", "Booking Confirmed", "City Football Arena · 12 Jun, 7:00 PM", "booking", False),
        ("77777777-7777-4777-8777-777777777772", auth_player_id, "player", "20% Off This Weekend", "Use code PLAY20 for badminton bookings", "offer", False),
        ("77777777-7777-4777-8777-777777777773", auth_owner_id, "owner", "New Booking Received", "Aarav Player booked City Football Arena", "booking", False),
        ("77777777-7777-4777-8777-777777777774", auth_owner_id, "owner", "Revenue Milestone", "Your arenas crossed Rs 29,640 in seeded demo revenue", "analytics", True),
    ]
    for notification_id, user_id, role, title, message, category, is_read in notifications:
        _upsert(
            client,
            "notifications",
            {
                "id": notification_id,
                "user_id": user_id,
                "role": role,
                "title": title,
                "message": message,
                "category": category,
                "is_read": is_read,
            },
            "id",
        )

    for index, amount in enumerate([18400, 11200, 3640, 940], start=1):
        _upsert(
            client,
            "analytics_events",
            {
                "id": f"88888888-8888-4888-8888-88888888888{index}",
                "owner_id": owner["id"],
                "arena_id": ARENAS[(index - 1) % len(ARENAS)]["id"],
                "event_type": "revenue",
                "amount": amount,
                "event_date": f"2026-06-0{index + 1}",
                "metadata": {"source": "seed_demo_data"},
            },
            "id",
        )

    print("Seed complete")
    print(f"Player: {PLAYER_EMAIL} / {DEMO_PASSWORD}")
    print(f"Owner:  {OWNER_EMAIL} / {DEMO_PASSWORD}")


if __name__ == "__main__":
    seed()
