"""
IRRI-DRIP — field layout on a map.

Draw the field boundary on a map, and the program takes its area, its true
dimensions and its orientation from the polygon instead of from a typed
number. This was the largest gap in IRRI-DRIP: every version to 0.6.0 knew
only "5.00 ha" and had to assume a rectangle, which is why the DXF export
carries a note saying it is not a site plan.

The map is folium with its Draw plugin, the same stack OpenIrri uses. It
needs no account and no API key: tiles come from OpenStreetMap. (OpenIrri
also has a Google Earth Engine module for satellite imagery, which DOES need
a service account; that is a separate, optional feature and is not required
for drawing.)

PROJECTION
----------
Coordinates are converted to a local metric frame by the equirectangular
approximation about the polygon's own centroid:

    x = (lon - lon0) * 111320 * cos(lat0)
    y = (lat - lat0) * 111320

This is the same approximation OpenIrri uses. It is accurate to well under a
metre over a field a few hundred metres across, which is the scale this
program works at, and it degrades over tens of kilometres. The distortion is
reported on the page rather than left implicit.
"""

from __future__ import annotations

import math

import streamlit as st

from engine import kernels as K
from engine import kml as KML
from modules.common import (section, cards, note, caption, banner, save,
                            welcome)

try:
    import folium
    from folium.plugins import Draw
    from streamlit_folium import st_folium
    MAP_AVAILABLE = True
    MAP_IMPORT_ERROR = ""
except Exception as exc:                                  # noqa: BLE001
    MAP_AVAILABLE = False
    MAP_IMPORT_ERROR = str(exc)

M_PER_DEG_LAT = 111320.0


# ---------------------------------------------------------------------------
# Geometry — pure functions, no Streamlit, so they are testable
# ---------------------------------------------------------------------------

def centroid(latlon: list[list[float]]) -> tuple[float, float]:
    lats = [p[0] for p in latlon]
    lons = [p[1] for p in latlon]
    return sum(lats) / len(lats), sum(lons) / len(lons)


def to_local(latlon: list[list[float]],
             origin: tuple[float, float] | None = None) -> list[list[float]]:
    """
    [[lat, lon], ...] -> [[x, y], ...] in metres about the centroid.

    Equirectangular about the origin latitude. Good to sub-metre over a few
    hundred metres; not a substitute for a projected CRS over a survey.
    """
    if not latlon:
        return []
    lat0, lon0 = origin if origin else centroid(latlon)
    mx = M_PER_DEG_LAT * math.cos(math.radians(lat0))
    return [[(lon - lon0) * mx, (lat - lat0) * M_PER_DEG_LAT]
            for lat, lon in latlon]


def to_gps(local: list[list[float]],
           origin: tuple[float, float]) -> list[list[float]]:
    """
    Inverse of :func:`to_local`: [[x, y], ...] in metres -> [[lat, lon], ...].

    Must use the SAME origin latitude as the forward transform, because the
    east scale depends on it. Passing a different origin does not fail; it
    quietly shifts the result, which is why the origin is required here rather
    than defaulted.
    """
    lat0, lon0 = origin
    mx = M_PER_DEG_LAT * math.cos(math.radians(lat0))
    return [[lat0 + y / M_PER_DEG_LAT, lon0 + x / mx] for x, y in local]


def long_axis_endpoints(centre: tuple[float, float], long_m: float,
                        bearing_deg: float) -> list[list[float]]:
    """
    The two ends of the best-fit rectangle's long axis, through the centroid.

    Bearing is clockwise from north, so the unit vector in local metres is
    (east, north) = (sin b, cos b). Drawn in the exported KML so the direction
    the program recommends for the laterals can be seen on the satellite image
    instead of only read as a number.

    On a markedly non-rectangular field the axis can run outside the boundary
    near its ends. That is the honest picture of a best-fit rectangle, and the
    rectangularity figure on the page is what says how much to trust it.
    """
    b = math.radians(bearing_deg)
    hx = math.sin(b) * long_m / 2.0
    hy = math.cos(b) * long_m / 2.0
    return to_gps([[-hx, -hy], [hx, hy]], centre)


def polygon_area_m2(local: list[list[float]]) -> float:
    """Shoelace. Returns the absolute area, so winding order does not matter."""
    n = len(local)
    if n < 3:
        return 0.0
    a = 0.0
    for i in range(n):
        x1, y1 = local[i]
        x2, y2 = local[(i + 1) % n]
        a += x1 * y2 - x2 * y1
    return abs(a) / 2.0


