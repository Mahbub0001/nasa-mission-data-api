"""
Comprehensive Automated Test Suite for NASA Mission Data API
Tests all endpoints against local logic and live NASA/JPL upstream services.
"""

from __future__ import annotations

import io
import sys
from typing import Any
from fastapi import HTTPException
import main

# Ensure UTF-8 output on Windows consoles
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

PASSED = 0
FAILED = 0


def report(name: str, success: bool, extra: str = "") -> None:
    global PASSED, FAILED
    if success:
        PASSED += 1
        print(f"  [PASS] {name} {extra}")
    else:
        FAILED += 1
        print(f"  [FAIL] {name} {extra}")


def test_overview_endpoints() -> None:
    print("\n--- Testing Overview Endpoints ---")
    
    # 1. Root
    try:
        r = main.root()
        assert r["status"] == "online"
        assert len(r["endpoints"]) >= 8
        report("GET / (root)", True, f"- Endpoints count: {len(r['endpoints'])}")
    except Exception as e:
        report("GET / (root)", False, str(e))

    # 2. Health
    try:
        h = main.health()
        assert h["status"] == "ok"
        report("GET /health", True, f"- Status: {h['status']}")
    except Exception as e:
        report("GET /health", False, str(e))

    # 3. Sources
    try:
        s = main.sources()
        assert len(s["sources"]) >= 6
        report("GET /sources", True, f"- Sources documented: {len(s['sources'])}")
    except Exception as e:
        report("GET /sources", False, str(e))


def test_missions_endpoints() -> None:
    print("\n--- Testing Missions Endpoints (NASA NSSDC Scraping) ---")
    
    # 1. Curated Missions
    try:
        m = main.missions()
        assert m["count"] >= 1
        report("GET /missions", True, f"- Missions: {m['count']}")
    except Exception as e:
        report("GET /missions", False, str(e))

    # 2. NEAR Shoemaker Scraped Page
    try:
        near = main.near_mission()
        assert near["mission"] == "NEAR Shoemaker"
        assert len(near["specifications"]) >= 3
        assert len(near["tables"]) >= 1
        assert len(near["paragraphs"]) >= 2
        specs = ", ".join(near["specifications"].keys())
        report("GET /missions/near", True, f"- Specs parsed: [{specs}] | Tables: {len(near['tables'])}")
    except Exception as e:
        report("GET /missions/near", False, str(e))

    # 3. NEAR Sections
    try:
        sec = main.near_sections()
        assert "specifications" in sec
        assert sec["paragraph_count"] >= 2
        report("GET /missions/near/sections", True, f"- Headings: {len(sec['sections'])} | Paragraphs: {sec['paragraph_count']}")
    except Exception as e:
        report("GET /missions/near/sections", False, str(e))


def test_asteroids_endpoints() -> None:
    print("\n--- Testing Asteroids Endpoints (JPL SBDB & SBDB Query) ---")
    
    # 1. Asteroid Search (NEO only)
    try:
        res = main.search_asteroids(limit=5, offset=0, neo_only=True)
        assert res["count"] == 5
        assert len(res["asteroids"]) == 5
        first = res["asteroids"][0]
        assert "spkid" in first
        assert "full_name" in first
        report("GET /asteroids/search (neo_only=True)", True, f"- Retrieved {res['count']} NEOs. Sample: {first['full_name'].strip()}")
    except Exception as e:
        report("GET /asteroids/search (neo_only=True)", False, str(e))

    # 2. Asteroid Search Pagination (offset=5)
    try:
        res_page = main.search_asteroids(limit=3, offset=5, neo_only=True)
        assert res_page["count"] == 3
        report("GET /asteroids/search (offset=5)", True, f"- Paged 3 items starting at offset 5")
    except Exception as e:
        report("GET /asteroids/search (offset=5)", False, str(e))

    # 3. Asteroid Details (433 Eros)
    try:
        det = main.asteroid_details("433 Eros")
        fullname = det["data"]["object"]["fullname"]
        report("GET /asteroids/433 Eros", True, f"- Full name: {fullname}")
    except Exception as e:
        report("GET /asteroids/433 Eros", False, str(e))

    # 4. Asteroid Ambiguous Query (Halley)
    try:
        ambig = main.asteroid_details("Halley")
        assert ambig["status"] == "multiple_matches"
        assert ambig["count"] >= 2
        report("GET /asteroids/Halley (ambiguous query)", True, f"- Handled multiple matches cleanly ({ambig['count']} candidates)")
    except Exception as e:
        report("GET /asteroids/Halley (ambiguous query)", False, str(e))

    # 5. Asteroid Not Found (404 handling)
    try:
        main.asteroid_details("nonexistent_asteroid_99999999")
        report("GET /asteroids/nonexistent (404 expected)", False, "Did not raise 404")
    except HTTPException as exc:
        if exc.status_code == 404:
            report("GET /asteroids/nonexistent (404 expected)", True, f"- Received proper 404: {exc.detail['message']}")
        else:
            report("GET /asteroids/nonexistent (404 expected)", False, f"Unexpected code: {exc.status_code}")
    except Exception as e:
        report("GET /asteroids/nonexistent (404 expected)", False, str(e))


