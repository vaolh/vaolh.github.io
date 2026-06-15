#################################################
################ WORLD PREVIEW ##################
#################################################

import argparse
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import to_rgba
from matplotlib.patches import Circle, PathPatch
from matplotlib.path import Path
import numpy as np
from shapely.geometry import shape

import config as cfg
from generate import build_world
from geometry import lonlat_to_xyz

### REPLICATION FILE: preview.py
### PYTHON VERSION:   3.13+
### LAST EDIT:        2026-06-15 by vao2116

"""Faithful preview of the world exactly as the website draws it.

The website renders the emitted geojson as flat-filled vector polygons on a
MapLibre globe: a blue ocean, pale-green land, white polar ice and blue
coastlines. This preview draws those same polygons with the same palette in an
orthographic globe and a flat panel, so a world that looks right here looks
identical on the page. There is no hypsometric relief, no separate preview mesh
and no separate ice rule; the only inputs are the geojson features and the
``polar`` flag the site itself styles on.
"""


#################################################
################ GLOBE PROJECTION ###############
#################################################

### Maximum lon/lat step, in degrees, that a coastline segment is densified to
### before projection, so a coast curving over the globe is broken at the limb
### at fine granularity rather than jumping across the visible disc.
_densify_step = 1.2


def _view_basis(center_lon, center_lat):
    """Return the view, east and north unit vectors for the globe centre."""
    view = lonlat_to_xyz(center_lon, center_lat)[0]
    east = np.cross(np.array([0.0, 0.0, 1.0]), view)
    norm = np.linalg.norm(east)
    east = np.array([1.0, 0.0, 0.0]) if norm < 1e-9 else east / norm
    north = np.cross(view, east)
    return view, east, north


def _densify(ring):
    """Insert intermediate vertices so no ring segment exceeds the step."""
    points = [ring[0]]
    for start, end in zip(ring[:-1], ring[1:]):
        span = max(abs(end[0] - start[0]), abs(end[1] - start[1]))
        steps = max(1, int(span / _densify_step))
        for index in range(1, steps + 1):
            points.append(start + (end - start) * index / steps)
    return np.asarray(points)


def _globe_land_image(features, view, east, north, size):
    """Return an RGBA image of land and ice on the globe, ocean transparent.

    The visible disc is sampled on a screen grid, each pixel inverse-projected
    to a longitude and latitude, and tested against the actual land polygons.
    Filling by point-in-polygon rather than by clipping vector rings sidesteps
    every limb special case, so a continent curving over the globe edge is always
    rendered correctly. Ocean is left transparent so the underlying ocean disc
    and graticule show through, exactly as land covers them on the page.
    """
    axis = np.linspace(-1.0, 1.0, size)
    screen_x, screen_y = np.meshgrid(axis, axis)
    radius2 = screen_x ** 2 + screen_y ** 2
    inside = radius2 <= 1.0
    depth = np.sqrt(np.clip(1.0 - radius2, 0.0, 1.0))
    point = (depth[..., None] * view + screen_x[..., None] * east
             + screen_y[..., None] * north)
    lon = np.degrees(np.arctan2(point[..., 1], point[..., 0]))
    lat = np.degrees(np.arcsin(np.clip(point[..., 2], -1.0, 1.0)))
    samples = np.column_stack((lon.ravel(), lat.ravel()))

    land = np.zeros(samples.shape[0], dtype=bool)
    ice = np.zeros(samples.shape[0], dtype=bool)
    for feature in features:
        target = ice if _is_ice(feature) else land
        geometry = shape(feature["geometry"])
        parts = (geometry.geoms if geometry.geom_type == "MultiPolygon"
                 else [geometry])
        for part in parts:
            covered = Path(np.asarray(part.exterior.coords)).contains_points(
                samples)
            for ring in part.interiors:
                covered &= ~Path(np.asarray(ring.coords)).contains_points(
                    samples)
            target |= covered

    image = np.zeros((size, size, 4), dtype=np.float64)
    flat = inside.ravel()
    image.reshape(-1, 4)[flat & land] = to_rgba(cfg.preview_land)
    image.reshape(-1, 4)[flat & ice] = to_rgba(cfg.preview_ice)
    return image


