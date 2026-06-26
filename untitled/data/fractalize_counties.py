#!/usr/bin/env python3
"""
fractalize_counties.py
======================

Displace county polygon borders with fractal (fBm) simplex noise so they read
like hand-drawn historical county borders, while strictly preserving topology.

Design (why this is gap/overlap-free):

  * The displacement is a *positional* 2-D vector field  D(x, y)  built from two
    independent fBm simplex-noise channels.  Because D depends only on a point's
    coordinates -- never on which county owns it -- any vertex shared by two
    counties moves identically.

  * Interior county borders in the input are straight Voronoi edges between
    shared "nodes" (the same node coordinate appears in both adjacent counties).
    We densify every interior edge *canonically* (subdivision derived only from
    its two endpoints), so both owners generate the exact same intermediate
    points; each is displaced by D -> the two sides stay perfectly coincident.

  * Coastline vertices (segments owned by a single county) are PINNED.  The coast
    therefore stays exactly on the continent boundary: no land is lost and no
    county bleeds into the ocean.  A final hard clip to the continents union is
    kept as a numerical safety net.

  * Capital containment is handled with a per-county amplitude factor that enters
    displacement only through a purely geometric helper AMP(point) = min over the
    counties incident to that point (0 on the coast).  Reducing one county's
    factor attenuates its borders symmetrically for both owners, so topology is
    never broken.  We iterate, halving the factor of any county whose capital
    escaped, until all 672 capitals are contained (factor -> 0 restores the
    original polygon, which trivially contains its capital, so this converges).

Dependencies: shapely, numpy.  (The `noise` package is not required -- a
vectorised simplex implementation is included below.)
"""

import json
import math
import os
from collections import defaultdict

import numpy as np
from shapely.geometry import shape, mapping, Point, Polygon, MultiPolygon
from shapely.ops import unary_union

# --------------------------------------------------------------------------- #
# Paths & tunables
# --------------------------------------------------------------------------- #
HERE = os.path.dirname(os.path.abspath(__file__))
COUNTIES_IN = os.path.join(HERE, "counties.geojson")
CAPITALS_IN = os.path.join(HERE, "countycapitals.geojson")
CONTINENTS_IN = os.path.join(HERE, "continents.geojson")
OUT_PATH = os.path.join(HERE, "counties_fractal.geojson")

ROUND = 6                 # decimals used to identify coincident vertices
AMPLITUDE_PCT = 0.05      # max displacement as a fraction of typical county diameter (3-8% range)
BASE_WAVELENGTH = 2.0     # degrees: wavelength of the coarsest noise octave
OCTAVES = 4               # fBm octaves
PERSISTENCE = 0.5         # amplitude falloff per octave
LACUNARITY = 2.0          # frequency growth per octave
DENSIFY_SPACING = 0.12    # degrees: target spacing when subdividing interior edges
EDGE_DISP_FRAC = 0.30     # cap a segment's displacement at this fraction of its own length
TAPER = 0.5               # fraction of an edge over which displacement ramps to 0 at a pinned (coast) end
MAX_CAPITAL_ITERS = 12    # iterations of per-county amplitude reduction
FACTOR_SHRINK = 0.5       # multiply a failing county's factor by this each iteration

SEED_X = 1337             # noise seeds for the two displacement channels
SEED_Y = 9001


# --------------------------------------------------------------------------- #
# Vectorised 2-D simplex noise (Gustavson), numpy arrays in/out, range ~[-1, 1]
# --------------------------------------------------------------------------- #
_GRAD3 = np.array([
    [1, 1, 0], [-1, 1, 0], [1, -1, 0], [-1, -1, 0],
    [1, 0, 1], [-1, 0, 1], [1, 0, -1], [-1, 0, -1],
    [0, 1, 1], [0, -1, 1], [0, 1, -1], [0, -1, -1],
], dtype=np.float64)

_F2 = 0.5 * (math.sqrt(3.0) - 1.0)
_G2 = (3.0 - math.sqrt(3.0)) / 6.0


