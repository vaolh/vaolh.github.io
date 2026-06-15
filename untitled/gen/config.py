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
default_seed = 21390380201

### Fixed display name of the world; never generated.
world_display_name = "The World"

### Counter-inductive build: fractal continents are generated first, then Euler
### rotations carry them together to assemble the supercontinent, the reverse of
### the Bullard fit-of-the-continents reconstruction.
world_mode = "continents"

#################################################
################ SPHERE MESH ####################
#################################################

### Number of Fibonacci mesh cells sampled on the unit sphere. The coastline can
### never be finer than these Voronoi cells, so this is the master detail dial.
### At 1.2M cells each patch is ~0.18 deg (~20 km) across, so the coast stays a
### crisp fractal even zoomed well in on the globe rather than showing facets.
mesh_cells = 1_200_000

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
supercontinent_center_lat = 20.0

### Angular width of the broad gaussian uplift that reinforces cohesion of the
### supercontinent, in degrees.
supercontinent_bias_width = 32.0

### Peak amplitude of that broad uplift, strong enough to gather the fractal
### terrain into one dominant supercontinent in the assembled era.
supercontinent_bias_amplitude = 1.6

#################################################
############### FRACTAL TERRAIN #################
#################################################

### Number of random great-circle faults summed into the fractal heightfield,
### the donjon / Mogensen fractal-planet method that gives crenulated fractal
### coastlines uniformly over the sphere, poles included. NOTE: this (with the
### seed and the fault chunk size) fixes the actual fault field, hence the
### continent shapes — changing it gives a different world. Detail is raised by
### sampling the SAME field on a finer mesh/grid, not by adding faults.
fault_count = 30000

### Weight of the high-pass fractal detail added to the continent templates. The
### fault field is high-passed so it supplies fractal coastline roughness without
### its large-scale structure percolating all land into one blob.
fault_weight = 1.0

### Neighbour-averaging passes used to high-pass the fault field; the smoothed
### low frequencies are subtracted, leaving fractal detail.
fractal_reach_ref = 0.12

### Target fraction of the surface left above sea level.
target_land_fraction = 0.29

#################################################
############### POLAR CONTINENTS ################
#################################################

### Localised uplifts that guarantee a fractal continent near each pole. The
### centres are offset from the poles and to one side so each landmass is a
### blob with fractal coasts rather than a circumpolar band, in degrees and
### elevation units.
arctic_bias_center_lon = 110.0
arctic_bias_center_lat = 74.0
antarctic_bias_center_lon = -70.0
antarctic_bias_center_lat = -72.0
polar_bias_amplitude = 2.4
polar_bias_width = 16.0

### Polar ice is a LATITUDE GRADIENT, not a per-continent flag: land is solid
### white poleward of ``ice_full_lat`` and the whiteness fades to none at
### ``ice_edge_lat``, so a continent that merely reaches the arctic whitens only
### its high-latitude part, like Greenland fading to green at its southern coast.
### The fade is emitted as latitude bands (``ice_band_step`` degrees wide) clipped
### from the real coastline, each carrying an ``ice`` opacity in [0, 1].
ice_edge_lat = 58.0
ice_full_lat = 80.0
ice_band_step = 2.0

### When land reaches the polar region, the few degrees right at the pole are
### capped with a solid white disc spanning all longitudes. A full-longitude
### polygon that closes at the pole is the one shape that fills cleanly on the
### globe (the ocean is drawn the same way), so the cap hides the ragged clamp
### seams where continents are cut just short of the pole, leaving a clean ice
### cap instead of a torn hole. Only added for a pole that actually has land.
ice_cap_lat = 85.0

### Continents whose centroid lies poleward of this latitude are still tagged
### ``polar`` in the metadata, but this no longer drives any colour.
ice_continent_lat = 62.0

#################################################
################ CONTINENTS #####################
#################################################

