"""Tests for the DXF export. Geometry is asserted by reading the file back."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import dxf as D


def _entities(txt):
    """
    Parse the ENTITIES section into dicts of {group_code: value}.

    DXF is a flat stream of alternating code/value lines, so a naive scan for
    the literal "8" also matches a colour VALUE of 8 and a naive zip
    desynchronises across entity boundaries. Both of my first two tests failed
    on exactly that, and the file was correct. Parse by position within the
    ENTITIES section and split on the 0 code, which is what actually delimits
    an entity.
    """
    body = txt.split("0\nSECTION\n2\nENTITIES\n", 1)[1].split("0\nENDSEC\n", 1)[0]
    lines = body.split("\n")
    pairs = [(lines[i], lines[i + 1]) for i in range(0, len(lines) - 1, 2)]
    out, cur = [], None
    for code, value in pairs:
        if code == "0":
            cur = {"type": value}
            out.append(cur)
        elif cur is not None:
            cur[code] = value
    return out


def _lines_on(txt, layer):
    return [e for e in _entities(txt)
            if e["type"] == "LINE" and e.get("8") == layer]


def _state(shifts=6, l_len=65.0, sl=2.0, se=0.5, n_lat=20, m_len=40.0,
           main_len=200.0):
    return {
        "setup": {"name": "Test", "location": "Delta", "area_ha": 5.0,
                  "crop": {"name": "Tomato"}, "soil": {"name": "Sandy loam"},
                  "q_avail": 40.0},
        "emitter": {"name": "Inline PC 4.0", "k": 3.734, "x": 0.03,
                    "q_emitter": 4.05, "se": se, "sl": sl, "h_op": 15.0},
        "operation": {"shifts": shifts, "q_shift": 33.8},
        "lateral": {"l_len": l_len, "eu": 94.6,
                    "lateral": {"nominal_mm": 16.0},
                    "res": {"spread_m": 3.467}},
        "manifold": {"n_lat": n_lat, "m_len": m_len, "main_len": main_len,
                     "manifold_pipe": {"nominal_mm": 63.0, "material": "PE"},
                     "main_pipe": {"nominal_mm": 110.0, "material": "PE"}},
        "pump": {"tdh": {"tdh_m": 45.6}},
    }


def test_dxf_is_well_formed_r12():
    txt = D.network_dxf(_state())
    assert txt.startswith("0\nSECTION\n2\nHEADER\n")
    assert "AC1009" in txt
    assert txt.rstrip().endswith("EOF")
    assert txt.count("0\nSECTION\n") == 3          # HEADER, TABLES, ENTITIES
    assert txt.count("0\nENDSEC\n") == 3


def test_dxf_is_pure_ascii():
    """R12 TEXT carries no encoding declaration, so non-ASCII must not survive."""
    st = _state()
    st["setup"]["name"] = "مشروع الصالحية"
    txt = D.network_dxf(st)
    assert all(ord(c) < 128 for c in txt)


def test_every_layer_used_is_declared():
    txt = D.network_dxf(_state())
    declared = {name for name, _ in D.LAYERS}
    used = {e["8"] for e in _entities(txt) if "8" in e}
    assert used, "no entities carried a layer"
    assert used <= declared, used - declared


def test_geometry_matches_the_design():
    """
    Read the drawing back and confirm the dimensions are the designed ones.
    A drawing that disagrees with the calculation it came from is worse than
    no drawing.
    """
    st = _state(shifts=3, l_len=65.0, sl=2.0, se=0.5, n_lat=20, m_len=40.0)
    d = D.build_layout(st)
    txt = d.render()

    vertical = [e for e in _lines_on(txt, "IRR-LATERAL")
                if abs(float(e["10"]) - float(e["11"])) < 1e-9]
    assert len(vertical) == 3 * 20                      # blocks x laterals
    for e in vertical:
        assert abs(abs(float(e["21"]) - float(e["20"])) - 65.0) < 1e-6

    xs = sorted({round(float(e["10"]), 6) for e in vertical})
    assert abs((xs[1] - xs[0]) - 2.0) < 1e-9            # lateral spacing


def test_mainline_is_drawn_at_its_designed_length():
    """
    Regression, finding 0.6.0-B1. The first draft ran one mainline from the
    source across every block, drawing 475 m for a 200 m designed mainline.
    The designed length is now drawn on its own, and the run continuing along
    the blocks is on the IRR-NOT-DESIGNED layer because the program never
    sized it.
    """
    txt = D.network_dxf(_state(shifts=6, main_len=200.0))
    main = [abs(float(e["11"]) - float(e["10"]))
            for e in _lines_on(txt, "IRR-MAINLINE")
            if abs(float(e["20"]) - float(e["21"])) < 1e-9]
    assert main, "no horizontal mainline drawn"
    assert abs(max(main) - 200.0) < 1e-6, main
    assert "IRR-NOT-DESIGNED" in txt
    assert "NOT SIZED BY THIS PROGRAM" in txt


def test_single_shift_draws_no_undesigned_run():
    txt = D.network_dxf(_state(shifts=1))
    assert "DISTRIBUTION RUN ALONG THE BLOCKS" not in txt


def test_emitter_detail_is_capped_and_labelled():
    txt = D.network_dxf(_state(l_len=300.0, se=0.3))   # 1000 emitters
    assert "FIRST 400 SHOWN" in txt


def test_drawing_states_it_is_not_a_site_plan():
    txt = D.network_dxf(_state())
    assert "THIS IS NOT A SITE PLAN" in txt


# --- verdict stamping (v0.8.2) -------------------------------------------
# Found by Dr. Mohamed running the program on his own field: the design
# reported "1 of 15 design checks failed" on screen and then exported a
# workbook, a drawing and a snapshot with no mark of the failure on any of
# them. The screen closes; the file is what gets forwarded.

def test_failed_design_is_stamped_on_the_drawing():
    st = _state()
    st["verdict"] = {"passed": False, "checks_applied": 15, "checks_failed": 1,
                     "failed_checks": ["Lateral head spread within allowable"]}
    txt = D.network_dxf(st)
    assert "NOT PASSED" in txt
    assert "DO NOT ISSUE, TENDER OR CONSTRUCT" in txt
    assert "LATERAL HEAD SPREAD WITHIN ALLOWABLE" in txt


def test_passed_design_says_so_and_carries_no_stamp():
    st = _state()
    st["verdict"] = {"passed": True, "checks_applied": 15, "checks_failed": 0,
                     "failed_checks": []}
    txt = D.network_dxf(st)
    assert "PASSED ALL DESIGN CHECKS" in txt
    assert "DO NOT ISSUE, TENDER OR CONSTRUCT" not in txt


def test_absent_verdict_is_not_reported_as_a_pass():
    # An old snapshot carries no verdict. Defaulting that to PASSED would put
    # an unearned clearance on a drawing.
    txt = D.network_dxf(_state())
    assert "VERDICT: NOT RECORDED" in txt
    assert "PASSED ALL DESIGN CHECKS" not in txt