class SimplexNoise:
    """Vectorised 2-D simplex noise with fBm over numpy coordinate arrays."""

    def __init__(self, seed):
        rng = np.random.default_rng(seed)
        p = np.arange(256, dtype=np.int32)
        rng.shuffle(p)
        self.perm = np.concatenate([p, p]).astype(np.int32)        # length 512
        self.perm_mod12 = (self.perm % 12).astype(np.int32)

    def noise2(self, xin, yin):
        """Single-octave simplex noise. xin, yin: float arrays. Returns array ~[-1,1]."""
        xin = np.asarray(xin, dtype=np.float64)
        yin = np.asarray(yin, dtype=np.float64)
        perm = self.perm
        perm_mod12 = self.perm_mod12

        s = (xin + yin) * _F2
        i = np.floor(xin + s).astype(np.int64)
        j = np.floor(yin + s).astype(np.int64)
        t = (i + j) * _G2
        X0 = i - t
        Y0 = j - t
        x0 = xin - X0
        y0 = yin - Y0

        i1 = np.where(x0 > y0, 1, 0).astype(np.int64)
        j1 = 1 - i1

        x1 = x0 - i1 + _G2
        y1 = y0 - j1 + _G2
        x2 = x0 - 1.0 + 2.0 * _G2
        y2 = y0 - 1.0 + 2.0 * _G2

        ii = (i & 255).astype(np.int64)
        jj = (j & 255).astype(np.int64)

        gi0 = perm_mod12[ii + perm[jj]]
        gi1 = perm_mod12[ii + i1 + perm[jj + j1]]
        gi2 = perm_mod12[ii + 1 + perm[jj + 1]]

        def contrib(x, y, gi):
            tt = 0.5 - x * x - y * y
            g = _GRAD3[gi]
            dot = g[..., 0] * x + g[..., 1] * y
            out = np.where(tt < 0, 0.0, (tt ** 4) * dot)
            return out

        n0 = contrib(x0, y0, gi0)
        n1 = contrib(x1, y1, gi1)
        n2 = contrib(x2, y2, gi2)
        return 70.0 * (n0 + n1 + n2)

    def fbm(self, x, y, octaves, persistence, lacunarity, base_freq):
        """Fractal Brownian motion, normalised to ~[-1, 1]."""
        x = np.asarray(x, dtype=np.float64)
        y = np.asarray(y, dtype=np.float64)
        total = np.zeros(x.shape, dtype=np.float64)
        amp = 1.0
        freq = base_freq
        norm = 0.0
        for _ in range(octaves):
            total += amp * self.noise2(x * freq, y * freq)
            norm += amp
            amp *= persistence
            freq *= lacunarity
        return total / norm


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def rkey(xy):
    return (round(xy[0], ROUND), round(xy[1], ROUND))


def smoothstep(t):
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def iter_rings(geom):
    """Yield (coords_list, is_exterior) for every ring of a (Multi)Polygon."""
    polys = geom.geoms if geom.geom_type == "MultiPolygon" else [geom]
    for poly in polys:
        yield list(poly.exterior.coords), True
        for ring in poly.interiors:
            yield list(ring.coords), False


# --------------------------------------------------------------------------- #
# Load data
# --------------------------------------------------------------------------- #
def load():
    with open(COUNTIES_IN) as f:
        counties_gj = json.load(f)
    with open(CAPITALS_IN) as f:
        capitals_gj = json.load(f)
    with open(CONTINENTS_IN) as f:
        continents_gj = json.load(f)
    return counties_gj, capitals_gj, continents_gj


# --------------------------------------------------------------------------- #
# Build static topology (independent of the noise factors)
# --------------------------------------------------------------------------- #
def build_topology(county_geoms):
    """
    Returns:
      edges:   dict canon_key -> edge record
      rings:   list per county of list of rings; each ring is the original coord list
      node_counties: dict node_key -> set(county indices)  (interior incidence)
      coast_nodes:   set of node_key that touch a single-owner (coast) segment
    """
    # First pass: count owners of every undirected segment.
    seg_owners = defaultdict(set)
    rings_per_county = []
    for ci, geom in enumerate(county_geoms):
        rings = list(iter_rings(geom))
        rings_per_county.append(rings)
        for coords, _ in rings:
            for a, b in zip(coords[:-1], coords[1:]):
                ka, kb = rkey(a), rkey(b)
                if ka == kb:
                    continue
                key = (ka, kb) if ka <= kb else (kb, ka)
                seg_owners[key].add(ci)

    # Identify coast nodes (endpoints of any single-owner segment) and interior
    # node incidence (counties meeting at each node via shared interior edges).
    coast_nodes = set()
    node_counties = defaultdict(set)
    edges = {}
    for ci, geom in enumerate(county_geoms):
        for coords, _ in rings_per_county[ci]:
            for a, b in zip(coords[:-1], coords[1:]):
                ka, kb = rkey(a), rkey(b)
                if ka == kb:
                    continue
                key = (ka, kb) if ka <= kb else (kb, ka)
                owners = seg_owners[key]
                if len(owners) == 1:
                    coast_nodes.add(ka)
                    coast_nodes.add(kb)
                else:
                    node_counties[ka].update(owners)
                    node_counties[kb].update(owners)
                    if key not in edges:
                        # canonical endpoints in canonical (sorted-key) order
                        A = a if ka <= kb else b
                        B = b if ka <= kb else a
                        edges[key] = {
                            "owners": tuple(sorted(owners)),
                            "A": A, "B": B,
                            "kA": ka if ka <= kb else kb,
                            "kB": kb if ka <= kb else ka,
                        }

    # Pre-compute the canonical densified geometry for each interior edge.
    for key, e in edges.items():
        ax, ay = e["A"]
        bx, by = e["B"]
        length = math.hypot(bx - ax, by - ay)
        n = max(1, int(math.ceil(length / DENSIFY_SPACING)))
        ts = np.linspace(0.0, 1.0, n + 1)
        xs = ax + (bx - ax) * ts
        ys = ay + (by - ay) * ts
        e["pts"] = np.column_stack([xs, ys])      # (n+1, 2), pts[0]=A, pts[-1]=B
        e["t"] = ts
        e["coast_A"] = e["kA"] in coast_nodes
        e["coast_B"] = e["kB"] in coast_nodes

    return edges, rings_per_county, node_counties, coast_nodes, seg_owners


