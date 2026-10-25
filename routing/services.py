import hashlib
import re
import time
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

import numpy as np
import requests
from django.conf import settings
from django.core.cache import cache

from .geo import build_profile, stations_near_route, to_xyz
from .models import FuelStation
from .planner import plan_stops

ORS = "https://api.openrouteservice.org"
LATLON = re.compile(r"^\s*(-?\d+(\.\d+)?)\s*,\s*(-?\d+(\.\d+)?)\s*$")
CITY_ST = re.compile(r"^\s*(.+?)\s*,\s*([A-Za-z]{2})\s*(?:,\s*(?:USA|US))?\s*$")

http = requests.Session()   # reuses the connection between calls


class RoutingError(Exception):
    pass


@lru_cache(maxsize=1)
def load_stations():
    rows = list(
        FuelStation.objects.filter(lat__isnull=False)
        .values("name", "address", "city", "state", "price", "lat", "lon")
    )
    xyz = to_xyz([r["lat"] for r in rows], [r["lon"] for r in rows])
    return rows, xyz


@lru_cache(maxsize=1)
def load_cities():
    """(city, state) -> (lat, lon), built from the stations we already geocoded."""
    rows, _ = load_stations()
    acc = {}
    for r in rows:
        k = (r["city"].lower(), r["state"])
        s = acc.setdefault(k, [0.0, 0.0, 0])
        s[0] += r["lat"]
        s[1] += r["lon"]
        s[2] += 1
    return {k: (v[0] / v[2], v[1] / v[2]) for k, v in acc.items()}


def local_geocode(text):
    """'City, ST' that we already know from the station data: no API call needed."""
    m = CITY_ST.match(text)
    if not m:
        return None
    city, state = m.group(1).strip().lower(), m.group(2).upper()
    hit = load_cities().get((city, state))
    if not hit:
        return None
    return {"label": f"{city.title()}, {state}, USA", "lat": hit[0], "lon": hit[1]}


def geocode(text):
    """'lat,lon' is used as-is. A known 'City, ST' is looked up locally.
    Anything else is looked up once with the routing service and cached."""
    m = LATLON.match(text)
    if m:
        return {"label": text.strip(), "lat": float(m.group(1)), "lon": float(m.group(3))}

    local = local_geocode(text)
    if local:
        return local

    key = "geo:" + hashlib.md5(text.strip().lower().encode()).hexdigest()
    hit = cache.get(key)
    if hit:
        return hit

    r = http.get(
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

    r = http.post(
        f"{ORS}/v2/directions/driving-car/geojson",
        json={
            "coordinates": [[start["lon"], start["lat"]], [finish["lon"], finish["lat"]]],
            "instructions": False,
            "radiuses": [-1, -1],   # city centres are not always on a road, so allow any snapping distance
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


def build_plan(start_text, finish_text):
    t0 = time.perf_counter()

    # load station data in this thread first, so the worker threads below only read from memory
    rows, xyz = load_stations()
    load_cities()

    with ThreadPoolExecutor(max_workers=2) as pool:
        start, finish = pool.map(geocode, [start_text, finish_text])

    route = get_route(start, finish)
    total = route["miles"]

    profile = build_profile(route["coords"], total)
    mask, along, dist = stations_near_route(profile, xyz, settings.MAX_DETOUR_MILES)

    candidates = [
        {**rows[i], "miles": float(along[i]), "detour": float(dist[i])}
        for i in np.flatnonzero(mask)
    ]
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