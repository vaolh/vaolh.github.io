#################################################
################ PAGE BUILDER ###################
#################################################

import json

import config as cfg

### REPLICATION FILE: build_pages.py
### PYTHON VERSION:   3.13+
### LAST EDIT:        2026-06-11 by vao2116

"""Generation of the wiki shell from the world metadata.

The world home page embeds the interactive MapLibre globe and the single
supercontinent is the only clickable feature, linking to its article. Pages
reuse the shared wiki styling through ``css/world.css`` so the map, the index
and the article form a navigable wiki in the millmint factbook style.
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
    """Write the world home page with the embedded globe."""
    extra = (f'<link rel="stylesheet" href="{maplibre_css}">\n'
             f'<script src="{maplibre_js}"></script>')
    name = meta["supercontinent_name"]
    html = _head(meta["world_name"], "", extra)
    html += f"""<h1>{meta['world_name']}</h1>

<p><b>{meta['world_name']}</b> is the world of an unnamed fantasy setting, shown
here in its <b>supercontinent era</b>. Its land is gathered into a single
landmass, the <b>{name}</b>, assembled by a simulated system of
{meta['plate_count']} tectonic plates. Drag to spin the globe, scroll to zoom,
toggle the flat map, and click the {name} to open its article.</p>

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
      <button id="wm-btn-fs" class="vk-ctrl-btn" title="Toggle fullscreen">Fullscreen</button>
    </div>
  </div>
  <div id="world-map-tooltip"><div class="vkl-popup-inner"></div></div>
</div>

<script src="js/worldmap.js"></script>
</body></html>
"""
    (cfg.project_dir / "index.html").write_text(html)


def build_article(meta):
    """Write the single supercontinent article with a geography infobox."""
    wiki_dir = cfg.project_dir / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)
    name = meta["supercontinent_name"]
    html = _head(f"{name} – {meta['world_name']}", "../")
    html += f"""<h1>{name}</h1>

<div class="infobox">
<div class="infobox-title">{name}</div>
<div class="infobox-section">Geography</div>
<table><tbody>
<tr><th>World</th><td><a href="../index.html">{meta['world_name']}</a></td></tr>
<tr><th>Era</th><td>Supercontinent</td></tr>
<tr><th>Land area</th><td>{_land_km2(meta['land_fraction']):,} km&sup2;</td></tr>
<tr><th>Share of globe</th><td>{round(meta['land_fraction'] * 100)}%</td></tr>
<tr><th>Highest point</th><td>{_meters(meta['highest_elevation']):,} m</td></tr>
<tr><th>Tectonic plates</th><td>{meta['plate_count']}</td></tr>
</tbody></table>
</div>

<p>The <b>{name}</b> is the single landmass of {meta['world_name']} during its
supercontinent era. It covers roughly {round(meta['land_fraction'] * 100)}% of
the planet's surface and was assembled by the convergence of
{meta['plate_count']} tectonic plates, whose collisions raised its mountain
belts and whose interior it now binds into one contiguous mass. Its highest
summit reaches about {_meters(meta['highest_elevation']):,} m above sea level.</p>

<p>This article is a stub. In later eras the {name} will rift apart into separate
continents, the stage on which the history of {meta['world_name']} unfolds.</p>

<p><a href="../index.html">&larr; Back to the map of {meta['world_name']}</a></p>
</body></html>
"""
    (wiki_dir / f"{meta['supercontinent_slug']}.html").write_text(html)


def main():
    """Build the index and the supercontinent article from the metadata."""
    meta = json.loads((cfg.data_dir / "meta.json").read_text())
    build_index(meta)
    build_article(meta)
    print("built index.html and the supercontinent article")


if __name__ == "__main__":
    main()
