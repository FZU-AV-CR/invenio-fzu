"""Standalone unit test for ConeSearchFacet (FRAM sky-position search).

Run this with the project's Python environment, e.g.:

    ./run.sh shell -c "python test_cone_search.py"

or if you have a virtualenv/uv env active locally with healpy/numpy/
invenio-search installed:

    python test_cone_search.py

This test does NOT require a running OpenSearch/Docker stack -- it only
exercises the Python query-building logic in models/fram/facets.py
(ConeSearchFacet.add_filter / _build_cone_query / _build_round1_query /
_build_round2_query / _circle_to_polygon), using the sample record's
known coordinates from sample_data/Fram/fram_001.json:

    center: {ra: 267.49140094924627, dec: -18.87911384043446}
    center_geo: {lat: -18.87911384043446, lon: -92.50859905075373}
    healpix_idx: 32574
    footprint: polygon around lon -92.6..-92.4, lat -18.98..-18.78

It verifies:
  1. A query centered exactly on the sample record's position (radius
     1 deg) produces a `terms` query (round 1) whose pixel list
     CONTAINS 32574 (the sample record's healpix_idx) -- i.e. round 1
     would match this record.
  2. The same query's round-2 `geo_shape` polygon (circle approximation
     around the query point) has all its vertices within `radius +
     epsilon` degrees of the query center (sanity-check the circle
     approximation itself is geometrically correct).
  3. A query for a sky position far away (e.g. RA=0, Dec=0, radius=1
     deg -- ~90+ degrees away from the sample point) produces a round-1
     pixel list that does NOT contain 32574 -- i.e. round 1 correctly
     excludes an unrelated record.
  4. Round 1 for the near query and the far query are different pixel
     sets (sanity check that query_disc is actually being driven by the
     input lat/lon, not returning some constant/degenerate output).

Because this only requires `healpy`, `numpy`, and the two very small
Invenio dependencies used by facets.py (`invenio_records_resources`,
`invenio_search`), it can be run in isolation, without a live
OpenSearch/DB/etc. -- those imports only pull in the DSL/`Facet` base
classes' Python definitions, not any actual network client.
"""

from __future__ import annotations

import json
import os
import sys

# Ensure the repo root (parent of this tests/ dir) is on sys.path, so
# `models.fram.facets` is importable regardless of the current working
# directory this script is run from (repo root, tests/, or elsewhere).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from models.fram.facets import (  # noqa: E402
    HEALPIX_NSIDE,
    MAX_FOV_RADIUS_DEG,
    ConeSearchFacet,
)

import healpy as hp  # noqa: E402
import numpy as np  # noqa: E402


SAMPLE_LAT = -18.87911384043446
SAMPLE_LON = -92.50859905075373
SAMPLE_HEALPIX_IDX = 32574


def _extract_terms_values(query) -> list[int]:
    """Extract the `terms` clause's value list from a combined `Q` object.

    `add_filter`/`_build_cone_query` returns `round1 & round2` (a
    `Bool` query with `must: [round1, round2]`, or a raw `terms`/
    `match_none` dsl.Q if it's round1 alone before the `&`). We only
    need round1's terms list here, which after `&` combination lives
    at `query.must[0]` if round1 was a `terms` Query object, or
    `query["terms"]` if inspecting a plain Query directly.
    """
    d = query.to_dict()
    # `&` on two Query objects produces {"bool": {"must": [q1, q2]}}
    # (assuming q1 is not itself a bool query, which terms/match_none
    # never are).
    if "bool" in d and "must" in d["bool"]:
        for clause in d["bool"]["must"]:
            if "terms" in clause:
                return clause["terms"]["metadata.healpix_idx"]
            if "match_none" in clause:
                return []
    if "terms" in d:
        return d["terms"]["metadata.healpix_idx"]
    if "match_none" in d:
        return []
    raise AssertionError(f"Could not find terms/match_none clause in: {d}")


def _extract_polygon_coords(query) -> list[list[float]]:
    """Extract round-2's geo_shape polygon coordinates from the combined query."""
    d = query.to_dict()
    if "bool" in d and "must" in d["bool"]:
        for clause in d["bool"]["must"]:
            if "geo_shape" in clause:
                return clause["geo_shape"]["metadata.footprint"]["shape"][
                    "coordinates"
                ][0]
    if "geo_shape" in d:
        return d["geo_shape"]["metadata.footprint"]["shape"]["coordinates"][0]
    raise AssertionError(f"Could not find geo_shape clause in: {d}")


