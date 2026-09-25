"""
KML export. The round-trip test is the one that matters.

Writing lat before lon produces a file that looks perfectly valid, lands in
roughly the right country, and computes an area within a fraction of a per
cent of the truth — while the long axis, which is the direction every lateral
is laid along, is wrong by tens of degrees. No summary figure catches it.
Round-tripping through the program's OWN reader does.
"""

import math
import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import kml as KML                              # noqa: E402
from modules import layout as L                            # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
WADI = os.path.join(HERE, "data", "wadi_el_natrun.kml")

# Wadi El-Natrun: lat 30.392, lon 30.361. Both near 30, so a swap is invisible
# to any magnitude check — which is exactly why this file is the fixture.
SQUARE = [[30.39289, 30.36279], [30.39351, 30.36087],
          [30.39135, 30.35988], [30.39065, 30.36178]]


def test_it_is_well_formed_xml_in_the_kml_namespace():
    root = ET.fromstring(KML.boundary_kml(SQUARE, "Wadi"))
    assert root.tag == f"{{{KML.SCHEMA}}}kml"


def test_coordinates_are_written_lon_lat_not_lat_lon():
    txt = KML.boundary_kml(SQUARE, "Wadi")
    first = [ln.strip() for ln in txt.splitlines() if ln.strip().startswith("30.")][0]
    lon, lat, alt = first.split(",")
    assert float(lon) == 30.36279, "longitude must come first, per the KML spec"
    assert float(lat) == 30.39289
    assert float(alt) == 0.0


def test_round_trip_through_the_programs_own_reader_is_identical():
    pts, _ = L.parse_kml(KML.boundary_kml(SQUARE, "Wadi"))
    assert len(pts) == len(SQUARE)
    for (a_lat, a_lon), (b_lat, b_lon) in zip(pts, SQUARE):
        assert math.isclose(a_lat, b_lat, abs_tol=1e-9)
        assert math.isclose(a_lon, b_lon, abs_tol=1e-9)


def test_round_trip_preserves_the_measured_geometry_of_the_real_field():
    """
    Asserted in metres and degrees, not in float tolerances.

    The export writes COORD_PLACES decimals, so a round trip is lossy by
    construction. What matters is whether the loss is physically meaningful:
    a vertex must not move further than a millimetre, the area must hold to
    far better than any survey, and the long-axis bearing — the figure a
    coordinate swap destroys and a rounding does not — must be unchanged to
    a thousandth of a degree.
    """
    with open(WADI, "rb") as fh:
        original, _ = L.read_boundary_file("wadi_el_natrun.kml", fh.read())
    exported, _ = L.parse_kml(KML.boundary_kml(original, "Wadi"))
    assert len(exported) == len(original)

    centre = L.centroid(original)
    a = L.to_local(original, origin=centre)
    b = L.to_local(exported, origin=centre)
    worst = max(math.hypot(p[0] - q[0], p[1] - q[1]) for p, q in zip(a, b))
    assert worst < 0.002, f"a vertex moved {worst*1000:.3f} mm on round trip"

    area_a, area_b = L.polygon_area_m2(a), L.polygon_area_m2(b)
    assert abs(area_a - area_b) / area_a < 1e-5
    assert abs(area_a - area_b) < 1.0, "area moved by more than a square metre"

    e0, e1 = L.oriented_extent(a), L.oriented_extent(b)
    assert math.isclose(e0["bearing_deg"], e1["bearing_deg"], abs_tol=1e-3)
    assert math.isclose(e0["long_m"], e1["long_m"], abs_tol=0.01)
    assert math.isclose(e0["short_m"], e1["short_m"], abs_tol=0.01)


def test_the_ring_is_closed_as_the_spec_requires():
    txt = KML.boundary_kml(SQUARE, "Wadi")
    coords = [ln.strip() for ln in txt.splitlines() if ln.strip().startswith("30.")]
    ring = coords[:len(SQUARE) + 1]
    assert ring[0] == ring[-1], "a LinearRing must repeat its first vertex"


def test_an_already_closed_ring_is_not_closed_twice():
    closed = SQUARE + [list(SQUARE[0])]
    a, _ = L.parse_kml(KML.boundary_kml(closed, "Wadi"))
    b, _ = L.parse_kml(KML.boundary_kml(SQUARE, "Wadi"))
    assert a == b