def oriented_extent(local: list[list[float]]) -> dict:
    """
    The best-fitting rectangle's dimensions and bearing.

    A field is rarely aligned to north, and laterals are laid along its long
    axis. Rotating calipers over the convex hull would be exact; a 1-degree
    scan of the bounding box is within a fraction of a per cent for a field
    boundary and needs no dependency.

    Returns the long and short sides in metres, and the bearing of the long
    axis in degrees clockwise from north, which is the direction the laterals
    should run.
    """
    if len(local) < 3:
        return {"long_m": 0.0, "short_m": 0.0, "bearing_deg": 0.0,
                "fill_ratio": 0.0}
    best = None
    for deg in range(0, 180):
        t = math.radians(deg)
        c, s = math.cos(t), math.sin(t)
        xs = [x * c + y * s for x, y in local]
        ys = [-x * s + y * c for x, y in local]
        w = max(xs) - min(xs)
        h = max(ys) - min(ys)
        if best is None or w * h < best[0]:
            best = (w * h, w, h, deg)
    _, w, h, deg = best
    long_m, short_m = (w, h) if w >= h else (h, w)
    # bearing of the long axis, clockwise from north
    axis_deg = deg if w >= h else deg + 90
    bearing = (90.0 - axis_deg) % 180.0
    area = polygon_area_m2(local)
    return {"long_m": long_m, "short_m": short_m, "bearing_deg": bearing,
            "fill_ratio": area / (long_m * short_m) if long_m * short_m else 0.0}



def parse_coordinates(text: str) -> tuple[list[list[float]], str]:
    """
    Parse a pasted boundary into [[lat, lon], ...].

    Accepts what people actually have to hand:
      - "lat, lon" one pair per line (Google Maps, a GPS handset, a survey)
      - "lat lon" or "lat;lon"
      - GeoJSON or KML coordinate strings, which are lon,lat — detected and
        swapped, because a silent transposition would put an Egyptian field
        in the Indian Ocean.

    Returns (points, message). An empty list means nothing usable was found
    and the message says why.
    """
    if not text or not text.strip():
        return [], ""
    pts, bad = [], 0
    for raw in text.replace(";", "\n").splitlines():
        line = raw.strip().strip(",")
        if not line or line.startswith("#"):
            continue
        parts = [p for p in line.replace(",", " ").split() if p]
        if len(parts) < 2:
            bad += 1
            continue
        try:
            a, b = float(parts[0]), float(parts[1])
        except ValueError:
            bad += 1
            continue
        pts.append([a, b])
    if len(pts) < 3:
        return [], (f"Found {len(pts)} usable point(s); a boundary needs at "
                    "least three. Put one point per line as 'lat, lon'.")

    # Order detection. Latitude is bounded at +/-90; longitude is not. If any
    # first value is outside +/-90 the columns must be lon,lat (GeoJSON/KML).
    if any(abs(p[0]) > 90 for p in pts):
        pts = [[p[1], p[0]] for p in pts]
        note_txt = ("Read as lon,lat and swapped to lat,lon — a value beyond "
                    "±90 in the first column cannot be a latitude.")
    else:
        note_txt = ""
    if any(abs(p[0]) > 90 or abs(p[1]) > 180 for p in pts):
        return [], ("Some values are outside the valid range for latitude "
                    "(±90) or longitude (±180). Check the paste.")
    if pts[0] == pts[-1] and len(pts) > 3:
        pts = pts[:-1]                     # a closed ring
    msg = note_txt
    if bad:
        msg = (msg + " " if msg else "") + f"{bad} line(s) could not be read and were skipped."
    return pts, msg



# ---------------------------------------------------------------------------
# File readers — the order is DEFINED by the format, so nothing is guessed
# ---------------------------------------------------------------------------

