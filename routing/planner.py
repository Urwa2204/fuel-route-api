class NoFuelStopError(Exception):
    pass
def plan_stops(stations, total_miles, max_range=500.0, mpg=10.0, min_saving=0.0, min_leg=0.0):

#def plan_stops(stations, total_miles, max_range=500.0, mpg=10.0):
    """
    stations: list of dicts with 'miles' (distance along the route) and 'price'.
    The car starts with a full tank. At each stop:
      1. if a cheaper station is within a full tank's reach, buy only enough to get there
      2. else if the destination is within reach, buy only enough to finish
      3. else fill up and head for the cheapest station in reach
    Returns only the stops where fuel is actually bought.
    """
    stations = sorted(stations, key=lambda s: s["miles"])
    eps = 1e-6
    pos, fuel, price = 0.0, max_range, None   # fuel is in miles of range
    stops = []

    def buy(miles):
        nonlocal fuel
        if miles <= eps:
            return
        fuel += miles
        gallons = miles / mpg
        stops[-1]["gallons"] += gallons
        stops[-1]["cost"] += gallons * stops[-1]["price"]

    def go_to(s):
        nonlocal pos, fuel, price
        fuel -= s["miles"] - pos
        pos, price = s["miles"], s["price"]
        stops.append({**s, "gallons": 0.0, "cost": 0.0})

    while total_miles - pos > fuel + eps:
        if price is None:
            # still on the starting tank
            reach = [s for s in stations if pos < s["miles"] <= pos + fuel]
            if not reach:
                raise NoFuelStopError("No fuel station within range of the start.")
            go_to(min(reach, key=lambda s: (s["price"], -s["miles"])))
            continue

        ahead = [s for s in stations if pos < s["miles"] <= pos + max_range]
       # cheaper = next((s for s in ahead if s["price"] < price), None)
        cheaper = next((s for s in ahead if s["price"] < price - min_saving and s["miles"] - pos >= min_leg),
            None,
        )
        if cheaper:
            buy(max(0.0, cheaper["miles"] - pos - fuel))
            go_to(cheaper)
        elif total_miles - pos <= max_range:
            buy(total_miles - pos - fuel)
        else:
            if not ahead:
                raise NoFuelStopError(
                    f"No fuel station within {max_range:.0f} miles after mile {pos:.0f}."
                )
            buy(max_range - fuel)
            #go_to(min(ahead, key=lambda s: (s["price"], -s["miles"])))
            lowest = min(s["price"] for s in ahead)
            near_best = [s for s in ahead if s["price"] <= lowest + min_saving]
            go_to(max(near_best, key=lambda s: s["miles"]))
    return [s for s in stops if s["gallons"] > eps]