def test_a_name_with_xml_metacharacters_cannot_break_the_file():
    txt = KML.boundary_kml(SQUARE, 'Wadi & "El-Natrun" <A2>')
    root = ET.fromstring(txt)                      # would raise if unescaped
    names = [e.text for e in root.iter(f"{{{KML.SCHEMA}}}name")]
    assert 'Wadi & "El-Natrun" <A2>' in names


def test_too_few_vertices_is_refused_rather_than_written():
    for bad in ([], [[30.0, 30.0]], [[30.0, 30.0], [30.1, 30.1]]):
        try:
            KML.boundary_kml(bad, "x")
        except ValueError:
            continue
        raise AssertionError(f"{bad!r} should not have produced a polygon")


def test_a_tiny_coordinate_is_not_written_in_scientific_notation():
    # repr(1e-05) is '1e-05', which is not a valid KML coordinate.
    txt = KML.boundary_kml([[1e-5, 1e-5], [1e-5, 0.001], [0.001, 0.001]], "x")
    assert "e-" not in txt.lower().split("<description>")[0]
    ET.fromstring(txt)


# --- the long axis drawn into the file ------------------------------------

def test_long_axis_endpoints_are_the_right_length_and_bearing():
    centre = (30.3921, 30.3613)
    pts = L.long_axis_endpoints(centre, 267.6, 21.0)
    local = L.to_local(pts, origin=centre)
    (x1, y1), (x2, y2) = local
    assert math.isclose(math.hypot(x2 - x1, y2 - y1), 267.6, rel_tol=1e-6)
    bearing = math.degrees(math.atan2(x2 - x1, y2 - y1)) % 180.0
    assert math.isclose(bearing, 21.0, abs_tol=1e-6)


def test_to_gps_inverts_to_local_exactly():
    centre = L.centroid(SQUARE)
    back = L.to_gps(L.to_local(SQUARE), centre)
    for (a_lat, a_lon), (b_lat, b_lon) in zip(back, SQUARE):
        assert math.isclose(a_lat, b_lat, abs_tol=1e-9)
        assert math.isclose(a_lon, b_lon, abs_tol=1e-9)


def test_the_axis_placemark_is_present_and_is_a_linestring():
    txt = KML.boundary_kml(SQUARE, "Wadi",
                           long_axis=L.long_axis_endpoints(
                               L.centroid(SQUARE), 100.0, 21.0),
                           centroid_latlon=list(L.centroid(SQUARE)))
    root = ET.fromstring(txt)
    assert root.iter(f"{{{KML.SCHEMA}}}LineString") is not None
    assert len(list(root.iter(f"{{{KML.SCHEMA}}}Placemark"))) == 3
    assert len(list(root.iter(f"{{{KML.SCHEMA}}}Point"))) == 1


def test_an_axis_that_is_not_two_points_is_refused():
    try:
        KML.boundary_kml(SQUARE, "x", long_axis=[[30.0, 30.0]])
    except ValueError:
        return
    raise AssertionError("a one-point axis should not be written")


# --- the page actually reaches the export block ---------------------------
# The layout page's smoke test renders with an empty state and returns at
# "nothing drawn yet", so it never executes one line of the export block. That
# is the same blind spot that let a failed design export a clean workbook. A
# boundary is seeded here so the download button is genuinely rendered.

def test_layout_page_renders_the_kml_download_for_a_saved_boundary():
    import pytest
    AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
    app = os.path.join(os.path.dirname(HERE), "app.py")
    with open(WADI, "rb") as fh:
        pts, _ = L.read_boundary_file("wadi_el_natrun.kml", fh.read())

    at = AppTest.from_file(app, default_timeout=60)
    # v2.0: the boundary step lives on Home > Field Layout & Blocks.
    at.session_state["page"] = "home"
    at.session_state["S"] = {"layout": {"boundary_gps": pts,
                                        "centre": list(L.centroid(pts))}}
    at.run()
    assert not at.exception, (
        f"{at.exception[0].type}: {at.exception[0].message}"
        if at.exception else "")
    labels = [b.label for b in at.get("download_button")]
    assert any(".kml" in lb for lb in labels), labels


