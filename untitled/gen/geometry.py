#################################################
############### SPHERE GEOMETRY #################
#################################################

import numpy as np
from scipy.spatial import cKDTree

### REPLICATION FILE: geometry.py
### PYTHON VERSION:   3.13+
### LAST EDIT:        2026-06-11 by vao2116

"""Geometric primitives on the unit sphere.

The world is modelled as a set of near-equal-area cells sampled on the unit
sphere. This module provides the sampling, the coordinate conversions between
unit vectors and geographic degrees, an approximate adjacency graph, and a
seamless fractal noise field defined directly on the sphere.
"""


def fibonacci_sphere(count):
    """Return ``count`` near-equal-area points on the unit sphere as an array.

    The Fibonacci spiral gives the most uniform simple distribution of points
    on a sphere, so each cell represents a comparable patch of surface area.
    """
    indices = np.arange(count, dtype=np.float64)
    golden = np.pi * (3.0 - np.sqrt(5.0))
    z = 1.0 - 2.0 * (indices + 0.5) / count
    radius = np.sqrt(np.clip(1.0 - z * z, 0.0, 1.0))
    theta = golden * indices
    x = radius * np.cos(theta)
    y = radius * np.sin(theta)
    return np.column_stack((x, y, z))


def xyz_to_lonlat(points):
    """Convert unit vectors to (longitude, latitude) pairs in degrees."""
    x, y, z = points[:, 0], points[:, 1], points[:, 2]
    lon = np.degrees(np.arctan2(y, x))
    lat = np.degrees(np.arcsin(np.clip(z, -1.0, 1.0)))
    return np.column_stack((lon, lat))


def lonlat_to_xyz(lon, lat):
    """Convert longitude and latitude arrays in degrees to unit vectors."""
    lon_r = np.radians(lon)
    lat_r = np.radians(lat)
    cos_lat = np.cos(lat_r)
    x = cos_lat * np.cos(lon_r)
    y = cos_lat * np.sin(lon_r)
    z = np.sin(lat_r)
    return np.column_stack((x, y, z))


def angular_distance(points, reference):
    """Return the great-circle angle in radians from each point to a reference."""
    dots = np.clip(points @ reference, -1.0, 1.0)
    return np.arccos(dots)


def build_adjacency(points, neighbours):
    """Return a k-nearest-neighbour adjacency as arrays of edge endpoints.

    Nearest neighbours in three-dimensional chord distance coincide with
    nearest neighbours in great-circle distance on the unit sphere, so this
    approximates the local mesh connectivity without a full triangulation.
    """
    tree = cKDTree(points)
    _, neighbour_index = tree.query(points, k=neighbours + 1, workers=-1)
    source = np.repeat(np.arange(points.shape[0]), neighbours)
    target = neighbour_index[:, 1:].reshape(-1)
    edges = np.column_stack((source, target))
    ordered = np.sort(edges, axis=1)
    unique_edges = np.unique(ordered, axis=0)
    return unique_edges


def rodrigues(points, axes, angle):
    """Rotate each point about its own unit axis by a shared angle.

    Uses the Rodrigues rotation formula vectorised over all points, which is how
    rigid plate motion is advanced: every cell is carried about its plate's Euler
    axis by the same angular amount for a given era.
    """
    cos_a = np.cos(angle)
    sin_a = np.sin(angle)
    dot = np.sum(axes * points, axis=1, keepdims=True)
    cross = np.cross(axes, points)
    return (points * cos_a + cross * sin_a + axes * dot * (1.0 - cos_a))


def domain_warp(points, rng, amplitude, components, frequency_min,
                frequency_max):
    """Return points displaced by a smooth vector noise field on the sphere.

    Warping positions before the nearest-seed test bends the otherwise straight
    Voronoi plate boundaries into fractal, natural-looking lines, which carry
    through to irregular coastlines once the supercontinent rifts apart.
    """
    displacement = np.column_stack([
        sphere_noise(points, rng, components, frequency_min, frequency_max, 1.0)
        for _ in range(3)])
    warped = points + amplitude * displacement
    return warped / np.linalg.norm(warped, axis=1, keepdims=True)


def fault_displacement(points, rng, faults, chunk=256):
    """Return a fractal heightfield built by random great-circle faults.

    This is the donjon / Mogensen fractal-planet method: each fault is a random
    great circle that raises one hemisphere and lowers the other by one unit.
    Summed over thousands of faults the result is fractional-Brownian terrain
    that is fractal uniformly over the sphere, so coastlines thresholded from it
    are naturally crenulated everywhere, including at the poles. The field is
    returned standardised to zero mean and unit variance.
    """
    field = np.zeros(points.shape[0], dtype=np.float64)
    done = 0
    while done < faults:
        size = min(chunk, faults - done)
        normals = rng.normal(size=(size, 3))
        normals /= np.linalg.norm(normals, axis=1, keepdims=True)
        signs = rng.choice(np.array([-1.0, 1.0]), size=size)
        projection = points @ normals.T
        field += (projection > 0).astype(np.float64) @ signs
        done += size
    field -= field.mean()
    spread = field.std()
    if spread > 0:
        field /= spread
    return field


def smooth_field(values, edges, passes):
    """Smooth a per-cell field by repeated averaging with adjacent cells.

    Each pass replaces a cell value with the mean of itself and its mesh
    neighbours, diffusing a sharp indicator into a continuous field. Applied to
    the binary continental indicator it yields a continentality value that ramps
    smoothly across the crust margin.
    """
    count = values.shape[0]
    neighbour_sum = np.zeros(count, dtype=np.float64)
    neighbour_n = np.zeros(count, dtype=np.float64)
    np.add.at(neighbour_n, edges[:, 0], 1.0)
    np.add.at(neighbour_n, edges[:, 1], 1.0)
    current = values.astype(np.float64).copy()
    for _ in range(passes):
        neighbour_sum[:] = 0.0
        np.add.at(neighbour_sum, edges[:, 0], current[edges[:, 1]])
        np.add.at(neighbour_sum, edges[:, 1], current[edges[:, 0]])
        current = (current + neighbour_sum) / (1.0 + neighbour_n)
    return current


def sphere_noise(points, rng, components, frequency_min, frequency_max,
                 amplitude):
    """Return a seamless fractal scalar field sampled at ``points``.

    The field is a sum of plane waves with random directions, frequencies and
    phases. Because each wave is a smooth function of position on the sphere,
    the result is continuous everywhere including across the antimeridian and
    at the poles, unlike grid-based noise.
    """
    total = np.zeros(points.shape[0], dtype=np.float64)
    directions = rng.normal(size=(components, 3))
    directions /= np.linalg.norm(directions, axis=1, keepdims=True)
    frequencies = rng.uniform(frequency_min, frequency_max, size=components)
    phases = rng.uniform(0.0, 2.0 * np.pi, size=components)
    weights = rng.uniform(0.4, 1.0, size=components) / frequencies
    for component in range(components):
        projection = points @ directions[component]
        total += weights[component] * np.sin(
            frequencies[component] * projection + phases[component])
    total /= np.max(np.abs(total)) + 1e-12
    return amplitude * total
