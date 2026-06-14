#################################################
################ PAGE BUILDER ###################
#################################################

import json

import config as cfg

### REPLICATION FILE: build_pages.py
### PYTHON VERSION:   3.13+
### LAST EDIT:        2026-06-12 by vao2116

"""Generation of the wiki shell from the world metadata.

The world home page embeds the interactive MapLibre globe; every landmass is a
clickable feature linking to its article, and one stub article is written per
landmass. Pages reuse the shared wiki styling through ``css/world.css`` so the
map, the index and the articles form a navigable wiki in the millmint factbook
style.
"""

### Pinned MapLibre GL build used by the globe viewer. Version 5 is required for
### the globe projection and its setProjection API.
maplibre_js = "https://unpkg.com/maplibre-gl@5.6.1/dist/maplibre-gl.js"
maplibre_css = "https://unpkg.com/maplibre-gl@5.6.1/dist/maplibre-gl.css"


def _meters(elevation):
    """Return a model elevation rendered as rounded metres."""
    return int(round(elevation * cfg.elevation_meters_per_unit, -1))


def _land_km2(land_fraction):
    """Return the landmass area as notional square kilometres."""
    return int(round(land_fraction * cfg.world_surface_km2, -4))


def _head(title, css_prefix, extra=""):
    """Return a shared html head block for a page at a given path depth."""
    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<link rel="stylesheet" href="{css_prefix}css/world.css">
{extra}</head>
<body>
"""


def build_index(meta):
    """Write the world home page with the embedded globe and continent index."""
    extra = (f'<link rel="stylesheet" href="{maplibre_css}">\n'
             f'<script src="{maplibre_js}"></script>')
    landmasses = meta["landmasses"]
    links = "\n".join(
        f'<div><a href="wiki/{land["slug"]}.html">{land["name"]}</a></div>'
        for land in landmasses)
    count = len(landmasses)
    html = _head(meta["world_name"], "", extra)
    html += f"""<h1>{meta['world_name']}</h1>

<p><b>{meta['world_name']}</b> is the world of an unnamed fantasy setting, its
coastlines shaped by a fractal terrain model. The <b>Era</b> button replays its
geological history: {count} drifting continents that the Euler rotations of plate
tectonics carry back together into one supercontinent and apart again. Drag to
spin the globe, scroll to zoom, toggle the flat map, and click a continent to
open its article.</p>

<div id="world-map-outer">
  <div id="world-map-wrap">
    <div id="world-map"></div>
    <div id="world-map-loader">
      <div class="vk-loader-spinner"></div>
      <span class="vk-loader-text">Loading map&hellip;</span>
    </div>
    <div id="world-map-controls">
      <button id="wm-btn-globe" class="vk-ctrl-btn active" title="Toggle globe or flat map">Globe</button>
      <button id="wm-btn-reset" class="vk-ctrl-btn" title="Reset view">Reset</button>
      <button id="wm-btn-era" class="vk-ctrl-btn" title="Step through the geological eras">Era</button>
      <button id="wm-btn-fs" class="vk-ctrl-btn" title="Toggle fullscreen">Fullscreen</button>
    </div>
  </div>
  <div id="world-map-tooltip"><div class="vkl-popup-inner"></div></div>
</div>

<h2>Continents</h2>
<div class="nation-list">
{links}
</div>

<script src="js/worldmap.js"></script>
</body></html>
"""
    (cfg.project_dir / "index.html").write_text(html)


def build_articles(meta):
    """Write one stub article per landmass that appears in any era."""
    wiki_dir = cfg.project_dir / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)
    for land in meta["articles"]:
        name = land["name"]
        share = land["land_fraction"]
        kind = "ice-capped continent" if land.get("polar") else "continent"
        html = _head(f"{name} – {meta['world_name']}", "../")
        html += f"""<h1>{name}</h1>

<div class="infobox">
<div class="infobox-title">{name}</div>
<div class="infobox-section">Geography</div>
<table><tbody>
<tr><th>World</th><td><a href="../index.html">{meta['world_name']}</a></td></tr>
<tr><th>Type</th><td>{kind.capitalize()}</td></tr>
<tr><th>Area</th><td>{_land_km2(share):,} km&sup2;</td></tr>
<tr><th>Share of globe</th><td>{round(share * 100, 1)}%</td></tr>
</tbody></table>
</div>

<p><b>{name}</b> is a {kind} of {meta['world_name']}, a world shaped by
fractal fault lines. It covers roughly
{round(share * 100, 1)}% of the planet's surface. This article is a stub
awaiting its name, geography, peoples and history.</p>

<p><a href="../index.html">&larr; Back to the map of {meta['world_name']}</a></p>
</body></html>
"""
        (wiki_dir / f"{land['slug']}.html").write_text(html)


def main():
    """Build the index and one article per landmass from the metadata."""
    meta = json.loads((cfg.data_dir / "meta.json").read_text())
    build_index(meta)
    build_articles(meta)
    print(f"built index.html and {len(meta['articles'])} articles")


if __name__ == "__main__":
    main()