### Continent template cores. Each is a broad uplift that anchors one continent;
### the high-pass fractal then carves its fractal coastline. Cores are scattered
### with a minimum separation so the continents stay distinct.
continent_count = 6
craton_lon_min = -170.0
craton_lon_max = 170.0
craton_lat_min = -52.0
craton_lat_max = 58.0
craton_min_separation = 44.0
craton_amplitude = 2.2
craton_width = 16.0
craton_size_min = 0.55
craton_size_max = 1.7

### A landmass counts as a continent when its area is at least this share of all
### land. Smaller landmasses are islands and are merged into the nearest
### continent rather than listed separately.
continent_min_land_share = 0.03

### Speck landmasses below this share of total land are dropped entirely.
landmass_min_land_share = 0.0015

#################################################
################ ERAS AND ASSEMBLY ##############
#################################################

### The three geological eras and the Euler angle, in radians, by which each
### continent is rotated toward the assembly centre to reach them. The earth-like
### era is the generated fractal world; larger angles pack the continents into
### the supercontinent.
era_names = ["World"]
era_assembly_radians = [0.0]

### Geographic centre toward which continents are gathered to assemble the
### supercontinent, in degrees.
assembly_center_lon = 0.0
assembly_center_lat = 10.0

### Geodesic distance within which a moved land cell paints land on the grid, in
### radians. Gaps wider than this between separated continents read as ocean.
drift_land_threshold = 0.06


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

### Equirectangular grid resolution used to vectorise fields into polygons. Kept
### well above the mesh density (here ~6x finer than a mesh cell) so the marching
### squares trace the true Voronoi coastline smoothly rather than re-introducing
### a coarse stair-step of their own.
grid_width = 8640
grid_height = 4320

### Land is dropped poleward of this latitude so no polygon reaches the ±90°
### singularity, where a ring spanning all longitudes degenerates to a point and
### tears open on the globe. The few degrees of cap left as ocean are invisible.
max_land_lat = 88.0

### Number of neighbours blended by inverse-distance weighting for the
### continuous elevation raster.
raster_idw_neighbours = 3

### Connected land specks and inland pinhole lakes smaller than these pixel
### areas are removed before a landmass is traced. Thresholding the fault field
### right at sea level leaves salt-and-pepper noise — single-cell islands and
### lakes everywhere — that reads as grime on the map; clearing it keeps the
### fractal coastline detailed while losing only sub-100 km specks.
min_island_pixels = 400
min_lake_pixels = 300

### Chaikin corner-cutting iterations applied to each coastline ring to round
### any residual marching-squares stair-steps into natural curves.
coastline_smoothing_iterations = 3

### Douglas-Peucker simplification tolerance applied to emitted rings, in
### degrees. The fine mesh and tracing grid produce hundreds of thousands of
### near-collinear coastline vertices; this collapses the redundant ones at
### ~1.6 km, far below what is visible on the globe, so the coast stays crisp
### while the emitted geojson is small enough to fetch and parse quickly.
simplify_tolerance_deg = 0.003

### Decimal places kept on emitted coordinates. Four places is ~11 m, finer than
### the coastline detail, and trims the geojson well below full float precision.
coordinate_decimals = 4

#################################################
################ PREVIEW ########################
#################################################

### The preview renders the exact vector geojson the website loads, with the
### website's flat palette and an orthographic globe, so a chosen world looks
### identical on the page. The montage builds each candidate seed through the
### same generator and vectoriser (so its shapes are truthful) but traces them
### on a coarser grid for speed, since shape fidelity comes from the mesh, not
### the tracing grid.
preview_grid_width = 1600
preview_grid_height = 800

### Grid of seeds rendered by the preview montage.
preview_grid_cols = 5
preview_grid_rows = 2

### Website palette (light theme) mirrored from css/world.css so the preview
### colours match the page exactly.
preview_ocean = "#bcd6ec"
preview_land = "#d6e8bf"
preview_ice = "#ffffff"
preview_coast = "#3a72ad"
preview_space = "#ffffff"
