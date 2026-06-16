#################################################
################ WORLD PIPELINE #################
#################################################

### REPLICATION FILE: Makefile
### MAKE VERSION:     4.0+
### LAST EDIT:        2026-06-16 by vao2116

### Master seed for drawing a fresh candidate world; override as `make seed seed=42`.
seed := 7

### Interpreter and source layout.
python := .venv/bin/python
gen := gen

.PHONY: all world seed pages preview montage clean

### Rebuild the shipped world from the hand-edited continents, then the pages.
all: world pages

### Rebuild every geojson layer and the metadata from data/continents.geojson:
### the authored land grouped into landmasses, the ice overlay, and the rivers
### and elevation model re-routed onto the moved continents.
world:
	$(python) $(gen)/build_from_continents.py

### Draw a fresh procedural candidate world from a seed (the source the author
### then edits in QGIS into data/continents.geojson).
seed:
	$(python) $(gen)/generate.py --seed $(seed)

### Render the wiki home page and the nation articles from the metadata.
pages:
	$(python) $(gen)/build_pages.py

### Render the built world exactly as the website draws it (globe + flat map).
preview:
	$(python) $(gen)/preview.py

### Render a montage of candidate seeds, each drawn in the page's true style.
montage:
	$(python) $(gen)/preview.py --montage --start $(seed)

### Remove generated data and pages, leaving the source untouched.
clean:
	rm -rf data index.html wiki
