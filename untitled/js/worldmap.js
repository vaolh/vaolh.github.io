/* REPLICATION FILE: worldmap.js
   JS RUNTIME:       browser, maplibre-gl v4
   LAST EDIT:        2026-06-11 by vao2116

   Interactive viewer for the supercontinent, built to match the aesthetic of
   the millmint factbook globe: a MapLibre GL line-art globe that toggles to a
   flat mercator map, with a graticule, a dashed equator, and a single
   clickable landmass that highlights on hover and
   links to its wiki article. */

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

    let highlight = css_color("--wm-highlight", "#0055cc");
    let land_fill = css_color("--wm-land", "#f5f5f5");
    let highlight_fill = css_color("--wm-highlight-bg", "rgba(0,85,204,0.16)");

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

    /* Reapply the fill colour expression after a hover, select or theme change. */
    function refresh_fill(map) {
        map.setPaintProperty("land-fill", "fill-color", [
            "case",
            ["boolean", ["feature-state", "selected"], false], highlight_fill,
            ["boolean", ["feature-state", "hover"], false], highlight_fill,
            land_fill
        ]);
    }

    /* Wire the reset, globe-toggle and fullscreen controls. */
    function attach_controls(map) {
        document.getElementById("wm-btn-reset").addEventListener("click",
            function () {
                map.flyTo({
                    center: [meta.center_lon, meta.center_lat],
                    zoom: reset_zoom, speed: 1.6 });
            });

        document.getElementById("wm-btn-globe").addEventListener("click",
            function () {
                is_globe = !is_globe;
                map.setProjection({ type: is_globe ? "globe" : "mercator" });
                this.classList.toggle("active", is_globe);
                this.textContent = is_globe ? "Globe" : "Flat map";
            });

        document.getElementById("wm-btn-fs").addEventListener("click",
            function () {
                const outer = document.getElementById(map_id + "-outer");
                const full = outer.classList.toggle("vk-fullscreen");
                document.body.classList.toggle("vk-map-fullscreen", full);
                setTimeout(function () { map.resize(); }, 60);
            });
    }

    /* React to colour-scheme changes so the globe matches the active theme. */
    function watch_theme(map) {
        const apply = function () {
            highlight = css_color("--wm-highlight", "#0055cc");
            land_fill = css_color("--wm-land", "#f5f5f5");
            highlight_fill = css_color("--wm-highlight-bg",
                                       "rgba(0,85,204,0.16)");
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
            center: [meta.center_lon, meta.center_lat],
            zoom: reset_zoom, dragRotate: false, minZoom: 0, maxZoom: 20
        });

        map.on("load", function () {
            map.setProjection({ type: "globe" });
            /* Disable the globe atmosphere entirely so there is no blue halo. */
            map.setSky({ "atmosphere-blend": 0 });

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

            fetch(data_path + "land.geojson")
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    map.addSource("land", { type: "geojson", data: data,
                                            generateId: true });
                    map.addLayer({ id: "land-fill", type: "fill",
                        source: "land",
                        paint: { "fill-color": land_fill, "fill-opacity": 1 } });
                    map.addLayer({ id: "land-line", type: "line",
                        source: "land",
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
