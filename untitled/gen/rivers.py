#################################################
################ RIVER NETWORK ##################
#################################################

import heapq

import numpy as np
from scipy import ndimage
from shapely.geometry import LineString, mapping

import config as cfg

### REPLICATION FILE: rivers.py
### PYTHON VERSION:   3.13+
### LAST EDIT:        2026-06-15 by vao2116

"""Procedural rivers carved from the elevation field by flow routing.

The relief is reduced to a coarse grid, its depressions are filled so every land
cell drains to the sea, and each cell is pointed at its lowest neighbour. The
number of cells draining through each cell — its catchment — is accumulated, and
the cells above a threshold form the river network, which is traced into reaches
whose flow sets their width. This is the standard fill / flow-direction / flow-
accumulation pipeline, run on the same heightfield the coastlines come from.
"""

### The eight grid neighbours, with the orthogonal ones first.
_neighbours = [(-1, 0), (1, 0), (0, -1), (0, 1),
               (-1, -1), (-1, 1), (1, -1), (1, 1)]

### A vanishing increment added as each depression is filled, so the filled
### surface strictly descends to the sea and the flow never stalls or loops.
_fill_epsilon = 1e-6


def _shift(field, row_step, col_step, fill):
    """Return the field shifted by one neighbour, wrapping in longitude only."""
    shifted = np.roll(field, (row_step, col_step), axis=(0, 1))
    if row_step > 0:
        shifted[:row_step, :] = fill
    elif row_step < 0:
        shifted[row_step:, :] = fill
    return shifted


def _downsample(field, height, width, reducer):
    """Reduce a grid to the given shape by aggregating blocks."""
    block_h = field.shape[0] // height
    block_w = field.shape[1] // width
    trimmed = field[:height * block_h, :width * block_w]
    blocks = trimmed.reshape(height, block_h, width, block_w)
    return reducer(blocks, axis=(1, 3))


def _fill_depressions(elevation, land):
    """Raise pits with priority flood so all land drains to the sea.

    Ocean cells bordering land are the spill points; the relief is flooded
    inward from them, each newly reached land cell set to the higher of its own
    height and a hair above the water that reached it. The result has no interior
    minimum, so a steepest-descent path from any land cell reaches the ocean.
    """
    height, width = elevation.shape
    filled = np.where(land, np.inf, elevation).astype(np.float64)
    resolved = ~land
    border = (~land) & ndimage.binary_dilation(land)
    heap = [(float(elevation[row, col]), int(row), int(col))
            for row, col in np.argwhere(border)]
    heapq.heapify(heap)
    while heap:
        level, row, col = heapq.heappop(heap)
        for row_step, col_step in _neighbours:
            near_row, near_col = row + row_step, (col + col_step) % width
            if near_row < 0 or near_row >= height or resolved[near_row, near_col]:
                continue
            resolved[near_row, near_col] = True
            raised = max(elevation[near_row, near_col], level + _fill_epsilon)
            filled[near_row, near_col] = raised
            heapq.heappush(heap, (raised, near_row, near_col))
    return filled


def _flow_and_accumulate(filled, land):
    """Return each cell's downstream neighbour and its accumulated catchment."""
    height, width = filled.shape
    ### Bring each neighbour's value to the cell by rolling the opposite way, so
    ### the chosen direction is genuinely the cell's lowest neighbour.
    stack = np.stack([_shift(filled, -row_step, -col_step, np.inf)
                      for row_step, col_step in _neighbours], axis=0)
    choice = np.argmin(stack, axis=0)
    row_steps = np.array([step[0] for step in _neighbours])[choice]
    col_steps = np.array([step[1] for step in _neighbours])[choice]
    rows, cols = np.indices((height, width))
    down_row = rows + row_steps
    down_col = (cols + col_steps) % width

    accumulation = land.astype(np.float64)
    land_cells = np.argwhere(land)
    order = np.argsort(filled[land])[::-1]
    for row, col in land_cells[order]:
        target_row, target_col = down_row[row, col], down_col[row, col]
        if 0 <= target_row < height:
            accumulation[target_row, target_col] += accumulation[row, col]
    return down_row, down_col, accumulation


def _cell_lonlat(row, col, height, width):
    """Return the longitude and latitude of a river-grid cell centre."""
    lon = -180.0 + (col + 0.5) * 360.0 / width
    lat = -90.0 + (row + 0.5) * 180.0 / height
    return lon, lat


def _trace(down_row, down_col, accumulation, land):
    """Trace the river cells into reaches between sources and confluences."""
    height, width = accumulation.shape
    river = (accumulation > cfg.river_min_cells) & land
    river_cells = [tuple(cell) for cell in np.argwhere(river)]

    inflow = np.zeros((height, width), dtype=np.int64)
    for row, col in river_cells:
        target = (down_row[row, col], down_col[row, col])
        if 0 <= target[0] < height and river[target]:
            inflow[target] += 1

    visited = np.zeros((height, width), dtype=bool)
    features = []
    for row, col in river_cells:
        if inflow[row, col] == 1:
            continue
        path = [(row, col)]
        visited[row, col] = True
        current = (row, col)
        while True:
            target = (down_row[current], down_col[current])
            if not 0 <= target[0] < height:
                break
            path.append(target)
            if not river[target] or inflow[target] >= 2 or visited[target]:
                break
            visited[target] = True
            current = target
        if len(path) < 2:
            continue
        coords = [_cell_lonlat(row, col, height, width) for row, col in path]
        mouth = path[-1] if river[path[-1]] else path[-2]
        flow = int(accumulation[mouth])
        features.append({
            "type": "Feature",
            "properties": {"flow": flow,
                           "order": int(np.log2(max(flow, 1)) + 1)},
            "geometry": mapping(LineString(coords)),
        })
    return features


def build_rivers(elevation_grid, land_grid):
    """Return river reach features routed from the rolled elevation grid."""
    height, width = cfg.river_grid_height, cfg.river_grid_width
    elevation = _downsample(elevation_grid, height, width, np.mean)
    land = _downsample(land_grid.astype(np.float64), height, width,
                       np.mean) > 0.5
    if not land.any():
        return []
    filled = _fill_depressions(elevation, land)
    down_row, down_col, accumulation = _flow_and_accumulate(filled, land)
    return _trace(down_row, down_col, accumulation, land)
