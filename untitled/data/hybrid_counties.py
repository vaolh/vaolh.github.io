#!/usr/bin/env python3
"""
hybrid_counties.py
==================

Keep the original (planar) counties for the south of the map -- where they look
good -- and replace ONLY the northern cap (where planar Voronoi shears into
meridian slivers on the globe) with sphere-uniform counties.

  * South of SPLIT_LAT : original counties, trimmed at the split line.
  * North of SPLIT_LAT : fresh sphere-uniform counties from a pole-centred
                         azimuthal-equidistant Voronoi (round cells on the globe),
                         at the same areal density as the southern counties.

The two halves meet on the SPLIT_LAT circle (a clean latitude seam). Reads the
pristine originals from the _bak_* backups so it is re-runnable; writes
counties.geojson + countycapitals.geojson. Then rerun: python fractalize_counties.py
"""

import json
import math
import os

import numpy as np
from shapely.geometry import shape, mapping, Point, MultiPoint, Polygon, MultiPolygon, box
from shapely.ops import unary_union, voronoi_diagram
from shapely.prepared import prep

HERE = os.path.dirname(os.path.abspath(__file__))
BAK_COUNTIES = os.path.join(HERE, "_bak_counties.geojson")
BAK_CAPITALS = os.path.join(HERE, "_bak_countycapitals.geojson")
CONTINENTS = os.path.join(HERE, "continents.geojson")
COUNTIES_OUT = os.path.join(HERE, "counties.geojson")
CAPITALS_OUT = os.path.join(HERE, "countycapitals.geojson")

SPLIT_LAT = 60.0          # below: keep originals; above: sphere-uniform cap
SEED = 21390380201
RNG = np.random.default_rng(SEED)
CRS = {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}}
DEG = math.pi / 180.0


# --- pole-centred azimuthal-equidistant projection (lat0 = 90) -------------- #
def azeq_fwd(lon, lat):
    lon = np.asarray(lon) * DEG; lat = np.asarray(lat) * DEG
    c = np.pi / 2 - lat               # colatitude = radial distance from pole
    return c * np.sin(lon), -c * np.cos(lon)


def azeq_inv(x, y):
    x = np.asarray(x); y = np.asarray(y)
    c = np.hypot(x, y)
    lat = 90 - c / DEG
    lon = np.arctan2(x, -y) / DEG
    return (lon + 180) % 360 - 180, lat


def densify_ring(co, step=1.0):
    """Insert points so no lon/lat segment exceeds `step` degrees (smooth arcs)."""
    out = []
    for (x0, y0), (x1, y1) in zip(co[:-1], co[1:]):
        out.append((x0, y0))
        n = int(max(abs(x1 - x0), abs(y1 - y0)) / step)
        for k in range(1, n):
            t = k / n
            out.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
    out.append(co[-1])
    return out


def proj(geom):
    def ring(co):
        co = densify_ring(list(co))
        x, y = azeq_fwd([c[0] for c in co], [c[1] for c in co])
        return list(zip(x.tolist(), y.tolist()))
    ps = geom.geoms if geom.geom_type == "MultiPolygon" else [geom]
    out = []
    for p in ps:
        poly = Polygon(ring(p.exterior.coords), [ring(r.coords) for r in p.interiors])
        poly = poly.buffer(0)
        if not poly.is_empty:
            out.append(poly)
    return unary_union(out)


def unproj(geom):
    def ring(co):
        lon, lat = azeq_inv([c[0] for c in co], [c[1] for c in co])
        return list(zip(lon.tolist(), lat.tolist()))
    ps = geom.geoms if geom.geom_type == "MultiPolygon" else [geom]
    out = []
    for p in ps:
        if p.is_empty:
            continue
        poly = Polygon(ring(p.exterior.coords), [ring(r.coords) for r in p.interiors])
        if not poly.is_valid:
            poly = poly.buffer(0)
        if not poly.is_empty:
            out.append(poly)
    return unary_union(out) if len(out) > 1 else (out[0] if out else None)


def as_multi(g):
    if g is None or g.is_empty:
        return None
    if g.geom_type == "Polygon":
        return MultiPolygon([g])
    if g.geom_type == "MultiPolygon":
        return g
    flat = []
    for p in getattr(g, "geoms", []):
        if p.geom_type == "Polygon":
            flat.append(p)
        elif p.geom_type == "MultiPolygon":
            flat += list(p.geoms)
    return MultiPolygon(flat) if flat else None