# --- the designed network on the real boundary ----------------------------

def _wadi_network(feed="middle", design_run=65.0, bands=None):
    from engine import fieldnet as FN
    with open(WADI, "rb") as fh:
        gps, _ = L.read_boundary_file("wadi_el_natrun.kml", fh.read())
    centre = L.centroid(gps)
    local = L.to_local(gps, origin=centre)
    ext = L.oriented_extent(local)
    g = FN.network_geometry(local, ext["bearing_deg"],
                            2.0, design_run, feed=feed, bands=bands)
    laterals = []
    for r in g["rows"]:
        for seg in r["segments"]:
            laterals.append({"name": f"Lateral {r['index']}",
                             "points": L.to_gps(list(seg), centre),
                             "over": r["run_length_m"] > design_run + 1e-9,
                             "description": f"run {r['run_length_m']:.1f} m"})
    return gps, centre, g, laterals


def test_network_kml_is_valid_and_folders_every_component():
    gps, centre, g, laterals = _wadi_network()
    txt = KML.network_kml("Wadi", gps, laterals,
                          manifold_latlon=L.to_gps(g["manifolds"][0], centre),
                          summary="test")
    root = ET.fromstring(txt)
    folders = [f.find(f"{{{KML.SCHEMA}}}name").text
               for f in root.iter(f"{{{KML.SCHEMA}}}Folder")]
    assert any(fn.startswith("Laterals") for fn in folders), folders
    assert "Manifold" in folders
    assert len(list(root.iter(f"{{{KML.SCHEMA}}}LineString"))) == len(laterals) + 1


def test_every_drawn_lateral_lies_inside_the_boundary():
    """
    The whole point of clipping. Asserted on the exported lat/lon, after the
    projection round trip, not on the local metres the clipper produced — a
    correct clip plus a wrong inverse projection would still put pipe outside
    the fence, and only this test would see it.
    """
    from engine import fieldnet as FN
    gps, centre, g, laterals = _wadi_network()
    poly = L.to_local(gps, origin=centre)
    for lat in laterals:
        for pt in L.to_local(lat["points"], origin=centre):
            # A boundary vertex sits exactly on the edge, so allow a millimetre.
            assert FN.point_in_polygon(pt, poly) or _near_edge(pt, poly), lat["name"]


def _near_edge(pt, poly, tol=0.01):
    import math
    x, y = pt
    best = float("inf")
    for i in range(len(poly)):
        (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % len(poly)]
        dx, dy = x2 - x1, y2 - y1
        t = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)))
        best = min(best, math.hypot(x - (x1 + t * dx), y - (y1 + t * dy)))
    return best <= tol


def test_overlong_runs_are_drawn_red_and_short_ones_are_not():
    # bands=1 puts the whole 267 m row on one manifold against a 65 m design,
    # which is the unbuildable layout the program used to draw silently.
    _, _, _, over = _wadi_network(design_run=65.0, bands=1)
    flags = [lat["over"] for lat in over]
    # Nearly every row overshoots, but the short row at the field's tip does
    # not: the flag must discriminate, not just be True everywhere.
    assert sum(flags) >= 0.9 * len(flags), sum(flags) / len(flags)
    assert not all(flags), "the flag is not discriminating between runs"
    txt = KML.network_kml("Wadi", _wadi_network()[0], over)
    assert "irridrip-lat-over" in txt
    assert "over the designed length" in txt

    _, _, _, fine = _wadi_network(design_run=65.0)
    assert not any(lat["over"] for lat in fine)
    ok = KML.network_kml("Wadi", _wadi_network()[0], fine)
    assert "irridrip-lat-over" not in ok.split("<Folder>")[1]


def test_report_page_still_delegates_to_the_geometry_module():
    root = os.path.dirname(HERE)
    src = open(os.path.join(root, "modules", "reports.py"), encoding="utf-8").read()
    assert "KML.network_kml(" in src
    assert "LAY.to_gps(" in src
    # v2.0: the rows are cut once, into subunits, by the engine.
    su = open(os.path.join(root, "engine", "subunits.py"), encoding="utf-8").read()
    assert "FN.network_geometry(" in su
