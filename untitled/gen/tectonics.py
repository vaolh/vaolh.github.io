#################################################
############### TECTONIC MODEL ##################
#################################################

import numpy as np
from scipy.spatial import cKDTree

import config as cfg
from geometry import (angular_distance, lonlat_to_xyz, domain_warp, rodrigues,
                      fault_displacement)

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


def _grow_region(continental, adjacency, cells_per_plate, seed_to_center,
                 target):
    """Grow a contiguous continental block from its nearest free plate.

    Starting at the unclaimed plate closest to a craton centre, neighbouring
    plates are annexed in order of proximity to that centre until the block
    reaches its target area, keeping each continent compact and contiguous.
    """
    free = [plate for plate in np.argsort(seed_to_center)
            if not continental[plate]]
    if not free:
        return
    nucleus = free[0]
    continental[nucleus] = True
    accumulated = cells_per_plate[nucleus]
    frontier = {p for p in adjacency[nucleus] if not continental[p]}
    while accumulated < target and frontier:
        candidate = min(frontier, key=lambda plate: seed_to_center[plate])
        continental[candidate] = True
        accumulated += cells_per_plate[candidate]
        frontier.discard(candidate)
        frontier.update(p for p in adjacency[candidate] if not continental[p])


def _craton_centers(rng):
    """Return spread-out craton centres within the seeding bounds.

    Centres are rejection-sampled so that every pair is at least the minimum
    separation apart, which keeps the resulting continents distinct rather than
    fused into one landmass.
    """
    separation = np.radians(cfg.craton_min_separation)
    centers = []
    attempts = 0
    while len(centers) < cfg.continent_count and attempts < 2000:
        attempts += 1
        candidate = lonlat_to_xyz(
            rng.uniform(cfg.craton_lon_min, cfg.craton_lon_max),
            rng.uniform(cfg.craton_lat_min, cfg.craton_lat_max))[0]
        if all(angular_distance(np.array([existing]), candidate)[0] > separation
               for existing in centers):
            centers.append(candidate)
    return np.array(centers)


def assign_plates(points, edges, rng):
    """Tessellate the sphere into plates and label continental crust.

    Plate seeds are drawn uniformly and every cell is assigned to its nearest
    seed, giving a spherical Voronoi tessellation. In supercontinent mode the
    continental crust is grown as one block at the supercontinent centre; in
    continents mode it is grown as several blocks of varied size around scattered
    craton centres, producing distinct Earth-like continents.
    """
    seed_indices = rng.choice(points.shape[0], size=cfg.plate_count,
                              replace=False)
    seeds = points[seed_indices]
    seed_tree = cKDTree(seeds)
    warped = domain_warp(points, rng, cfg.boundary_warp_amplitude,
                         cfg.boundary_warp_components,
                         cfg.boundary_warp_frequency_min,
                         cfg.boundary_warp_frequency_max)
    _, plate_id = seed_tree.query(warped, workers=-1)

    adjacency = plate_adjacency(plate_id, edges)
    cells_per_plate = np.bincount(plate_id, minlength=cfg.plate_count)
    total_target = cfg.continental_area_fraction * points.shape[0]
    continental = np.zeros(cfg.plate_count, dtype=bool)

    if cfg.world_mode == "continents":
        centers = _craton_centers(rng)
        weights = rng.uniform(cfg.continent_size_min, cfg.continent_size_max,
                              size=centers.shape[0])
        targets = weights / weights.sum() * total_target
        for center, target in zip(centers, targets):
            _grow_region(continental, adjacency, cells_per_plate,
                         angular_distance(seeds, center), target)
    else:
        center = lonlat_to_xyz(cfg.supercontinent_center_lon,
                               cfg.supercontinent_center_lat)[0]
        _grow_region(continental, adjacency, cells_per_plate,
                     angular_distance(seeds, center), total_target)

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


