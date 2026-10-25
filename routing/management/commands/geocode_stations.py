import time

import requests
from django.core.management.base import BaseCommand

from routing.models import FuelStation

URL = "https://nominatim.openstreetmap.org/search"
HEADERS = {"User-Agent": "fuel-route-assignment/1.0 (urwamaqsood4@gmail.com)"}


def lookup(city, state):
    r = requests.get(
        URL,
        params={"q": f"{city}, {state}, USA", "format": "json", "limit": 1},
        headers=HEADERS,
        timeout=15,
    )
    time.sleep(1.1)   # Nominatim allows 1 request per second
    if r.status_code == 429:      # asked to slow down
        time.sleep(30)
        return None
    data = r.json() if r.ok else []
    if data:
        return float(data[0]["lat"]), float(data[0]["lon"])
    return None


class Command(BaseCommand):
    help = "Geocode each distinct city/state once. Safe to stop and re-run."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=0,
                            help="only do this many city/state pairs (for testing)")

    def handle(self, *args, **opts):
        pairs = list(
            FuelStation.objects.filter(lat__isnull=True)
            .values_list("city", "state")
            .distinct()
        )
        if opts["limit"]:
            pairs = pairs[: opts["limit"]]
        self.stdout.write(f"{len(pairs)} city/state pairs to do")

        misses = []
        for i, (city, state) in enumerate(pairs, 1):
            try:
                res = lookup(city, state)
            except requests.RequestException:
                res = None
            if res:
                FuelStation.objects.filter(city=city, state=state).update(
                    lat=res[0], lon=res[1]
                )
            else:
                misses.append((city, state))
            if i % 50 == 0:
                self.stdout.write(f"{i}/{len(pairs)} done")

        self.stdout.write(f"Finished. {len(misses)} not found: {misses[:20]}")