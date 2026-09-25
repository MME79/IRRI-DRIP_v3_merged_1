"""
KML writer for the field boundary and its measured geometry.

Dependency-free, like the DXF writer: KML is plain XML and pulling in a
geospatial stack to emit forty lines of it would add an install risk for no
capability.

Two rules govern every line below, and both are here because of a defect this
program actually shipped.

1. KML COORDINATES ARE ``lon,lat,alt`` — longitude FIRST. The program's own
   internal representation is ``[lat, lon]``, which is the opposite. At Wadi
   El-Natrun the latitude is 30.392 and the longitude is 30.361, so a swap
   changes the computed area by 0.03 % — invisible — while rotating the long
   axis by 41 degrees. Every lateral would be laid out in the wrong direction
   and no summary figure would show it. The order is defined by the format, so
   it is never inferred here; it is written, and asserted in the tests.

2. A KML ``LinearRing`` MUST repeat the first coordinate as its last. The
   program stores rings open (the reader drops the duplicate closing vertex on
   import). Google Earth rejects, or silently mis-draws, a ring that does not
   close, so the closing vertex is restored on the way out.
"""

from __future__ import annotations

import math
from xml.sax.saxutils import escape

__all__ = ["boundary_kml", "network_kml", "kml_document", "SCHEMA",
           "COORD_PLACES"]

SCHEMA = "http://www.opengis.net/kml/2.2"

# Decimal places written per coordinate. One degree of latitude is 111 320 m,
# so 8 places is about 1.1 mm — three orders of magnitude finer than any GPS
# or survey input this program will ever be given, and finer than the
# equirectangular projection's own error over a field. Google Earth Pro emits
# 14 places; carrying them here would be false precision in a file that
# already warns it is not a survey. The cost is a round-trip that reproduces
# the area to about 1 part in 10^6, which the tests assert in metres rather
# than in float ULPs.
COORD_PLACES = 8

# Google Earth ABGR, not RGB: alpha, blue, green, red.
_LINE_ABGR = "ffd47800"      # opaque, the program's #0078d4 primary
_FILL_ABGR = "33d47800"      # the same colour at 20 % alpha
_AXIS_ABGR = "ff2020e0"      # opaque red, so the axis reads against the fill


def _fmt(value: float, places: int = COORD_PLACES) -> str:
    """
    Fixed notation, never scientific.

    ``repr(1e-05)`` is ``'1e-05'``, which is not a valid KML coordinate. A
    near-zero longitude is rare but is exactly the kind of input that turns up
    once and corrupts a file silently.
    """
    if not math.isfinite(value):
        raise ValueError(f"Coordinate is not finite: {value!r}")
    return f"{value:.{places}f}".rstrip("0").rstrip(".") or "0"


def _coord_string(latlon, indent: str = "") -> str:
    """``[lat, lon]`` pairs in, ``lon,lat,0`` triples out."""
    return "\n".join(
        f"{indent}{_fmt(lon)},{_fmt(lat)},0" for lat, lon in latlon)


def _closed(latlon: list[list[float]]) -> list[list[float]]:
    pts = [[float(a), float(b)] for a, b in latlon]
    if len(pts) < 3:
        raise ValueError(
            f"A boundary needs at least 3 vertices; got {len(pts)}.")
    if pts[0] != pts[-1]:
        pts.append(list(pts[0]))
    return pts


def kml_document(name: str, placemarks: str, styles: str = "") -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<kml xmlns="{SCHEMA}">\n'
        "<Document>\n"
        f"\t<name>{escape(name)}</name>\n"
        f"{styles}"
        f"{placemarks}"
        "</Document>\n"
        "</kml>\n")


def _styles() -> str:
    return (
        '\t<Style id="irridrip-field">\n'
        f"\t\t<LineStyle><color>{_LINE_ABGR}</color><width>3</width></LineStyle>\n"
        f"\t\t<PolyStyle><color>{_FILL_ABGR}</color></PolyStyle>\n"
        "\t</Style>\n"
        '\t<Style id="irridrip-axis">\n'
        f"\t\t<LineStyle><color>{_AXIS_ABGR}</color><width>2</width></LineStyle>\n"
        "\t</Style>\n")


def boundary_kml(latlon: list[list[float]], name: str = "Field",
                 description: str = "",
                 long_axis: list[list[float]] | None = None,
                 centroid_latlon: list[float] | None = None) -> str:
    """
    A KML document for one field boundary.

    Parameters
    ----------
    latlon
        Ring vertices as ``[[lat, lon], ...]``, open or closed.
    name
        Placemark and document name. XML-escaped, so a project name containing
        ``&`` or ``<`` cannot break the file.
    description
        Free text placed in the boundary's ``<description>``. Escaped.
    long_axis
        Optional two-point ``[[lat, lon], [lat, lon]]`` drawn as a separate
        line, so the bearing the program recommends for the laterals is
        visible in Google Earth rather than only stated as a number.
    centroid_latlon
        Optional ``[lat, lon]`` point placemark.
    """
    ring = _closed(latlon)
    parts = [
        "\t<Placemark>\n"
        f"\t\t<name>{escape(name)}</name>\n"
        f"\t\t<description>{escape(description)}</description>\n"
        "\t\t<styleUrl>#irridrip-field</styleUrl>\n"
        "\t\t<Polygon>\n"
        "\t\t\t<tessellate>1</tessellate>\n"
        "\t\t\t<altitudeMode>clampToGround</altitudeMode>\n"
        "\t\t\t<outerBoundaryIs><LinearRing><coordinates>\n"
        f"{_coord_string(ring, chr(9) * 4)}\n"
        "\t\t\t</coordinates></LinearRing></outerBoundaryIs>\n"
        "\t\t</Polygon>\n"
        "\t</Placemark>\n"
    ]
    if long_axis:
        if len(long_axis) != 2:
            raise ValueError("long_axis must be exactly two points.")
        parts.append(
            "\t<Placemark>\n"
            "\t\t<name>Long axis (suggested lateral direction)</name>\n"
            "\t\t<styleUrl>#irridrip-axis</styleUrl>\n"
            "\t\t<LineString>\n"
            "\t\t\t<tessellate>1</tessellate>\n"
            "\t\t\t<altitudeMode>clampToGround</altitudeMode>\n"
            "\t\t\t<coordinates>\n"
            f"{_coord_string(long_axis, chr(9) * 4)}\n"
            "\t\t\t</coordinates>\n"
            "\t\t</LineString>\n"
            "\t</Placemark>\n")
    if centroid_latlon:
        parts.append(
            "\t<Placemark>\n"
            "\t\t<name>Centroid</name>\n"
            "\t\t<Point><coordinates>"
            f"{_coord_string([centroid_latlon])}"
            "</coordinates></Point>\n"
            "\t</Placemark>\n")
    return kml_document(name, "".join(parts), _styles())


