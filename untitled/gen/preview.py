#################################################
################ SEED PREVIEW ###################
#################################################

import argparse

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.spatial import cKDTree

import config as cfg
from geometry import fibonacci_sphere, build_adjacency, lonlat_to_xyz
from tectonics import simulate
from vectorize import build_grid, rasterize_nearest, rasterize_idw

### REPLICATION FILE: preview.py
### PYTHON VERSION:   3.13+
### LAST EDIT:        2026-06-11 by vao2116

"""Fast multi-seed preview montage for choosing a supercontinent.

Each candidate seed is simulated at a reduced mesh resolution and rendered as a
shaded relief map centred on the supercontinent. Browsing the montage is how a
preferred world is selected before the full-resolution geojson is built for it.
"""

def _hexrgb(value):
    """Return an RGB float triple for a hex colour string."""
    return tuple(int(value[index:index + 2], 16) / 255.0
                 for index in (1, 3, 5))


def _hypsometric(elevation, land_grid):
    """Map the elevation grid to hypsometric tints for a readable preview.

    Ocean is shaded by depth, land ramps from coastal green through highland
    brown, and terrain above the mountain threshold whitens toward peaks, so the
    tectonic mountain belts stand out against the continental interior.
    """
    deep, shallow = _hexrgb("#0a1830"), _hexrgb("#3a78b0")
    coast, upland = _hexrgb("#5f8f48"), _hexrgb("#7d6a3c")
    peak = _hexrgb("#f4f4f4")
    image = np.zeros(elevation.shape + (3,), dtype=np.float64)

    ocean = ~land_grid
    depth = np.clip(elevation / cfg.oceanic_base_elevation, 0.0, 1.0)
    for channel in range(3):
        image[..., channel] = np.where(
            ocean, shallow[channel] + (deep[channel] - shallow[channel]) * depth,
            image[..., channel])

    low = land_grid & (elevation <= cfg.mountain_elevation)
    ramp = np.clip(elevation / cfg.mountain_elevation, 0.0, 1.0)
    high = land_grid & (elevation > cfg.mountain_elevation)
    snow = np.clip((elevation - cfg.mountain_elevation)
                   / cfg.tectonic_max_uplift, 0.0, 1.0)
    for channel in range(3):
        image[..., channel] = np.where(
            low, coast[channel] + (upland[channel] - coast[channel]) * ramp,
            image[..., channel])
        image[..., channel] = np.where(
            high, upland[channel] + (peak[channel] - upland[channel]) * snow,
            image[..., channel])
    return image


def _render_tile(axis, seed):
    """Simulate one seed at preview resolution and draw its relief tile."""
    rng = np.random.default_rng(seed)
    points = fibonacci_sphere(cfg.preview_mesh_cells)
    edges = build_adjacency(points, cfg.mesh_neighbours)
    world = simulate(points, edges, rng)

    tree = cKDTree(points)
    lon, lat, grid_xyz = build_grid()
    land_grid = rasterize_nearest(
        tree, world["is_land"].astype(np.int64), grid_xyz).astype(bool)
    elevation = rasterize_idw(tree, world["elevation"], grid_xyz)

    axis.imshow(_hypsometric(elevation, land_grid), origin="lower",
                extent=[-180, 180, -90, 90])
    axis.set_xlim(cfg.supercontinent_center_lon - 110,
                  cfg.supercontinent_center_lon + 110)
    axis.set_ylim(cfg.supercontinent_center_lat - 80,
                  cfg.supercontinent_center_lat + 80)
    axis.set_title(f"seed {seed}", fontsize=9)
    axis.set_xticks([])
    axis.set_yticks([])


def main():
    """Render a montage of consecutive seeds for visual selection."""
    parser = argparse.ArgumentParser(
        description="Render a montage of supercontinent seeds.")
    parser.add_argument("--start", type=int, default=1,
                        help="first seed in the montage")
    arguments = parser.parse_args()

    cfg.preview_dir.mkdir(parents=True, exist_ok=True)
    rows, cols = cfg.preview_grid_rows, cfg.preview_grid_cols
    figure, axes = plt.subplots(rows, cols, figsize=(cols * 3.2, rows * 2.4))

    for index, axis in enumerate(axes.ravel()):
        _render_tile(axis, arguments.start + index)

    figure.tight_layout()
    output = cfg.preview_dir / f"seeds_{arguments.start}.png"
    figure.savefig(output, dpi=110)
    print(f"montage written to {output}")


if __name__ == "__main__":
    main()
