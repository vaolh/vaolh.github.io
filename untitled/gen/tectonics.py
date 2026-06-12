#################################################
############### TECTONIC MODEL ##################
#################################################

import numpy as np
from scipy.spatial import cKDTree

import config as cfg
from geometry import (angular_distance, lonlat_to_xyz, sphere_noise,
                      smooth_field)

### REPLICATION FILE: tectonics.py
### PYTHON VERSION:   3.13+
### LAST EDIT:        2026-06-11 by vao2116

"""The tectonic plate simulation that shapes the supercontinent.

The model tessellates the sphere into rigid plates, assigns each an Euler-pole
rotation, classifies every plate boundary as convergent, divergent or
transform from the relative plate motions, and converts that forcing into an
elevation field. Continental crust is clustered toward a chosen pole so that
emergent land coalesces into a single supercontinent, after which sea level is
chosen and detached fragments below an island threshold are flooded.
"""

### Boundary regime codes shared with the elevation and vectorisation stages.
regime_collision = 0
regime_subduction = 1
regime_arc = 2
regime_ridge = 3
regime_rift = 4
regime_transform = 5

### Human-readable regime names used in the emitted geojson properties.
regime_names = {
    regime_collision: "collision",
    regime_subduction: "subduction",
    regime_arc: "island_arc",
    regime_ridge: "ridge",
    regime_rift: "rift",
    regime_transform: "transform",
}


def plate_adjacency(plate_id, edges):
    """Return, for each plate, the set of plates sharing a boundary with it."""
    first = plate_id[edges[:, 0]]
    second = plate_id[edges[:, 1]]
    crossing = first != second
    adjacency = {plate: set() for plate in range(cfg.plate_count)}
    for left, right in zip(first[crossing], second[crossing]):
        adjacency[int(left)].add(int(right))
        adjacency[int(right)].add(int(left))
    return adjacency


def assign_plates(points, edges, rng):
    """Tessellate the sphere into plates and label continental crust.

    Plate seeds are drawn uniformly and every cell is assigned to its nearest
    seed, giving a spherical Voronoi tessellation. Continental crust is then
    grown outward from the plate at the supercontinent centre, repeatedly
    annexing whichever neighbouring plate sits closest to that centre, until the
    continental area fraction is met. Because the continental plates are
    mutually adjacent the crust forms one contiguous block, which is what makes
    the emergent land a single supercontinent rather than scattered continents.
    """
    seed_indices = rng.choice(points.shape[0], size=cfg.plate_count,
                              replace=False)
    seeds = points[seed_indices]
    seed_tree = cKDTree(seeds)
    _, plate_id = seed_tree.query(points, workers=-1)

    center = lonlat_to_xyz(cfg.supercontinent_center_lon,
                           cfg.supercontinent_center_lat)[0]
    seed_to_center = angular_distance(seeds, center)
    adjacency = plate_adjacency(plate_id, edges)

    cells_per_plate = np.bincount(plate_id, minlength=cfg.plate_count)
    target_continental_cells = cfg.continental_area_fraction * points.shape[0]
    continental = np.zeros(cfg.plate_count, dtype=bool)

    nucleus = int(np.argmin(seed_to_center))
    continental[nucleus] = True
    accumulated = cells_per_plate[nucleus]
    frontier = set(adjacency[nucleus])
    while accumulated < target_continental_cells and frontier:
        candidate = min(frontier, key=lambda plate: seed_to_center[plate])
        continental[candidate] = True
        accumulated += cells_per_plate[candidate]
        frontier.discard(candidate)
        frontier.update(p for p in adjacency[candidate] if not continental[p])

    return plate_id, seeds, continental


def plate_velocities(points, plate_id, rng):
    """Return the surface velocity of every cell from per-plate Euler rotation.

    Each plate rotates about a random Euler pole at a random angular speed. A
    cell's velocity is the cross product of its plate's rotation vector with the
    cell position, the standard rigid-rotation velocity on a sphere.
    """
    axes = rng.normal(size=(cfg.plate_count, 3))
    axes /= np.linalg.norm(axes, axis=1, keepdims=True)
    speeds = rng.uniform(cfg.plate_speed_min, cfg.plate_speed_max,
                         size=cfg.plate_count)
    rotation = axes * speeds[:, None]
    return np.cross(rotation[plate_id], points)


