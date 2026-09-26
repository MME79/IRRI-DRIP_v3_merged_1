# Copyright (c) 2026 Dr. Mohamed Embaby. All rights reserved.
# IRRI-DRIP is the intellectual property of Dr. Mohamed Embaby (see COPYRIGHT.txt).
"""
IRRI-DRIP — drip irrigation system design (Streamlit).
Copyright (c) 2026 Dr. Mohamed Embaby. All rights reserved.
Developed by Dr. Mohamed Embaby, Water Management Research Institute (WMRI),
National Water Research Center.

The drip counterpart to OpenIrri / PY-IRRI (sprinkler system design). From
version 2.0 the two programs share one interface: the same sidebar, the same
page sequence, the same stylesheet (config/theme.py is OpenIrri's own). The
engineering underneath is drip's — see engine/.

Run locally with:
    streamlit run app.py
"""

from __future__ import annotations

import json
import os

import streamlit as st

from modules.common import inject_css
from modules import theme

from engine import APP_VERSION, APP_AUTHOR, COPYRIGHT, OWNERSHIP  # noqa: E402  (single source)
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

# ---------------------------------------------------------------------------
# Page modules, imported defensively as OpenIrri does, so an environment
# problem in one page (e.g. the optional map libraries) cannot stop the rest
# of the program from opening.
# ---------------------------------------------------------------------------
_IMPORT_ERRORS: list[str] = []


def _load(name):
    try:
        return __import__(f"modules.{name}", fromlist=[name])
    except Exception as exc:  # noqa: BLE001
        _IMPORT_ERRORS.append(f"{name}: {type(exc).__name__}: {exc}")
        return None


home = _load("home")
crop_water = _load("crop_water")
emitter = _load("emitter")
operation = _load("operation")
network_layout = _load("network_layout")
network_design = _load("network_design")
quality = _load("quality")
hydraulic = _load("hydraulic")
pump = _load("pump")
cost = _load("cost")
reports = _load("reports")

# (key, sidebar label, module, the state key the page produces)
PAGES = [
    ("home",      "🏠 Home",                       home,           "setup"),
    ("water",     "🌾 Crop Water Requirements",    crop_water,     "water"),
    ("emitter",   "💧 Emitter Selection",          emitter,        "emitter"),
    ("operation", "📋 Operational Design",         operation,      "operation"),
    ("network",   "🔵 Pipe Network Layout",        network_layout, "network"),
    ("design",    "🚰 Pipe Network Design",        network_design, "manifold"),
    ("quality",   "🧪 Water Quality & Filtration", quality,        "quality"),
    ("hydraulic", "🧮 Hydraulic Design",           hydraulic,      "hydraulic"),
    ("pump",      "⚙️ Pump Selection",             pump,           "pump"),
    ("cost",      "💰 Cost Estimation",            cost,           "cost"),
    ("report",    "📊 Reports & Export",           reports,        "verdict"),
]

# Design steps for the progress figures on the Home page. Home itself is the
# project set-up, so it counts; the report step counts once a verdict exists.
DESIGN_STEPS = PAGES


@st.cache_data
def load_data():
    def rd(name):
        with open(os.path.join(DATA_DIR, name), encoding="utf-8") as fh:
            return json.load(fh)
    return (rd("emitters.json"), rd("pipes.json"), rd("crops.json"),
            rd("pumps.json"), rd("unit_rates.json"))


def init_state():
    if "S" not in st.session_state:
        st.session_state.S = {}
    if "page" not in st.session_state:
        st.session_state.page = "home"
    if "dev_mode" not in st.session_state:
        st.session_state.dev_mode = False


def _sidebar():
    # OpenIrri's brand block, word for word except the name and subtitle.
    st.sidebar.markdown(
        f"""
        <div style="text-align:center;padding:1rem 0;">
            <div style="font-size:2rem;">💧</div>
            <div style="font-size:1.05rem;font-weight:700;color:#4da6ff;letter-spacing:1px;">
                IRRI-DRIP v.{APP_VERSION.rsplit('.', 1)[0]}
            </div>
            <div style="font-size:0.7rem;color:#6c757d;letter-spacing:2px;">
                Drip System Design
            </div>
        </div>
        <hr/>
        """,
        unsafe_allow_html=True,
    )

    for key, label, _mod, _state in PAGES:
        is_active = st.session_state.page == key
        if st.sidebar.button(label, key=f"nav_{key}", width="stretch",
                             type="primary" if is_active else "secondary"):
            st.session_state.page = key
            st.rerun()

    st.sidebar.markdown("---")
    st.sidebar.markdown('<p class="sidebar-section-header">🔧 Developer Tools</p>',
                        unsafe_allow_html=True)
    dev = st.sidebar.checkbox("Developer Mode", value=st.session_state.dev_mode,
                              key="dev_mode_widget",
                              help="Show the stored state of every page for "
                                   "troubleshooting")
    if dev != st.session_state.dev_mode:
        st.session_state.dev_mode = dev
        st.rerun()
    if st.session_state.dev_mode:
        st.sidebar.markdown('<span class="dev-mode-badge">🔧 Dev Mode Active</span>',
                            unsafe_allow_html=True)

    st.sidebar.markdown("---")
    theme.dark_mode_toggle()

    st.sidebar.markdown(
        """
        <hr/>
        <div style="font-size:0.7rem;color:#6c757d;text-align:center;line-height:1.5;">
            <b style="color:#adb5bd;">{COPYRIGHT}</b><br/>
            Developed by {APP_AUTHOR}<br/>
            Water Management Research Institute · NWRC<br/>
            Drip counterpart to OpenIrri (PY-IRRI)
        </div>
        """.format(COPYRIGHT=COPYRIGHT, APP_AUTHOR=APP_AUTHOR),
        unsafe_allow_html=True,
    )


def main() -> None:
    st.set_page_config(page_title="IRRI-DRIP — Drip System Design",
                       page_icon="💧", layout="wide",
                       initial_sidebar_state="expanded",
                       menu_items={"About": f"**IRRI-DRIP {APP_VERSION}** — drip irrigation "
                                            f"system design.\n\n{COPYRIGHT}\n\n{OWNERSHIP}"})
    init_state()
    # CSS first: a navigation click aborts the run inside the sidebar, and a
    # run that injected no stylesheet renders unstyled.
    inject_css()
    _sidebar()

    if _IMPORT_ERRORS:
        with st.sidebar.expander("⚠️ Import warnings", expanded=False):
            for e in _IMPORT_ERRORS:
                st.caption(e)

    emitters, pipes, crops, pumps, rates = load_data()
    from engine import boq as BQ
    # The project's own pipe prices, applied before any page sees the
    # catalogue, so the telescoped sizing and the BOQ use the same price.
    ctx = {"emitters": emitters,
           "pipes": BQ.apply_pipe_prices(pipes, st.session_state.S.get("pipe_prices")),
           "pipes_catalogue": pipes, "crops": crops,
           "pumps": pumps, "rates": rates, "S": st.session_state.S,
           "version": APP_VERSION, "pages": PAGES}

    for key, label, mod, _state in PAGES:
        if st.session_state.page != key:
            continue
        if mod is None or not hasattr(mod, "show"):
            st.error(f"Page '{label}' is not available.")
        else:
            mod.show(ctx)
        break


if __name__ == "__main__":
    main()