def _kmz_documents(data: bytes) -> tuple[list[bytes], str]:
    """
    Every .kml inside a KMZ, best candidate first.

    The KMZ convention is a single ``doc.kml`` at the archive root beside a
    ``files/`` directory of images and styles, but nothing enforces it: the
    main document can carry any name, and other .kml entries can sit beside
    it. So the order is doc.kml, then anything at the root, then the rest —
    and the caller tries them in turn rather than trusting the first.

    A KMZ larger than this is refused rather than expanded: a zip bomb is a
    real upload, and a boundary file has no business being tens of megabytes.
    """
    import io
    import zipfile

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = [n for n in z.namelist() if n.lower().endswith(".kml")]
            if not names:
                return [], ("The KMZ archive contains no .kml document. If it "
                            "holds a network link to an online map, open it in "
                            "Google Earth and save the placemark as KML first.")
            total = sum(z.getinfo(n).file_size for n in names)
            if total > 64 * 1024 * 1024:
                return [], (f"The KML inside this KMZ expands to {total/1e6:.0f} MB, "
                            "which is far larger than any field boundary. Refused.")

            def rank(n: str) -> tuple[int, str]:
                low = n.lower()
                if low == "doc.kml":
                    return (0, low)
                return (1 if "/" not in n else 2, low)

            return [z.read(n) for n in sorted(names, key=rank)], ""
    except (zipfile.BadZipFile, RuntimeError, OSError) as exc:
        return [], f"This KMZ could not be opened: {exc}"


def parse_kml(data: bytes | str) -> tuple[list[list[float]], str]:
    """
    Read the first polygon out of a KML (or KMZ) document.

    KML and GeoJSON both store coordinates as lon,lat. Reading the file
    format directly means the order is KNOWN rather than inferred, which
    matters because inference genuinely fails: at Wadi El-Natrun the station's
    longitude is 30.36 and its latitude is 30.39, so BOTH columns are under
    90 and no rule based on magnitude can tell them apart. Taken the wrong way
    round, that real boundary still reports 5.20 ha against a true 5.20 ha —
    the area a user would sanity-check is unchanged — while the long axis
    comes out 283 m instead of 268 m and its bearing 62 degrees instead of 21.
    Laterals laid on that bearing would be 41 degrees off the field.
    """
    import xml.etree.ElementTree as ET

    if isinstance(data, bytes):
        if data[:2] == b"PK":                    # a KMZ is a zip
            docs, err = _kmz_documents(data)
            if err:
                return [], err
            # Try every candidate, best first, and keep the first that yields
            # a polygon. Picking namelist()[0] was wrong: a Google Earth KMZ
            # routinely carries a legend or style .kml alongside doc.kml, and
            # whichever the zip happened to list first won. The failure was
            # silent — "no polygon found" on a file that plainly has one.
            last = "The KMZ archive contains no readable polygon."
            for doc in docs:
                pts, msg = parse_kml(doc)
                if pts:
                    return pts, msg
                last = msg or last
            return [], last
        text = data.decode("utf-8", errors="replace")
    else:
        text = data

    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        return [], f"This does not parse as KML: {exc}"

    def strip(tag):
        return tag.rsplit("}", 1)[-1]

    # The outer boundary of the first Polygon in the document.
    for elem in root.iter():
        if strip(elem.tag) != "Polygon":
            continue
        for sub in elem.iter():
            if strip(sub.tag) != "outerBoundaryIs":
                continue
            for coord in sub.iter():
                if strip(coord.tag) != "coordinates" or not (coord.text or "").strip():
                    continue
                pts = []
                for triple in coord.text.split():
                    parts = triple.split(",")
                    if len(parts) < 2:
                        continue
                    try:
                        lon, lat = float(parts[0]), float(parts[1])
                    except ValueError:
                        continue
                    pts.append([lat, lon])          # KML is lon,lat
                if len(pts) > 3 and pts[0] == pts[-1]:
                    pts = pts[:-1]                  # drop the closing vertex
                if len(pts) >= 3:
                    return pts, ""
                return [], "The polygon in this KML has fewer than three points."
    return [], "No polygon with an outer boundary was found in this KML."


def parse_geojson(data: bytes | str) -> tuple[list[list[float]], str]:
    """First Polygon in a GeoJSON document. GeoJSON is lon,lat by spec."""
    import json as _json
    if isinstance(data, bytes):
        data = data.decode("utf-8", errors="replace")
    try:
        obj = _json.loads(data)
    except ValueError as exc:
        return [], f"This does not parse as GeoJSON: {exc}"

    def rings(node):
        if isinstance(node, dict):
            if node.get("type") == "Polygon" and node.get("coordinates"):
                yield node["coordinates"][0]
            for v in node.values():
                yield from rings(v)
        elif isinstance(node, list):
            for v in node:
                yield from rings(v)

    for ring in rings(obj):
        pts = [[p[1], p[0]] for p in ring
               if isinstance(p, (list, tuple)) and len(p) >= 2]
        if len(pts) > 3 and pts[0] == pts[-1]:
            pts = pts[:-1]
        if len(pts) >= 3:
            return pts, ""
    return [], "No polygon was found in this GeoJSON."


