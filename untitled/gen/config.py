#################################################
################ CONFIGURATION ##################
#################################################

### REPLICATION FILE: config.py
### PYTHON VERSION:   3.13+
### LAST EDIT:        2026-06-11 by vao2116

"""Central configuration for the supercontinent world generator.

Every tunable constant of the tectonic pipeline lives here so that a design
choice can be changed in exactly one place. No other module hard-codes a
numeric parameter of the geological model.
"""

from pathlib import Path

#################################################
################ FILE SYSTEM ####################
#################################################

### Generator root and the sibling data directory that holds emitted geojson.
gen_dir = Path(__file__).resolve().parent
project_dir = gen_dir.parent
data_dir = project_dir / "data"
preview_dir = data_dir / "previews"

#################################################
################ RANDOM SEED ####################
#################################################

### Default master seed; override on the command line to explore alternatives.
default_seed = 7

#################################################
################ SPHERE MESH ####################
#################################################

### Number of Fibonacci mesh cells sampled on the unit sphere. Higher values
### produce finer coastlines at the cost of generation time.
mesh_cells = 12000

### Number of nearest neighbours used to approximate the mesh adjacency graph.
mesh_neighbours = 7

#################################################
################ PLATES #########################
#################################################

### Number of tectonic plates tessellated across the globe.
plate_count = 22

### Fraction of total surface area that begins as continental crust.
continental_area_fraction = 0.34

### Plateau elevation of continental interior and floor of oceanic crust, in
### model units where sea level is zero.
continental_base_elevation = 0.55
oceanic_base_elevation = -0.55

### Number of neighbour-averaging passes that smooth the continental indicator
### into a continentality field, so the coastline ramps across the crust margin
### rather than snapping to the polygonal plate boundary.
continentality_smoothing_passes = 2

### Range of plate angular speeds (model units per step) drawn per plate.
plate_speed_min = 0.20
plate_speed_max = 1.00

#################################################
################ SUPERCONTINENT #################
#################################################

### Geographic centre toward which continental plates are clustered so that
### emergent land coheres into a single supercontinent, in degrees.
supercontinent_center_lon = 0.0
supercontinent_center_lat = 8.0

### Angular width of the broad gaussian uplift that reinforces cohesion of the
### supercontinent, in degrees.
supercontinent_bias_width = 45.0

### Peak amplitude of that broad uplift in elevation units. Kept subtle so it
### raises the continental interior without lifting open ocean into land.
supercontinent_bias_amplitude = 0.12

### Display name and article slug for the single landmass of the present era.
supercontinent_name = "Supercontinent"
supercontinent_slug = "supercontinent"

#################################################
################ TECTONIC FORCING ###############
#################################################

### Elevation response coefficients for each convergent boundary regime.
uplift_continental_collision = 1.60
uplift_oceanic_subduction = 0.95
uplift_island_arc = 0.55

### Trench depression coefficient on the subducting oceanic side.
trench_depression = 0.70

### Rift and ridge response coefficients for divergent boundaries.
rift_depression = 0.45
ridge_elevation = 0.25

### Fraction below which a boundary's convergence is treated as pure shear and
### classified as a transform fault rather than convergent or divergent.
transform_convergence_ratio = 0.30

### Geodesic decay length over which boundary stress spreads inland, in radians.
boundary_decay_length = 0.14

### Search radius for accumulating boundary stress, in radians.
boundary_search_radius = 0.45

### Peak uplift and trench depth the accumulated tectonic field is normalised
### to, in elevation units, so the result is independent of mesh density.
tectonic_max_uplift = 0.95
tectonic_max_trench = 0.60

### Percentile used as the reference extreme when normalising the tectonic
### field, so isolated outliers do not flatten the whole relief.
tectonic_scale_percentile = 98.0

#################################################
################ FRACTAL NOISE ##################
#################################################

### Number of random sinusoidal components summed to form seamless sphere noise.
noise_components = 48

### Spatial frequency range of those components, in inverse radians.
noise_frequency_min = 1.5
noise_frequency_max = 9.0

### Overall amplitude of the fractal noise relative to elevation units.
noise_amplitude = 0.32

#################################################
################ SEA LEVEL ######################
#################################################

### Fixed sea level in model units. Land is everything above this elevation;
### the continentality plateau is calibrated so the supercontinent interior
### stays above it and the deep ocean floor stays below it.
sea_level = 0.0

### Minimum size of a detached land component, as a fraction of the largest
### component, for it to survive as an island rather than be flooded.
island_min_relative_size = 0.012

#################################################
################ ELEVATION CLASSES ##############
#################################################

### Elevation above which land is classified as mountainous, in model units.
mountain_elevation = 1.3

#################################################
################ COUNTRIES ######################
#################################################

### Number of nations the supercontinent is partitioned into.
country_count = 17

#################################################
################ DISPLAY SCALES #################
#################################################

### Notional planetary surface area used to report nation sizes, in square
### kilometres, matching Earth so the figures read intuitively.
world_surface_km2 = 510_000_000

### Conversion from model elevation units to metres for human-readable relief.
elevation_meters_per_unit = 3500

#################################################
################ RASTERISATION ##################
#################################################

### Equirectangular grid resolution used to vectorise fields into polygons.
grid_width = 2048
grid_height = 1024

### Number of neighbours blended by inverse-distance weighting for the
### continuous elevation raster.
raster_idw_neighbours = 4

### Douglas-Peucker simplification tolerance applied to emitted rings, in
### degrees, to keep geojson compact without visible loss on a globe.
simplify_tolerance_deg = 0.12

#################################################
################ PREVIEW ########################
#################################################

### Mesh resolution used for fast multi-seed previews.
preview_mesh_cells = 5000

### Grid of seeds rendered by the preview montage.
preview_grid_cols = 4
preview_grid_rows = 3
