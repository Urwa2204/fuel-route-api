import re
import time
from functools import lru_cache
import hashlib

import numpy as np
import requests
from django.conf import settings
from django.core.cache import cache

from .geo import build_profile, stations_near_route, to_xyz
from .models import FuelStation
from .planner import plan_stops

ORS = "https://api.openrouteservice.org"
LATLON = re.compile(r"^\s*(-?\d+(\.\d+)?)\s*,\s*(-?\d+(\.\d+)?)\s*$")


class RoutingError(Exception):
    pass


def geocode(text):
    """'lat,lon' is used as-is (no API call). Anything else is looked up once and cached."""
    m = LATLON.match(text)
    if m:
        return {"label": text.strip(), "lat": float(m.group(1)), "lon": float(m.group(3))}

    key = "geo:" + hashlib.md5(text.strip().lower().encode()).hexdigest()
    hit = cache.get(key)
    if hit:
        return hit

    r = requests.get(
        f"{ORS}/geocode/search",
        params={"api_key": settings.ORS_API_KEY, "text": text,
                "boundary.country": "US", "size": 1},
        timeout=10,
    )
    if r.status_code != 200:
        raise RoutingError(f"Geocoding failed ({r.status_code})")
    feats = r.json().get("features", [])
    if not feats:
        raise RoutingError(f"Could not find a US location for '{text}'")
    lon, lat = feats[0]["geometry"]["coordinates"]
    out = {"label": feats[0]["properties"].get("label", text), "lat": lat, "lon": lon}
    cache.set(key, out, 60 * 60 * 24)
    return out


def get_route(start, finish):
    """One directions call per unique start/finish pair."""
    key = f"route:{start['lat']:.4f},{start['lon']:.4f}:{finish['lat']:.4f},{finish['lon']:.4f}"
    hit = cache.get(key)
    if hit:
        return hit

    r = requests.post(
        f"{ORS}/v2/directions/driving-car/geojson",
        json={
            "coordinates": [[start["lon"], start["lat"]], [finish["lon"], finish["lat"]]],
            "instructions": False,
        },
        headers={"Authorization": settings.ORS_API_KEY},
        timeout=30,
    )
    if r.status_code != 200:
        try:
            msg = r.json()["error"]["message"]
        except Exception:
            msg = f"status {r.status_code}"
        raise RoutingError(f"Routing failed: {msg}")

    feature = r.json()["features"][0]
    out = {
        "coords": feature["geometry"]["coordinates"],
        "miles": feature["properties"]["summary"]["distance"] / 1609.344,
    }
    cache.set(key, out, 60 * 60 * 24)
    return out


@lru_cache(maxsize=1)
def load_stations():
    rows = list(
        FuelStation.objects.filter(lat__isnull=False)
        .values("name", "address", "city", "state", "price", "lat", "lon")
    )
    xyz = to_xyz([r["lat"] for r in rows], [r["lon"] for r in rows])
    return rows, xyz


def build_plan(start_text, finish_text):
    t0 = time.perf_counter()
    start = geocode(start_text)
    finish = geocode(finish_text)
    route = get_route(start, finish)
    total = route["miles"]

    profile = build_profile(route["coords"], total)
    rows, xyz = load_stations()
    mask, along, dist = stations_near_route(profile, xyz, settings.MAX_DETOUR_MILES)

    candidates = [
        {**rows[i], "miles": float(along[i]), "detour": float(dist[i])}
        for i in np.flatnonzero(mask)
    ]
    #stops = plan_stops(candidates, total, settings.VEHICLE_RANGE_MILES, settings.VEHICLE_MPG)
    stops = plan_stops(
        candidates, total,
        settings.VEHICLE_RANGE_MILES, settings.VEHICLE_MPG,
        settings.MIN_PRICE_SAVING, settings.MIN_LEG_MILES,
    )

    r_lat, r_lon, _ = profile
    return {
        "start": start,
        "finish": finish,
        "distance_miles": round(total, 1),
        "fuel_stops": [
            {
                "stop": n,
                "name": s["name"],
                "address": s["address"],
                "city": s["city"],
                "state": s["state"],
                "lat": s["lat"],
                "lon": s["lon"],
                "miles_from_start": round(s["miles"], 1),
                "price_per_gallon": round(s["price"], 3),
                "gallons": round(s["gallons"], 2),
                "cost": round(s["cost"], 2),
            }
            for n, s in enumerate(stops, 1)
        ],
        "total_gallons": round(sum(s["gallons"] for s in stops), 2),
        "total_fuel_cost": round(sum(s["cost"] for s in stops), 2),
        "route": {
            "type": "LineString",
            "coordinates": [[round(float(x), 5), round(float(y), 5)] for y, x in zip(r_lat, r_lon)],
        },
        "elapsed_ms": round((time.perf_counter() - t0) * 1000),
    }