def read_boundary_file(name: str, data: bytes) -> tuple[list[list[float]], str]:
    """Dispatch on the file extension."""
    low = (name or "").lower()
    if low.endswith((".kml", ".kmz")):
        return parse_kml(data)
    if low.endswith((".geojson", ".json")):
        return parse_geojson(data)
    return [], (f"Unsupported file type: {name}. Use .kml, .kmz, .geojson "
                "or .json, or paste the coordinates instead.")


def order_is_ambiguous(pts: list[list[float]]) -> bool:
    """
    True when nothing in the numbers can settle lat,lon versus lon,lat.

    Both columns within +/-90 means either reading is arithmetically valid.
    Egypt has real places where this bites: at Wadi El-Natrun longitude 30.36
    and latitude 30.39 are indistinguishable by magnitude.
    """
    return all(abs(p[0]) <= 90 and abs(p[1]) <= 90 for p in pts)


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------

DEFAULT_CENTRE = (30.60, 31.50)      # East Delta, a neutral starting view



def _render_map(prev: dict, boundary: list[list[float]] | None = None):
    """
    Build and show the folium map. Only called when the libraries imported.

    When a boundary has already arrived from a file or a paste, the map
    centres on IT rather than on the default view. Uploading the Wadi
    El-Natrun boundary and then finding the map still parked over the East
    Delta, 130 km away, makes the map look broken and gives the user no way
    to see what was just read.
    """
    if boundary:
        clat, clon = centroid(boundary)
    else:
        clat, clon = prev.get("centre", DEFAULT_CENTRE)
    c1, c2 = st.columns([1, 1])
    with c1:
        lat0 = st.number_input("Centre latitude", value=float(clat),
            format="%.5f", min_value=-85.0, max_value=85.0, step=0.01,
            key="idr_map_lat")
    with c2:
        lon0 = st.number_input("Centre longitude", value=float(clon),
            format="%.5f", min_value=-180.0, max_value=180.0, step=0.01,
            key="idr_map_lon")

    # scrollWheelZoom off. The map fills most of the viewport, so scrolling
    # the page to reach the measurements below it went into the map instead
    # and zoomed it — the user loses the view they just framed and never
    # reaches the numbers. Found by scrolling the real page on the user's own
    # machine. Zoom stays available on the +/- control and on double-click.
    fmap = folium.Map(location=[lat0, lon0], zoom_start=15,
                      tiles="OpenStreetMap", control_scale=True,
                      scrollWheelZoom=False)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/"
              "World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri World Imagery", name="Satellite", overlay=False,
        control=True).add_to(fmap)
    folium.LayerControl().add_to(fmap)
    Draw(export=False,
         draw_options={"polyline": False, "circle": False,
                       "circlemarker": False, "marker": False,
                       "rectangle": True, "polygon": True},
         edit_options={"edit": True}).add_to(fmap)
    shown = boundary or prev.get("boundary_gps")
    if shown:
        folium.Polygon(shown, color="#0078d4", weight=3, fill=True,
                       fill_opacity=0.18,
                       tooltip="Boundary in use").add_to(fmap)
        # Frame it, so a field a few hundred metres across is not a dot.
        lats = [p[0] for p in shown]
        lons = [p[1] for p in shown]
        fmap.fit_bounds([[min(lats), min(lons)], [max(lats), max(lons)]],
                        padding=(30, 30))
    return st_folium(fmap, height=520, width=None,
                     returned_objects=["all_drawings"], key="idr_map")


