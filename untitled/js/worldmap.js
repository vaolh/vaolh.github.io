/* REPLICATION FILE: worldmap.js
   JS RUNTIME:       browser, maplibre-gl v5
   LAST EDIT:        2026-06-12 by vao2116

   Interactive viewer for the world, in the aesthetic of the millmint factbook
   globe: a MapLibre GL globe of green continents on a blue ocean with white
   polar ice, that toggles to a flat mercator map. Each continent is a clickable
   feature that highlights on hover and links to its wiki article. */

(function () {
    "use strict";

    /* Identifiers and view constants. */
    const map_id = "world-map";
    const data_path = "data/";
    const reset_zoom = 2;
    const grid_step_lon = 15;
    const grid_step_lat = 10;

    /* Resolve a themed colour from a css custom property with a fallback. */
    function css_color(name, fallback) {
        const value = getComputedStyle(document.documentElement)
            .getPropertyValue(name).trim();
        return value || fallback;
    }

    let highlight = css_color("--wm-highlight", "#3a72ad");
    let land_fill = css_color("--wm-land", "#d6e8bf");
    let highlight_fill = css_color("--wm-highlight-bg", "rgba(58,114,173,0.3)");
    let ocean_fill = css_color("--wm-ocean", "#bcd6ec");
    let ice_fill = css_color("--wm-ice", "#ffffff");

    let meta = null;
    let is_globe = true;
    let selected_id = null;
    let hovered_id = null;

    /* Build the longitude and latitude graticule as a line feature set. */
    function graticule() {
        const features = [];
        for (let lng = -180; lng <= 180; lng += grid_step_lon) {
            features.push({ type: "Feature", geometry: {
                type: "LineString", coordinates: [[lng, -85], [lng, 85]] } });
        }
        for (let lat = -80; lat <= 80; lat += grid_step_lat) {
            if (lat !== 0) {
                features.push({ type: "Feature", geometry: {
                    type: "LineString",
                    coordinates: [[-180, lat], [180, lat]] } });
            }
        }
        return { type: "FeatureCollection", features: features };
    }

    /* Show the popup anchored at a geographic point with a link to the article. */
    function show_popup(map, feature, lnglat) {
        const popup = document.getElementById(map_id + "-tooltip");
        const inner = popup.querySelector(".vkl-popup-inner");
        const href = "wiki/" + feature.properties.slug + ".html";
        inner.innerHTML =
            '<div class="vkl-popup-title">' + feature.properties.name +
            '</div><a class="vkl-popup-link" href="' + href +
            '">Read more &rarr;</a>';
        popup.classList.add("open");
        popup._lnglat = lnglat;
        reposition_popup(map);
    }

    /* Keep an open popup pinned above its anchor point as the map moves. */
    function reposition_popup(map) {
        const popup = document.getElementById(map_id + "-tooltip");
        if (!popup.classList.contains("open") || !popup._lnglat) {
            return;
        }
        const wrap = document.getElementById(map_id + "-wrap");
        const point = map.project(popup._lnglat);
        let left = point.x - popup.offsetWidth / 2;
        left = Math.max(6, Math.min(left, wrap.clientWidth - popup.offsetWidth - 6));
        let top = point.y - popup.offsetHeight - 16;
        if (top < 6) {
            top = point.y + 16;
        }
        popup.style.left = left + "px";
        popup.style.top = top + "px";
    }

    function hide_popup() {
        document.getElementById(map_id + "-tooltip").classList.remove("open");
    }

    /* Reapply the fill colour expression after a hover, select or theme change.
       All land is green; the white polar ice is a separate gradient overlay. */
    function refresh_fill(map) {
        map.setPaintProperty("land-fill", "fill-color", [
            "case",
            ["boolean", ["feature-state", "selected"], false], highlight_fill,
            ["boolean", ["feature-state", "hover"], false], highlight_fill,
            land_fill
        ]);
    }

    /* Load the polar ice overlay. The latitude bands carry a per-feature "ice"
       opacity (solid at the poles, fading out toward the temperate latitudes)
       and sit beneath the coastline so the blue coast still reads through. The
       pole caps (cap === true) are solid white and sit ABOVE the coastline so
       they hide the ragged seams where continents are clamped short of the pole,
       leaving one clean ice cap. */
    function add_ice(map) {
        fetch(data_path + (meta.ice_file || "ice.geojson"))
            .then(function (r) { return r.json(); })
            .then(function (ice_data) {
                if (!ice_data.features || !ice_data.features.length) {
                    return;
                }
                map.addSource("ice", { type: "geojson", data: ice_data });
                map.addLayer({ id: "ice-fill", type: "fill", source: "ice",
                    filter: ["!=", ["get", "cap"], true],
                    paint: { "fill-color": ice_fill,
                             "fill-opacity": ["get", "ice"] } },
                    map.getLayer("land-line") ? "land-line" : undefined);
                map.addLayer({ id: "ice-cap", type: "fill", source: "ice",
                    filter: ["==", ["get", "cap"], true],
                    paint: { "fill-color": ice_fill, "fill-opacity": 1 } });
            })
            .catch(function () {});
    }

    /* Latitude the flat views centre on, and zoom they open at. */
    const flat_lat = -10;
    const flat_zoom = 0.3;

    /* Sync the globe button label to the current projection. */
    function set_globe_button(on_globe) {
        const button = document.getElementById("wm-btn-globe");
        button.classList.toggle("active", on_globe);
        button.textContent = on_globe ? "Globe" : "Flat map";
    }

    /* Show the spherical globe centred on the main landmass. */
    function show_globe(map) {
        is_globe = true;
        map.setProjection({ type: "globe" });
        map.flyTo({ center: [meta.center_lon, meta.center_lat],
                    zoom: reset_zoom, speed: 1.6 });
        set_globe_button(true);
    }

    /* Show the flat mercator map centred on a chosen longitude. */
    function show_flat(map, lon) {
        is_globe = false;
        map.setProjection({ type: "mercator" });
        map.flyTo({ center: [lon, flat_lat], zoom: flat_zoom, speed: 1.4 });
        set_globe_button(false);
    }

    /* Wire the globe-toggle, reset and fullscreen controls. */
    function attach_controls(map) {
        document.getElementById("wm-btn-reset").addEventListener("click",
            function () { show_globe(map); });

        document.getElementById("wm-btn-globe").addEventListener("click",
            function () {
                if (is_globe) {
                    show_flat(map, 0);
                } else {
                    show_globe(map);
                }
            });

        document.getElementById("wm-btn-fs").addEventListener("click",
            function () {
                const outer = document.getElementById(map_id + "-outer");
                const full = outer.classList.toggle("vk-fullscreen");
                document.body.classList.toggle("vk-map-fullscreen", full);
                setTimeout(function () { map.resize(); }, 60);
            });
    }

    /* Drop any hover or selection feature-state before reloading the source. */
    function clear_states(map) {
        if (hovered_id !== null) {
            map.setFeatureState({ source: "land", id: hovered_id },
                                { hover: false });
            hovered_id = null;
        }
        if (selected_id !== null) {
            map.setFeatureState({ source: "land", id: selected_id },
                                { selected: false });
            selected_id = null;
        }
    }

    /* React to colour-scheme changes so the globe matches the active theme. */
    function watch_theme(map) {
        const apply = function () {
            highlight = css_color("--wm-highlight", "#3a72ad");
            land_fill = css_color("--wm-land", "#d6e8bf");
            highlight_fill = css_color("--wm-highlight-bg",
                                       "rgba(58,114,173,0.3)");
            ocean_fill = css_color("--wm-ocean", "#bcd6ec");
            ice_fill = css_color("--wm-ice", "#ffffff");
            if (map.getLayer("ocean-fill")) {
                map.setPaintProperty("ocean-fill", "fill-color", ocean_fill);
            }
            ["ice-fill", "ice-cap"].forEach(function (id) {
                if (map.getLayer(id)) {
                    map.setPaintProperty(id, "fill-color", ice_fill);
                }
            });
            ["graticule-line", "equator-line", "land-line"].forEach(
                function (id) {
                    if (map.getLayer(id)) {
                        map.setPaintProperty(id, "line-color", highlight);
                    }
                });
            refresh_fill(map);
        };
        window.matchMedia("(prefers-color-scheme: dark)")
            .addEventListener("change", apply);
    }

    /* Build the map once the metadata and library are ready. */
    function init() {
        /* Allow the page to open straight into the flat map with #flat. */
        if (window.location.hash === "#flat") {
            is_globe = false;
        }

        const map = new maplibregl.Map({
            container: map_id,
            attributionControl: false,
            canvasContextAttributes: { antialias: true },
            style: {
                version: 8,
                sources: {},
                layers: [{ id: "space", type: "background",
                           paint: { "background-color": "rgba(0,0,0,0)" } }]
            },
            center: is_globe ? [meta.center_lon, meta.center_lat] : [0, -10],
            zoom: is_globe ? reset_zoom : 0.3,
            dragRotate: false, minZoom: 0, maxZoom: 20
        });

        map.on("load", function () {
            map.setProjection({ type: is_globe ? "globe" : "mercator" });
            /* Disable the globe atmosphere entirely so there is no blue halo. */
            map.setSky({ "atmosphere-blend": 0 });

            /* Ocean fills the whole sphere; the transparent space layer lets the
               page background show outside the globe. */
            map.addSource("ocean", { type: "geojson", data: {
                type: "FeatureCollection", features: [{ type: "Feature",
                    geometry: { type: "Polygon", coordinates: [[
                        [-180, -90], [180, -90], [180, 90], [-180, 90],
                        [-180, -90]]] } }] } });
            map.addLayer({ id: "ocean-fill", type: "fill", source: "ocean",
                paint: { "fill-color": ocean_fill } });

            map.addSource("graticule", { type: "geojson", data: graticule() });
            map.addLayer({ id: "graticule-line", type: "line",
                source: "graticule",
                paint: { "line-color": highlight, "line-width": 0.5,
                         "line-opacity": 0.4 } });

            map.addSource("equator", { type: "geojson", data: {
                type: "FeatureCollection", features: [{ type: "Feature",
                    geometry: { type: "LineString",
                        coordinates: [[-180, 0], [180, 0]] } }] } });
            map.addLayer({ id: "equator-line", type: "line", source: "equator",
                paint: { "line-color": highlight, "line-width": 1,
                         "line-dasharray": [4, 4], "line-opacity": 0.5 } });

            fetch(data_path + meta.eras[0].file)
                .then(function (r) { return r.json(); })
                .then(function (land_data) {
                map.addSource("land", { type: "geojson",
                    data: land_data, generateId: true });
                map.addLayer({ id: "land-fill", type: "fill", source: "land",
                    paint: { "fill-color": land_fill, "fill-opacity": 1 } });
                add_ice(map);
                map.addLayer({ id: "land-line", type: "line", source: "land",
                    paint: { "line-color": highlight, "line-width": [
                        "interpolate", ["linear"], ["zoom"],
                        2, 0.9, 6, 1.6, 10, 2.2] } });
                refresh_fill(map);
                attach_interaction(map);

                const loader = document.getElementById(map_id + "-loader");
                if (loader) {
                    loader.classList.add("hidden");
                }
            });
        });

        map.on("render", function () { reposition_popup(map); });
        attach_controls(map);
        watch_theme(map);
    }

    /* Hover highlight, click select and link behaviour on the landmass. */
    function attach_interaction(map) {
        map.on("mousemove", "land-fill", function (event) {
            map.getCanvas().style.cursor = "pointer";
            const id = event.features[0].id;
            if (hovered_id !== null && hovered_id !== id) {
                map.setFeatureState({ source: "land", id: hovered_id },
                                    { hover: false });
            }
            hovered_id = id;
            map.setFeatureState({ source: "land", id: id }, { hover: true });
        });

        map.on("mouseleave", "land-fill", function () {
            map.getCanvas().style.cursor = "";
            if (hovered_id !== null) {
                map.setFeatureState({ source: "land", id: hovered_id },
                                    { hover: false });
            }
            hovered_id = null;
        });

        map.on("click", "land-fill", function (event) {
            const feature = event.features[0];
            if (selected_id !== null) {
                map.setFeatureState({ source: "land", id: selected_id },
                                    { selected: false });
            }
            selected_id = feature.id;
            map.setFeatureState({ source: "land", id: selected_id },
                                { selected: true });
            show_popup(map, feature, event.lngLat);
            event.originalEvent.stopPropagation();
        });

        map.on("click", function (event) {
            const hits = map.queryRenderedFeatures(event.point,
                { layers: ["land-fill"] });
            if (!hits.length) {
                hide_popup();
                if (selected_id !== null) {
                    map.setFeatureState({ source: "land", id: selected_id },
                                        { selected: false });
                    selected_id = null;
                }
            }
        });
    }

    /* Load the metadata, then wait for the library before initialising. */
    function boot() {
        if (typeof maplibregl === "undefined") {
            return setTimeout(boot, 50);
        }
        fetch(data_path + "meta.json")
            .then(function (r) { return r.json(); })
            .then(function (data) { meta = data; init(); });
    }

    boot();
}());
