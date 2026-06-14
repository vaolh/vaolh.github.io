#################################################
############### WORLD BUILDER ###################
#################################################

import argparse
import json

import numpy as np
from scipy.spatial import cKDTree
from shapely.geometry import mapping

import config as cfg
from geometry import fibonacci_sphere, build_adjacency, lonlat_to_xyz
from tectonics import simulate, drift_axes, drift_points
from names import generate_world_name
from vectorize import build_grid, mask_to_multipolygon, label_landmasses

### REPLICATION FILE: generate.py
### PYTHON VERSION:   3.13+
### LAST EDIT:        2026-06-12 by vao2116

"""Command-line entry point that builds one world.

Running this module with a seed produces the land geojson and a metadata file
consumed by the map viewer and the wiki. In continents mode it emits several
named, separately clickable continents plus a polar cap; in supercontinent mode
it emits one landmass. A different seed yields a different but equally plausible
world, which is how a preferred world is chosen.
"""


def _feature(geometry, properties):
    """Wrap a shapely geometry and property dictionary as a geojson feature."""
    return {
        "type": "Feature",
        "properties": properties,
        "geometry": mapping(geometry),
    }


def _write_collection(path, features):
    """Write a list of features to disk as a geojson feature collection."""
    collection = {"type": "FeatureCollection", "features": features}
    path.write_text(json.dumps(collection))


def _area_fraction(mask, row_weight):
    """Return the area-weighted share of the globe covered by a grid mask."""
    return float((mask * row_weight).sum()
                 / (row_weight.sum() * cfg.grid_width))


def _name_landmass(era_index, rank, island_counter, continent_counter):
    """Return the placeholder name and slug for a landmass in an era.

    Names are deliberately generic numbered placeholders, since the continents
    are named by hand later. Era one's largest mass is the supercontinent.
    """
    if era_index == 0 and rank == 0:
        return cfg.supercontinent_name, cfg.supercontinent_slug
    if era_index == 0:
        island_counter[0] += 1
        return f"Island {island_counter[0]}", f"island-{island_counter[0]}"
    continent_counter[0] += 1
    return (f"Continent {continent_counter[0]}",
            f"continent-{continent_counter[0]}")


def _extract_era(era_index, angle, land_xyz, land_plate, axes, grid_xyz,
                 lon, lat, safe, row_weight):
    """Drift the land to one era and return its features and landmass metadata.

    Every land cell is carried about its plate's drift axis by the era angle,
    the drifted cloud is painted onto the grid wherever a cell falls within the
    drift threshold, and each connected landmass is traced into a polygon. Gaps
    that open between diverging fragments become ocean.
    """
    moved = drift_points(land_xyz, land_plate, axes, angle)
    tree = cKDTree(moved)
    chord = 2.0 * np.sin(cfg.drift_land_threshold / 2.0)
    distance, _ = tree.query(grid_xyz, workers=-1)
    mask = (distance < chord).reshape(cfg.grid_height, cfg.grid_width) & safe

    components = label_landmasses(mask)
    features = []
    landmasses = []
    if not components:
        return features, landmasses
    largest = components[0].sum()
    island_counter = [0]
    continent_counter = [0]
    rank = 0
    for component in components:
        if component.sum() < cfg.landmass_min_relative_size * largest:
            continue
        geometry = mask_to_multipolygon(component)
        if geometry is None:
            continue
        rows = np.where(component.any(axis=1))[0]
        centroid_lat = float(np.average(lat[rows],
                                        weights=row_weight[rows, 0]))
        polar = abs(centroid_lat) > cfg.ice_continent_lat
        name, slug = _name_landmass(era_index, rank, island_counter,
                                    continent_counter)
        features.append(_feature(geometry, {"name": name, "slug": slug,
                                            "polar": polar}))
        landmasses.append({"name": name, "slug": slug, "polar": polar,
                           "land_fraction": _area_fraction(component,
                                                           row_weight)})
        rank += 1
    return features, landmasses


def build_world(seed):
    """Generate the three drift eras of one world and their metadata.

    A single supercontinent is simulated, then its land cells are drifted
    outward by increasing angles to produce the supercontinent, early-rifting,
    and dispersed-continents eras. Because every continent is a fragment of the
    same supercontinent, their facing coastlines fit back together.
    """
    rng = np.random.default_rng(seed)

    points = fibonacci_sphere(cfg.mesh_cells)
    edges = build_adjacency(points, cfg.mesh_neighbours)
    world = simulate(points, edges, rng)
    world_name = generate_world_name(rng)

    center = lonlat_to_xyz(cfg.supercontinent_center_lon,
                           cfg.supercontinent_center_lat)[0]
    is_land = world["is_land"]
    land_xyz = points[is_land]
    land_plate = world["plate_id"][is_land]
    axes = drift_axes(points, world["plate_id"], center)

    lon, lat, grid_xyz = build_grid()
    row_weight = np.cos(np.radians(lat))[:, None]
    safe = ((np.abs(lat)[:, None] <= cfg.safe_lat_limit)
            & (np.abs(lon)[None, :] <= cfg.safe_lon_limit))

    cfg.data_dir.mkdir(parents=True, exist_ok=True)

    eras = []
    articles = {}
    final_landmasses = []
    for era_index, (name, angle) in enumerate(
            zip(cfg.era_names, cfg.era_drift_radians)):
        features, landmasses = _extract_era(
            era_index, angle, land_xyz, land_plate, axes, grid_xyz, lon, lat,
            safe, row_weight)
        filename = f"land_era{era_index + 1}.geojson"
        _write_collection(cfg.data_dir / filename, features)
        eras.append({"name": name, "file": filename, "count": len(features)})
        for landmass in landmasses:
            articles[landmass["slug"]] = landmass
        if era_index == len(cfg.era_names) - 1:
            final_landmasses = landmasses

    meta = {
        "world_name": world_name,
        "seed": int(seed),
        "mesh_cells": cfg.mesh_cells,
        "plate_count": cfg.plate_count,
        "center_lon": cfg.supercontinent_center_lon,
        "center_lat": cfg.supercontinent_center_lat,
        "eras": eras,
        "landmasses": final_landmasses,
        "articles": list(articles.values()),
    }
    (cfg.data_dir / "meta.json").write_text(json.dumps(meta, indent=2))
    return meta


def main():
    """Parse arguments and build the world for the requested seed."""
    parser = argparse.ArgumentParser(
        description="Generate a supercontinent world.")
    parser.add_argument("--seed", type=int, default=cfg.default_seed,
                        help="master random seed for the world")
    arguments = parser.parse_args()

    meta = build_world(arguments.seed)
    print(f"world '{meta['world_name']}' built from seed {meta['seed']}")
    for era in meta["eras"]:
        print(f"  {era['name']}: {era['count']} landmasses ({era['file']})")
    print(f"geojson written to {cfg.data_dir}")


if __name__ == "__main__":
    main()
