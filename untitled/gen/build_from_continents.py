#################################################
########## CONTINENT-DRIVEN WORLD BUILD #########
#################################################

import json

import numpy as np
from matplotlib.path import Path
from scipy import ndimage
from shapely.geometry import box, shape
from shapely.ops import unary_union

import config as cfg
from generate import (_feature, _ice_bands, _round_features, _write_collection,
                      _write_dem)
from rivers import build_rivers

### REPLICATION FILE: build_from_continents.py
### PYTHON VERSION:   3.13+
### LAST EDIT:        2026-06-16 by vao2116

"""Rebuild the shipped world from a hand-edited continent geojson.

The procedural generator draws a candidate world from a seed; once the author has
moved the continents around in QGIS and grouped the loose polygons into named
landmasses with a shared ``slug``, that edited ``continents.geojson`` becomes the
source of truth. This module re-derives every downstream layer from it — the land
feature collection the website draws, the polar ice overlay, the river network and
the elevation model — so the page, the previews and the QGIS layers all agree with
the new positions. The relief no longer comes from the seed (the continents have
moved out from under it); it is synthesised from the new coastlines so rivers run
from each interior to the nearest sea.
"""

### The continent grid the relief, rivers and area shares are sampled on. It is
### coarser than the website's vector coastlines because the rivers ship at half
### this resolution and the land outlines come straight from the geojson, not the
### raster — the grid only carries the heightfield.
_grid_height = cfg.dem_grid_height
_grid_width = cfg.dem_grid_width

### Relief synthesis weights: the coast-distance trend that drains every interior
### to the sea, and the fractal noise that breaks the radial drainage into ridges
### and valleys so the rivers branch instead of running straight to the shore.
_relief_distance_weight = 0.55
_relief_noise_weight = 0.22
_relief_octaves = (32.0, 16.0, 8.0, 4.0)
_relief_octave_falloff = 0.55
_relief_land_floor = 0.03
_ocean_elevation = -0.3


def _grid_centres():
    """Return the longitude and latitude of every relief-grid cell centre."""
    lon = -180.0 + (np.arange(_grid_width) + 0.5) * 360.0 / _grid_width
    lat = -90.0 + (np.arange(_grid_height) + 0.5) * 180.0 / _grid_height
    return lon, lat


def _rasterize(geometry, samples):
    """Return a flat boolean mask of the sample points inside the geometry."""
    parts = (geometry.geoms if geometry.geom_type == "MultiPolygon"
             else [geometry])
    mask = np.zeros(samples.shape[0], dtype=bool)
    for part in parts:
        covered = Path(np.asarray(part.exterior.coords)).contains_points(
            samples)
        for ring in part.interiors:
            covered &= ~Path(np.asarray(ring.coords)).contains_points(samples)
        mask |= covered
    return mask


def _synth_elevation(land, rng):
    """Synthesise a heightfield over the land mask for river routing.

    The continents have moved away from the seed's relief, so a new field is
    built straight from the coastlines: distance from the coast gives every
    interior a seaward slope, and summed bands of smoothed noise add the ridges
    and valleys that make the drainage branch. Ocean sits below the land floor so
    the exported model reads as bathymetry, and the land minimum is lifted clear
    of sea level so the whole mask routes as land.
    """
    distance = ndimage.distance_transform_edt(land)
    distance /= distance.max() or 1.0

    noise = np.zeros(land.shape, dtype=np.float64)
    amplitude, total = 1.0, 0.0
    for sigma in _relief_octaves:
        white = rng.standard_normal(land.shape)
        noise += amplitude * ndimage.gaussian_filter(white, sigma,
                                                     mode="reflect")
        total += amplitude
        amplitude *= _relief_octave_falloff
    noise /= total
    noise = (noise - noise.mean()) / (noise.std() or 1.0)

    relief = _relief_distance_weight * distance + _relief_noise_weight * noise
    relief += _relief_land_floor - relief[land].min()
    return np.where(land, relief, _ocean_elevation)


def _centroid_lat(geometry):
    """Return the latitude of a geometry's centroid for the polar test."""
    return geometry.centroid.y


def _land_fraction(mask, cos_lat):
    """Return the area-weighted share of the globe a grid mask covers."""
    return float((mask * cos_lat[:, None]).sum()
                 / (cos_lat.sum() * _grid_width))


