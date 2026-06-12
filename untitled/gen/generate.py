#################################################
############### WORLD BUILDER ###################
#################################################

import argparse
import json

import numpy as np
from scipy.spatial import cKDTree
from shapely.geometry import mapping

import config as cfg
from geometry import fibonacci_sphere, build_adjacency
from tectonics import simulate
from names import generate_world_name
from vectorize import (build_grid, rasterize_idw, mask_to_multipolygon,
                       keep_supercontinent)

### REPLICATION FILE: generate.py
### PYTHON VERSION:   3.13+
### LAST EDIT:        2026-06-11 by vao2116

"""Command-line entry point that builds one supercontinent world.

Running this module with a seed produces the full set of geojson layers and a
metadata file consumed by the map viewer and the wiki. Re-running with a
different seed yields a different but equally plausible supercontinent, which is
how a preferred world is chosen.
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


def build_world(seed):
    """Generate the supercontinent landmass geojson and metadata for a seed.

    Only the single landmass is emitted for now. The full plate simulation still
    runs underneath, so its boundaries and relief are available for the later
    geological eras, but the present map shows one clickable supercontinent.
    """
    rng = np.random.default_rng(seed)

    points = fibonacci_sphere(cfg.mesh_cells)
    edges = build_adjacency(points, cfg.mesh_neighbours)
    world = simulate(points, edges, rng)
    world_name = generate_world_name(rng)

    tree = cKDTree(points)
    lon, lat, grid_xyz = build_grid()
    elevation_grid = rasterize_idw(tree, world["elevation"], grid_xyz)
    land_grid = keep_supercontinent(elevation_grid > world["sea_level"])

    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    land_geometry = mask_to_multipolygon(land_grid)
    _write_collection(cfg.data_dir / "land.geojson", [_feature(
        land_geometry,
        {"name": cfg.supercontinent_name, "slug": cfg.supercontinent_slug})])

    ### Report the area-weighted land share of the displayed continent, since
    ### the equirectangular grid over-represents the poles.
    row_weight = np.cos(np.radians(lat))[:, None]
    land_fraction = float((land_grid * row_weight).sum()
                          / (row_weight.sum() * cfg.grid_width))
    meta = {
        "world_name": world_name,
        "era": "supercontinent",
        "supercontinent_name": cfg.supercontinent_name,
        "supercontinent_slug": cfg.supercontinent_slug,
        "seed": int(seed),
        "mesh_cells": cfg.mesh_cells,
        "plate_count": cfg.plate_count,
        "land_fraction": land_fraction,
        "highest_elevation": float(np.max(world["elevation"])),
        "center_lon": cfg.supercontinent_center_lon,
        "center_lat": cfg.supercontinent_center_lat,
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
    print(f"supercontinent land fraction {meta['land_fraction']:.3f}")
    print(f"geojson written to {cfg.data_dir}")


if __name__ == "__main__":
    main()
