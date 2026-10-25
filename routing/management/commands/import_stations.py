import csv

from django.core.management.base import BaseCommand
from django.db import transaction

from routing.models import FuelStation

CANADA = {"AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT"}


class Command(BaseCommand):
    help = "Load fuel prices from the CSV (US only, cheapest row per station ID)"

    def add_arguments(self, parser):
        parser.add_argument("csv_path")

    def handle(self, *args, **opts):
        best = {}
        with open(opts["csv_path"], newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                state = row["State"].strip().upper()
                if state in CANADA:
                    continue
                sid = int(row["OPIS Truckstop ID"])
                price = float(row["Retail Price"])
                if sid not in best or price < best[sid]["price"]:
                    best[sid] = {
                        "name": row["Truckstop Name"].strip(),
                        "address": row["Address"].strip(),
                        "city": row["City"].strip(),
                        "state": state,
                        "price": price,
                    }

        with transaction.atomic():
            for sid, values in best.items():
                FuelStation.objects.update_or_create(opis_id=sid, defaults=values)

        self.stdout.write(self.style.SUCCESS(f"Loaded {len(best)} stations"))