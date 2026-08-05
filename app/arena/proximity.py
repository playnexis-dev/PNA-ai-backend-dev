from __future__ import annotations

from math import asin, cos, radians, sin, sqrt
from typing import Any


EARTH_RADIUS_KM = 6371.0088


def normalize_city(value: str | None) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def haversine_distance_km(
    latitude: float,
    longitude: float,
    arena_latitude: float,
    arena_longitude: float,
) -> float:
    latitude_delta = radians(arena_latitude - latitude)
    longitude_delta = radians(arena_longitude - longitude)
    origin_latitude = radians(latitude)
    target_latitude = radians(arena_latitude)
    haversine = (
        sin(latitude_delta / 2) ** 2
        + cos(origin_latitude)
        * cos(target_latitude)
        * sin(longitude_delta / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * asin(sqrt(haversine))


def rank_arenas_by_location(
    arenas: list[dict[str, Any]],
    *,
    city: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    radius_km: float = 50,
) -> list[dict[str, Any]]:
    if (latitude is None) != (longitude is None):
        raise ValueError("Latitude and longitude must be provided together")

    target_city = normalize_city(city)
    has_origin = latitude is not None and longitude is not None
    ranked: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    for arena in arenas:
        item = dict(arena)
        candidates = _location_candidates(item)
        same_city_candidates = [
            candidate for candidate in candidates
            if target_city and normalize_city(candidate.get("city")) == target_city
        ]
        located_same_city_candidates = [
            candidate for candidate in same_city_candidates if candidate.get("has_coordinates")
        ]
        same_city = bool(same_city_candidates) or (
            bool(target_city) and normalize_city(item.get("city")) == target_city
        )
        located_candidates = [candidate for candidate in candidates if candidate.get("has_coordinates")]
        selected_location: dict[str, Any] | None = None
        distance_km: float | None = None

        if has_origin and located_candidates:
            if same_city_candidates:
                preferred = located_same_city_candidates
            else:
                preferred = [
                    candidate for candidate in located_candidates
                    if _inside_radius_bounding_box(
                        float(latitude),
                        float(longitude),
                        float(candidate["latitude"]),
                        float(candidate["longitude"]),
                        radius_km,
                    )
                ]
            if preferred:
                selected_location = min(
                    preferred,
                    key=lambda candidate: haversine_distance_km(
                        float(latitude),
                        float(longitude),
                        float(candidate["latitude"]),
                        float(candidate["longitude"]),
                    ),
                )
                distance_km = haversine_distance_km(
                    float(latitude),
                    float(longitude),
                    float(selected_location["latitude"]),
                    float(selected_location["longitude"]),
                )
        elif same_city_candidates:
            selected_location = next(
                (candidate for candidate in same_city_candidates if candidate.get("has_coordinates")),
                same_city_candidates[0],
            )
        elif located_candidates:
            selected_location = located_candidates[0]

        if target_city:
            if same_city:
                group = "same_city"
            elif distance_km is not None and distance_km <= radius_km:
                group = "nearby"
            else:
                continue
        elif has_origin:
            if distance_km is None or distance_km > radius_km:
                continue
            group = "nearby"
        else:
            group = "unranked"

        if selected_location and selected_location.get("has_coordinates"):
            item["latitude"] = selected_location["latitude"]
            item["longitude"] = selected_location["longitude"]
        item["nearest_turf_id"] = selected_location.get("turf_id") if selected_location else None
        item["distance_km"] = round(distance_km, 1) if distance_km is not None else None
        item["proximity_group"] = group
        item["location_incomplete"] = not located_candidates
        rating = float(item.get("rating") or 0)

        if group == "same_city" and distance_km is not None:
            sort_key = (0, distance_km, -rating, str(item.get("name") or ""))
        elif group == "same_city":
            sort_key = (1, 0, -rating, str(item.get("name") or ""))
        elif group == "nearby":
            sort_key = (2, distance_km or 0, -rating, str(item.get("name") or ""))
        else:
            sort_key = (3, 0, -rating, str(item.get("name") or ""))
        ranked.append((sort_key, item))

    ranked.sort(key=lambda entry: entry[0])
    return [item for _, item in ranked]


def _location_candidates(arena: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for turf in arena.get("turfs") or []:
        if turf.get("is_active") is False or turf.get("status") == "inactive":
            continue
        turf_latitude = _coordinate(turf.get("latitude"), -90, 90)
        turf_longitude = _coordinate(turf.get("longitude"), -180, 180)
        candidates.append({
            "turf_id": turf.get("id"),
            "city": turf.get("city") or arena.get("city"),
            "latitude": turf_latitude,
            "longitude": turf_longitude,
            "has_coordinates": turf_latitude is not None and turf_longitude is not None,
        })

    if not any(candidate["has_coordinates"] for candidate in candidates):
        arena_latitude = _coordinate(arena.get("latitude"), -90, 90)
        arena_longitude = _coordinate(arena.get("longitude"), -180, 180)
        candidates.append({
            "turf_id": None,
            "city": arena.get("city"),
            "latitude": arena_latitude,
            "longitude": arena_longitude,
            "has_coordinates": arena_latitude is not None and arena_longitude is not None,
        })
    return candidates


def _coordinate(value: Any, minimum: float, maximum: float) -> float | None:
    try:
        coordinate = float(value)
    except (TypeError, ValueError):
        return None
    return coordinate if minimum <= coordinate <= maximum else None


def _inside_radius_bounding_box(
    latitude: float,
    longitude: float,
    arena_latitude: float,
    arena_longitude: float,
    radius_km: float,
) -> bool:
    latitude_delta = radius_km / 111.32
    longitude_scale = max(abs(cos(radians(latitude))), 0.01)
    longitude_delta = radius_km / (111.32 * longitude_scale)
    return (
        latitude - latitude_delta <= arena_latitude <= latitude + latitude_delta
        and longitude - longitude_delta <= arena_longitude <= longitude + longitude_delta
    )
