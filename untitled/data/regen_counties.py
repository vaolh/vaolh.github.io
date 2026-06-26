#!/usr/bin/env python3
"""
regen_counties.py
=================

Regenerate the county partition from scratch so the cells (a) are evenly sized
on the GLOBE at every latitude and (b) tile each continent completely, down to
the real coastline -- fixing the "white strip below the counties" (land left
uncovered because the old planar Voronoi was cut on a straight line) and the
shear of cells toward the poles.

How uniform-on-the-globe is achieved
------------------------------------
Each continent is handled in its OWN azimuthal-equidistant projection, centred
on that continent. In an azimuthal-equidistant plane distances from the centre
are true, so an evenly spaced point set there maps to evenly sized, round cells
on the sphere -- independent of latitude. (This is the same trick the old
hybrid_counties.py used only for the polar cap, here applied to every land.)

Pipeline per continent
-----------------------
  1. centre an azeq projection on the continent's representative point;
  2. project the continent (coastline densified so it stays smooth);
  3. drop a lightly jittered hexagonal point lattice inside it -- hex spacing is
     a single global constant, so every continent gets the SAME cell size;
  4. build the planar Voronoi diagram of those seeds;
  5. clip each cell to the projected continent (lakes removed, coast followed);
  6. un-project the cells back to lon/lat.

Interior Voronoi edges are kept as straight chords between shared nodes (the
same vertex appears in both neighbours), exactly what fractalize_counties.py
expects; only the coastline carries the dense, single-owner vertices it pins.

Writes counties.geojson + countycapitals.geojson, then run:
    python fractalize_counties.py

Dependencies: shapely (>=2), numpy.
"""

import json
import math
import os

import numpy as np
from shapely.geometry import shape, Point, MultiPoint, Polygon, MultiPolygon
from shapely.ops import unary_union, voronoi_diagram
from shapely.prepared import prep
from shapely.strtree import STRtree

# --------------------------------------------------------------------------- #
# Paths & tunables
# --------------------------------------------------------------------------- #
HERE = os.path.dirname(os.path.abspath(__file__))
CONTINENTS = os.path.join(HERE, "continents.geojson")
COUNTIES_OUT = os.path.join(HERE, "counties.geojson")
CAPITALS_OUT = os.path.join(HERE, "countycapitals.geojson")

TARGET_COUNTIES = 451      # aim for ~the previous count (density 0.025 / deg^2)
JITTER = 0.33              # lattice jitter as a fraction of hex spacing
COAST_STEP = 0.5          # deg: densify continent boundary before projecting
ROUND = 6                 # output decimals (must match fractalize_counties.ROUND)
SEED = 20260625

RNG = np.random.default_rng(SEED)
CRS = {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}}
D2R = math.pi / 180.0


# --------------------------------------------------------------------------- #
# Azimuthal-equidistant projection, centred on (lon0, lat0). Units: radians.
# --------------------------------------------------------------------------- #
def azeq_fwd(lon, lat, lon0, lat0):
    lon = np.asarray(lon, float) * D2R
    lat = np.asarray(lat, float) * D2R
    lo0, la0 = lon0 * D2R, lat0 * D2R
    cosc = np.clip(np.sin(la0) * np.sin(lat) +
                   np.cos(la0) * np.cos(lat) * np.cos(lon - lo0), -1.0, 1.0)
    c = np.arccos(cosc)
    sinc = np.sin(c)
    k = np.where(sinc < 1e-12, 1.0, c / np.where(sinc < 1e-12, 1.0, sinc))
    x = k * np.cos(lat) * np.sin(lon - lo0)
    y = k * (np.cos(la0) * np.sin(lat) -
             np.sin(la0) * np.cos(lat) * np.cos(lon - lo0))
    return x, y


def azeq_inv(x, y, lon0, lat0):
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    lo0, la0 = lon0 * D2R, lat0 * D2R
    rho = np.hypot(x, y)
    safe = np.where(rho < 1e-12, 1.0, rho)
    c = rho
    sinc, cosc = np.sin(c), np.cos(c)
    lat = np.arcsin(np.clip(
        np.where(rho < 1e-12, np.sin(la0),
                 cosc * np.sin(la0) + y * sinc * np.cos(la0) / safe), -1.0, 1.0))
    lon = lo0 + np.arctan2(x * sinc,
                           rho * np.cos(la0) * cosc - y * np.sin(la0) * sinc)
    lon = (np.degrees(lon) + 180.0) % 360.0 - 180.0
    return lon, np.degrees(lat)


def densify(coords, step):
    """Insert points so no lon/lat segment exceeds `step` degrees."""
    out = []
    for (x0, y0), (x1, y1) in zip(coords[:-1], coords[1:]):
        out.append((x0, y0))
        n = int(math.hypot(x1 - x0, y1 - y0) / step)
        for k in range(1, n):
            t = k / n
            out.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
    out.append(coords[-1])
    return out


