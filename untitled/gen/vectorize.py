#################################################
############### VECTORISATION ###################
#################################################

import numpy as np
from scipy import ndimage
from scipy.spatial import cKDTree
from skimage import measure
from shapely.geometry import LineString, Polygon, MultiPolygon, mapping

import config as cfg
from tectonics import regime_names

### REPLICATION FILE: vectorize.py
### PYTHON VERSION:   3.13+
### LAST EDIT:        2026-06-11 by vao2116

"""Conversion of scattered sphere fields into geojson geometry.

The continuous and categorical fields defined on the mesh are sampled onto an
equirectangular grid, then traced into polygons with marching squares. Land,
nations and mountain belts become polygons; plate boundaries become coloured
lines classified by tectonic regime. The supercontinent is centred away from
the antimeridian and poles, so polygon tracing never has to stitch across the
grid seam.
"""


def build_grid():
    """Return the longitude axis, latitude axis and grid unit vectors."""
    lon = np.linspace(-180.0, 180.0, cfg.grid_width)
    lat = np.linspace(-90.0, 90.0, cfg.grid_height)
    lon_mesh, lat_mesh = np.meshgrid(lon, lat)
    lon_r = np.radians(lon_mesh.ravel())
    lat_r = np.radians(lat_mesh.ravel())
    cos_lat = np.cos(lat_r)
    grid_xyz = np.column_stack((cos_lat * np.cos(lon_r),
                                cos_lat * np.sin(lon_r),
                                np.sin(lat_r)))
    return lon, lat, grid_xyz


def rasterize_nearest(tree, values, grid_xyz):
    """Sample a categorical field onto the grid by nearest mesh cell."""
    _, nearest = tree.query(grid_xyz, workers=-1)
    return values[nearest].reshape(cfg.grid_height, cfg.grid_width)


def rasterize_idw(tree, values, grid_xyz):
    """Sample a continuous field onto the grid by inverse-distance weighting."""
    distance, nearest = tree.query(grid_xyz, k=cfg.raster_idw_neighbours,
                                   workers=-1)
    weight = 1.0 / (distance + 1e-9)
    sampled = np.sum(weight * values[nearest], axis=1) / np.sum(weight, axis=1)
    return sampled.reshape(cfg.grid_height, cfg.grid_width)


def rasterize_continents(moved_xyz, cell_elevation, continent_index, sea_level,
                         grid_xyz, gap_chord):
    """Paint each grid cell with the continent it belongs to in an era.

    Nearest-neighbour lookup is used for both the elevation threshold and the
    continent assignment. IDW blending between sparse mesh cells produces smooth
    oval transitions — the "circles" artefact — because the interpolated surface
    is smooth and its threshold is round. Nearest-neighbour snaps each grid cell
    to its closest mesh cell, so the coastline follows the actual fractal
    boundaries between cells rather than a smooth gradient.
    """
    tree = cKDTree(moved_xyz)
    distance, nearest = tree.query(grid_xyz, workers=-1)
    elevation = cell_elevation[nearest]
    land = (elevation > sea_level) & (distance < gap_chord)
    painted = np.where(land, continent_index[nearest], -1)
    return painted.reshape(cfg.grid_height, cfg.grid_width)


def keep_landmasses(land_mask):
    """Flood land components that should not survive for the active mode.

    Working on the grid mask rather than the mesh removes the faceted Voronoi
    coastline that nearest-cell rasterising produces. In supercontinent mode the
    largest mass plus small islands are kept; in continents mode every component
    above a small relative size is kept, leaving several distinct continents.
    """
    labels, count = ndimage.label(land_mask)
    if count == 0:
        return land_mask
    sizes = ndimage.sum(np.ones_like(labels), labels,
                        index=np.arange(1, count + 1))
    largest = sizes.max()
    keep = np.zeros(count + 1, dtype=bool)
    if cfg.world_mode == "continents":
        keep[1:] = sizes >= cfg.continent_min_relative_size * largest
    else:
        keep[1:] = sizes <= cfg.island_max_relative_size * largest
        keep[int(np.argmax(sizes)) + 1] = True
    return keep[labels]


def label_landmasses(land_mask):
    """Return per-component masks ordered from largest to smallest.

    Each surviving connected landmass becomes its own mask so it can be
    vectorised into a separately named, separately clickable continent.
    """
    labels, count = ndimage.label(land_mask)
    if count == 0:
        return []
    sizes = ndimage.sum(np.ones_like(labels), labels,
                        index=np.arange(1, count + 1))
    order = np.argsort(sizes)[::-1] + 1
    return [labels == component for component in order]


### Latitude used to close polar polygons, just shy of the pole so the ring does
### not contain the pole singularity that breaks globe rendering.
near_pole_lat = 89.9


def build_polar_cap(rng):
    """Return a south-polar continent as one polygon closed near the pole.

    The wavy coast is a periodic function of longitude so it joins across the
    antimeridian, and the ring is closed by a densely sampled line at -89.9
    degrees rather than the exact pole. This is how a real circum-polar landmass
    such as Antarctica is encoded, and it renders correctly on the globe.
    """
    longitudes = np.linspace(-179.0, 179.0, 181)
    coast = np.full_like(longitudes, cfg.antarctica_coast_lat)
    for harmonic in range(1, cfg.antarctica_harmonics + 1):
        amplitude = cfg.antarctica_coast_roughness * rng.uniform(0.2, 1.0) \
            / harmonic
        phase = rng.uniform(0.0, 2.0 * np.pi)
        coast += amplitude * np.sin(harmonic * np.radians(longitudes) + phase)
    coast[-1] = coast[0]
    top = list(zip(longitudes, coast))
    bottom = [(lon, -near_pole_lat) for lon in longitudes[::-1]]
    return Polygon(top + bottom + [top[0]])