def great_circle_distance_deg(lat1, lon1, lat2, lon2) -> float:
    """Haversine great-circle distance in degrees between two lat/lon points."""
    lat1_r, lon1_r, lat2_r, lon2_r = map(np.radians, (lat1, lon1, lat2, lon2))
    dlat = lat2_r - lat1_r
    dlon = lon2_r - lon1_r
    a = (
        np.sin(dlat / 2) ** 2
        + np.cos(lat1_r) * np.cos(lat2_r) * np.sin(dlon / 2) ** 2
    )
    c = 2 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))
    return np.degrees(c)


def test_near_query_matches_sample_record():
    """Round 1 for a query centered on the sample point should include its pixel."""
    facet = ConeSearchFacet(
        field="metadata.healpix_idx", footprint_field="metadata.footprint"
    )
    value = json.dumps({"lat": SAMPLE_LAT, "lon": SAMPLE_LON, "radius": 1.0})
    query = facet.add_filter([value])
    assert query is not None, "add_filter returned None for a valid cone query"

    pix_list = _extract_terms_values(query)
    assert SAMPLE_HEALPIX_IDX in pix_list, (
        f"Expected healpix_idx {SAMPLE_HEALPIX_IDX} to be included in round-1 "
        f"terms query for a search centered exactly on the sample record's "
        f"position, but it was not found in {len(pix_list)} returned pixels."
    )

    # Sanity check: the widened query radius (1.0 + MAX_FOV_RADIUS_DEG) should
    # produce a broad-ish set of pixels, not a single pixel or the whole sky.
    total_pixels = hp.nside2npix(HEALPIX_NSIDE)
    assert 0 < len(pix_list) < total_pixels, (
        f"round-1 pixel list size {len(pix_list)} looks degenerate "
        f"(total sky pixels at NSIDE={HEALPIX_NSIDE}: {total_pixels})"
    )
    print(
        f"[PASS] near query: healpix_idx {SAMPLE_HEALPIX_IDX} found in "
        f"round-1 terms list ({len(pix_list)} / {total_pixels} pixels, "
        f"query radius {1.0 + MAX_FOV_RADIUS_DEG} deg)"
    )


def test_far_query_excludes_sample_record():
    """Round 1 for a query far from the sample point should exclude its pixel."""
    facet = ConeSearchFacet(
        field="metadata.healpix_idx", footprint_field="metadata.footprint"
    )
    # RA=0 (lon=0), Dec=0 -- roughly ~90+ degrees away from the sample
    # point (lat=-18.88, lon=-92.51), well beyond even the widened
    # radius (1.0 + MAX_FOV_RADIUS_DEG = 26 deg).
    far_lat, far_lon = 0.0, 0.0
    dist = great_circle_distance_deg(SAMPLE_LAT, SAMPLE_LON, far_lat, far_lon)
    assert dist > (1.0 + MAX_FOV_RADIUS_DEG), (
        f"Test setup error: far query point is only {dist:.1f} deg from the "
        f"sample point, not far enough to test exclusion "
        f"(need > {1.0 + MAX_FOV_RADIUS_DEG} deg)"
    )

    value = json.dumps({"lat": far_lat, "lon": far_lon, "radius": 1.0})
    query = facet.add_filter([value])
    assert query is not None

    pix_list = _extract_terms_values(query)
    assert SAMPLE_HEALPIX_IDX not in pix_list, (
        f"Expected healpix_idx {SAMPLE_HEALPIX_IDX} to be EXCLUDED from "
        f"round-1 terms query for a search {dist:.1f} deg away from the "
        f"sample record's position, but it was found."
    )
    print(
        f"[PASS] far query ({dist:.1f} deg away): healpix_idx "
        f"{SAMPLE_HEALPIX_IDX} correctly excluded from round-1 terms list "
        f"({len(pix_list)} pixels)"
    )


