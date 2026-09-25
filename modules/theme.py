"""
IRRI-DRIP visual theme — OpenIrri's stylesheet, applied literally.

VERSION 2.0 DECISION
--------------------
Version 1 took OpenIrri's colour tokens but kept a navy/blue navigation,
deliberately reserving orange for warnings. For 2.0 the Institute asked for
the drip program to look and behave exactly like the sprinkler program. The
stylesheet is therefore OpenIrri's own ``get_main_css`` and
``get_graph_paper_css``, carried unchanged in config/theme.py — the same
orange navigation, headers, info boxes, tabs, metrics and graph paper.

What this module adds sits strictly ON TOP and never overrides OpenIrri's
look in light mode:

1. Classes for IRRI-DRIP's own components (result cards, banners, the
   context strip), written in OpenIrri's tokens so they read as part of it.
2. A dark mode that actually darkens the canvas and inputs. OpenIrri's
   ``dark_mode`` flag only swaps a few CSS variables; the Streamlit canvas
   stays white. The v1 fix for this is kept.

The FAIL signal
---------------
With orange navigation, the warm colour no longer means "warning" in the
sidebar. A failed design check is therefore always shown as a RED error box
with a ✗ mark and the word FAIL or NOT PASSED, never by colour alone.
"""

from __future__ import annotations

import streamlit as st

from config.theme import (COLORS as OI_COLORS, FONTS, LAYOUT as OI_LAYOUT,
                          get_main_css, get_graph_paper_css)

# Re-exported: graphics and common read their tokens from here.
COLORS = dict(OI_COLORS)
LAYOUT = {
    "sidebar_width": OI_LAYOUT["sidebar_width"],
    "radius": OI_LAYOUT["border_radius"],
    "radius_sm": OI_LAYOUT["border_radius_sm"],
    "radius_lg": OI_LAYOUT["border_radius_lg"],
    "shadow_sm": OI_LAYOUT["shadow_sm"],
    "shadow_md": OI_LAYOUT["shadow_md"],
    "shadow_lg": OI_LAYOUT["shadow_lg"],
}

# The preference is held in a PLAIN session-state key, not in the widget's
# own key: Streamlit discards the state of a widget that is not rendered in a
# run, and a navigation click aborts the run before the switch is drawn. The
# mode was lost on every navigation in v0.7 until this was done.
PREF_KEY = "dark_mode_pref"


def is_dark() -> bool:
    return bool(st.session_state.get(PREF_KEY, False))


def tokens(dark: bool | None = None) -> dict:
    d = is_dark() if dark is None else dark
    C = COLORS
    return {
        **C,
        "canvas": C["bg_canvas_dark"] if d else "#ffffff",
        "card": C["bg_card_dark"] if d else C["bg_card"],
        "ink": C["text_inverse"] if d else C["text_primary"],
        "muted": C["text_muted"] if d else C["text_secondary"],
        "grid": C["grid_line_dark"] if d else C["grid_line"],
        "border": "#2a3441" if d else "rgba(0,0,0,0.08)",
    }