def _chaikin(ring):
    """Round a closed coordinate ring with Chaikin corner cutting.

    Each iteration replaces every edge with two points a quarter and three
    quarters along it, smoothing the axis-aligned marching-squares steps into
    natural curves while preserving the overall coastline shape.
    """
    points = np.asarray(ring, dtype=np.float64)
    if points.shape[0] >= 2 and np.allclose(points[0], points[-1]):
        points = points[:-1]
    for _ in range(cfg.coastline_smoothing_iterations):
        following = np.roll(points, -1, axis=0)
        quarter = 0.75 * points + 0.25 * following
        three_quarter = 0.25 * points + 0.75 * following
        points = np.empty((quarter.shape[0] * 2, 2), dtype=np.float64)
        points[0::2] = quarter
        points[1::2] = three_quarter
    return np.vstack((points, points[0]))


def _row_to_lat(rows):
    """Map fractional grid rows to latitude in degrees."""
    return -90.0 + rows * (180.0 / (cfg.grid_height - 1))


def _col_to_lon(cols):
    """Map fractional grid columns to longitude in degrees."""
    return -180.0 + cols * (360.0 / (cfg.grid_width - 1))


def mask_to_multipolygon(mask):
    """Trace a boolean grid mask into a shapely multipolygon with holes."""
    padded = np.pad(mask.astype(float), 1)
    contours = measure.find_contours(padded, 0.5)
    rings = []
    for contour in contours:
        if contour.shape[0] < 4:
            continue
        lon = np.clip(_col_to_lon(contour[:, 1] - 1.0), -180.0, 180.0)
        lat = np.clip(_row_to_lat(contour[:, 0] - 1.0), -90.0, 90.0)
        polygon = Polygon(_chaikin(np.column_stack((lon, lat))))
        if not polygon.is_valid:
            polygon = polygon.buffer(0)
        if polygon.is_empty or polygon.area == 0.0:
            continue
        parts = (polygon.geoms if polygon.geom_type == "MultiPolygon"
                 else [polygon])
        rings.extend(parts)
    if not rings:
        return None

    representatives = [ring.representative_point() for ring in rings]
    depth = np.zeros(len(rings), dtype=np.int64)
    for outer in range(len(rings)):
        for inner in range(len(rings)):
            if outer != inner and rings[outer].contains(representatives[inner]):
                depth[inner] += 1

    order = np.argsort([ring.area for ring in rings])
    parent = {}
    for inner in order:
        if depth[inner] % 2 == 0:
            continue
        for outer in order[::-1]:
            if (depth[outer] == depth[inner] - 1
                    and rings[outer].contains(representatives[inner])):
                parent.setdefault(outer, []).append(inner)
                break

    shells = []
    for index, ring in enumerate(rings):
        if depth[index] % 2 != 0:
            continue
        holes = [rings[hole].exterior.coords for hole in parent.get(index, [])]
        shells.append(Polygon(ring.exterior.coords, holes))

    if not shells:
        return None
    geometry = MultiPolygon(shells) if len(shells) > 1 else shells[0]
    return geometry.simplify(cfg.simplify_tolerance_deg)


def plate_boundary_features(world, plate_grid):
    """Return line features for plate boundaries coloured by tectonic regime.

    Each plate region outline is traced, every vertex is labelled with the
    regime of the nearest classified boundary, and the outline is split into
    runs of a single regime so that collision, subduction, ridge, rift and
    transform segments can be styled distinctly on the map.
    """
    boundary_tree = cKDTree(world["boundary_xyz"])
    regime = world["boundary_regime"]
    features = []
    for plate in np.unique(plate_grid):
        contours = measure.find_contours((plate_grid == plate).astype(float),
                                         0.5)
        for contour in contours:
            if contour.shape[0] < 2:
                continue
            lon = _col_to_lon(contour[:, 1])
            lat = _row_to_lat(contour[:, 0])
            lon_r = np.radians(lon)
            lat_r = np.radians(lat)
            cos_lat = np.cos(lat_r)
            vertex_xyz = np.column_stack((cos_lat * np.cos(lon_r),
                                          cos_lat * np.sin(lon_r),
                                          np.sin(lat_r)))
            _, nearest = boundary_tree.query(vertex_xyz, workers=-1)
            vertex_regime = regime[nearest]
            start = 0
            for position in range(1, len(vertex_regime) + 1):
                ends = position == len(vertex_regime)
                if ends or vertex_regime[position] != vertex_regime[start]:
                    segment = np.column_stack(
                        (lon[start:position], lat[start:position]))
                    if segment.shape[0] >= 2:
                        line = LineString(segment).simplify(
                            cfg.simplify_tolerance_deg)
                        features.append({
                            "type": "Feature",
                            "properties": {
                                "regime": regime_names[
                                    int(vertex_regime[start])],
                            },
                            "geometry": mapping(line),
                        })
                    start = position
    return features