def test_close_approaches_endpoints() -> None:
    print("\n--- Testing Close Approaches Endpoints (JPL CAD) ---")
    
    # 1. General Close Approaches
    try:
        cad = main.close_approaches(
            date_min="2026-01-01",
            date_max="2027-12-31",
            dist_max_au=0.1,
            designation=None,
            limit=5,
        )
        assert cad["count"] >= 1
        assert "events" in cad
        sample = cad["events"][0]
        report("GET /close-approaches", True, f"- Found {cad['count']} events. Sample des: {sample.get('des')}, dist: {sample.get('dist')} au")
    except Exception as e:
        report("GET /close-approaches", False, str(e))

    # 2. Specific Asteroid Close Approach (433 Eros)
    try:
        cad_eros = main.close_approaches(
            date_min="2000-01-01",
            date_max="2035-12-31",
            dist_max_au=0.3,
            designation="433",
            limit=5,
        )
        assert cad_eros["count"] >= 1
        report("GET /close-approaches?des=433", True, f"- Found {cad_eros['count']} Eros approaches. Earth dist: {cad_eros['events'][0].get('dist')} au")
    except Exception as e:
        report("GET /close-approaches?des=433", False, str(e))


def test_mission_design_endpoints() -> None:
    print("\n--- Testing Mission Design Endpoints (JPL MDesign) ---")
    
    # 1. Accessible Targets (Criterion 1 - Min Departure V-infinity)
    try:
        md = main.accessible_mission_targets(
            years="2027",
            limit=5,
            small_body_group="neo",
            criterion=1,
        )
        assert md["count"] >= 1
        assert "targets" in md
        first = md["targets"][0]
        report("GET /mission-design/accessible (crit=1)", True, f"- Target: {first.get('name')}, Dep: {first.get('date0')}, Total DV: {first.get('dv_tot')} km/s")
    except Exception as e:
        report("GET /mission-design/accessible (crit=1)", False, str(e))

    # 2. Accessible Targets (Criterion 3 - Min Total Delta-V)
    try:
        md3 = main.accessible_mission_targets(
            years="2028",
            limit=5,
            small_body_group="neo",
            criterion=3,
        )
        assert md3["count"] >= 1
        first3 = md3["targets"][0]
        report("GET /mission-design/accessible (crit=3)", True, f"- Target: {first3.get('name')}, Total DV: {first3.get('dv_tot')} km/s")
    except Exception as e:
        report("GET /mission-design/accessible (crit=3)", False, str(e))


def main_test() -> None:
    print("==========================================================")
    print("🚀 Running NASA Mission Data API Automated Verification")
    print("==========================================================")
    
    test_overview_endpoints()
    test_missions_endpoints()
    test_asteroids_endpoints()
    test_close_approaches_endpoints()
    test_mission_design_endpoints()

    print("\n==========================================================")
    print(f"📊 Summary: {PASSED} Passed, {FAILED} Failed")
    print("==========================================================")
    
    if FAILED > 0:
        sys.exit(1)


if __name__ == "__main__":
    main_test()
