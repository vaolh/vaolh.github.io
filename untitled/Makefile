#################################################
################ WORLD PIPELINE #################
#################################################

### REPLICATION FILE: Makefile
### MAKE VERSION:     4.0+
### LAST EDIT:        2026-06-11 by vao2116

### Master seed for the world; override as `make all seed=42`.
seed := 7

### Interpreter and source layout.
python := .venv/bin/python
gen := gen

.PHONY: all world pages preview clean

### Build the geojson world and then the wiki pages for the chosen seed.
all: world pages

### Generate every geojson layer and the metadata for the seed.
world:
	$(python) $(gen)/generate.py --seed $(seed)

### Render the wiki home page and the nation articles from the metadata.
pages:
	$(python) $(gen)/build_pages.py

### Render a montage of candidate seeds for visual selection.
preview:
	$(python) $(gen)/preview.py --start $(seed)

### Remove generated data and pages, leaving the source untouched.
clean:
	rm -rf data index.html wiki
