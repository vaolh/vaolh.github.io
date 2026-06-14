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

### Base generation always builds one supercontinent and then drifts it apart
### into the later eras, so the continents are torn fragments whose coastlines
### fit back together rather than unrelated blobs.
world_mode = "supercontinent"

#################################################
################ SPHERE MESH ####################
#################################################

### Number of Fibonacci mesh cells sampled on the unit sphere. Higher values
### produce finer coastlines at the cost of generation time.
mesh_cells = 26000

### Number of nearest neighbours used to approximate the mesh adjacency graph.
mesh_neighbours = 7

#################################################
################ PLATES #########################
#################################################

### Number of tectonic plates tessellated across the globe.
plate_count = 44

### Domain-warp amplitude and noise applied to plate assignment so plate
### boundaries, and therefore the torn coastlines, are fractal rather than the
### straight edges of a raw Voronoi tessellation.
boundary_warp_amplitude = 0.07
boundary_warp_components = 40
boundary_warp_frequency_min = 2.0
boundary_warp_frequency_max = 9.0

### Fraction of total surface area that begins as continental crust. Tuned so
### the emergent supercontinent covers a Pangaea-like share of the globe.
continental_area_fraction = 0.18

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
supercontinent_bias_amplitude = 0.18

### Display name and article slug for the single landmass of the present era.
supercontinent_name = "Supercontinent"
supercontinent_slug = "supercontinent"

#################################################
################ CONTINENTS #####################
#################################################

### Number of separate non-polar continents grown in continents mode.
continent_count = 6

### Bounds within which continent cratons are seeded, in degrees, kept clear of
### the antimeridian and poles so coastline extraction stays seam-free.
craton_lon_min = -150.0
craton_lon_max = 150.0
craton_lat_min = -55.0
craton_lat_max = 65.0

### Minimum angular separation enforced between craton centres, in degrees, so
### continents do not merge into one mass.
craton_min_separation = 42.0

### Spread of continent target sizes. Each craton's share of the continental
### area is drawn from this range before normalisation, giving Earth-like
### variety from large continents down to small ones.
continent_size_min = 0.4
continent_size_max = 1.8

### Minimum size of a kept landmass, as a fraction of the largest continent, so
### tiny specks are flooded while genuine continents and islands survive.
continent_min_relative_size = 0.02

#################################################
################ ERAS AND DRIFT #################
#################################################

### The three geological eras and the outward drift angle, in radians, applied
### to each plate to reach them. Era one is the assembled supercontinent.
era_names = ["Supercontinent", "First tectonic movements",
             "Earth-like continents"]
era_drift_radians = [0.0, 0.30, 0.85]

### Geodesic distance within which a drifted land cell paints land on the grid,
### in radians. Gaps wider than this between drifting fragments become ocean.
drift_land_threshold = 0.038

### Land is clipped inside these longitude and latitude limits, in degrees, so a
### drifting continent never reaches the antimeridian seam or a pole where
### coastline extraction would break; the excluded margins read as open ocean.
safe_lon_limit = 168.0
safe_lat_limit = 84.0

### Continents whose centroid lies poleward of this latitude render as white
### ice rather than green land, giving polar continents an ice-sheet look.
ice_continent_lat = 60.0

### Minimum size of a kept landmass, as a fraction of the largest, low enough to
### preserve island arcs and archipelagos rather than only major continents.
landmass_min_relative_size = 0.004

#################################################
################ ANTARCTICA #####################
#################################################

### Whether a polar ice continent is placed at the south pole.
include_antarctica = True

### Mean latitude of the antarctic coastline and the amplitude of its waviness,
### in degrees.
antarctica_coast_lat = -64.0
antarctica_coast_roughness = 7.0

### Number of periodic harmonics shaping the antarctic coastline.
antarctica_harmonics = 9

### Display name and article slug for the polar continent.
antarctica_name = "Antarctica"
antarctica_slug = "antarctica"

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
noise_components = 72

### Spatial frequency range of those components, in inverse radians. The upper
### bound sets how crenulated the coastline becomes with capes and bays.
noise_frequency_min = 1.5
noise_frequency_max = 18.0

### Overall amplitude of the fractal noise relative to elevation units.
noise_amplitude = 0.38

#################################################
################ SEA LEVEL ######################
#################################################

### Fixed sea level in model units. Land is everything above this elevation;
### the continentality plateau is calibrated so the supercontinent interior
### stays above it and the deep ocean floor stays below it.
sea_level = 0.0

### Maximum size of a secondary land component, as a fraction of the largest,
### for it to be kept as an offshore island. Components larger than this but
### smaller than the main mass are flooded, so the result is always one
### supercontinent surrounded by at most small islands.
island_max_relative_size = 0.03

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
grid_width = 2400
grid_height = 1200

### Number of neighbours blended by inverse-distance weighting for the
### continuous elevation raster.
raster_idw_neighbours = 6

### Chaikin corner-cutting iterations applied to each coastline ring to round
### the marching-squares stair-steps into natural curves.
coastline_smoothing_iterations = 3

### Douglas-Peucker simplification tolerance applied to emitted rings, in
### degrees, kept small so simplification does not reintroduce angular coasts.
simplify_tolerance_deg = 0.05

#################################################
################ PREVIEW ########################
#################################################

### Mesh resolution used for fast multi-seed previews.
preview_mesh_cells = 5000

### Grid of seeds rendered by the preview montage.
preview_grid_cols = 4
preview_grid_rows = 3