def classify_boundaries(points, edges, plate_id, continental, velocity):
    """Classify every inter-plate edge and return its midpoint and regime.

    For each edge that separates two plates the relative velocity is projected
    onto the edge direction to measure convergence. The sign of that projection
    and the crust types of the two plates determine whether the boundary builds
    mountains, subducts, spreads as a ridge, rifts or simply shears.
    """
    crossing = plate_id[edges[:, 0]] != plate_id[edges[:, 1]]
    pairs = edges[crossing]
    first, second = pairs[:, 0], pairs[:, 1]

    direction = points[second] - points[first]
    direction /= np.linalg.norm(direction, axis=1, keepdims=True) + 1e-12
    relative = velocity[first] - velocity[second]
    convergence = np.einsum("ij,ij->i", relative, direction)
    speed = np.linalg.norm(relative, axis=1) + 1e-12

    cont_first = continental[plate_id[first]]
    cont_second = continental[plate_id[second]]
    both_continental = cont_first & cont_second
    both_oceanic = (~cont_first) & (~cont_second)

    regime = np.full(pairs.shape[0], regime_transform, dtype=np.int64)
    is_transform = np.abs(convergence) < cfg.transform_convergence_ratio * speed
    converging = (convergence > 0) & ~is_transform
    diverging = (convergence < 0) & ~is_transform

    regime[converging & both_continental] = regime_collision
    regime[converging & both_oceanic] = regime_arc
    regime[converging & ~both_continental & ~both_oceanic] = regime_subduction
    regime[diverging & both_oceanic] = regime_ridge
    regime[diverging & ~both_oceanic] = regime_rift

    midpoint = points[first] + points[second]
    midpoint /= np.linalg.norm(midpoint, axis=1, keepdims=True)

    return midpoint, regime, np.abs(convergence)


def boundary_stress(regime, magnitude, receiving_continental):
    """Return the elevation response a boundary imparts to a receiving cell.

    The subduction response is asymmetric: the overriding continental side is
    lifted into a coastal range while the descending oceanic side is pulled down
    into a trench, so the coefficient depends on the crust receiving the stress.
    """
    if regime == regime_collision:
        return cfg.uplift_continental_collision * magnitude
    if regime == regime_subduction:
        if receiving_continental:
            return cfg.uplift_oceanic_subduction * magnitude
        return -cfg.trench_depression * magnitude
    if regime == regime_arc:
        return cfg.uplift_island_arc * magnitude
    if regime == regime_ridge:
        return cfg.ridge_elevation * magnitude
    if regime == regime_rift:
        return -cfg.rift_depression * magnitude
    return 0.0


def accumulate_tectonic_elevation(points, continental_cell, boundary_xyz,
                                  regime, magnitude):
    """Spread boundary stress inland with geodesic exponential decay.

    Each cell sums the contribution of every boundary within the search radius,
    weighted by distance through an exponential kernel. This yields broad
    mountain belts behind collision zones and deep basins along rifts rather
    than knife-edge ridges.
    """
    boundary_tree = cKDTree(boundary_xyz)
    chord_radius = 2.0 * np.sin(cfg.boundary_search_radius / 2.0)
    neighbours = boundary_tree.query_ball_point(points, r=chord_radius,
                                                workers=-1)
    elevation = np.zeros(points.shape[0], dtype=np.float64)
    for cell, found in enumerate(neighbours):
        if not found:
            continue
        found = np.asarray(found)
        chord = np.linalg.norm(boundary_xyz[found] - points[cell], axis=1)
        geodesic = 2.0 * np.arcsin(np.clip(chord / 2.0, 0.0, 1.0))
        weight = np.exp(-geodesic / cfg.boundary_decay_length)
        cont = continental_cell[cell]
        contribution = 0.0
        for local, boundary in enumerate(found):
            contribution += weight[local] * boundary_stress(
                regime[boundary], magnitude[boundary], cont)
        elevation[cell] = contribution
    return elevation