# --- the designed network on the real boundary ----------------------------

_LAT_OK_ABGR = "ff40c040"     # green: a row within the designed run length
_LAT_BAD_ABGR = "ff2020e0"    # red: a row longer than the design allowed for
_MANIFOLD_ABGR = "ff00a5ff"   # orange
_MAIN_ABGR = "ffff00ff"       # magenta


def _line_style(sid: str, abgr: str, width: int) -> str:
    return (f'\t<Style id="{sid}">\n'
            f"\t\t<LineStyle><color>{abgr}</color><width>{width}</width>"
            "</LineStyle>\n\t</Style>\n")


def _linestring(name: str, style: str, latlon, description: str = "") -> str:
    return ("\t\t<Placemark>\n"
            f"\t\t\t<name>{escape(name)}</name>\n"
            + (f"\t\t\t<description>{escape(description)}</description>\n"
               if description else "")
            + f"\t\t\t<styleUrl>#{style}</styleUrl>\n"
            "\t\t\t<LineString>\n"
            "\t\t\t\t<tessellate>1</tessellate>\n"
            "\t\t\t\t<altitudeMode>clampToGround</altitudeMode>\n"
            "\t\t\t\t<coordinates>\n"
            f"{_coord_string(latlon, chr(9) * 5)}\n"
            "\t\t\t\t</coordinates>\n"
            "\t\t\t</LineString>\n"
            "\t\t</Placemark>\n")


def network_kml(name: str, boundary_latlon: list[list[float]],
                laterals: list[dict], manifold_latlon=None,
                mainline_latlon=None, summary: str = "") -> str:
    """
    The designed network drawn on the real field, in folders by component.

    ``laterals`` is a list of ``{"name", "points", "over": bool, "length_m"}``,
    where ``points`` is ``[[lat, lon], ...]`` for one run. Rows longer than the
    length the hydraulics were computed for are drawn RED and say so in their
    own description, because that is the finding a reader must not be able to
    miss while panning around a field of green lines.

    Folders, not one flat list: Google Earth lets a folder be switched off, and
    a hundred laterals on top of a satellite image is unreadable until the
    laterals can be hidden to check the boundary underneath.
    """
    styles = (_styles()
              + _line_style("irridrip-lat", _LAT_OK_ABGR, 2)
              + _line_style("irridrip-lat-over", _LAT_BAD_ABGR, 3)
              + _line_style("irridrip-manifold", _MANIFOLD_ABGR, 4)
              + _line_style("irridrip-main", _MAIN_ABGR, 5))

    parts = ["\t<Placemark>\n"
             f"\t\t<name>{escape(name)} — boundary</name>\n"
             f"\t\t<description>{escape(summary)}</description>\n"
             "\t\t<styleUrl>#irridrip-field</styleUrl>\n"
             "\t\t<Polygon>\n\t\t\t<tessellate>1</tessellate>\n"
             "\t\t\t<altitudeMode>clampToGround</altitudeMode>\n"
             "\t\t\t<outerBoundaryIs><LinearRing><coordinates>\n"
             f"{_coord_string(_closed(boundary_latlon), chr(9) * 4)}\n"
             "\t\t\t</coordinates></LinearRing></outerBoundaryIs>\n"
             "\t\t</Polygon>\n\t</Placemark>\n"]

    n_over = sum(1 for lat in laterals if lat.get("over"))
    parts.append(
        "\t<Folder>\n"
        f"\t\t<name>Laterals ({len(laterals)} runs"
        + (f", {n_over} over the designed length" if n_over else "")
        + ")</name>\n")
    for lat in laterals:
        parts.append(_linestring(
            lat.get("name", "lateral"),
            "irridrip-lat-over" if lat.get("over") else "irridrip-lat",
            lat["points"], lat.get("description", "")))
    parts.append("\t</Folder>\n")

    if manifold_latlon and len(manifold_latlon) >= 2:
        parts.append("\t<Folder>\n\t\t<name>Manifold</name>\n"
                     + _linestring("Manifold", "irridrip-manifold",
                                   manifold_latlon)
                     + "\t</Folder>\n")
    if mainline_latlon and len(mainline_latlon) >= 2:
        parts.append("\t<Folder>\n\t\t<name>Mainline</name>\n"
                     + _linestring("Mainline", "irridrip-main",
                                   mainline_latlon)
                     + "\t</Folder>\n")
    return kml_document(name, "".join(parts), styles)
