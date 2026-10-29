"""
Live End-to-End HTTP Integration Test Suite for NASA Mission Data API.
Spawns the real FastAPI ASGI server on localhost and executes real HTTP requests
against all routes, asserting response codes, headers, and payload structures.
"""

from __future__ import annotations

import io
import sys
import threading
import time
from typing import Any
import requests
import uvicorn
from main import app

# Ensure clean UTF-8 output on Windows consoles
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

TEST_PORT = 8008
BASE_URL = f"http://127.0.0.1:{TEST_PORT}"

PASSED = 0
FAILED = 0


def log_result(name: str, passed: bool, info: str = "") -> None:
    global PASSED, FAILED
    if passed:
        PASSED += 1
        print(f"  [PASS] {name} {info}")
    else:
        FAILED += 1
        print(f"  [FAIL] {name} {info}")


def run_tests() -> None:
    global PASSED, FAILED
    print("=" * 65)
    print("🛰️  STARTING LIVE HTTP END-TO-END VERIFICATION")
    print(f"    Target: {BASE_URL}")
    print("=" * 65)

    # -------------------------------------------------------------
    # 1. System & Documentation
    # -------------------------------------------------------------
    print("\n[Group 1] System Health & Documentation Endpoints")
    
    # Health Probe
    try:
        t0 = time.time()
        r = requests.get(f"{BASE_URL}/health", headers={"Origin": "https://spaceapps.game"}, timeout=5)
        dt = round((time.time() - t0) * 1000, 1)
        data = r.json()
        assert r.status_code == 200
        assert data.get("status") == "ok"
        assert r.headers.get("access-control-allow-origin") == "*"
        log_result("GET /health", True, f"({r.status_code} OK, {dt}ms) - CORS Origin: * Verified")
    except Exception as e:
        log_result("GET /health", False, str(e))

    # Root
    try:
        r = requests.get(f"{BASE_URL}/", timeout=5)
        data = r.json()
        assert r.status_code == 200
        assert "documentation" in data
        assert len(data.get("endpoints", [])) >= 9
        log_result("GET /", True, f"({r.status_code} OK) - Endpoints: {len(data['endpoints'])}")
    except Exception as e:
        log_result("GET /", False, str(e))

    # Swagger Documentation
    try:
        r = requests.get(f"{BASE_URL}/docs", timeout=5)
        assert r.status_code == 200
        assert "swagger-ui" in r.text.lower()
        log_result("GET /docs", True, f"({r.status_code} OK) - Swagger UI HTML loaded")
    except Exception as e:
        log_result("GET /docs", False, str(e))

    # OpenAPI JSON Schema
    try:
        r = requests.get(f"{BASE_URL}/openapi.json", timeout=5)
        data = r.json()
        assert r.status_code == 200
        assert data.get("openapi", "").startswith("3.")
        assert "/asteroids/search" in data.get("paths", {})
        log_result("GET /openapi.json", True, f"({r.status_code} OK) - OpenAPI {data.get('openapi')} Valid")
    except Exception as e:
        log_result("GET /openapi.json", False, str(e))

    # Scientific Data Sources & Policy
    try:
        r = requests.get(f"{BASE_URL}/sources", timeout=5)
        data = r.json()
        assert r.status_code == 200
        assert len(data.get("sources", [])) == 6
        assert "data_policy" in data
        log_result("GET /sources", True, f"({r.status_code} OK) - {len(data['sources'])} sources documented")
    except Exception as e:
        log_result("GET /sources", False, str(e))

    # -------------------------------------------------------------
    # 2. Historical Missions (NASA NSSDC Scraping)
    # -------------------------------------------------------------
    print("\n[Group 2] Historical Missions & NASA NSSDC Scraping")
    
    # Curated Missions
    try:
        r = requests.get(f"{BASE_URL}/missions", timeout=5)
        data = r.json()
        assert r.status_code == 200
        assert data.get("count") >= 1
        log_result("GET /missions", True, f"({r.status_code} OK) - Curated missions count: {data['count']}")
    except Exception as e:
        log_result("GET /missions", False, str(e))

    # Scraped NEAR Shoemaker Full Page
    try:
        t0 = time.time()
        r = requests.get(f"{BASE_URL}/missions/near", timeout=15)
        dt = round((time.time() - t0) * 1000, 1)
        data = r.json()
        assert r.status_code == 200
        assert data.get("mission") == "NEAR Shoemaker"
        specs = data.get("specifications", {})
        assert "Launch Date" in specs
        assert "Launch Vehicle" in specs
        assert "Planned on-orbit mass" in specs
        assert "Power System" in specs
        assert len(data.get("tables", [])) >= 1
        assert len(data.get("paragraphs", [])) >= 2
        log_result("GET /missions/near", True, f"({r.status_code} OK, {dt}ms) - Specs: {len(specs)} items, Tables: {len(data['tables'])}, Paras: {len(data['paragraphs'])}")
    except Exception as e:
        log_result("GET /missions/near", False, str(e))

    # NEAR Sections Breakdown
    try:
        r = requests.get(f"{BASE_URL}/missions/near/sections", timeout=5)
        data = r.json()
        assert r.status_code == 200
        assert "specifications" in data
        assert len(data.get("sections", [])) >= 3
        log_result("GET /missions/near/sections", True, f"({r.status_code} OK) - Sections: {len(data['sections'])}, Paras: {data.get('paragraph_count')}")
    except Exception as e:
        log_result("GET /missions/near/sections", False, str(e))

    # -------------------------------------------------------------
    # 3. Asteroid Queries (JPL SBDB & SBDB Query)
    # -------------------------------------------------------------
    print("\n[Group 3] Asteroids Search & Physical Parameters")
    
    # Search Near-Earth Objects (NEOs)
    first_pdes = None
    try:
        t0 = time.time()
        r = requests.get(f"{BASE_URL}/asteroids/search?limit=5&neo_only=true", timeout=15)
        dt = round((time.time() - t0) * 1000, 1)
        data = r.json()
        assert r.status_code == 200
        assert data.get("count") == 5
        asteroids = data.get("asteroids", [])
        assert len(asteroids) == 5
        first = asteroids[0]
        first_pdes = first.get("pdes")
        assert first.get("neo") == "Y"
        assert "H" in first
        log_result("GET /asteroids/search (neo_only=true)", True, f"({r.status_code} OK, {dt}ms) - 5 NEOs retrieved. First: {first.get('full_name').strip()}")
    except Exception as e:
        log_result("GET /asteroids/search (neo_only=true)", False, str(e))

    # Pagination Offset Test
    try:
        r = requests.get(f"{BASE_URL}/asteroids/search?limit=5&offset=5&neo_only=true", timeout=15)
        data = r.json()
        assert r.status_code == 200
        paged_first = data.get("asteroids", [])[0]
        assert paged_first.get("pdes") != first_pdes
        log_result("GET /asteroids/search (offset=5)", True, f"({r.status_code} OK) - Pagination offset verified (Different item: {paged_first.get('full_name').strip()})")
    except Exception as e:
        log_result("GET /asteroids/search (offset=5)", False, str(e))

    # Search General Asteroids (neo_only=false)
    try:
        r = requests.get(f"{BASE_URL}/asteroids/search?limit=3&neo_only=false", timeout=15)
        data = r.json()
        assert r.status_code == 200
        assert data.get("count") == 3
        log_result("GET /asteroids/search (neo_only=false)", True, f"({r.status_code} OK) - General asteroids query succeeded")
    except Exception as e:
        log_result("GET /asteroids/search (neo_only=false)", False, str(e))

    # Asteroid Details: 433 Eros
    try:
        t0 = time.time()
        r = requests.get(f"{BASE_URL}/asteroids/433%20Eros", timeout=15)
        dt = round((time.time() - t0) * 1000, 1)
        data = r.json()
        assert r.status_code == 200
        obj = data.get("data", {}).get("object", {})
        fullname = obj.get("fullname", "")
        spkid = obj.get("spkid")
        assert "433 Eros" in fullname
        log_result("GET /asteroids/433 Eros", True, f"({r.status_code} OK, {dt}ms) - Object: {fullname}, SPK-ID: {spkid}")
    except Exception as e:
        log_result("GET /asteroids/433 Eros", False, str(e))

    # Asteroid Details: 99942 Apophis
    try:
        r = requests.get(f"{BASE_URL}/asteroids/99942%20Apophis", timeout=15)
        data = r.json()
        assert r.status_code == 200
        obj = data.get("data", {}).get("object", {})
        log_result("GET /asteroids/99942 Apophis", True, f"({r.status_code} OK) - Object: {obj.get('fullname')}")
    except Exception as e:
        log_result("GET /asteroids/99942 Apophis", False, str(e))

    # Asteroid Details: 101955 Bennu
    try:
        r = requests.get(f"{BASE_URL}/asteroids/101955%20Bennu", timeout=15)
        data = r.json()
        assert r.status_code == 200
        obj = data.get("data", {}).get("object", {})
        log_result("GET /asteroids/101955 Bennu", True, f"({r.status_code} OK) - Object: {obj.get('fullname')}")
    except Exception as e:
        log_result("GET /asteroids/101955 Bennu", False, str(e))

    # Ambiguous Name Disambiguation: Halley
    try:
        r = requests.get(f"{BASE_URL}/asteroids/Halley", timeout=15)
        data = r.json()
        assert r.status_code == 200
        assert data.get("status") == "multiple_matches"
        assert len(data.get("matches", [])) >= 2
        log_result("GET /asteroids/Halley", True, f"({r.status_code} OK) - Disambiguation handled: {len(data['matches'])} candidates")
    except Exception as e:
        log_result("GET /asteroids/Halley", False, str(e))

    # Non-existent Asteroid (404 Error handling)
    try:
        r = requests.get(f"{BASE_URL}/asteroids/nonexistent_asteroid_88888888", timeout=15)
        assert r.status_code == 404
        data = r.json()
        assert "not found" in data.get("detail", {}).get("message", "").lower()
        log_result("GET /asteroids/nonexistent", True, f"({r.status_code} Not Found) - Clean 404 payload confirmed")
    except Exception as e:
        log_result("GET /asteroids/nonexistent", False, str(e))

    # -------------------------------------------------------------
    # 4. Close Approaches (JPL CAD)
    # -------------------------------------------------------------
    print("\n[Group 4] Earth Close-Approach Events")
    
    # General Close Approaches
    try:
        t0 = time.time()
        r = requests.get(f"{BASE_URL}/close-approaches?limit=5&dist-max=0.15", timeout=15)
        dt = round((time.time() - t0) * 1000, 1)
        data = r.json()
        assert r.status_code == 200
        assert data.get("count") >= 1
        events = data.get("events", [])
        assert len(events) >= 1
        first_ev = events[0]
        assert "dist" in first_ev
        assert "v_rel" in first_ev
        log_result("GET /close-approaches", True, f"({r.status_code} OK, {dt}ms) - {data['count']} events. Sample des: {first_ev.get('des')}, dist: {first_ev.get('dist')} au")
    except Exception as e:
        log_result("GET /close-approaches", False, str(e))

    # Targeted Close Approach: 433 Eros
    try:
        r = requests.get(f"{BASE_URL}/close-approaches?des=433&dist-max=0.3&date-min=2000-01-01&date-max=2035-12-31", timeout=15)
        data = r.json()
        assert r.status_code == 200
        assert data.get("count") >= 1
        ev = data.get("events", [])[0]
        log_result("GET /close-approaches?des=433", True, f"({r.status_code} OK) - {data['count']} Eros encounters. Nominal dist: {ev.get('dist')} au")
    except Exception as e:
        log_result("GET /close-approaches?des=433", False, str(e))

    # Invalid Parameter Handling (400 Bad Request)
    try:
        r = requests.get(f"{BASE_URL}/close-approaches?date-min=invalid-date-format", timeout=15)
        assert r.status_code == 400
        detail = r.json().get("detail", {})
        assert "invalid datetime" in detail.get("message", "").lower()
        log_result("GET /close-approaches?date-min=invalid", True, f"({r.status_code} Bad Request) - Transparent upstream error propagated")
    except Exception as e:
        log_result("GET /close-approaches?date-min=invalid", False, str(e))

    # -------------------------------------------------------------
    # 5. Mission Design Screening (JPL MDesign)
    # -------------------------------------------------------------
    print("\n[Group 5] Ballistic Mission Design Trajectories")
    
    # Accessible Targets: Criterion 1 (Min Departure V-infinity)
    try:
        t0 = time.time()
        r = requests.get(f"{BASE_URL}/mission-design/accessible?year=2027&crit=1&lim=5&sb-group=neo", timeout=25)
        dt = round((time.time() - t0) * 1000, 1)
        data = r.json()
        assert r.status_code == 200
        assert data.get("count") >= 1
        target = data.get("targets", [])[0]
        assert "vinf_dep" in target
        assert "dv_tot" in target
        assert "tof" in target
        log_result("GET /mission-design/accessible (crit=1)", True, f"({r.status_code} OK, {dt}ms) - Target: {target.get('name')}, Total DV: {target.get('dv_tot')} km/s, TOF: {target.get('tof')}d")
    except Exception as e:
        log_result("GET /mission-design/accessible (crit=1)", False, str(e))

    # Accessible Targets: Criterion 3 (Min Total Delta-V)
    try:
        t0 = time.time()
        r = requests.get(f"{BASE_URL}/mission-design/accessible?year=2028&crit=3&lim=5&sb-group=neo", timeout=25)
        dt = round((time.time() - t0) * 1000, 1)
        data = r.json()
        assert r.status_code == 200
        assert data.get("count") >= 1
        target = data.get("targets", [])[0]
        log_result("GET /mission-design/accessible (crit=3)", True, f"({r.status_code} OK, {dt}ms) - Target: {target.get('name')}, Min Total DV: {target.get('dv_tot')} km/s")
    except Exception as e:
        log_result("GET /mission-design/accessible (crit=3)", False, str(e))

    # Invalid Criterion Range: crit=9 (FastAPI validation catches crit > 6)
    try:
        r = requests.get(f"{BASE_URL}/mission-design/accessible?crit=9", timeout=10)
        assert r.status_code == 422
        log_result("GET /mission-design/accessible?crit=9", True, f"({r.status_code} Unprocessable Entity) - Validated le=6 before upstream query")
    except Exception as e:
        log_result("GET /mission-design/accessible?crit=9", False, str(e))

    # -------------------------------------------------------------
    # Summary
    # -------------------------------------------------------------
    print("\n" + "=" * 65)
    print(f"📊 LIVE E2E TEST SUMMARY: {PASSED} Passed, {FAILED} Failed (Total {PASSED + FAILED} tests)")
    print("=" * 65)


def start_server_and_test() -> None:
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=TEST_PORT,
        log_level="error",
        access_log=False,
    )
    server = uvicorn.Server(config)
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()

    # Wait for server ready
    ready = False
    for _ in range(30):
        try:
            r = requests.get(f"{BASE_URL}/health", timeout=1)
            if r.status_code == 200:
                ready = True
                break
        except Exception:
            time.sleep(0.1)

    if not ready:
        print("❌ Server failed to initialize within 3 seconds.")
        sys.exit(1)

    try:
        run_tests()
    finally:
        server.should_exit = True
        server_thread.join(timeout=3)
        print("🛑 Local test server stopped cleanly.")


if __name__ == "__main__":
    start_server_and_test()