def _coast_runs(ring, view, east, north):
    """Return projected polylines of the ring that lie on the near hemisphere.

    The coastline is broken wherever it passes behind the limb, so the globe
    edge itself is never drawn as a coast, matching how the sphere hides the
    far side on the page.
    """
    dense = _densify(np.asarray(ring))
    xyz = lonlat_to_xyz(dense[:, 0], dense[:, 1])
    visible = (xyz @ view) > 0
    runs, current = [], []
    for point, seen in zip(xyz, visible):
        if seen:
            current.append((point @ east, point @ north))
        elif len(current) > 1:
            runs.append(current)
            current = []
    if len(current) > 1:
        runs.append(current)
    return runs


#################################################
################ PATH HELPERS ###################
#################################################

def _add_polygon(axis, polygon, facecolor):
    """Fill a shapely polygon, holes included, as a single matplotlib patch."""
    parts = polygon.geoms if polygon.geom_type == "MultiPolygon" else [polygon]
    vertices, codes = [], []
    for part in parts:
        for ring in [part.exterior, *part.interiors]:
            coords = np.asarray(ring.coords)
            if coords.shape[0] < 3:
                continue
            vertices.extend(coords)
            codes.append(Path.MOVETO)
            codes.extend([Path.LINETO] * (coords.shape[0] - 2))
            codes.append(Path.CLOSEPOLY)
    if not vertices:
        return
    axis.add_patch(PathPatch(Path(vertices, codes), facecolor=facecolor,
                             edgecolor="none", linewidth=0, antialiased=True))


#################################################
################ PANEL RENDERERS ################
#################################################

def _is_ice(feature):
    """Return whether a feature is a polar continent the site renders white."""
    return bool(feature["properties"].get("polar"))


### Graticule spacing in degrees, matching the website's worldmap.js.
_grid_step_lon = 15
_grid_step_lat = 10


def _graticule_lines():
    """Return the meridian and parallel polylines the website draws."""
    lines = []
    for lon in range(-180, 181, _grid_step_lon):
        lines.append((np.column_stack((np.full(35, lon),
                                       np.linspace(-85, 85, 35))), False))
    for lat in range(-80, 81, _grid_step_lat):
        coords = np.column_stack((np.linspace(-180, 180, 73),
                                  np.full(73, lat)))
        lines.append((coords, lat == 0))
    return lines


def _draw_globe_graticule(axis, view, east, north):
    """Draw the graticule and equator on the globe, clipped to the near side."""
    for coords, equator in _graticule_lines():
        for run in _coast_runs(coords, view, east, north):
            run = np.asarray(run)
            axis.plot(run[:, 0], run[:, 1], color=cfg.preview_coast,
                      linewidth=0.6 if equator else 0.4,
                      alpha=0.5 if equator else 0.35,
                      dashes=[4, 4] if equator else [], zorder=0.5)


def _draw_globe(axis, features, center_lon, center_lat, fill_size=800):
    """Draw the features as the website's orthographic globe view.

    The ocean disc and graticule are drawn first, then a point-in-polygon raster
    of the land and ice on top so it covers them the way land covers the ocean
    and grid on the page, and finally the vector coastlines, which fade where
    they pass behind the limb.
    """
    view, east, north = _view_basis(center_lon, center_lat)
    axis.add_patch(Circle((0.0, 0.0), 1.0, facecolor=cfg.preview_ocean,
                          edgecolor="none", zorder=0))
    _draw_globe_graticule(axis, view, east, north)
    axis.imshow(_globe_land_image(features, view, east, north, fill_size),
                origin="lower", extent=[-1.0, 1.0, -1.0, 1.0], zorder=1,
                interpolation="bilinear")
    for feature in features:
        geometry = shape(feature["geometry"])
        parts = (geometry.geoms if geometry.geom_type == "MultiPolygon"
                 else [geometry])
        for part in parts:
            for ring in [part.exterior, *part.interiors]:
                for run in _coast_runs(ring.coords, view, east, north):
                    run = np.asarray(run)
                    axis.plot(run[:, 0], run[:, 1], color=cfg.preview_coast,
                              linewidth=0.7, zorder=3)
    axis.add_patch(Circle((0.0, 0.0), 1.0, fill=False,
                          edgecolor=cfg.preview_coast, linewidth=0.6,
                          alpha=0.5, zorder=4))
    axis.set_xlim(-1.04, 1.04)
    axis.set_ylim(-1.04, 1.04)
    axis.set_aspect("equal")
    axis.set_facecolor(cfg.preview_space)
    axis.set_xticks([])
    axis.set_yticks([])