def main():
    counties = json.load(open(BAK_COUNTIES))
    capitals = json.load(open(BAK_CAPITALS))
    cap_by_id = {f["properties"]["id"]: shape(f["geometry"]) for f in capitals["features"]}
    land = unary_union([shape(f["geometry"]) for f in continents_features()]).buffer(0)
    pland = prep(land)

    south_box = box(-180, -90, 180, SPLIT_LAT)
    north_land = as_multi(land.intersection(box(-180, SPLIT_LAT, 180, 90)).buffer(0))

    # ---- southern counties: original, trimmed at the split line ----
    south_counties, south_caps = [], []
    for f in counties["features"]:
        g = shape(f["geometry"]).buffer(0)
        s = g.intersection(south_box)
        if s.is_empty or s.area <= 1e-9:
            continue
        sm = as_multi(s)
        cap = cap_by_id.get(f["properties"]["id"])
        if cap is None or not sm.buffer(1e-9).covers(cap):
            cap = sm.representative_point()
        south_counties.append(sm)
        south_caps.append(cap)
    n_south = len(south_counties)
    print(f"south of {SPLIT_LAT}: kept {n_south} original counties.")

    if north_land is None or north_land.area <= 0:
        print("no land north of split; nothing to replace.")
        return

    # ---- choose northern county count to match southern areal density ----
    M = 200000
    u = RNG.uniform(math.sin(-90 * DEG), 1.0, M)        # sphere-uniform latitudes
    lat = np.degrees(np.arcsin(u)); lon = RNG.uniform(-180, 180, M)
    in_land = np.array([pland.covers(Point(lo, la)) for lo, la in zip(lon[:8000], lat[:8000])])
    # estimate densities from the 8000-sample subset
    sub_lat = lat[:8000]
    m_s = int((in_land & (sub_lat < SPLIT_LAT)).sum())
    m_n = int((in_land & (sub_lat >= SPLIT_LAT)).sum())
    n_north = max(6, round(n_south * m_n / max(1, m_s)))
    print(f"north of {SPLIT_LAT}: generating {n_north} sphere-uniform counties "
          f"(density-matched).")

    # ---- sphere-uniform seeds inside the northern land ----
    seeds = []
    while len(seeds) < n_north * 60 and len(seeds) < 200000:
        uu = RNG.uniform(math.sin(SPLIT_LAT * DEG), 1.0, n_north * 40)
        la = np.degrees(np.arcsin(uu)); lo = RNG.uniform(-180, 180, uu.size)
        for a, o in zip(la, lo):
            if pland.covers(Point(o, a)):
                seeds.append((o, a))
        if len(seeds) >= n_north:
            break
    seeds = seeds[: max(n_north, 3)]

    # ---- pole-centred azimuthal Voronoi of those seeds, clipped to the cap ----
    plane_land = proj(north_land)
    pts_xy = [tuple(azeq_fwd([o], [a])[i][0] for i in (0, 1)) for o, a in seeds]
    mp = MultiPoint([Point(p) for p in pts_xy])
    env = plane_land.buffer(abs(plane_land.bounds[2] - plane_land.bounds[0]) + 1.0)
    cells = voronoi_diagram(mp, envelope=env)

    north_counties, north_caps = [], []
    for cell in cells.geoms:
        piece = cell.intersection(plane_land)
        if piece.is_empty or piece.area <= 0:
            continue
        geom_ll = unproj(piece.buffer(0))
        geom_ll = as_multi(geom_ll.intersection(north_land)) if geom_ll else None
        if geom_ll is None or geom_ll.is_empty:
            continue
        north_counties.append(geom_ll)
        seed_pt = None
        for (o, a), xy in zip(seeds, pts_xy):
            if cell.contains(Point(xy)):
                seed_pt = Point(o, a)
                break
        if seed_pt is None or not geom_ll.buffer(1e-9).covers(seed_pt):
            seed_pt = geom_ll.representative_point()
        north_caps.append(seed_pt)
    print(f"north: built {len(north_counties)} counties.")

    # ---- combine + renumber ----
    all_c = south_counties + north_counties
    all_p = south_caps + north_caps
    feats_c, feats_p = [], []
    for i, (g, p) in enumerate(zip(all_c, all_p)):
        mp_g = as_multi(g)
        if not mp_g.buffer(1e-9).covers(p):
            p = mp_g.representative_point()
        feats_c.append({"type": "Feature", "properties": {"id": i}, "geometry": mapping(mp_g)})
        feats_p.append({"type": "Feature", "properties": {"id": i}, "geometry": mapping(p)})

    json.dump({"type": "FeatureCollection", "crs": CRS, "features": feats_c}, open(COUNTIES_OUT, "w"))
    json.dump({"type": "FeatureCollection", "crs": CRS, "features": feats_p}, open(CAPITALS_OUT, "w"))
    print(f"wrote {len(feats_c)} counties ({n_south} south + {len(north_counties)} north).")


def continents_features():
    return json.load(open(CONTINENTS))["features"]


if __name__ == "__main__":
    main()
