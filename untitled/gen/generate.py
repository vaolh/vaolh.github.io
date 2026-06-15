#################################################
############### WORLD BUILDER ###################
#################################################

import argparse
import json

import numpy as np
from scipy import ndimage
from scipy.spatial import cKDTree
from shapely.geometry import box, mapping
from shapely.ops import unary_union

import config as cfg
from geometry import (fibonacci_sphere, lonlat_to_xyz,
                      xyz_to_lonlat, angular_distance, rodrigues)
from tectonics import simulate
from vectorize import (build_grid, mask_to_multipolygon, rasterize_continents,
                       rasterize_idw)

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


def _round_coords(value):
    """Recursively round coordinate floats to the configured precision."""
    if isinstance(value, (list, tuple)):
        return [_round_coords(item) for item in value]
    return round(value, cfg.coordinate_decimals)


def _feature(geometry, properties):
    """Wrap a shapely geometry and property dictionary as a geojson feature."""
    shape = mapping(geometry)
    shape["coordinates"] = _round_coords(shape["coordinates"])
    return {
        "type": "Feature",
        "properties": properties,
        "geometry": shape,
    }


def _write_collection(path, features):
    """Write a list of features to disk as a geojson feature collection."""
    collection = {"type": "FeatureCollection", "features": features}
    path.write_text(json.dumps(collection))


def _area_fraction(mask, row_weight):
    """Return the area-weighted share of the globe covered by a grid mask."""
    return float((mask * row_weight).sum()
                 / (row_weight.sum() * cfg.grid_width))


def _ice_bands(land_geoms):
    """Return ice overlay features: the land clipped into latitude bands.

    The combined land is intersected with successive latitude strips in both
    hemispheres; each strip carries an ``ice`` opacity that ramps from zero at
    ``ice_edge_lat`` to one at ``ice_full_lat``. Rendered white over the green
    land, the disjoint strips read as a polar ice cap that fades toward the
    temperate latitudes instead of whitening a whole continent.
    """
    if not land_geoms:
        return []
    land = unary_union(land_geoms)
    edges = np.arange(cfg.ice_edge_lat, cfg.max_land_lat + cfg.ice_band_step,
                      cfg.ice_band_step)
    span = max(cfg.ice_full_lat - cfg.ice_edge_lat, 1e-6)
    features = []
    for low, high in zip(edges[:-1], edges[1:]):
        iciness = float(np.clip(((low + high) / 2.0 - cfg.ice_edge_lat) / span,
                                0.0, 1.0))
        if iciness <= 0.0:
            continue
        strips = [land.intersection(box(-180.0, low, 180.0, high)),
                  land.intersection(box(-180.0, -high, 180.0, -low))]
        band = unary_union([strip for strip in strips if not strip.is_empty])
        if band.is_empty:
            continue
        features.append(_feature(band, {"ice": round(iciness, 3)}))
    return features