def drift_axes(points, plate_id, center):
    """Return each plate's Euler axis for drifting outward from the centre.

    Rotating a plate about the axis ``centre x centroid`` carries its centroid
    away from the supercontinent centre along their great circle, so applying it
    to every plate breaks the assembled landmass apart radially, the way Pangaea
    rifted into the modern continents.
    """
    axes = np.zeros((cfg.plate_count, 3))
    for plate in range(cfg.plate_count):
        cells = points[plate_id == plate]
        if cells.shape[0] == 0:
            continue
        centroid = cells.mean(axis=0)
        centroid /= np.linalg.norm(centroid) + 1e-12
        ### Freeze polar plates so the polar continent stays put across eras.
        latitude = np.degrees(np.arcsin(np.clip(centroid[2], -1.0, 1.0)))
        if latitude < cfg.polar_drift_cutoff_lat:
            continue
        axis = np.cross(center, centroid)
        norm = np.linalg.norm(axis)
        if norm > 1e-6:
            axes[plate] = axis / norm
    return axes


def drift_points(positions, plate, axes, angle):
    """Carry positions about their plate's drift axis by a given angle."""
    return rodrigues(positions, axes[plate], angle)


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


def enforce_landmasses(points, edges, is_land):
    """Keep the supercontinent, the polar continent and small islands.

    The largest component is the supercontinent and any small component is an
    offshore island; a component whose centroid lies far enough south is the
    guaranteed polar continent. Everything else, such as stray rival landmasses
    thrown up by the fractal field away from the centre, is flooded so the
    assembled era reads as one supercontinent plus a polar landmass.
    """
    labels = connected_components(points.shape[0], edges, is_land)
    land_labels = labels[labels >= 0]
    if land_labels.size == 0:
        return is_land
    unique, counts = np.unique(land_labels, return_counts=True)
    largest = counts.max()
    latitudes = np.degrees(np.arcsin(np.clip(points[:, 2], -1.0, 1.0)))
    keep = {unique[np.argmax(counts)]}

    ### Small components are offshore islands and archipelagos.
    for label, count in zip(unique, counts):
        if count <= cfg.island_max_relative_size * largest:
            keep.add(label)

    ### Keep only the single largest deep-southern component as the polar
    ### continent, flooding stray southern fault land that would clip flat.
    southern = [(count, label) for label, count in zip(unique, counts)
                if latitudes[labels == label].mean() < cfg.polar_drift_cutoff_lat]
    if southern:
        keep.add(max(southern)[1])

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

    ### Fractal fault terrain is the base; broad biases gather it into one
    ### supercontinent and guarantee a fractal landmass at the south pole.
    fractal = fault_displacement(points, rng, cfg.fault_count)

    center = lonlat_to_xyz(cfg.supercontinent_center_lon,
                           cfg.supercontinent_center_lat)[0]
    width = np.radians(cfg.supercontinent_bias_width)
    bias = cfg.supercontinent_bias_amplitude * np.exp(
        -(angular_distance(points, center) / width) ** 2)

    south = lonlat_to_xyz(cfg.polar_bias_center_lon,
                          cfg.polar_bias_center_lat)[0]
    polar_width = np.radians(cfg.polar_bias_width)
    polar_bias = cfg.polar_bias_amplitude * np.exp(
        -(angular_distance(points, south) / polar_width) ** 2)

    tectonic = normalize_tectonic(accumulate_tectonic_elevation(
        points, continental_cell, boundary_xyz, regime, magnitude))

    ### A ramp floods everything south of the Southern Ocean latitude, so the
    ### only deep-southern land is the polar continent poking through.
    cell_lat = np.degrees(np.arcsin(np.clip(points[:, 2], -1.0, 1.0)))
    southern_ocean = cfg.southern_ocean_amplitude * np.clip(
        (cfg.southern_ocean_center_lat - cell_lat) / cfg.southern_ocean_width,
        0.0, 1.0)

    elevation = (cfg.fault_weight * fractal + bias + polar_bias
                 - southern_ocean + tectonic)

    sea_level = np.quantile(elevation, 1.0 - cfg.target_land_fraction)
    is_land = enforce_landmasses(points, edges, elevation > sea_level)

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