def _draw_flat(axis, features):
    """Draw the features as the website's flat equirectangular view."""
    axis.set_facecolor(cfg.preview_ocean)
    for coords, equator in _graticule_lines():
        axis.plot(coords[:, 0], coords[:, 1], color=cfg.preview_coast,
                  linewidth=0.6 if equator else 0.4,
                  alpha=0.5 if equator else 0.35,
                  dashes=[4, 4] if equator else [], zorder=0.5)
    for feature in features:
        fill = cfg.preview_ice if _is_ice(feature) else cfg.preview_land
        geometry = shape(feature["geometry"])
        _add_polygon(axis, geometry, fill)
        parts = (geometry.geoms if geometry.geom_type == "MultiPolygon"
                 else [geometry])
        for part in parts:
            for ring in [part.exterior, *part.interiors]:
                coords = np.asarray(ring.coords)
                axis.plot(coords[:, 0], coords[:, 1], color=cfg.preview_coast,
                          linewidth=0.6)
    axis.set_xlim(-180, 180)
    axis.set_ylim(-90, 90)
    axis.set_aspect("equal")
    axis.set_xticks([])
    axis.set_yticks([])


#################################################
################ ENTRY POINTS ###################
#################################################

def _load_shipped():
    """Return the on-disk geojson features and view centre the website uses."""
    meta = json.loads((cfg.data_dir / "meta.json").read_text())
    data = json.loads((cfg.data_dir / meta["eras"][0]["file"]).read_text())
    return data["features"], meta["center_lon"], meta["center_lat"]


def render_final():
    """Render the chosen, already-built world exactly as the page shows it."""
    features, center_lon, center_lat = _load_shipped()
    cfg.preview_dir.mkdir(parents=True, exist_ok=True)
    figure, (globe, flat) = plt.subplots(1, 2, figsize=(13, 5.2))
    figure.patch.set_facecolor(cfg.preview_space)
    _draw_globe(globe, features, center_lon, center_lat)
    globe.set_title("globe (default view)", fontsize=10)
    _draw_flat(flat, features)
    flat.set_title("flat map (#flat)", fontsize=10)
    figure.tight_layout()
    output = cfg.preview_dir / "world.png"
    figure.savefig(output, dpi=150, facecolor=cfg.preview_space)
    print(f"faithful preview of the shipped world written to {output}")


def render_montage(start):
    """Render a montage of candidate seeds as truthful globe thumbnails.

    Every tile is built through the same generator and vectoriser as the shipped
    world, only on a coarser tracing grid for speed, so the coastlines are the
    real ones a seed would ship, drawn in the page palette.
    """
    cfg.preview_dir.mkdir(parents=True, exist_ok=True)
    rows, cols = cfg.preview_grid_rows, cfg.preview_grid_cols
    figure, axes = plt.subplots(rows, cols, figsize=(cols * 2.7, rows * 2.7))
    figure.patch.set_facecolor(cfg.preview_space)

    ### Trace candidate seeds on the coarse preview grid; shape fidelity comes
    ### from the mesh, which is left at full resolution.
    full_grid = (cfg.grid_width, cfg.grid_height)
    cfg.grid_width, cfg.grid_height = (cfg.preview_grid_width,
                                       cfg.preview_grid_height)
    try:
        for index, axis in enumerate(np.atleast_1d(axes).ravel()):
            seed = start + index
            meta, era_features = build_world(seed, write=False)
            _draw_globe(axis, era_features[0],
                        meta["center_lon"], meta["center_lat"], fill_size=420)
            axis.set_title(f"seed {seed}", fontsize=9)
    finally:
        cfg.grid_width, cfg.grid_height = full_grid

    figure.tight_layout()
    output = cfg.preview_dir / f"seeds_{start}.png"
    figure.savefig(output, dpi=120, facecolor=cfg.preview_space)
    print(f"montage written to {output}")


def main():
    """Render either the faithful single-world preview or a seed montage."""
    parser = argparse.ArgumentParser(
        description="Preview the world exactly as the website draws it.")
    parser.add_argument("--montage", action="store_true",
                        help="render a grid of candidate seeds instead")
    parser.add_argument("--start", type=int, default=cfg.default_seed,
                        help="first seed in the montage")
    arguments = parser.parse_args()

    if arguments.montage:
        render_montage(arguments.start)
    else:
        render_final()


if __name__ == "__main__":
    main()