def boundary_step(S):
    """
    Step 1 of the Field Layout & Blocks workflow on the Home page.

    Four routes to the boundary: a KML/KMZ/GeoJSON file, typed coordinates,
    a drawing on the map, or — with no geodata at all — the field's length
    and width, which gives an assumed rectangle that every later page labels
    as such.
    """
    prev = S.get("layout", {})

    st.markdown("### 📐 Draw Main Field Boundary")
    boundary = None
    source_label = ""

    section("Option A — upload the boundary file")
    caption(
        "A <code>.kml</code> or <code>.kmz</code> from Google Earth, or a "
        "<code>.geojson</code>. <b>This is the most reliable route:</b> the file "
        "format defines which column is longitude, so nothing has to be "
        "guessed. Works with no internet."
        "<br><b>From Google Earth Pro:</b> draw the field with the polygon "
        "tool, then right-click the placemark in <i>Places</i> and choose "
        "<i>Save Place As…</i> — either .kml or .kmz works, and a .kmz that "
        "contains several documents is handled. If the placemark is a network "
        "link to an online map, save it as KML first: a link carries no "
        "coordinates.")
    up = st.file_uploader("Boundary file", type=["kml", "kmz", "geojson", "json"],
                          label_visibility="collapsed")
    if up is not None:
        pts, msg = read_boundary_file(up.name, up.getvalue())
        if msg:
            banner("bad", msg)
        if pts:
            boundary = pts
            source_label = f"file <b>{up.name}</b>"
            banner("ok", f"Read <b>{len(pts)} points</b> from <b>{up.name}</b>. "
                         "Longitude and latitude come from the file format, "
                         "not from a guess.")

    section("Option B — type or paste the boundary")
    caption(
        "One point per line as <code>lat, lon</code>. Also works with no "
        "internet, but the column order has to be inferred — see the warning "
        "below if it cannot be.")
    pasted = st.text_area(
        "Boundary coordinates",
        value=prev.get("pasted_text", ""),
        height=120,
        placeholder="30.60100, 31.50100\n30.60100, 31.50220\n"
                    "30.60190, 31.50220\n30.60190, 31.50100",
        label_visibility="collapsed")
    if pasted.strip() and boundary is None:
        pts, msg = parse_coordinates(pasted)
        if msg:
            note(msg)
        if pts:
            if order_is_ambiguous(pts):
                # Both columns within +/-90: arithmetic cannot settle it. Ask,
                # rather than assume. At Wadi El-Natrun (lon 30.36, lat 30.39)
                # assuming wrongly leaves the AREA almost unchanged — 5.20 ha
                # either way — while the long axis bearing moves from 21 to 62
                # degrees. Nothing on the page would have looked wrong.
                banner("warn",
                       "<b>The column order cannot be determined from these "
                       "numbers.</b> Both values in every row are within ±90, "
                       "so either reading is arithmetically valid — this "
                       "happens wherever longitude and latitude are close, and "
                       "Wadi El-Natrun (30.36 E, 30.39 N) is exactly such a "
                       "place. Getting it wrong barely changes the AREA, so "
                       "nothing looks wrong, but it can move the long-axis "
                       "bearing by tens of degrees — and that is the direction "
                       "the laterals run. Check the box below if your first "
                       "column is longitude, or upload the file instead.")
                if st.checkbox("My first column is longitude (KML / GeoJSON order)",
                               value=prev.get("swap_order", False),
                               key="idr_swap_order"):
                    pts = [[p[1], p[0]] for p in pts]
            boundary = pts
            source_label = "pasted coordinates"
            banner("ok", f"Read <b>{len(pts)} points</b> from the paste.")

    section("Option C — draw it on the map")
    if not MAP_AVAILABLE:
        banner("bad",
               "<b>The map libraries are not installed.</b> This page needs "
               "<code>folium</code> and <code>streamlit-folium</code>. Import "
               f"error: <code>{MAP_IMPORT_ERROR}</code><br>"
               "Close the program and run <code>Run_IRRI_DRIP.bat</code> again "
               "— it now checks for them and installs what is missing. "
               "<b>Options A and B above still work</b>, and every number this page "
               "produces comes from the coordinates, not from the map.")
        out = None
    else:
        # The warning goes ABOVE the map, not below it. Below, the reader
        # stares at a blank rectangle first and only then finds out why.
        banner("warn",
               "<b>The map needs internet access.</b> Folium loads the Leaflet "
               "library from <code>cdn.jsdelivr.net</code> and its tiles from "
               "OpenStreetMap. On a network that blocks those — which many "
               "ministry and institute networks do — <b>the map below simply "
               "appears blank, with no error message of its own</b>. That is "
               "the network, not a fault in the program. Use Option A or B in that "
               "case: every number on this page comes from the coordinates, "
               "not from the map.")
        caption(
            "Drag to pan; zoom with the <b>+ / −</b> buttons or a double-click. "
            "The scroll wheel deliberately does not zoom, so scrolling the page "
            "past the map does not throw away the view you just framed. Then "
            "use the polygon or rectangle tool on the left. Draw one closed "
            "shape; redrawing replaces it.")
        out = _render_map(prev, boundary)

    section("Option D — no geodata: field length and width")
    caption("An assumed rectangle, long side north–south. Every page built on it "
            "says so, and nothing georeferenced is exported from it.")
    c1, c2, c3 = st.columns([1, 1, 1])
    with c1:
        rect_l = st.number_input("Field length (m)", min_value=10.0, max_value=5000.0,
                                 value=float(prev.get("rect_length_m", 250.0)), step=5.0,
                                 key="idr_rect_l")
    with c2:
        rect_w = st.number_input("Field width (m)", min_value=10.0, max_value=5000.0,
                                 value=float(prev.get("rect_width_m", 200.0)), step=5.0,
                                 key="idr_rect_w")
    with c3:
        st.write("")
        st.write("")
        use_rect = st.button("📝 Use this rectangle", key="idr_use_rect")
    if use_rect:
        from engine import subunits as _SU
        rect = _SU.rectangle_polygon(rect_l, rect_w)
        ext_r = oriented_extent(rect)
        save(S, "layout", {
            "source": "assumed rectangle", "assumed_rectangle": True,
            "boundary_gps": None, "boundary_local": rect, "centre": None,
            "area_m2": rect_l * rect_w, "area_ha": rect_l * rect_w / 10000.0,
            "long_m": ext_r["long_m"], "short_m": ext_r["short_m"],
            "bearing_deg": ext_r["bearing_deg"], "fill_ratio": 1.0,
            "rect_length_m": rect_l, "rect_width_m": rect_w,
        })
        _invalidate_blocks(S)
        st.success(f"✅ Assumed rectangle {rect_l:.0f} m × {rect_w:.0f} m saved "
                   f"({rect_l*rect_w/10000:.2f} ha). Continue with step 2.")

    boundary = boundary or _extract_polygon(out) or prev.get("boundary_gps")
    if not boundary:
        if prev.get("assumed_rectangle"):
            banner("warn", f"Using an <b>assumed rectangle</b> of "
                           f"{prev['rect_length_m']:.0f} m × {prev['rect_width_m']:.0f} m. "
                           "Upload or draw the real boundary to replace it.")
        else:
            note("Nothing drawn yet. Use one of the four options above.")
        return

    local = to_local(boundary)
    area_m2 = polygon_area_m2(local)
    area_ha = area_m2 / 10000.0
    ext = oriented_extent(local)
    lat_c, lon_c = centroid(boundary)

    section("Measured from the polygon")
    cards([
        ("Area", f"{area_ha:.3f}", "ha", "accent"),
        ("Long axis", f"{ext['long_m']:.1f}", "m", "neutral"),
        ("Short axis", f"{ext['short_m']:.1f}", "m", "neutral"),
        ("Long-axis bearing", f"{ext['bearing_deg']:.0f}", "° from N", "neutral"),
    ])
    cards([
        ("Vertices", f"{len(boundary)}", "", "neutral"),
        ("Centroid", f"{lat_c:.5f}, {lon_c:.5f}", "", "neutral"),
        ("Rectangularity", f"{ext['fill_ratio']*100:.0f}", "%",
         "ok" if ext["fill_ratio"] > 0.85 else "warn"),
    ])

    if ext["fill_ratio"] <= 0.85:
        note(
            f"The boundary fills only <b>{ext['fill_ratio']*100:.0f} %</b> of "
            "its best-fitting rectangle, so the field is materially "
            "non-rectangular. The area above is the true polygon area and is "
            "correct, but the hydraulic design still lays out uniform "
            "rectangular blocks, and the DXF will show them that way. Expect "
            "to trim laterals against the boundary on site, and treat the "
            "lateral count as an upper bound.")

    note(
        "Laterals should run along the <b>long axis</b> where the ground "
        f"allows — here a bearing of about <b>{ext['bearing_deg']:.0f}°</b> "
        "from north. Running them along the short axis multiplies the number "
        "of manifold connections and the manifold length for the same area.")

    caption(
        "Projection: equirectangular about the centroid, "
        f"x = Δlon · 111320 · cos({lat_c:.2f}°), y = Δlat · 111320. Sub-metre "
        "over a few hundred metres, which is this program's working scale. It "
        "is not a substitute for a projected CRS over a survey, and the area "
        "here should be checked against the title deed or a GPS traverse "
        "before it goes into a contract.")

    # --- export ----------------------------------------------------------
    # The boundary can arrive three ways, and two of them (typed coordinates,
    # drawn on the map) previously had no way out of the program. A boundary
    # you can only see inside one Streamlit session is not a record: it cannot
    # be checked in Google Earth against the satellite image, sent to a
    # colleague, or kept with the project file. It goes out in the same format
    # it comes in.
    section("Export the field")
    stem = K.safe_filename(S.get("setup", {}).get("name", "") or "field")
    axis = long_axis_endpoints((lat_c, lon_c), ext["long_m"], ext["bearing_deg"])
    desc = (
        f"Area {area_ha:.3f} ha ({area_m2:,.0f} m2). "
        f"Long axis {ext['long_m']:.1f} m, short axis {ext['short_m']:.1f} m, "
        f"long-axis bearing {ext['bearing_deg']:.0f} deg from north. "
        f"{len(boundary)} vertices, rectangularity {ext['fill_ratio']*100:.0f} %. "
        f"Source: {source_label or 'map drawing'}. "
        "Measured by IRRI-DRIP, Water Management Research Institute. "
        "Equirectangular projection about the centroid: check against a "
        "surveyed traverse before contractual use.")
    st.download_button(
        "⬇  Download the field (.kml)",
        KML.boundary_kml(boundary, name=stem, description=desc,
                         long_axis=axis, centroid_latlon=[lat_c, lon_c]).encode("utf-8"),
        file_name=f"IRRI-DRIP_{stem}.kml",
        mime="application/vnd.google-earth.kml+xml")
    caption(
        "Opens in Google Earth, QGIS or any GIS. It carries the boundary, a "
        "centroid marker, and the long axis drawn as a red line — the "
        "direction the laterals should run. The measured figures are written "
        "into the placemark description, so the file explains itself a year "
        "from now. Coordinates are written <b>lon,lat</b> as the KML "
        "specification requires; a file exported here re-imports into this "
        "program unchanged.")

    if st.button("✅ Boundary Complete → Save", type="primary", key="idr_save_boundary"):
        keep = {k: prev[k] for k in ("source_local", "source_gps", "blocks")
                if k in prev and not prev.get("assumed_rectangle")}
        save(S, "layout", {**keep,
            "pasted_text": pasted,
            "source": source_label or "map drawing",
            "swap_order": bool(st.session_state.get("idr_swap_order", False)),
            "boundary_gps": boundary,
            "boundary_local": local,
            "centre": [lat_c, lon_c],
            "area_m2": area_m2,
            "area_ha": area_ha,
            "long_m": ext["long_m"],
            "short_m": ext["short_m"],
            "bearing_deg": ext["bearing_deg"],
            "fill_ratio": ext["fill_ratio"],
            "assumed_rectangle": False,
        })
        if not same_boundary(prev.get("boundary_gps"), boundary):
            _invalidate_blocks(S)
        # No push into setup: the Project Setup tab PULLS this measurement.
        st.success("✅ Boundary saved. Continue with step 2 — Mark Water Source.")