def normalize_tectonic(tectonic):
    """Rescale the accumulated tectonic field to configured relief extremes.

    The raw summation scales with mesh density and boundary length, so it is
    renormalised: positive uplift and negative trench depth are each mapped so
    that their high percentile matches the configured maximum. This keeps
    mountains a rare top fraction of the surface regardless of resolution while
    preserving the relative strength of collision, subduction and rift zones.
    """
    scaled = tectonic.copy()
    positive = tectonic[tectonic > 0]
    if positive.size:
        reference = np.percentile(positive, cfg.tectonic_scale_percentile)
        if reference > 0:
            scaled[tectonic > 0] *= cfg.tectonic_max_uplift / reference
    negative = -tectonic[tectonic < 0]
    if negative.size:
        reference = np.percentile(negative, cfg.tectonic_scale_percentile)
        if reference > 0:
            scaled[tectonic < 0] *= cfg.tectonic_max_trench / reference
    return scaled


def connected_components(point_count, edges, is_land):
    """Label connected land components via union-find over the mesh edges."""
    parent = np.arange(point_count)

    def find(node):
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    land_edges = edges[is_land[edges[:, 0]] & is_land[edges[:, 1]]]
    for first, second in land_edges:
        root_first, root_second = find(first), find(second)
        if root_first != root_second:
            parent[root_first] = root_second

    labels = np.full(point_count, -1, dtype=np.int64)
    for node in np.where(is_land)[0]:
        labels[node] = find(node)
    return labels


def enforce_supercontinent(point_count, edges, is_land):
    """Keep one supercontinent plus only small offshore islands.

    The largest land component is the supercontinent. Secondary components are
    kept only if they are small enough to read as islands; anything larger but
    short of the main mass is flooded, so a seed that would otherwise split into
    rival continents still yields a single supercontinent.
    """
    labels = connected_components(point_count, edges, is_land)
    land_labels = labels[labels >= 0]
    if land_labels.size == 0:
        return is_land
    unique, counts = np.unique(land_labels, return_counts=True)
    largest_label = unique[np.argmax(counts)]
    largest = counts.max()
    keep = set(unique[counts <= cfg.island_max_relative_size * largest])
    keep.add(largest_label)
    return np.array([label in keep for label in labels])


def simulate(points, edges, rng):
    """Run the full tectonic pipeline and return the world state.

    The returned dictionary carries the per-cell plate, elevation and land
    fields together with the classified boundary geometry, which downstream
    stages vectorise into coastline, country and plate-boundary geojson.
    """
    plate_id, seeds, continental = assign_plates(points, edges, rng)
    velocity = plate_velocities(points, plate_id, rng)
    boundary_xyz, regime, magnitude = classify_boundaries(
        points, edges, plate_id, continental, velocity)

    continental_cell = continental[plate_id]
    continentality = smooth_field(continental_cell.astype(np.float64), edges,
                                  cfg.continentality_smoothing_passes)
    plateau = (cfg.oceanic_base_elevation
               + (cfg.continental_base_elevation - cfg.oceanic_base_elevation)
               * continentality)

    center = lonlat_to_xyz(cfg.supercontinent_center_lon,
                           cfg.supercontinent_center_lat)[0]
    distance_to_center = angular_distance(points, center)
    width = np.radians(cfg.supercontinent_bias_width)
    bias = cfg.supercontinent_bias_amplitude * np.exp(
        -(distance_to_center / width) ** 2)

    tectonic = normalize_tectonic(accumulate_tectonic_elevation(
        points, continental_cell, boundary_xyz, regime, magnitude))
    noise = sphere_noise(points, rng, cfg.noise_components,
                         cfg.noise_frequency_min, cfg.noise_frequency_max,
                         cfg.noise_amplitude)

    elevation = plateau + bias + tectonic + noise

    sea_level = cfg.sea_level
    is_land = enforce_supercontinent(points.shape[0], edges,
                                     elevation > sea_level)

    return {
        "points": points,
        "plate_id": plate_id,
        "plate_seeds": seeds,
        "plate_continental": continental,
        "elevation": elevation,
        "sea_level": sea_level,
        "is_land": is_land,
        "boundary_xyz": boundary_xyz,
        "boundary_regime": regime,
        "boundary_magnitude": magnitude,
    }