def build_world(seed, write=True):
    """Generate the fractal world and assemble its three geological eras.

    Continents are separated on the raster grid, where narrow seas truly divide
    them, rather than on the mesh graph which bridges them. Islands are merged
    into the nearest continent, and each continent is rotated toward the assembly
    centre by the per-era angle. The earth-like era is the world as generated and
    the supercontinent era is the continents packed back together.
    """
    rng = np.random.default_rng(seed)

    ### The fault-fractal simulation depends only on the cell positions, so the
    ### k-nearest-neighbour mesh graph is not built — it was pure overhead at this
    ### cell count.
    points = fibonacci_sphere(cfg.mesh_cells)
    world = simulate(points, None, rng)
    is_land = world["is_land"]

    lon, lat, grid_xyz = build_grid()
    row_weight = np.cos(np.radians(lat))[:, None]
    chord = 2.0 * np.sin(cfg.drift_land_threshold / 2.0)

    ### Separate landmasses on the grid by true sea connectivity. The land mask
    ### comes from the elevation field interpolated onto the grid and thresholded
    ### at sea level, NOT from each grid cell snapping to its nearest mesh cell:
    ### nearest-cell snapping makes the coastline the blocky Voronoi-cell edge,
    ### which reads as stair-step faceting when zoomed in. Inverse-distance
    ### interpolation over the dense mesh yields a smooth sub-cell contour that
    ### still follows the fine fault detail.
    tree = cKDTree(points)
    elevation_grid = rasterize_idw(tree, world["elevation"], grid_xyz)
    land_grid = elevation_grid > world["sea_level"]
    ### Drop land within a few degrees of either pole so no polygon reaches the
    ### singularity and tears open on the globe.
    land_grid[np.abs(lat) > cfg.max_land_lat, :] = False
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
    ### flag when polar. Polar is judged by the continent's CENTROID latitude,
    ### its centre of mass, not the furthest latitude it reaches: a continent
    ### centred on the equator that merely sends a cape past the ice latitude is
    ### temperate land, not an ice cap, and must render green.
    assembly = lonlat_to_xyz(cfg.assembly_center_lon, cfg.assembly_center_lat)[0]
    continent_info = {}
    for label in continents:
        here = centroids[label]
        axis = np.cross(here, assembly)
        norm = np.linalg.norm(axis)
        centroid_lat = np.degrees(np.arcsin(np.clip(here[2], -1.0, 1.0)))
        index = continent_number[label]
        continent_info[label] = {
            "axis": axis / norm if norm > 1e-6 else np.zeros(3),
            "polar": bool(abs(centroid_lat) > cfg.ice_continent_lat),
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

    ### Open the globe on the largest non-polar continent so the default view
    ### lands on green land rather than a white polar ice cap at the pole.
    view_label = next((label for label in continents
                       if not continent_info[label]["polar"]), continents[0])
    view_lonlat = xyz_to_lonlat(centroids[view_label][None])[0]

    ### Build a direct label→continent-index lookup over the full grid.
    ### This is pixel-for-pixel identical to the preview: every grid cell maps
    ### to its nearest mesh cell with no gap threshold, no IDW blending, and no
    ### island filtering — the exact same raster the preview PNG renders from.
    max_label = int(grid_labels.max()) if grid_labels.max() >= 0 else 0
    label_to_index = np.full(max_label + 1, -1, dtype=np.int64)
    for grid_label, cont_label in component_continent.items():
        label_to_index[grid_label] = continent_number[cont_label]
    painted_base = label_to_index[
        np.clip(grid_labels, 0, max_label)]
    painted_base[grid_labels == 0] = -1   # ocean background

    if write:
        cfg.data_dir.mkdir(parents=True, exist_ok=True)

    eras = []
    articles = {}
    final_landmasses = []
    final_geoms = []
    era_features = []
    for era_index, (era_name, angle) in enumerate(
            zip(cfg.era_names, cfg.era_assembly_radians)):
        if angle == 0.0:
            ### No drift: use the grid-label raster directly so the vector
            ### output is indistinguishable from the preview PNG.
            painted = painted_base
        else:
            moved = rodrigues(land_xyz, land_axis, angle)
            painted = rasterize_continents(moved, land_elevation, land_index,
                                           world["sea_level"], grid_xyz, chord)

        features = []
        landmasses = []
        geoms = []
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
            geoms.append(geometry)
            landmasses.append({**properties,
                               "land_fraction": _area_fraction(mask,
                                                               row_weight)})

        filename = f"land_era{era_index + 1}.geojson"
        if write:
            _write_collection(cfg.data_dir / filename, features)
        era_features.append(features)
        eras.append({"name": era_name, "file": filename,
                     "count": len(features)})
        for landmass in landmasses:
            articles[landmass["slug"]] = landmass
        if era_index == len(cfg.era_names) - 1:
            final_landmasses = landmasses
            final_geoms = geoms

    ### Polar ice as a latitude gradient: the real coastline clipped into bands
    ### whose whiteness rises from none at ``ice_edge_lat`` to full at
    ### ``ice_full_lat``, so high latitudes read as solid ice fading to green.
    ice_features = _ice_bands(final_geoms)
    if write:
        _write_collection(cfg.data_dir / "ice.geojson", ice_features)

    meta = {
        "world_name": cfg.world_display_name,
        "seed": int(seed),
        "mesh_cells": cfg.mesh_cells,
        "continent_count": len(continents),
        "center_lon": float(view_lonlat[0]),
        "center_lat": float(view_lonlat[1]),
        "eras": eras,
        "ice_file": "ice.geojson",
        "landmasses": final_landmasses,
        "articles": list(articles.values()),
    }
    if write:
        (cfg.data_dir / "meta.json").write_text(json.dumps(meta, indent=2))
    return meta, era_features, ice_features


def main():
    """Parse arguments and build the world for the requested seed."""
    parser = argparse.ArgumentParser(
        description="Generate a supercontinent world.")
    parser.add_argument("--seed", type=int, default=cfg.default_seed,
                        help="master random seed for the world")
    arguments = parser.parse_args()

    meta, _, _ = build_world(arguments.seed)
    print(f"world '{meta['world_name']}' built from seed {meta['seed']}")
    for era in meta["eras"]:
        print(f"  {era['name']}: {era['count']} landmasses ({era['file']})")
    print(f"geojson written to {cfg.data_dir}")


if __name__ == "__main__":
    main()