def same_boundary(a, b, tol=1e-9) -> bool:
    if not a or not b or len(a) != len(b):
        return False
    return all(abs(p[0] - q[0]) <= tol and abs(p[1] - q[1]) <= tol for p, q in zip(a, b))


def _invalidate_blocks(S):
    """A new boundary makes the old blocks meaningless: they are cut from it."""
    lay = S.get("layout") or {}
    if lay.get("blocks"):
        lay["blocks"] = []
    for k in ("operation", "network", "lateral", "manifold", "hydraulic"):
        S.pop(k, None)


def _extract_polygon(map_out) -> list[list[float]] | None:
    """
    Pull the last drawn polygon out of st_folium's GeoJSON, as [[lat, lon], ...].

    GeoJSON is [lon, lat]; folium and the rest of this module use [lat, lon].
    Getting that order wrong silently transposes the field and would put an
    Egyptian farm in the Indian Ocean, so the swap happens once, here.
    """
    if not map_out:
        return None
    drawings = map_out.get("all_drawings") or []
    for feature in reversed(drawings):
        geom = (feature or {}).get("geometry") or {}
        if geom.get("type") != "Polygon":
            continue
        rings = geom.get("coordinates") or []
        if not rings or len(rings[0]) < 4:
            continue
        ring = rings[0]
        if ring[0] == ring[-1]:            # GeoJSON closes the ring
            ring = ring[:-1]
        return [[pt[1], pt[0]] for pt in ring]
    return None