def extra_css(dark: bool | None = None) -> str:
    """IRRI-DRIP components in OpenIrri's tokens, plus the dark-mode canvas."""
    t = tokens(dark)
    d = is_dark() if dark is None else dark
    dark_rules = f"""
    .stApp {{ background: {t['canvas']} !important; }}
    [data-testid="stMain"] p, [data-testid="stMain"] li,
    [data-testid="stMain"] h1, [data-testid="stMain"] h2,
    [data-testid="stMain"] h3, [data-testid="stMain"] h4,
    [data-testid="stMain"] label, [data-testid="stWidgetLabel"] p,
    [data-testid="stMain"] span {{ color: {t['ink']}; }}
    [data-testid="stMain"] input, [data-testid="stMain"] textarea,
    [data-testid="stMain"] [data-baseweb="select"] > div {{
        background: {t['card']} !important; color: {t['ink']} !important;
        border-color: {t['border']} !important; }}
    [data-testid="stMain"] [data-testid="stExpander"] details {{
        background: {t['card']} !important; border-color: {t['border']} !important; }}
    [data-testid="stMain"] [data-testid="stExpander"] summary,
    [data-testid="stMain"] [data-testid="stExpander"] summary:hover {{
        background: {t['card']} !important; color: {t['ink']} !important; }}
    [data-testid="stMain"] [data-testid="stExpander"] summary * {{ color: {t['ink']} !important; }}
    [data-testid="stMetric"] {{ background: {t['card']} !important;
        border-color: {t['border']} !important; }}
    [data-testid="stTabs"] [role="tablist"] button p {{ color: {t['ink']}; }}
    /* message boxes hold bare text nodes, not <p>: colour the box itself */
    [data-testid="stMain"] .info-box, [data-testid="stMain"] .success-box,
    [data-testid="stMain"] .warning-box, [data-testid="stMain"] .error-box,
    [data-testid="stMain"] .idr-note {{ color: {t['ink']}; }}
    """ if d else ""
    return f"""
    <style>
    /* ---------- IRRI-DRIP result cards, drawn like OpenIrri's st.metric ---------- */
    .idr-cards {{ display:flex; gap:0.75rem; flex-wrap:wrap; margin:0.5rem 0 1rem; }}
    .idr-card {{
        flex:1 1 170px; background:{t['card']}; border:1px solid {t['border']};
        border-radius:{LAYOUT['radius']}; padding:1rem;
    }}
    .idr-card .idr-k {{
        font-size:0.875rem; letter-spacing:0.5px; text-transform:uppercase;
        color:{t['muted']};
    }}
    .idr-card .idr-v {{
        font-family:{FONTS['monospace']}; font-weight:600; font-size:1.6rem;
        color:{t['ink']}; line-height:1.3; margin-top:0.2rem;
    }}
    .idr-card .idr-u {{ font-size:0.95rem; color:{t['muted']}; font-weight:400; }}
    .idr-card .idr-s {{ font-size:0.8rem; font-weight:600; margin-top:0.35rem;
        display:inline-block; padding:0.1rem 0.6rem; border-radius:20px; }}
    .idr-ok .idr-s   {{ background:rgba(0,200,83,0.15); color:{COLORS['status_ok']}; }}
    .idr-warn .idr-s {{ background:rgba(255,152,0,0.15); color:{COLORS['status_warning']}; }}
    .idr-bad .idr-s  {{ background:rgba(244,67,54,0.15); color:{COLORS['status_error']}; }}
    .idr-bad  {{ border-color:{COLORS['status_error']}; }}

    /* ---------- a disabled primary button kept its blue fill but lost its
       text contrast (dark text on blue): grey it out instead ---------- */
    [data-testid="stBaseButton-primary"]:disabled,
    [data-testid="stBaseButton-primary"]:disabled p {{
        background: #9aa5b1 !important; color: #ffffff !important;
        border-color: #9aa5b1 !important; opacity: 0.8; cursor: not-allowed; }}
    /* ---------- context strip ---------- */
    .idr-ctx {{ display:flex; gap:1.4rem; flex-wrap:wrap; background:{t['card']};
        border:1px solid {t['border']}; border-radius:{LAYOUT['radius']};
        padding:0.5rem 0.9rem; margin:0.25rem 0 1rem; font-size:0.85rem; }}
    .idr-ctx b {{ color:{t['ink']}; }}
    .idr-ctx span {{ color:{t['muted']}; }}

    /* ---------- workflow step chips (OpenIrri field-layout pattern) ---------- */
    .idr-step {{ text-align:center; padding:10px; border-radius:8px; color:white; }}
    .idr-step .ic {{ font-size:1.4em; }}
    .idr-step .nm {{ font-size:0.8em; }}

    /* ---------- captions ---------- */
    .idr-caption {{ color:{t['muted']}; font-size:0.85rem; line-height:1.6;
        margin:0.2rem 0 0.8rem; }}
    .idr-note {{ font-size:0.92rem; line-height:1.65; }}
    .idr-dev {{ background:{COLORS['bg_darker']}; color:{COLORS['accent_green']};
        font-family:{FONTS['monospace']}; font-size:0.75rem; padding:0.5rem 0.75rem;
        border-radius:{LAYOUT['radius']}; border-left:3px solid {COLORS['accent_green']}; }}
    {dark_rules}
    </style>
    """


def inject():
    """
    Apply OpenIrri's stylesheet, then IRRI-DRIP's additions. Call once, early,
    on every run — before the sidebar, whose navigation can abort the run.
    """
    dark = is_dark()
    st.markdown(get_main_css(dark_mode=dark), unsafe_allow_html=True)
    st.markdown(get_graph_paper_css(), unsafe_allow_html=True)
    st.markdown(extra_css(dark), unsafe_allow_html=True)


def dark_mode_toggle():
    """OpenIrri's '🌙 Dark mode' checkbox at the foot of the sidebar."""
    dark = st.sidebar.checkbox("🌙 Dark mode",
                               value=st.session_state.get(PREF_KEY, False),
                               key="dark_mode_widget")
    if dark != st.session_state.get(PREF_KEY, False):
        st.session_state[PREF_KEY] = dark
        st.rerun()
