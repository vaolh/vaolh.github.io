#################################################
############### WORLD BUILDER ###################
#################################################

import argparse
import json

import numpy as np
from scipy import ndimage
from scipy.spatial import cKDTree
from shapely.geometry import mapping

import config as cfg
from geometry import (fibonacci_sphere, build_adjacency, lonlat_to_xyz,
                      xyz_to_lonlat, angular_distance, rodrigues)
from tectonics import simulate
from vectorize import build_grid, mask_to_multipolygon, rasterize_continents

### REPLICATION FILE: generate.py
### PYTHON VERSION:   3.13+
### LAST EDIT:        2026-06-14 by vao2116

"""Command-line entry point that builds one world across its geological eras.

A dispersed world of fractal continents is generated first; islands are merged
into the nearest continent and each continent is assigned an Euler axis toward
the assembly centre. The eras are then produced by rotating the continents
together by increasing angles, so the earth-like era is the generated fractal
world and the supercontinent era is its reconstruction. A different seed yields a
different world, which is how a preferred one is chosen.
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
    """Generate the fractal world and assemble its three geological eras.

    Continents are separated on the raster grid, where narrow seas truly divide
    them, rather than on the mesh graph which bridges them. Islands are merged
    into the nearest continent, and each continent is rotated toward the assembly
    centre by the per-era angle. The earth-like era is the world as generated and
    the supercontinent era is the continents packed back together.
    """
    rng = np.random.default_rng(seed)

    points = fibonacci_sphere(cfg.mesh_cells)
    edges = build_adjacency(points, cfg.mesh_neighbours)
    world = simulate(points, edges, rng)
    is_land = world["is_land"]

    lon, lat, grid_xyz = build_grid()
    row_weight = np.cos(np.radians(lat))[:, None]
    chord = 2.0 * np.sin(cfg.drift_land_threshold / 2.0)

    ### Separate landmasses on the grid by true sea connectivity.
    tree = cKDTree(points)
    _, nearest = tree.query(grid_xyz, workers=-1)
    land_grid = is_land[nearest].reshape(cfg.grid_height, cfg.grid_width)
    grid_labels, count = ndimage.label(land_grid)
    indices = np.arange(1, count + 1)
    weighted = ndimage.sum(np.broadcast_to(row_weight, land_grid.shape),
                           grid_labels, index=indices)
    shares = weighted / weighted.sum()
    grid_xyz_image = grid_xyz.reshape(cfg.grid_height, cfg.grid_width, 3)

    def centroid(label):
        vector = grid_xyz_image[grid_labels == label].mean(axis=0)
        return vector / np.linalg.norm(vector)

    kept = [int(label) for label, share in zip(indices, shares)
            if share >= cfg.landmass_min_land_share]
    continents = sorted(
        [int(label) for label, share in zip(indices, shares)
         if share >= cfg.continent_min_land_share],
        key=lambda label: -shares[label - 1])
    centroids = {label: centroid(label) for label in continents}

    ### Islands merge into the nearest continent so they are not listed alone.
    component_continent = {}
    for label in kept:
        if label in centroids:
            component_continent[label] = label
        else:
            here = centroid(label)
            component_continent[label] = min(
                continents,
                key=lambda c: angular_distance(centroids[c][None], here)[0])
    continent_number = {label: index for index, label in enumerate(continents)}

    ### Each continent gets an Euler axis toward the assembly centre and an ice
    ### flag when polar.
    assembly = lonlat_to_xyz(cfg.assembly_center_lon, cfg.assembly_center_lat)[0]
    continent_info = {}
    for label in continents:
        here = centroids[label]
        axis = np.cross(here, assembly)
        norm = np.linalg.norm(axis)
        rows = np.where(np.any(grid_labels == label, axis=1))[0]
        reaches = float(np.max(np.abs(lat[rows]))) if rows.size else 0.0
        index = continent_number[label]
        continent_info[label] = {
            "axis": axis / norm if norm > 1e-6 else np.zeros(3),
            "polar": bool(reaches > cfg.ice_continent_lat),
            "name": "",
            "slug": f"landmass-{index + 1}",
        }

    ### Tag each mesh land cell with the continent of its grid cell.
    mesh_lonlat = xyz_to_lonlat(points)
    mesh_col = np.clip(((mesh_lonlat[:, 0] + 180.0) / 360.0
                        * (cfg.grid_width - 1)).round().astype(int),
                       0, cfg.grid_width - 1)
    mesh_row = np.clip(((mesh_lonlat[:, 1] + 90.0) / 180.0
                        * (cfg.grid_height - 1)).round().astype(int),
                       0, cfg.grid_height - 1)
    mesh_label = grid_labels[mesh_row, mesh_col]
    in_continent = np.isin(mesh_label, list(component_continent.keys()))
    land_cells = np.where(is_land & in_continent)[0]
    land_xyz = points[land_cells]
    land_component = [component_continent[int(mesh_label[cell])]
                      for cell in land_cells]
    land_index = np.array([continent_number[label]
                           for label in land_component])
    land_axis = np.array([continent_info[label]["axis"]
                          for label in land_component])
    land_elevation = world["elevation"][land_cells]

    view_lonlat = xyz_to_lonlat(centroids[continents[0]][None])[0]

    cfg.data_dir.mkdir(parents=True, exist_ok=True)

    eras = []
    articles = {}
    final_landmasses = []
    for era_index, (era_name, angle) in enumerate(
            zip(cfg.era_names, cfg.era_assembly_radians)):
        moved = rodrigues(land_xyz, land_axis, angle)
        painted = rasterize_continents(moved, land_elevation, land_index,
                                       world["sea_level"], grid_xyz, chord)

        features = []
        landmasses = []
        for label in continents:
            info = continent_info[label]
            mask = painted == continent_number[label]
            if not mask.any():
                continue
            geometry = mask_to_multipolygon(mask)
            if geometry is None:
                continue
            properties = {"name": info["name"], "slug": info["slug"],
                          "polar": info["polar"]}
            features.append(_feature(geometry, properties))
            landmasses.append({**properties,
                               "land_fraction": _area_fraction(mask,
                                                               row_weight)})

        filename = f"land_era{era_index + 1}.geojson"
        _write_collection(cfg.data_dir / filename, features)
        eras.append({"name": era_name, "file": filename,
                     "count": len(features)})
        for landmass in landmasses:
            articles[landmass["slug"]] = landmass
        if era_index == len(cfg.era_names) - 1:
            final_landmasses = landmasses

    meta = {
        "world_name": cfg.world_display_name,
        "seed": int(seed),
        "mesh_cells": cfg.mesh_cells,
        "continent_count": len(continents),
        "center_lon": float(view_lonlat[0]),
        "center_lat": float(view_lonlat[1]),
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
