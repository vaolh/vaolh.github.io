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


def _ice_mask(land_grid, lat):
    """BFS from pole rows through land cells above 60 deg lat only.

    The fractal polar landmass is naturally blob-shaped, like Antarctica.
    The 60 deg cutoff stops the fill escaping through any narrow isthmus
    that connects the polar land to a mid-latitude continent.
    """
    H, W = land_grid.shape
    # rows where |lat| >= 60
    polar_rows = np.where(np.abs(lat) >= 60.0)[0]
    eligible = np.zeros((H, W), dtype=bool)
    eligible[polar_rows, :] = True

    ice = np.zeros((H, W), dtype=bool)
    for pole_row in [H - 1, 0]:
        queue = [(pole_row, c) for c in range(W)
                 if land_grid[pole_row, c] and eligible[pole_row, c]]
        for pos in queue:
            ice[pos] = True
        i = 0
        while i < len(queue):
            r, c = queue[i]; i += 1
            for nr, nc in [(r+1,c),(r-1,c),(r,c+1),(r,c-1)]:
                nc = nc % W
                if (0 <= nr < H and eligible[nr, nc]
                        and land_grid[nr, nc] and not ice[nr, nc]):
                    ice[nr, nc] = True
                    queue.append((nr, nc))
    return ice


def _hypsometric(elevation, land_grid, ice_grid):
    """Map the elevation grid to hypsometric tints for a readable preview.

    Ocean is shaded by depth, land ramps from coastal green through highland
    brown, terrain above the mountain threshold whitens toward peaks, and land
    covered by polar ice (flood-filled from the poles, donjo-style) is painted
    glacier-white.
    """
    deep, shallow = _hexrgb("#0a1830"), _hexrgb("#3a78b0")
    coast, upland = _hexrgb("#5f8f48"), _hexrgb("#7d6a3c")
    peak = _hexrgb("#f4f4f4")
    ice = _hexrgb("#ddeeff")
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

    ### Polar ice: land reached by flood-fill from the poles, donjo-style.
    for channel in range(3):
        image[..., channel] = np.where(ice_grid, ice[channel],
                                        image[..., channel])
    return image


def _render_tile(axis, seed):
    """Simulate one seed at preview resolution and draw its relief tile."""
    rng = np.random.default_rng(seed)
    points = fibonacci_sphere(cfg.preview_mesh_cells)
    edges = build_adjacency(points, cfg.mesh_neighbours)
    world = simulate(points, edges, rng)

    tree = cKDTree(points)
    _, lat, grid_xyz = build_grid()
    land_grid = rasterize_nearest(
        tree, world["is_land"].astype(np.int64), grid_xyz).astype(bool)
    elevation = rasterize_idw(tree, world["elevation"], grid_xyz)
    ice_grid = _ice_mask(land_grid, lat)

    axis.imshow(_hypsometric(elevation, land_grid, ice_grid), origin="lower",
                extent=[-180, 180, -90, 90])
    axis.set_xlim(-180, 180)
    axis.set_ylim(-90, 90)
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
