"""
Tests for the map field layout.

The geometry functions are deliberately free of Streamlit so they can be
tested without a browser. The map itself cannot be unit-tested here; what can
be, and what matters, is the projection, the area, the orientation and the
coordinate ORDER — a [lat, lon] / [lon, lat] swap is silent and would put an
Egyptian field in the Indian Ocean.
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.layout import (centroid, to_local, polygon_area_m2,
                            oriented_extent, _extract_polygon, M_PER_DEG_LAT)


# --------------------------------------------------------------------------
# Projection
# --------------------------------------------------------------------------

def test_one_degree_of_latitude_is_the_stated_constant():
    local = to_local([[30.0, 31.0], [31.0, 31.0]], origin=(30.0, 31.0))
    assert abs((local[1][1] - local[0][1]) - M_PER_DEG_LAT) < 1e-6


def test_longitude_is_scaled_by_the_cosine_of_latitude():
    """
    A degree of longitude shrinks towards the poles. At 30 N it is
    111320 * cos(30) = 96,406 m. Omitting the cosine is the classic error and
    would overstate an east-west field width by 15 % in Egypt.
    """
    local = to_local([[30.0, 31.0], [30.0, 32.0]], origin=(30.0, 31.0))
    expected = M_PER_DEG_LAT * math.cos(math.radians(30.0))
    assert abs((local[1][0] - local[0][0]) - expected) < 1e-6
    assert abs(expected - 96_406.0) < 50.0


def test_local_frame_is_centred_on_the_centroid():
    square = [[30.0, 31.0], [30.0, 31.001], [30.001, 31.001], [30.001, 31.0]]
    local = to_local(square)
    assert abs(sum(p[0] for p in local)) < 1e-6
    assert abs(sum(p[1] for p in local)) < 1e-6


def test_centroid_of_a_square():
    lat, lon = centroid([[30.0, 31.0], [30.0, 31.002],
                         [30.002, 31.002], [30.002, 31.0]])
    assert abs(lat - 30.001) < 1e-9
    assert abs(lon - 31.001) < 1e-9


# --------------------------------------------------------------------------
# Area
# --------------------------------------------------------------------------

def test_area_of_a_100m_square():
    local = [[0, 0], [100, 0], [100, 100], [0, 100]]
    assert abs(polygon_area_m2(local) - 10_000.0) < 1e-9      # exactly 1 ha


def test_area_ignores_winding_direction():
    cw = [[0, 0], [0, 100], [100, 100], [100, 0]]
    ccw = [[0, 0], [100, 0], [100, 100], [0, 100]]
    assert abs(polygon_area_m2(cw) - polygon_area_m2(ccw)) < 1e-9


def test_area_of_a_triangle():
    assert abs(polygon_area_m2([[0, 0], [200, 0], [0, 100]]) - 10_000.0) < 1e-9


def test_degenerate_polygons_have_no_area():
    assert polygon_area_m2([]) == 0.0
    assert polygon_area_m2([[0, 0], [1, 1]]) == 0.0


def test_area_round_trip_through_the_projection():
    """
    A real one-hectare field drawn at 30 N must come back as one hectare.
    100 m north-south is 100/111320 degrees of latitude; 100 m east-west is
    100/(111320 cos 30) degrees of longitude.
    """
    dlat = 100.0 / M_PER_DEG_LAT
    dlon = 100.0 / (M_PER_DEG_LAT * math.cos(math.radians(30.0)))
    field = [[30.0, 31.0], [30.0, 31.0 + dlon],
             [30.0 + dlat, 31.0 + dlon], [30.0 + dlat, 31.0]]
    area_ha = polygon_area_m2(to_local(field)) / 10_000.0
    assert abs(area_ha - 1.0) < 0.002, area_ha


# --------------------------------------------------------------------------
# Orientation
# --------------------------------------------------------------------------

def test_extent_of_an_axis_aligned_rectangle():
    ext = oriented_extent([[0, 0], [200, 0], [200, 50], [0, 50]])
    assert abs(ext["long_m"] - 200.0) < 1.0
    assert abs(ext["short_m"] - 50.0) < 1.0
    assert ext["fill_ratio"] > 0.99


def test_extent_finds_a_rotated_rectangle():
    """A 200x50 rectangle turned 30 degrees must still measure 200 by 50."""
    t = math.radians(30.0)
    c, s = math.cos(t), math.sin(t)
    rect = [[0, 0], [200, 0], [200, 50], [0, 50]]
    turned = [[x * c - y * s, x * s + y * c] for x, y in rect]
    ext = oriented_extent(turned)
    assert abs(ext["long_m"] - 200.0) < 2.0, ext
    assert abs(ext["short_m"] - 50.0) < 2.0, ext
    assert ext["fill_ratio"] > 0.97


def test_fill_ratio_flags_a_non_rectangular_field():
    """A triangle fills half its bounding rectangle, and must say so."""
    ext = oriented_extent([[0, 0], [200, 0], [0, 100]])
    assert 0.45 < ext["fill_ratio"] < 0.55, ext


def test_extent_of_a_degenerate_polygon_is_zero():
    ext = oriented_extent([[0, 0], [1, 1]])
    assert ext["long_m"] == 0.0 and ext["fill_ratio"] == 0.0


# --------------------------------------------------------------------------
# GeoJSON extraction — where a silent coordinate swap would live
# --------------------------------------------------------------------------

def _feature(ring_lonlat):
    return {"geometry": {"type": "Polygon", "coordinates": [ring_lonlat]}}


def test_geojson_lon_lat_is_swapped_to_lat_lon():
    """
    GeoJSON orders coordinates [lon, lat]; folium and this module use
    [lat, lon]. Getting it wrong is silent and would place a field at
    31 N 30 E — the Mediterranean — instead of 30 N 31 E.
    """
    ring = [[31.0, 30.0], [31.001, 30.0], [31.001, 30.001], [31.0, 30.001],
            [31.0, 30.0]]
    got = _extract_polygon({"all_drawings": [_feature(ring)]})
    assert got[0] == [30.0, 31.0], got[0]
    assert all(29.0 < lat < 32.0 for lat, _ in got)


def test_closing_vertex_is_dropped():
    ring = [[31.0, 30.0], [31.001, 30.0], [31.001, 30.001], [31.0, 30.0]]
    got = _extract_polygon({"all_drawings": [_feature(ring)]})
    assert len(got) == 3
    assert got[0] != got[-1]


def test_the_last_drawing_wins():
    a = [[31.0, 30.0], [31.001, 30.0], [31.001, 30.001], [31.0, 30.0]]
    b = [[35.0, 25.0], [35.001, 25.0], [35.001, 25.001], [35.0, 25.0]]
    got = _extract_polygon({"all_drawings": [_feature(a), _feature(b)]})
    assert abs(got[0][0] - 25.0) < 1e-9


def test_non_polygon_and_empty_input_return_none():
    assert _extract_polygon(None) is None
    assert _extract_polygon({}) is None
    assert _extract_polygon({"all_drawings": []}) is None
    assert _extract_polygon(
        {"all_drawings": [{"geometry": {"type": "Point",
                                        "coordinates": [31.0, 30.0]}}]}) is None
    # a ring with too few points is not a polygon
    assert _extract_polygon(
        {"all_drawings": [_feature([[31.0, 30.0], [31.001, 30.0]])]}) is None


# --------------------------------------------------------------------------
# Pasted coordinates — the fallback for a network that blocks the map CDN
# --------------------------------------------------------------------------

from modules.layout import parse_coordinates


def test_paste_lat_lon_one_per_line():
    pts, msg = parse_coordinates(
        "30.60100, 31.50100\n30.60100, 31.50220\n30.60190, 31.50220")
    assert len(pts) == 3
    assert abs(pts[0][0] - 30.601) < 1e-9 and abs(pts[0][1] - 31.501) < 1e-9
    assert msg == ""


def test_paste_accepts_spaces_and_semicolons():
    a, _ = parse_coordinates("30.6 31.5\n30.7 31.5\n30.7 31.6")
    b, _ = parse_coordinates("30.6,31.5;30.7,31.5;30.7,31.6")
    assert len(a) == 3 and len(b) == 3
    assert a == b


def test_paste_detects_and_swaps_lon_lat():
    """
    GeoJSON and KML give lon,lat. A longitude beyond ±90 cannot be a latitude,
    so the order is detectable. Missing this would place a field at 31 N 30 E
    — in the Mediterranean — instead of 30 N 31 E.
    """
    pts, msg = parse_coordinates(
        "121.5, 25.0\n121.6, 25.0\n121.6, 25.1")     # Taipei, lon first
    assert all(24.0 < lat < 26.0 for lat, _ in pts), pts
    assert "swapped" in msg


def test_paste_keeps_ambiguous_input_as_lat_lon():
    """Both columns under 90: no evidence of a swap, so trust the stated order."""
    pts, msg = parse_coordinates("30.6, 31.5\n30.7, 31.5\n30.7, 31.6")
    assert abs(pts[0][0] - 30.6) < 1e-9
    assert "swapped" not in msg


def test_paste_drops_a_closing_vertex():
    pts, _ = parse_coordinates(
        "30.6,31.5\n30.7,31.5\n30.7,31.6\n30.6,31.5")
    assert len(pts) == 3


def test_paste_rejects_too_few_points():
    pts, msg = parse_coordinates("30.6, 31.5\n30.7, 31.5")
    assert pts == []
    assert "at least three" in msg


def test_paste_rejects_out_of_range_values():
    pts, msg = parse_coordinates("30.6, 300.0\n30.7, 301.0\n30.8, 302.0")
    assert pts == []
    assert "outside the valid range" in msg


def test_paste_skips_junk_lines_and_says_so():
    pts, msg = parse_coordinates(
        "# my field\n30.6,31.5\nnonsense\n30.7,31.5\n30.7,31.6\nx")
    assert len(pts) == 3
    assert "could not be read" in msg


def test_paste_of_nothing_is_silent():
    assert parse_coordinates("") == ([], "")
    assert parse_coordinates("   \n  ") == ([], "")


def test_pasted_square_gives_the_right_area():
    """End to end: paste -> project -> area, for a 1 ha field at 30 N."""
    import math
    from modules.layout import to_local, polygon_area_m2, M_PER_DEG_LAT
    dlat = 100.0 / M_PER_DEG_LAT
    dlon = 100.0 / (M_PER_DEG_LAT * math.cos(math.radians(30.0)))
    text = "\n".join([
        f"30.0, 31.0", f"30.0, {31.0+dlon:.8f}",
        f"{30.0+dlat:.8f}, {31.0+dlon:.8f}", f"{30.0+dlat:.8f}, 31.0"])
    pts, _ = parse_coordinates(text)
    area_ha = polygon_area_m2(to_local(pts)) / 10_000.0
    assert abs(area_ha - 1.0) < 0.002, area_ha


def test_measured_area_survives_drawing_the_field_first():
    """
    Regression, finding 0.7.2-B1.

    The measured area used to be PUSHED from the layout page into setup, and
    only when "setup" already existed. Opening Field Layout first — which the
    Home page invites — meant the push never fired: the measurement was
    discarded and Project & Field opened on its 5.00 ha default. A 3.2 ha
    field would have been designed as 5 ha with nothing on screen saying so.
    The layout page must therefore leave a measurement that setup can read,
    and must not write into setup itself.
    """
    import inspect
    from modules import layout, home
    src = inspect.getsource(layout.boundary_step)
    assert 'S["setup"]["area_ha"]' not in src, "layout must not push into setup"
    assert '"area_ha": area_ha' in src, "layout must record the measured area"
    pull = inspect.getsource(home.net_area_ha) + inspect.getsource(home.project_setup_tab)
    assert 'S.get("layout")' in pull, "setup must pull the measurement"


def test_map_does_not_zoom_on_the_scroll_wheel():
    """
    Regression, finding 0.7.3-B1, found by scrolling the real page on the
    user's own machine. The map fills most of the viewport, so a scroll aimed
    at the measurements below it was captured by the map and zoomed it: the
    framed view was lost and the numbers were never reached.
    """
    import inspect
    from modules import layout
    src = inspect.getsource(layout._render_map)
    assert "scrollWheelZoom=False" in src


# --------------------------------------------------------------------------
# Real boundary file — Wadi El-Natrun research station
#
# This is a genuine Google Earth export from the station, and it exposed a
# defect no synthetic test had: at Wadi El-Natrun longitude is 30.36 and
# latitude is 30.39, so BOTH columns are under 90 and no magnitude rule can
# tell them apart.
# --------------------------------------------------------------------------

import os as _os

from modules.layout import (parse_kml, parse_geojson, read_boundary_file,
                            order_is_ambiguous)

WADI = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                     "data", "wadi_el_natrun.kml")


def _wadi_bytes():
    with open(WADI, "rb") as fh:
        return fh.read()


def test_kml_reads_the_real_station_boundary():
    pts, msg = parse_kml(_wadi_bytes())
    assert msg == ""
    assert len(pts) == 4, pts
    # KML stores lon,lat; the station is at ~30.39 N, ~30.36 E
    lat, lon = pts[0]
    assert abs(lat - 30.392891) < 1e-6, lat
    assert abs(lon - 30.362789) < 1e-6, lon


def test_closing_vertex_dropped_from_the_real_file():
    pts, _ = parse_kml(_wadi_bytes())
    assert pts[0] != pts[-1]


def test_real_boundary_measures_correctly():
    """
    Hand-checked against the polygon: 5.198 ha, 268 m by 200 m, long axis
    bearing 21 degrees from north, and very nearly a rectangle.
    """
    pts, _ = parse_kml(_wadi_bytes())
    local = to_local(pts)
    area_ha = polygon_area_m2(local) / 10_000.0
    ext = oriented_extent(local)
    assert abs(area_ha - 5.1982) < 0.005, area_ha
    assert abs(ext["long_m"] - 267.6) < 2.0, ext
    assert abs(ext["short_m"] - 199.7) < 2.0, ext
    assert abs(ext["bearing_deg"] - 21.0) < 2.0, ext
    assert ext["fill_ratio"] > 0.95


def test_this_boundary_is_exactly_the_ambiguous_case():
    """The reason the file reader exists rather than a cleverer paste rule."""
    pts, _ = parse_kml(_wadi_bytes())
    assert order_is_ambiguous(pts) is True


def test_the_wrong_column_order_hides_in_the_area_and_shows_in_the_bearing():
    """
    Regression, finding 0.8.0-B1, and the reason the ambiguous case must be
    ASKED about rather than assumed.

    Read the wrong way round this real boundary still reports essentially the
    same area — 5.200 ha against a true 5.198 — so the one number a user would
    sanity-check looks right. The long-axis bearing, which is the direction
    the laterals are laid, moves from 21 degrees to 62.
    """
    pts, _ = parse_kml(_wadi_bytes())
    swapped = [[p[1], p[0]] for p in pts]

    right = oriented_extent(to_local(pts))
    wrong = oriented_extent(to_local(swapped))
    a_right = polygon_area_m2(to_local(pts)) / 10_000.0
    a_wrong = polygon_area_m2(to_local(swapped)) / 10_000.0

    assert abs(a_right - a_wrong) < 0.01, "the area does NOT reveal the error"
    assert abs(right["bearing_deg"] - wrong["bearing_deg"]) > 30.0, \
        "the bearing MUST reveal it"


def test_geojson_reader_agrees_with_the_kml_reader():
    """Both formats are lon,lat; both readers must produce the same field."""
    import json
    pts, _ = parse_kml(_wadi_bytes())
    ring = [[lon, lat] for lat, lon in pts] + [[pts[0][1], pts[0][0]]]
    gj = json.dumps({"type": "Feature",
                     "geometry": {"type": "Polygon", "coordinates": [ring]}})
    got, msg = parse_geojson(gj)
    assert msg == ""
    assert len(got) == len(pts)
    for a, b in zip(got, pts):
        assert abs(a[0] - b[0]) < 1e-9 and abs(a[1] - b[1]) < 1e-9


def test_dispatch_by_extension_and_rejection_of_others():
    pts, msg = read_boundary_file("wadi_el_natrun.kml", _wadi_bytes())
    assert len(pts) == 4 and msg == ""
    pts2, msg2 = read_boundary_file("field.dwg", b"nonsense")
    assert pts2 == [] and "Unsupported file type" in msg2


def test_malformed_files_report_rather_than_raise():
    assert parse_kml(b"<kml>not really")[0] == []
    assert "does not parse" in parse_kml(b"<kml>not really")[1]
    assert parse_geojson(b"{oops")[0] == []
    assert parse_kml(b"<kml xmlns='http://www.opengis.net/kml/2.2'></kml>")[0] == []


def test_map_centres_on_a_boundary_that_came_from_a_file():
    """
    Regression, finding 0.8.1-B1. Uploading the Wadi El-Natrun boundary left
    the map parked on the default East Delta view, 130 km away, so the user
    could not see what had just been read and the map looked broken.
    """
    import inspect
    from modules import layout
    src = inspect.getsource(layout._render_map)
    assert "centroid(boundary)" in src, "map must centre on the loaded boundary"
    assert "fit_bounds" in src, "map must frame the boundary, not just centre"
    assert "boundary" in inspect.signature(layout._render_map).parameters


# --- KMZ upload (v0.11.0) -------------------------------------------------
# A KMZ is the format Google Earth saves by default, so it is what a user
# reaches for first. The reader took namelist()[0], and a real Google Earth
# KMZ routinely carries a legend or style .kml beside doc.kml — whichever the
# zip listed first won, and the failure was silent: "no polygon found" on a
# file that plainly has one.

import io as _io                                            # noqa: E402
import zipfile as _zipfile                                  # noqa: E402
from modules import layout as L                             # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
_WADI = os.path.join(_HERE, "data", "wadi_el_natrun.kml")


def _raw_wadi():
    with open(_WADI, "rb") as fh:
        return fh.read()


def _kmz(entries):
    buf = _io.BytesIO()
    with _zipfile.ZipFile(buf, "w") as z:
        for name, data in entries:
            z.writestr(name, data)
    return buf.getvalue()


def test_kmz_with_a_single_document():
    pts, msg = L.read_boundary_file("f.kmz", _kmz([("doc.kml", _raw_wadi())]))
    assert len(pts) == 4 and not msg


def test_kmz_laid_out_the_way_google_earth_saves_one():
    data = _kmz([("files/overlay.png", b"\x89PNG"), ("doc.kml", _raw_wadi())])
    pts, msg = L.read_boundary_file("f.kmz", data)
    assert len(pts) == 4 and not msg


def test_a_decoy_kml_listed_first_does_not_win():
    """The defect: namelist()[0] was a legend, and the boundary was missed."""
    data = _kmz([("files/legend.kml", b"<kml/>"), ("doc.kml", _raw_wadi())])
    pts, _ = L.read_boundary_file("f.kmz", data)
    assert len(pts) == 4


def test_the_document_is_found_even_when_it_is_not_called_doc_kml():
    data = _kmz([("files/legend.kml", b"<kml/>"), ("boundary.kml", _raw_wadi())])
    pts, _ = L.read_boundary_file("f.kmz", data)
    assert len(pts) == 4


def test_a_kmz_with_no_polygon_anywhere_says_so():
    pts, msg = L.read_boundary_file("f.kmz", _kmz([("a.kml", b"<kml/>"),
                                                   ("b.kml", b"<kml/>")]))
    assert not pts and "polygon" in msg.lower()


def test_a_kmz_holding_no_kml_at_all_says_so_and_suggests_the_fix():
    pts, msg = L.read_boundary_file("f.kmz", _kmz([("a.txt", b"x")]))
    assert not pts and "no .kml" in msg
    assert "network link" in msg.lower()


def test_a_corrupt_archive_is_reported_not_raised():
    pts, msg = L.read_boundary_file("f.kmz", b"PK\x03\x04not really a zip")
    assert not pts and "could not be opened" in msg


def test_the_extension_does_not_decide_the_format():
    """
    A KMZ renamed .kml, and a KML renamed .kmz, both still read. Users rename
    files; the magic number is the truth and the extension is a hint.
    """
    kmz_as_kml = L.read_boundary_file("f.kml", _kmz([("doc.kml", _raw_wadi())]))[0]
    kml_as_kmz = L.read_boundary_file("f.kmz", _raw_wadi())[0]
    plain = L.read_boundary_file("f.kml", _raw_wadi())[0]
    assert kmz_as_kml == kml_as_kmz == plain
    assert len(plain) == 4


def test_a_kmz_that_expands_absurdly_is_refused():
    big = _kmz([("doc.kml", b"<kml/>" + b" " * (65 * 1024 * 1024))])
    pts, msg = L.read_boundary_file("f.kmz", big)
    assert not pts and "Refused" in msg
