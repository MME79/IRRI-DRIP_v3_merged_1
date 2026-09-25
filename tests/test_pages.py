"""
Smoke test: every page must render without raising.

The engineering kernels have 100+ tests, but until now nothing tested that a
PAGE actually renders. A typo in a page, a key renamed in the state dict, or
a component signature changed in common.py would all reach the user's screen
before anyone noticed. Streamlit's own AppTest harness runs the real script
headlessly, so this catches that class before it ships.

It is a smoke test, not a check of what the pages say: a page reached without
its prerequisites correctly shows a stage guard, and that counts as rendering.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "app.py")

# v2.0: OpenIrri's page sequence, drip content.
PAGE_KEYS = ["home", "water", "emitter", "operation", "network", "design",
             "quality", "hydraulic", "pump", "cost", "report"]


@pytest.mark.parametrize("page", PAGE_KEYS)
def test_page_renders_without_exception(page):
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["page"] = page
    at.session_state["S"] = {}
    at.run()
    assert not at.exception, (
        f"{page}: {at.exception[0].type}: {at.exception[0].message}"
        if at.exception else page)


def test_every_page_key_is_registered_in_the_app():
    """PAGE_KEYS above must not drift from the app's own PAGES table."""
    import app as A
    assert [k for k, _, _, _ in A.PAGES] == PAGE_KEYS


def test_progress_is_counted_from_saved_state_not_from_visits():
    """
    Progress on the Home page counts pages whose RESULT is stored, so opening
    a page does not advance it. v1's rule — Home and the map are not design
    steps — is kept: the map is part of Home, and Home counts only once the
    project set-up is saved.
    """
    import app as A
    from modules import home
    assert home.completion({}, A.PAGES)["completed"] == 0
    assert home.completion({"setup": {"x": 1}}, A.PAGES)["completed"] == 1
    assert len(A.PAGES) == 11


def test_dark_mode_renders_too():
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["page"] = "home"
    at.session_state["S"] = {}
    at.session_state["dark_mode_pref"] = True
    at.run()
    assert not at.exception


def test_dark_mode_actually_changes_the_stylesheet():
    """
    Regression, finding 0.7.2-B2.

    The stylesheet was injected before the dark-mode switch existed, so it was
    always generated from the previous run's value. The switch read as on, the
    sidebar (whose navy is the same in both modes) looked right, and the
    canvas, cards and banners stayed light.
    """
    import re
    dark_bg = "#0f1419"
    light_bg = "#f5f7fa"

    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["page"] = "home"
    at.session_state["S"] = {}
    at.session_state["dark_mode_pref"] = True
    at.run()
    assert not at.exception
    css = "\n".join(m.value for m in at.markdown if "<style>" in str(m.value))
    assert dark_bg in css, "dark palette not emitted when dark_mode is on"
    assert light_bg not in css, "light canvas emitted while dark_mode is on"


def test_light_mode_emits_the_light_palette():
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["page"] = "home"
    at.session_state["S"] = {}
    at.session_state["dark_mode_pref"] = False
    at.run()
    css = "\n".join(m.value for m in at.markdown if "<style>" in str(m.value))
    assert "#f5f7fa" in css
    assert "#0f1419" not in css


def test_stylesheet_is_injected_before_the_sidebar():
    """
    Regression, finding 0.7.2-B4. A sidebar navigation button calls st.rerun()
    from inside sidebar(), which aborts the run. Anything after sidebar() may
    therefore never execute, so the stylesheet must be injected before it.
    """
    import inspect, app as A
    # Compare CALLS, not text: the explanatory comment mentions both names.
    calls = [ln.strip() for ln in inspect.getsource(A.main).split("\n")
             if ln.strip() in ("inject_css()", "_sidebar()")]
    assert calls[:2] == ["inject_css()", "_sidebar()"], calls


def test_dark_mode_preference_is_not_stored_in_a_widget_key():
    """
    Streamlit discards the state of a widget that is not rendered during a
    run. The dark-mode toggle sits below the navigation buttons, so a
    navigation click aborted the run before the toggle existed and the
    preference was thrown away — the switch read on while the page went back
    to light. The preference must live in a plain key.
    """
    from modules import theme
    assert theme.PREF_KEY != "dark_mode_widget"
    import inspect
    src = inspect.getsource(theme.dark_mode_toggle)
    assert "key=\"dark_mode_widget\"" in src
    assert "PREF_KEY" in src, "the toggle must write the plain key"