# --------------------------------------------------------------------------- #
# Displacement
# --------------------------------------------------------------------------- #
def displacement(pts, noise_x, noise_y, amp_scale):
    """Vector displacement of an (N,2) point array, before the per-point AMP scaling.

    The noise is sampled and applied in TRUE SURFACE distance, not in raw lon/lat
    degrees: longitude is scaled by cos(lat) so the wiggle has the same wavelength
    and amplitude everywhere on the globe (otherwise a fixed degree-wavelength
    collapses toward the poles, leaving northern borders smooth and southern ones
    jagged). It stays a pure function of (lon, lat), so a vertex shared by two
    counties is displaced identically and the partition stays gap/overlap-free."""
    lat = pts[:, 1]
    coslat = np.clip(np.cos(np.radians(lat)), 0.05, 1.0)
    u = pts[:, 0] * coslat                       # surface-uniform longitude
    v = lat
    dx = noise_x.fbm(u, v, OCTAVES, PERSISTENCE, LACUNARITY, 1.0 / BASE_WAVELENGTH)
    dy = noise_y.fbm(u, v, OCTAVES, PERSISTENCE, LACUNARITY, 1.0 / BASE_WAVELENGTH)
    # surface offset -> degree offset: longitude span grows as 1/cos(lat).
    return np.column_stack([dx / coslat, dy]) * amp_scale


def compute_edge_curves(edges, node_counties, coast_nodes, factors,
                        noise_x, noise_y, amp_scale):
    """
    For every interior edge, return its displaced canonical polyline (A..B order).
    Amplitude per point uses purely geometric AMP so both owners are identical.
    """
    def node_amp(nk):
        if nk in coast_nodes:
            return 0.0
        cs = node_counties.get(nk)
        if not cs:
            return 1.0
        return min(factors[c] for c in cs)

    curves = {}
    for key, e in edges.items():
        pts = e["pts"]
        t = e["t"]
        disp = displacement(pts, noise_x, noise_y, amp_scale)

        # Cap displacement at a fraction of this edge's own length: keeps the
        # offset proportional to segment length and prevents short borders from
        # folding over themselves. Both owners see the same length -> identical.
        ax, ay = e["A"]; bx, by = e["B"]
        # Surface length (longitude scaled by cos of the edge's mean latitude), so
        # the cap bounds the real on-globe offset uniformly at every latitude.
        mcos = max(0.05, math.cos(math.radians(0.5 * (ay + by))))
        length = math.hypot((bx - ax) * mcos, by - ay)
        edge_cap = min(1.0, (EDGE_DISP_FRAC * length) / amp_scale) if amp_scale > 0 else 0.0

        # Endpoints (shared nodes) must NOT be capped per-edge, or a node shared
        # by edges of differing length would move inconsistently and tear. Only
        # the interior bowing of the edge is capped by its own length.
        pair_amp = min(factors[e["owners"][0]], factors[e["owners"][1]]) * edge_cap
        ampA = node_amp(e["kA"])
        ampB = node_amp(e["kB"])

        # Per-point amplitude: endpoints use node amplitude; interior points use
        # pair amplitude, tapered to zero toward any pinned (coast) endpoint so we
        # never create spurs into the ocean.
        amp = np.full(pts.shape[0], pair_amp, dtype=np.float64)
        wA = 1.0 if not e["coast_A"] else smoothstep(t / TAPER)
        wB = 1.0 if not e["coast_B"] else smoothstep((1.0 - t) / TAPER)
        amp = amp * wA * wB
        amp[0] = ampA
        amp[-1] = ampB

        curve = pts + disp * amp[:, None]
        curves[key] = curve
    return curves


