"""
Tests for the charts and schematics.

These check the two things that are easy to get wrong and impossible to see
in the source: that the drawing follows the page's light/dark mode, and that
the file is valid on the OLDEST Python the launcher accepts.
"""

import base64
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st

from modules import graphics as G


@pytest.fixture(autouse=True)
def _light_by_default():
    st.session_state["dark_mode_pref"] = False
    yield
    st.session_state["dark_mode_pref"] = False


def _svg_ground(html_str):
    b64 = re.search(r"base64,([^\"]+)", html_str).group(1)
    doc = base64.b64decode(b64).decode("utf-8")
    return re.search(r'fill="(#[0-9a-fA-F]{6})"', doc).group(1)


EM = {"se": 0.5, "sl": 2.0, "dw": 0.6, "pw": 0.5}


def test_chart_ground_follows_the_mode():
    """
    Regression, finding 0.7.2-B3. The charts and the schematic carried a
    hardcoded white ground, so on a dark page they were bright rectangles in
    the middle of the layout. The schematic was the worst: its background is
    baked into a base64 image at generation time, so nothing downstream could
    correct it.
    """
    light = G.magnitude_bars(["a", "b"], [3.0, 1.0], "Head (m)", "t").to_dict()
    assert light["background"] == "#ffffff"

    st.session_state["dark_mode_pref"] = True
    dark = G.magnitude_bars(["a", "b"], [3.0, 1.0], "Head (m)", "t").to_dict()
    assert dark["background"] == G._DARK["surface"]
    assert dark["background"] != light["background"]


def test_schematic_ground_follows_the_mode():
    light = _svg_ground(G.wetting_section_svg(EM, "Sandy loam"))
    st.session_state["dark_mode_pref"] = True
    dark = _svg_ground(G.wetting_section_svg(EM, "Sandy loam"))
    assert light == "#ffffff"
    assert dark.lower() == G._DARK["surface"]


def test_data_colours_do_not_change_between_modes():
    """
    The categorical and status colours were validated for contrast and for
    colour-vision deficiency AS A SET. Re-tuning them per mode would throw
    that validation away, so only the surface colours are allowed to move.
    """
    before = (G.SERIES_1, G.SERIES_2, G.SERIES_3, G.GOOD, G.WARNING, G.CRITICAL)
    st.session_state["dark_mode_pref"] = True
    after = (G.SERIES_1, G.SERIES_2, G.SERIES_3, G.GOOD, G.WARNING, G.CRITICAL)
    assert before == after


def test_skin_falls_back_to_light_without_a_theme(monkeypatch):
    """A chart must still render if the theme module cannot be reached."""
    import builtins
    real = builtins.__import__

    def boom(name, *a, **k):
        if name == "modules.theme" or name.endswith("theme"):
            raise ImportError("simulated")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", boom)
    assert G.skin() == G._LIGHT


def test_module_compiles_on_python_311():
    """
    The launcher accepts Python 3.11 as well as 3.12. Nesting the same quote
    character inside an f-string expression is a SyntaxError before 3.12, and
    a first attempt at the dark-mode change introduced exactly that — it would
    have crashed the whole app at import on a 3.11 machine while parsing
    cleanly on 3.12.
    """
    import ast
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for folder in ("modules", "engine"):
        d = os.path.join(here, folder)
        for fname in os.listdir(d):
            if fname.endswith(".py"):
                src = open(os.path.join(d, fname), encoding="utf-8").read()
                ast.parse(src, filename=fname)      # raises on a syntax error
