import numpy as np
from scipy.spatial import cKDTree

EARTH_RADIUS_MI = 3958.8


def to_xyz(lat, lon):
    """Degrees -> 3D points on a sphere, in miles."""
    lat = np.radians(np.asarray(lat, dtype=float))
    lon = np.radians(np.asarray(lon, dtype=float))
    return EARTH_RADIUS_MI * np.column_stack((
        np.cos(lat) * np.cos(lon),
        np.cos(lat) * np.sin(lon),
        np.sin(lat),
    ))


def haversine_miles(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = (np.sin((lat2 - lat1) / 2) ** 2
         + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2)
    return 2 * EARTH_RADIUS_MI * np.arcsin(np.sqrt(a))


def build_profile(coords, total_miles, step=1.0):
    """
    coords: [[lon, lat], ...] from the routing API.
    Returns (lat, lon, miles_from_start) arrays thinned to about one
    point per `step` miles, so later lookups stay cheap.
    """
    arr = np.asarray(coords, dtype=float)
    lon, lat = arr[:, 0], arr[:, 1]
    seg = haversine_miles(lat[:-1], lon[:-1], lat[1:], lon[1:])
    cum = np.concatenate(([0.0], np.cumsum(seg)))
    if cum[-1] > 0:
        cum *= total_miles / cum[-1]   # match the API's own distance
    idx = np.searchsorted(cum, np.arange(0, cum[-1], step))
    idx = np.unique(np.append(idx, len(cum) - 1))
    return lat[idx], lon[idx], cum[idx]


def stations_near_route(profile, st_xyz, max_detour):
    """
    For every station, find the closest route point.
    Returns (mask, miles_along_route, distance_off_route).
    """
    r_lat, r_lon, r_miles = profile
    tree = cKDTree(to_xyz(r_lat, r_lon))
    dist, idx = tree.query(st_xyz, distance_upper_bound=max_detour)
    mask = np.isfinite(dist)
    along = np.zeros(len(st_xyz))
    along[mask] = r_miles[idx[mask]]
    return mask, along, dist