def assemble_county(rings, seg_owners, curves):
    """Rebuild one county's (Multi)Polygon from displaced interior edges + pinned coast."""
    out_polys = []
    pending_holes = []
    for coords, is_exterior in rings:
        ring_pts = []
        for a, b in zip(coords[:-1], coords[1:]):
            ka, kb = rkey(a), rkey(b)
            if ka == kb:
                continue
            key = (ka, kb) if ka <= kb else (kb, ka)
            if len(seg_owners[key]) == 1:
                # coastal segment: pinned -> keep original start vertex
                ring_pts.append((a[0], a[1]))
            else:
                curve = curves[key]
                seq = curve if ka <= kb else curve[::-1]
                # append all but last to avoid duplicating the shared node
                ring_pts.extend([(x, y) for x, y in seq[:-1]])
        if len(ring_pts) < 3:
            continue
        ring_pts.append(ring_pts[0])
        ring = Polygon(ring_pts)
        if not ring.is_valid:
            ring = ring.buffer(0)  # repair self-intersections from displacement
        if ring.is_empty:
            continue
        if is_exterior:
            out_polys.append(ring)
        else:
            pending_holes.append(ring)

    if not out_polys:
        return None
    geom = unary_union(out_polys) if len(out_polys) > 1 else out_polys[0]
    geom = geom.buffer(0)  # repair any residual self-touch from displacement
    if pending_holes:
        holes = unary_union([h.buffer(0) for h in pending_holes])
        geom = geom.difference(holes)
    return geom