def project_poly(poly, lon0, lat0):
    def ring(co):
        co = densify(list(co), COAST_STEP)
        xs, ys = azeq_fwd([c[0] for c in co], [c[1] for c in co], lon0, lat0)
        return list(zip(xs.tolist(), ys.tolist()))
    p = Polygon(ring(poly.exterior.coords),
                [ring(r.coords) for r in poly.interiors])
    return p.buffer(0)


def unproject_poly(poly, lon0, lat0):
    def ring(co):
        xs = [c[0] for c in co]
        ys = [c[1] for c in co]
        lon, lat = azeq_inv(xs, ys, lon0, lat0)
        return list(zip(lon.tolist(), lat.tolist()))
    p = Polygon(ring(poly.exterior.coords),
                [ring(r.coords) for r in poly.interiors])
    if not p.is_valid:
        p = p.buffer(0)
    return p


# --------------------------------------------------------------------------- #
# Even point lattice inside a projected continent.
# --------------------------------------------------------------------------- #
def hex_points(projC, spacing):
    minx, miny, maxx, maxy = projC.bounds
    pc = prep(projC)
    dy = spacing * math.sqrt(3) / 2.0
    pts = []
    row = 0
    y = miny - dy
    while y <= maxy + dy:
        xoff = (spacing / 2.0) if (row % 2) else 0.0
        x = minx - spacing + xoff
        while x <= maxx + spacing:
            jx = x + RNG.uniform(-JITTER, JITTER) * spacing
            jy = y + RNG.uniform(-JITTER, JITTER) * spacing
            if pc.contains(Point(jx, jy)):
                pts.append((jx, jy))
            x += spacing
        y += dy
        row += 1
    if not pts:                       # tiny continent: at least its centroid
        c = projC.representative_point()
        pts.append((c.x, c.y))
    return pts


def explode(geom):
    if geom.is_empty:
        return []
    if geom.geom_type == "Polygon":
        return [geom]
    if geom.geom_type == "MultiPolygon":
        return list(geom.geoms)
    return [g for g in getattr(geom, "geoms", []) if g.geom_type == "Polygon"]


def rings_of(poly):
    def r(co):
        return [[round(x, ROUND), round(y, ROUND)] for x, y in co]
    return [r(poly.exterior.coords)] + [r(i.coords) for i in poly.interiors]


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main():
    data = json.load(open(CONTINENTS))
    union = unary_union([shape(f["geometry"]) for f in data["features"]])
    continents = explode(union)
    print(f"continents: {len(continents)}  plate-carree area: {union.area:.1f}")

    # One global cell size, chosen so the planet ends up with ~TARGET counties.
    # Work out each continent's TRUE area via its own azeq projection, sum it,
    # then size the hexagon so total / cell_area ~= TARGET.
    centres, proj = [], []
    true_area = 0.0
    for c in continents:
        rp = c.representative_point()
        lon0, lat0 = rp.x, rp.y
        pc = project_poly(c, lon0, lat0)
        centres.append((lon0, lat0))
        proj.append(pc)
        true_area += pc.area
    cell_area = true_area / TARGET_COUNTIES
    spacing = math.sqrt(cell_area * 2.0 / math.sqrt(3))   # hex spacing (radians)
    print(f"true land area: {true_area:.4f} sr  cell: {cell_area:.5f} sr  "
          f"spacing: {math.degrees(spacing):.2f} deg")

    counties, capitals = [], []
    cid = 0
    for c, (lon0, lat0), pc in zip(continents, centres, proj):
        seeds = hex_points(pc, spacing)
        regions = list(voronoi_diagram(MultiPoint(seeds),
                                       envelope=pc.buffer(spacing * 4).envelope).geoms)
        tree = STRtree(regions)
        for (sx, sy) in seeds:
            sp = Point(sx, sy)
            region = None
            for idx in tree.query(sp):
                if regions[idx].covers(sp):
                    region = regions[idx]
                    break
            if region is None:
                continue
            cell = region.intersection(pc)
            parts = []
            for p in explode(cell):
                if p.area <= 0:
                    continue
                up = unproject_poly(p, lon0, lat0)
                if up is None or up.is_empty:
                    continue
                parts.extend(g for g in explode(up) if g.area > 0)
            if not parts:
                continue
            multi = [rings_of(p) for p in parts]
            clon, clat = azeq_inv([sx], [sy], lon0, lat0)
            counties.append({
                "type": "Feature", "properties": {"id": cid},
                "geometry": {"type": "MultiPolygon", "coordinates": multi},
            })
            capitals.append({
                "type": "Feature", "properties": {"id": cid},
                "geometry": {"type": "Point",
                             "coordinates": [round(float(clon[0]), ROUND),
                                             round(float(clat[0]), ROUND)]},
            })
            cid += 1

    for path, feats in ((COUNTIES_OUT, counties), (CAPITALS_OUT, capitals)):
        json.dump({"type": "FeatureCollection", "crs": CRS, "features": feats},
                  open(path, "w"))
    print(f"wrote {len(counties)} counties -> {COUNTIES_OUT}")
    print(f"wrote {len(capitals)} capitals -> {CAPITALS_OUT}")


if __name__ == "__main__":
    main()
