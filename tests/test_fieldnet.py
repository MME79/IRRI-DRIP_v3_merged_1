"""
The designed network laid on the real boundary.

The question this module exists to answer: the hydraulics size ONE lateral
length and apply it to every row, but a real field is not a rectangle. How
long are the rows actually, and how many exceed the length the head-spread
check was computed for?
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import fieldnet as FN                      # noqa: E402
from modules import layout as L                        # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
WADI = os.path.join(HERE, "data", "wadi_el_natrun.kml")

# 200 m east-west by 100 m north-south, centred on the origin.
RECT = [[-100.0, -50.0], [100.0, -50.0], [100.0, 50.0], [-100.0, 50.0]]

# An L: the top-right quadrant is missing. A row across the notch must come
# back as TWO runs, not one.
LSHAPE = [[-100.0, -50.0], [100.0, -50.0], [100.0, 0.0],
          [0.0, 0.0], [0.0, 50.0], [-100.0, 50.0]]


def test_unit_vectors_are_orthonormal_and_point_the_right_way():
    for b in (0.0, 21.0, 90.0, 137.0, 180.0):
        along, across = FN.unit_vectors(b)
        assert math.isclose(math.hypot(*along), 1.0, abs_tol=1e-12)
        assert math.isclose(math.hypot(*across), 1.0, abs_tol=1e-12)
        assert abs(along[0] * across[0] + along[1] * across[1]) < 1e-12
    north, east = FN.unit_vectors(0.0)
    assert math.isclose(north[1], 1.0, abs_tol=1e-12)   # bearing 0 -> north
    e, _ = FN.unit_vectors(90.0)
    assert math.isclose(e[0], 1.0, abs_tol=1e-12)       # bearing 90 -> east


def test_point_in_polygon_on_a_concave_shape():
    assert FN.point_in_polygon((-50.0, 25.0), LSHAPE)     # in the tall arm
    assert FN.point_in_polygon((50.0, -25.0), LSHAPE)     # in the low arm
    assert not FN.point_in_polygon((50.0, 25.0), LSHAPE)  # in the notch
    assert not FN.point_in_polygon((500.0, 0.0), LSHAPE)


def test_a_row_across_a_notch_returns_two_runs_not_one():
    # y = 25 crosses the tall arm only in the L; y = -25 crosses the full width.
    two = FN.clip_segment((-500.0, -25.0), (500.0, -25.0), LSHAPE)
    assert len(two) == 1 and math.isclose(FN._length(two[0]), 200.0, abs_tol=1e-6)
    one = FN.clip_segment((-500.0, 25.0), (500.0, 25.0), LSHAPE)
    assert len(one) == 1 and math.isclose(FN._length(one[0]), 100.0, abs_tol=1e-6)

    # A genuinely split row: a rectangle with a slot cut out of its middle.
    slot = [[-100.0, -50.0], [-10.0, -50.0], [-10.0, 50.0], [10.0, 50.0],
            [10.0, -50.0], [100.0, -50.0], [100.0, 60.0], [-100.0, 60.0]]
    runs = FN.clip_segment((-500.0, 0.0), (500.0, 0.0), slot)
    assert len(runs) == 2, [FN._length(r) for r in runs]
    assert math.isclose(sum(FN._length(r) for r in runs), 180.0, abs_tol=1e-6)


def test_rows_on_a_rectangle_are_the_expected_count_and_length():
    # Laterals along the long axis: 200 m east-west means bearing 90.
    rows = FN.lateral_rows(RECT, 90.0, 2.0)
    assert len(rows) == 50, len(rows)               # 100 m / 2 m
    for r in rows:
        assert math.isclose(r["run_length_m"], 200.0, abs_tol=1e-6)
        assert r["n_runs"] == 1


def test_first_row_is_half_a_spacing_in_from_the_edge():
    rows = FN.lateral_rows(RECT, 90.0, 10.0)
    offsets = sorted(r["offset_m"] for r in rows)
    assert math.isclose(offsets[1] - offsets[0], 10.0, abs_tol=1e-9)
    # 100 m of width at 10 m spacing -> 10 rows, first at 5 m from the edge.
    assert len(rows) == 10
    assert math.isclose(min(abs(o - (-50.0)) for o in offsets), 5.0, abs_tol=1e-6)


def test_total_lateral_length_times_spacing_recovers_the_area():
    """
    The strongest independent check available without a second library:
    each row represents a strip of width = spacing, so length x spacing must
    sum to the polygon area. It holds for the concave shape too.
    """
    for poly, bearing in ((RECT, 90.0), (LSHAPE, 90.0), (LSHAPE, 0.0),
                          (RECT, 21.0)):
        area = L.polygon_area_m2(poly)
        for sp in (1.0, 2.0, 5.0):
            g = FN.network_geometry(poly, bearing, sp, design_run_m=1e9, bands=1)
            swept = g["total_lateral_m"] * sp
            assert abs(swept - area) / area < 0.06, (
                f"{bearing} deg, {sp} m: swept {swept:.0f} vs area {area:.0f}")


def test_rows_longer_than_the_design_length_are_counted_and_named():
    # bands=1 forces the whole 200 m row onto one manifold, which is what a
    # single-manifold layout would do and what the old DXF silently assumed.
    g = FN.network_geometry(RECT, 90.0, 10.0, design_run_m=150.0, bands=1)
    assert g["n_laterals"] == 10
    assert g["n_laterals_over_design"] == 10       # every row is 200 m
    assert math.isclose(g["worst_overrun_m"], 50.0, abs_tol=1e-6)
    assert g["laterals_over_design"] == list(range(1, 11))

    ok = FN.network_geometry(RECT, 90.0, 10.0, design_run_m=250.0, bands=1)
    assert ok["n_laterals_over_design"] == 0 and ok["worst_overrun_m"] == 0.0


def test_mid_feed_halves_the_hydraulic_run_but_not_the_pipe():
    end = FN.network_geometry(RECT, 90.0, 10.0, 150.0, feed="end", bands=1)
    mid = FN.network_geometry(RECT, 90.0, 10.0, 150.0, feed="middle", bands=1)
    assert math.isclose(end["max_run_m"], 200.0, abs_tol=1e-6)
    assert math.isclose(mid["max_run_m"], 100.0, abs_tol=1e-6)
    # Same pipe in the ground either way.
    assert math.isclose(end["total_lateral_m"], mid["total_lateral_m"],
                        rel_tol=1e-9)
    # And mid-feed is what turns the failure into a pass at this design length.
    assert end["n_laterals_over_design"] == 10
    assert mid["n_laterals_over_design"] == 0


def test_bad_arguments_are_refused():
    for bad in (0.0, -1.0):
        try:
            FN.lateral_rows(RECT, 0.0, bad)
        except ValueError:
            continue
        raise AssertionError(f"spacing {bad} should be refused")
    try:
        FN.lateral_rows(RECT, 0.0, 2.0, feed="sideways")
    except ValueError:
        pass
    else:
        raise AssertionError("an unknown feed mode should be refused")


# --- the real field -------------------------------------------------------

def test_on_the_real_wadi_el_natrun_boundary():
    with open(WADI, "rb") as fh:
        pts, _ = L.read_boundary_file("wadi_el_natrun.kml", fh.read())
    local = L.to_local(pts)
    ext = L.oriented_extent(local)
    area = L.polygon_area_m2(local)

    # One manifold for the whole field: this is what the program drew before,
    # and it is unbuildable. A 267 m field cannot be served by 65 m laterals.
    one = FN.network_geometry(local, ext["bearing_deg"], 2.0, 65.0,
                              feed="end", bands=1)
    assert 90 <= one["n_rows_across"] <= 105, one["n_rows_across"]
    assert one["max_run_m"] > 200.0
    assert one["n_laterals_over_design"] == one["n_laterals"]

    # Banded automatically: no lateral may exceed the designed run length.
    g = FN.network_geometry(local, ext["bearing_deg"], 2.0, 65.0, feed="end")
    assert g["bands"] == FN.bands_needed(g["span_m"], 65.0, "end") == 5
    assert g["n_laterals_over_design"] == 0, g["worst_overrun_m"]
    assert g["max_run_m"] <= 65.0 + 1e-6
    # Banding cuts rows into pieces; it does not change the pipe in the ground.
    assert abs(g["total_lateral_m"] - one["total_lateral_m"]) / one["total_lateral_m"] < 0.02
    assert abs(g["total_lateral_m"] * 2.0 - area) / area < 0.04

    # Mid-feed reaches twice as far, so it needs half the manifolds.
    mid = FN.network_geometry(local, ext["bearing_deg"], 2.0, 65.0,
                              feed="middle")
    assert mid["bands"] == 3, mid["bands"]
    assert mid["max_run_m"] <= 65.0 + 1e-6
    assert mid["n_laterals_over_design"] == 0