def to_multipolygon(geom):
    if geom is None or geom.is_empty:
        return None
    if geom.geom_type == "Polygon":
        return MultiPolygon([geom])
    if geom.geom_type == "MultiPolygon":
        return geom
    # GeometryCollection -> keep polygonal parts
    polys = [g for g in geom.geoms if g.geom_type in ("Polygon", "MultiPolygon")]
    flat = []
    for g in polys:
        flat.extend(g.geoms if g.geom_type == "MultiPolygon" else [g])
    return MultiPolygon(flat) if flat else None


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main():
    counties_gj, capitals_gj, continents_gj = load()

    county_feats = counties_gj["features"]
    county_geoms = [shape(f["geometry"]) for f in county_feats]
    n_counties = len(county_geoms)

    capital_by_id = {f["properties"]["id"]: shape(f["geometry"]) for f in capitals_gj["features"]}
    capital_pts = []
    for f in county_feats:
        cid = f["properties"]["id"]
        capital_pts.append(capital_by_id[cid])

    continents = unary_union([shape(f["geometry"]) for f in continents_gj["features"]]).buffer(0)

    # Typical county diameter (median bbox diagonal, in SURFACE distance) ->
    # displacement amplitude. Longitude is scaled by cos(lat) so the equal-on-
    # globe counties give a stable median instead of one inflated by the
    # degree-stretched northern cells.
    diags = []
    for g in county_geoms:
        minx, miny, maxx, maxy = g.bounds
        mc = max(0.05, math.cos(math.radians(0.5 * (miny + maxy))))
        diags.append(math.hypot((maxx - minx) * mc, maxy - miny))
    typ_diam = float(np.median(diags))
    amp_scale = AMPLITUDE_PCT * typ_diam
    print(f"counties: {n_counties}  typical diameter: {typ_diam:.3f} deg  "
          f"max displacement: {amp_scale:.3f} deg ({AMPLITUDE_PCT*100:.0f}%)")

    edges, rings_per_county, node_counties, coast_nodes, seg_owners = build_topology(county_geoms)
    print(f"interior edges: {len(edges)}  coast nodes: {len(coast_nodes)}")

    noise_x = SimplexNoise(SEED_X)
    noise_y = SimplexNoise(SEED_Y)

    factors = [1.0] * n_counties

    final_geoms = [None] * n_counties
    for it in range(MAX_CAPITAL_ITERS):
        curves = compute_edge_curves(edges, node_counties, coast_nodes, factors,
                                     noise_x, noise_y, amp_scale)
        failed = []
        for ci in range(n_counties):
            geom = assemble_county(rings_per_county[ci], seg_owners, curves)
            if geom is not None:
                geom = geom.intersection(continents)
            mp = to_multipolygon(geom)
            final_geoms[ci] = mp
            cap = capital_pts[ci]
            if mp is None or not mp.buffer(1e-9).covers(cap):
                failed.append(ci)

        if not failed:
            print(f"iter {it}: all capitals contained.")
            break
        print(f"iter {it}: {len(failed)} capitals outside -> reducing their amplitude.")
        for ci in failed:
            factors[ci] *= FACTOR_SHRINK
    else:
        print(f"WARNING: {len(failed)} capitals still outside after {MAX_CAPITAL_ITERS} iters: {failed[:20]}")

    # ----------------------------------------------------------------------- #
    # Partition pass: enforce strictly non-overlapping counties.
    #
    # Shared interior borders are byte-identical between owners, so on a normal
    # seam this subtracts only a zero-width line (no visible change). It only
    # bites where a strongly-bowed border crossed a *non-shared* neighbour edge,
    # assigning that thin sliver to the lower-indexed county. Because we never
    # remove area that no one else covers, the union (land coverage) is preserved
    # exactly -- this removes overlaps without introducing gaps.
    # ----------------------------------------------------------------------- #
    from shapely.strtree import STRtree
    from shapely.prepared import prep

    idx_geoms = [g if g is not None else Point(0, 0) for g in final_geoms]
    tree = STRtree(idx_geoms)
    resolved = [None] * n_counties
    n_clipped = 0
    for ci in range(n_counties):
        g = final_geoms[ci]
        if g is None:
            continue
        earlier = []
        for j in tree.query(g):
            j = int(j)
            if j < ci and resolved[j] is not None and g.intersects(resolved[j]):
                if g.intersection(resolved[j]).area > 1e-12:
                    earlier.append(resolved[j])
        if earlier:
            g = g.difference(unary_union(earlier))
            g = g.buffer(0)
            n_clipped += 1
        resolved[ci] = g
    # keep capitals safe: if the partition clipped a capital out, fall back
    for ci in range(n_counties):
        mp = to_multipolygon(resolved[ci])
        if mp is not None and final_geoms[ci] is not None:
            cap = capital_pts[ci]
            if not mp.buffer(1e-9).covers(cap):
                mp = to_multipolygon(final_geoms[ci])
        final_geoms[ci] = mp
    print(f"partition pass: clipped overlaps from {n_clipped} counties")

    # ----------------------------------------------------------------------- #
    # Topology / sanity verification
    # ----------------------------------------------------------------------- #
    valid_geoms = [g for g in final_geoms if g is not None]
    union = unary_union(valid_geoms)
    sum_area = sum(g.area for g in valid_geoms)
    cont_area = continents.area
    print("--- verification ---")
    print(f"continents area:        {cont_area:.4f}")
    print(f"union(counties) area:   {union.area:.4f}  (land coverage diff: {cont_area - union.area:+.6f})")
    print(f"sum(county areas):      {sum_area:.4f}  (overlap proxy: {sum_area - union.area:+.6f})")
    print(f"counties outside land:  {union.difference(continents).area:.8f}")
    n_invalid = sum(0 if g.is_valid else 1 for g in valid_geoms)
    print(f"invalid geometries:     {n_invalid}")
    contained = sum(1 for ci in range(n_counties)
                    if final_geoms[ci] is not None and final_geoms[ci].buffer(1e-9).covers(capital_pts[ci]))
    print(f"capitals contained:     {contained}/{n_counties}")
    reduced = sum(1 for f in factors if f < 1.0)
    print(f"counties with reduced amplitude: {reduced}")

    # ----------------------------------------------------------------------- #
    # Write output (same attributes, CRS, and feature order as the input)
    # ----------------------------------------------------------------------- #
    out_features = []
    for ci, f in enumerate(county_feats):
        mp = final_geoms[ci]
        if mp is None:
            mp = county_geoms[ci]
            mp = mp if mp.geom_type == "MultiPolygon" else MultiPolygon([mp])
        out_features.append({
            "type": "Feature",
            "properties": dict(f["properties"]),
            "geometry": mapping(mp),
        })

    out = {
        "type": "FeatureCollection",
        "features": out_features,
    }
    if "crs" in counties_gj:
        out["crs"] = counties_gj["crs"]

    with open(OUT_PATH, "w") as f:
        json.dump(out, f)
    print(f"wrote {OUT_PATH}  ({len(out_features)} features)")


if __name__ == "__main__":
    main()
