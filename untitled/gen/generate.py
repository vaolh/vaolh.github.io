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
from names import generate_world_name, generate_names
from vectorize import (build_grid, rasterize_idw, mask_to_multipolygon,
                       keep_landmasses, label_landmasses, build_polar_cap)

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


def build_world(seed):
    """Generate the land geojson and metadata for a seed.

    The full plate simulation runs first; its land field is rasterised, split
    into landmasses, and each surviving continent is vectorised as a separately
    named feature. In continents mode a wavy polar cap is appended as Antarctica.
    """
    rng = np.random.default_rng(seed)

    points = fibonacci_sphere(cfg.mesh_cells)
    edges = build_adjacency(points, cfg.mesh_neighbours)
    world = simulate(points, edges, rng)
    world_name = generate_world_name(rng)

    tree = cKDTree(points)
    lon, lat, grid_xyz = build_grid()
    elevation_grid = rasterize_idw(tree, world["elevation"], grid_xyz)
    land_grid = keep_landmasses(elevation_grid > world["sea_level"])
    row_weight = np.cos(np.radians(lat))[:, None]

    cfg.data_dir.mkdir(parents=True, exist_ok=True)

    features = []
    landmasses = []
    if cfg.world_mode == "continents":
        masks = label_landmasses(land_grid)
        names = generate_names(len(masks), rng)
        for mask, (name, slug) in zip(masks, names):
            geometry = mask_to_multipolygon(mask)
            if geometry is None:
                continue
            fraction = _area_fraction(mask, row_weight)
            features.append(_feature(geometry, {"name": name, "slug": slug}))
            landmasses.append({"name": name, "slug": slug,
                               "land_fraction": fraction})
        if cfg.include_antarctica:
            cap = build_polar_cap(rng)
            features.append(_feature(cap, {"name": cfg.antarctica_name,
                                           "slug": cfg.antarctica_slug}))
            polar = (np.sin(np.radians(cfg.antarctica_coast_lat)) + 1.0) / 2.0
            landmasses.append({"name": cfg.antarctica_name,
                               "slug": cfg.antarctica_slug,
                               "land_fraction": float(polar)})
    else:
        geometry = mask_to_multipolygon(land_grid)
        features.append(_feature(geometry, {"name": cfg.supercontinent_name,
                                            "slug": cfg.supercontinent_slug}))
        landmasses.append({"name": cfg.supercontinent_name,
                           "slug": cfg.supercontinent_slug,
                           "land_fraction": _area_fraction(land_grid,
                                                           row_weight)})

    _write_collection(cfg.data_dir / "land.geojson", features)

    meta = {
        "world_name": world_name,
        "era": cfg.world_mode,
        "seed": int(seed),
        "mesh_cells": cfg.mesh_cells,
        "plate_count": cfg.plate_count,
        "land_fraction": sum(m["land_fraction"] for m in landmasses),
        "highest_elevation": float(np.max(world["elevation"])),
        "center_lon": cfg.supercontinent_center_lon,
        "center_lat": cfg.supercontinent_center_lat,
        "landmasses": landmasses,
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
    print(f"{len(meta['landmasses'])} landmasses, "
          f"land fraction {meta['land_fraction']:.3f}")
    print(f"geojson written to {cfg.data_dir}")


if __name__ == "__main__":
    main()