def build_from_continents():
    """Rebuild every shipped layer from the hand-edited continent geojson."""
    source = json.loads((cfg.data_dir / "continents.geojson").read_text())

    ### Drop any geometry poleward of the clamp latitude, exactly as the
    ### procedural build does, so no polygon reaches the pole singularity and
    ### tears on the globe; the solid ice cap covers the clipped edge.
    valid = box(-180.0, -cfg.max_land_lat, 180.0, cfg.max_land_lat)

    ### Group the loose polygons by the slug the author assigned, so the polygons
    ### that belong to one landmass become a single multipolygon feature.
    groups = {}
    for feature in source["features"]:
        geometry = shape(feature["geometry"]).intersection(valid)
        if geometry.is_empty:
            continue
        slug = feature["properties"].get("slug")
        groups.setdefault(slug, []).append(geometry)

    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    lon, lat = _grid_centres()
    lon_grid, lat_grid = np.meshgrid(lon, lat)
    samples = np.column_stack((lon_grid.ravel(), lat_grid.ravel()))
    cos_lat = np.cos(np.radians(lat))

    ### One land feature and one landmass record per slug, plus the per-slug
    ### masks that drive the area shares, the polar test and the relief.
    land_features = []
    land_geoms = []
    landmasses = []
    land_grid = np.zeros((_grid_height, _grid_width), dtype=bool)
    for slug, parts in groups.items():
        geometry = unary_union(parts)
        polar = bool(abs(_centroid_lat(geometry)) > cfg.ice_continent_lat)
        properties = {"name": "", "slug": slug, "polar": polar}
        land_features.append(_feature(geometry, properties))
        land_geoms.append(geometry)
        mask = _rasterize(geometry, samples).reshape(_grid_height, _grid_width)
        land_grid |= mask
        landmasses.append({**properties,
                           "land_fraction": _land_fraction(mask, cos_lat)})

    landmasses.sort(key=lambda land: -land["land_fraction"])
    _write_collection(cfg.data_dir / "land_era1.geojson", land_features)

    ### Polar ice as the latitude-gradient overlay, rebuilt for the new land.
    ice_features = _ice_bands(land_geoms)
    _write_collection(cfg.data_dir / "ice.geojson", ice_features)

    ### Rivers and the elevation model from a relief synthesised over the moved
    ### coastlines, so both follow the continents to their new positions.
    rng = np.random.default_rng(cfg.default_seed)
    elevation_grid = _synth_elevation(land_grid, rng)
    river_features = _round_features(build_rivers(elevation_grid, land_grid))
    _write_collection(cfg.data_dir / "rivers.geojson", river_features)
    _write_dem(cfg.data_dir / "elevation.asc", elevation_grid)

    ### Open the globe on the largest temperate landmass, not a polar ice cap.
    view = next((land for land in landmasses if not land["polar"]),
                landmasses[0])
    view_geom = unary_union(groups[view["slug"]]).centroid

    existing = cfg.data_dir / "meta.json"
    seed = (json.loads(existing.read_text()).get("seed", cfg.default_seed)
            if existing.exists() else cfg.default_seed)
    meta = {
        "world_name": cfg.world_display_name,
        "seed": int(seed),
        "mesh_cells": cfg.mesh_cells,
        "continent_count": len(landmasses),
        "center_lon": float(view_geom.x),
        "center_lat": float(view_geom.y),
        "eras": [{"name": cfg.era_names[0], "file": "land_era1.geojson",
                  "count": len(land_features)}],
        "ice_file": "ice.geojson",
        "rivers_file": "rivers.geojson",
        "dem_file": "elevation.asc",
        "landmasses": landmasses,
        "articles": landmasses,
    }
    existing.write_text(json.dumps(meta, indent=2))
    return meta


def main():
    """Rebuild the world from continents.geojson and report what was written."""
    meta = build_from_continents()
    print(f"world '{meta['world_name']}' rebuilt from continents.geojson")
    for land in meta["landmasses"]:
        share = round(land["land_fraction"] * 100, 2)
        kind = "ice" if land["polar"] else "temperate"
        print(f"  {land['slug']}: {share}% of globe ({kind})")
    print(f"geojson written to {cfg.data_dir}")


if __name__ == "__main__":
    main()