def test_round1_pixel_sets_differ_by_query_position():
    """Sanity check: different query positions produce different pixel sets."""
    facet = ConeSearchFacet(
        field="metadata.healpix_idx", footprint_field="metadata.footprint"
    )
    near_value = json.dumps({"lat": SAMPLE_LAT, "lon": SAMPLE_LON, "radius": 1.0})
    far_value = json.dumps({"lat": 0.0, "lon": 0.0, "radius": 1.0})

    near_pixels = set(_extract_terms_values(facet.add_filter([near_value])))
    far_pixels = set(_extract_terms_values(facet.add_filter([far_value])))

    assert near_pixels != far_pixels, (
        "Round-1 pixel sets for two very different query positions are "
        "identical -- query_disc does not appear to be responding to the "
        "input lat/lon (possible bug: are lat/lon swapped, or is a "
        "constant/cached value being used?)"
    )
    assert len(near_pixels & far_pixels) == 0, (
        "Round-1 pixel sets for two ~90+ deg-apart query positions "
        "unexpectedly overlap -- widened search radius "
        f"({1.0 + MAX_FOV_RADIUS_DEG} deg) may be too large, or "
        "there's a bug in the disc-query geometry."
    )
    print(
        f"[PASS] near/far round-1 pixel sets are disjoint "
        f"({len(near_pixels)} vs {len(far_pixels)} pixels, no overlap)"
    )


def test_round2_polygon_is_geometrically_sane():
    """Round 2's circle->polygon approximation should stay within radius+eps of center."""
    facet = ConeSearchFacet(
        field="metadata.healpix_idx", footprint_field="metadata.footprint"
    )
    radius = 2.5
    value = json.dumps({"lat": SAMPLE_LAT, "lon": SAMPLE_LON, "radius": radius})
    query = facet.add_filter([value])
    assert query is not None

    coords = _extract_polygon_coords(query)
    assert coords[0] == coords[-1], "Polygon ring is not closed (first != last point)"
    assert len(coords) >= 10, f"Polygon has suspiciously few points: {len(coords)}"

    max_dist = 0.0
    for lon, lat in coords[:-1]:
        d = great_circle_distance_deg(SAMPLE_LAT, SAMPLE_LON, lat, lon)
        max_dist = max(max_dist, d)

    assert abs(max_dist - radius) < 0.05, (
        f"Polygon vertices' max distance from center ({max_dist:.4f} deg) "
        f"deviates too much from the requested radius ({radius} deg) -- "
        f"circle-to-polygon approximation may be broken."
    )
    print(
        f"[PASS] round-2 polygon: {len(coords) - 1} vertices, "
        f"max distance from center = {max_dist:.4f} deg (requested radius "
        f"{radius} deg)"
    )


def test_zero_radius_produces_valid_nondegenerate_polygon():
    """radius=0 ('exact position') should still produce a usable polygon."""
    facet = ConeSearchFacet(
        field="metadata.healpix_idx", footprint_field="metadata.footprint"
    )
    value = json.dumps({"lat": SAMPLE_LAT, "lon": SAMPLE_LON, "radius": 0})
    query = facet.add_filter([value])
    assert query is not None

    coords = _extract_polygon_coords(query)
    assert coords[0] == coords[-1]
    # All vertices should be extremely close to the center (epsilon radius).
    for lon, lat in coords[:-1]:
        d = great_circle_distance_deg(SAMPLE_LAT, SAMPLE_LON, lat, lon)
        assert d < 0.01, f"radius=0 polygon vertex too far from center: {d} deg"
    print(f"[PASS] radius=0 query produces a valid non-degenerate polygon")


def test_invalid_filter_values_are_ignored():
    """Malformed filter values should be silently skipped, not raise."""
    facet = ConeSearchFacet(
        field="metadata.healpix_idx", footprint_field="metadata.footprint"
    )
    assert facet.add_filter([]) is None
    assert facet.add_filter(["not json"]) is None
    assert facet.add_filter([json.dumps({"lat": 0, "lon": 0})]) is None  # missing radius
    assert facet.add_filter([json.dumps({"lat": 0, "lon": 0, "radius": -1})]) is None
    print("[PASS] invalid filter values correctly ignored (return None)")


if __name__ == "__main__":
    tests = [
        test_near_query_matches_sample_record,
        test_far_query_excludes_sample_record,
        test_round1_pixel_sets_differ_by_query_position,
        test_round2_polygon_is_geometrically_sane,
        test_zero_radius_produces_valid_nondegenerate_polygon,
        test_invalid_filter_values_are_ignored,
    ]
    failures = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failures += 1
            print(f"[FAIL] {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failures += 1
            print(f"[ERROR] {t.__name__}: {type(e).__name__}: {e}")

    print()
    if failures:
        print(f"{failures} test(s) FAILED.")
        sys.exit(1)
    else:
        print(f"All {len(tests)} tests PASSED.")
