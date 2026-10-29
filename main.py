from __future__ import annotations

import re
import threading
import time
from typing import Any

import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

APP_NAME = "NASA Mission Data API"

NEAR_URL = "https://nssdc.gsfc.nasa.gov/planetary/near.html"
NASA_NEAR_URL = "https://science.nasa.gov/mission/near-shoemaker/"

SBDB_URL = "https://ssd-api.jpl.nasa.gov/sbdb.api"
SBDB_QUERY_URL = "https://ssd-api.jpl.nasa.gov/sbdb_query.api"
CAD_URL = "https://ssd-api.jpl.nasa.gov/cad.api"
MDESIGN_URL = "https://ssd-api.jpl.nasa.gov/mdesign.api"
HORIZONS_URL = "https://ssd.jpl.nasa.gov/api/horizons.api"

app = FastAPI(
    title=APP_NAME,
    description=(
        "An educational & mission-planning API combining historical NASA NEAR Shoemaker "
        "spacecraft telemetry with live JPL Small-Body Database (SBDB), Close-Approach (CAD), "
        "Mission Design (MDesign) trajectory screening, and Horizons 3D Ephemeris vectors."
    ),
    version="1.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)

session = requests.Session()

retry = Retry(
    total=2,
    connect=2,
    read=2,
    backoff_factor=0.4,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET"],
)

session.mount("https://", HTTPAdapter(max_retries=retry))
session.headers.update({
    "User-Agent": "NASA-Mission-Data-API/1.2 (educational space mission project)"
})

TIMEOUT = 25
CACHE_TTL = 6 * 60 * 60
MAX_CACHE_ENTRIES = 500

_cache_lock = threading.Lock()
_cache: dict[str, tuple[float, Any]] = {}

SPACECRAFT_MAP: dict[str, tuple[str, str]] = {
    "near": ("-93", "NEAR Shoemaker (Asteroid 433 Eros Orbiter & Lander)"),
    "near-shoemaker": ("-93", "NEAR Shoemaker (Asteroid 433 Eros Orbiter & Lander)"),
    "osiris-rex": ("-64", "OSIRIS-REx (Asteroid 101955 Bennu Sample Return)"),
    "dart": ("-170", "DART (Double Asteroid Redirection Test / Dimorphos)"),
    "voyager-1": ("-31", "Voyager 1 (Interstellar Mission)"),
    "voyager-2": ("-32", "Voyager 2 (Outer Solar System & Interstellar)"),
    "dawn": ("-98", "Dawn (Vesta and Ceres Orbiter)"),
    "new-horizons": ("-48", "New Horizons (Pluto and Kuiper Belt)"),
}


def cache_set(key: str, value: Any) -> None:
    with _cache_lock:
        if len(_cache) >= MAX_CACHE_ENTRIES:
            oldest_keys = sorted(_cache.keys(), key=lambda k: _cache[k][0])[
                : MAX_CACHE_ENTRIES // 5
            ]
            for k in oldest_keys:
                _cache.pop(k, None)
        _cache[key] = (time.time(), value)


def cache_get(key: str, ttl: int) -> Any | None:
    with _cache_lock:
        entry = _cache.get(key)
        if entry and (time.time() - entry[0]) < ttl:
            return entry[1]
    return None


def cached_get(
    key: str,
    url: str,
    params: dict[str, Any] | None = None,
    ttl: int = CACHE_TTL,
) -> Any:
    cached_data = cache_get(key, ttl)
    if cached_data is not None:
        return cached_data

    try:
        response = session.get(url, params=params, timeout=TIMEOUT)

        if response.status_code == 400:
            try:
                err_data = response.json()
                detail_msg = err_data.get("message", "Invalid query parameter.")
            except Exception:
                detail_msg = response.text or "Invalid query parameter."
            raise HTTPException(
                status_code=400,
                detail={
                    "message": detail_msg,
                    "source_url": url,
                    "query": params,
                },
            )

        if response.status_code == 404:
            raise HTTPException(
                status_code=404,
                detail={
                    "message": "Target resource was not found by upstream NASA/JPL service.",
                    "source_url": url,
                },
            )

        response.raise_for_status()

        if "json" in response.headers.get("content-type", "").lower():
            data = response.json()
        else:
            data = response.text

        cache_set(key, data)
        return data

    except HTTPException:
        raise

    except (requests.RequestException, ValueError) as exc:
        with _cache_lock:
            entry = _cache.get(key)
            if entry:
                return entry[1]

        raise HTTPException(
            status_code=502,
            detail={
                "message": "NASA/JPL upstream source is temporarily unreachable or timed out.",
                "source_url": url,
                "error": str(exc),
            },
        ) from exc


def parse_horizons_vectors(text: str) -> list[dict[str, Any]]:
    start = text.find("$$SOE")
    end = text.find("$$EOE")
    if start == -1 or end == -1:
        return []
    table_text = text[start + 5 : end]

    records: list[dict[str, Any]] = []
    time_matches = list(re.finditer(r"(\d{7}\.\d+)\s*=\s*A\.D\.\s*([\d\w\-:\. ]+?)\s*TDB", table_text))
    pos_matches = list(re.finditer(r"X\s*=\s*([-\d.E+]+)\s*Y\s*=\s*([-\d.E+]+)\s*Z\s*=\s*([-\d.E+]+)", table_text))
    vel_matches = list(re.finditer(r"VX\s*=\s*([-\d.E+]+)\s*VY\s*=\s*([-\d.E+]+)\s*VZ\s*=\s*([-\d.E+]+)", table_text))
    range_matches = list(re.finditer(r"RG\s*=\s*([-\d.E+]+)\s*RR\s*=\s*([-\d.E+]+)", table_text))

    n = min(len(time_matches), len(pos_matches), len(vel_matches))
    for i in range(n):
        jd = float(time_matches[i].group(1))
        date_str = time_matches[i].group(2).strip()
        x = float(pos_matches[i].group(1))
        y = float(pos_matches[i].group(2))
        z = float(pos_matches[i].group(3))
        vx = float(vel_matches[i].group(1))
        vy = float(vel_matches[i].group(2))
        vz = float(vel_matches[i].group(3))
        rg = float(range_matches[i].group(1)) if i < len(range_matches) else None
        rr = float(range_matches[i].group(2)) if i < len(range_matches) else None

        records.append({
            "jd": jd,
            "calendar_date": date_str,
            "position_km": {"x": x, "y": y, "z": z},
            "velocity_kms": {"vx": vx, "vy": vy, "vz": vz},
            "range_km": rg,
            "range_au": round(rg / 149597870.7, 6) if rg is not None else None,
            "range_rate_kms": rr,
        })
    return records


def fetch_near_page() -> dict[str, Any]:
    key = "near_page"
    cached_data = cache_get(key, CACHE_TTL)
    if cached_data is not None:
        return cached_data

    try:
        response = session.get(NEAR_URL, timeout=TIMEOUT)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        for tag in soup(["script", "style", "noscript", "svg"]):
            tag.decompose()

        title = (
            soup.title.get_text(" ", strip=True)
            if soup.title
            else "NEAR Shoemaker"
        )

        headings = [
            h.get_text(" ", strip=True)
            for h in soup.find_all(["h1", "h2", "h3"])
            if h.get_text(strip=True)
        ]

        specifications: dict[str, str] = {}
        for strong in soup.find_all("strong"):
            label = strong.get_text(strip=True).rstrip(":")
            next_node = strong.next_sibling
            if next_node and isinstance(next_node, str):
                val = next_node.strip()
                if label and val:
                    specifications[label] = val

        paragraphs = [
            p.get_text(" ", strip=True)
            for p in soup.find_all("p")
            if p.get_text(strip=True)
        ]

        tables: list[list[list[str]]] = []
        if specifications:
            specs_table = [["Specification", "Value"]]
            for k, v in specifications.items():
                specs_table.append([k, v])
            tables.append(specs_table)

        for table in soup.find_all("table"):
            rows = []
            for tr in table.find_all("tr"):
                cells = [
                    cell.get_text(" ", strip=True)
                    for cell in tr.find_all(["th", "td"])
                ]
                if cells:
                    rows.append(cells)
            if rows:
                tables.append(rows)

        links = []
        for a in soup.find_all("a", href=True):
            label = a.get_text(" ", strip=True)
            href = a["href"].strip()

            if not href or href.startswith(("javascript:", "mailto:")):
                continue

            if not href.startswith(("http://", "https://")):
                href = requests.compat.urljoin(NEAR_URL, href)

            if href.startswith(("http://", "https://")):
                links.append({
                    "title": label or href,
                    "url": href,
                })

        result = {
            "mission": "NEAR Shoemaker",
            "title": title,
            "specifications": specifications,
            "headings": headings,
            "paragraphs": paragraphs,
            "tables": tables,
            "links": links[:100],
            "source_url": NEAR_URL,
            "additional_official_source": NASA_NEAR_URL,
            "retrieved_at_unix": int(time.time()),
            "note": (
                "Parsed from NASA NSSDC public HTML page. "
                "Includes structured spacecraft specifications and mission history."
            ),
        }

        cache_set(key, result)
        return result

    except requests.RequestException as exc:
        with _cache_lock:
            entry = _cache.get(key)
            if entry:
                return entry[1]

        raise HTTPException(
            status_code=502,
            detail={
                "message": "NASA NSSDC page is temporarily unavailable.",
                "source_url": NEAR_URL,
                "error": str(exc),
            },
        ) from exc


@app.get("/", tags=["Overview"])
def root() -> dict[str, Any]:
    return {
        "name": APP_NAME,
        "status": "online",
        "version": app.version,
        "documentation": "/docs",
        "openapi_json": "/openapi.json",
        "endpoints": [
            "/health",
            "/sources",
            "/missions",
            "/missions/near",
            "/missions/near/sections",
            "/asteroids/search",
            "/asteroids/433%20Eros",
            "/close-approaches",
            "/mission-design/accessible",
            "/mission-design/porkchop",
            "/ephemeris/vectors",
            "/ephemeris/spacecraft/near-shoemaker",
        ],
        "note": (
            "Grounded for the NASA Space Apps Challenge 2026 Space Mission Design Game. "
            "Data sourced from NASA NSSDC and JPL SSD APIs."
        ),
    }


@app.get("/health", tags=["Overview"])
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": APP_NAME,
        "version": app.version,
    }


@app.get("/sources", tags=["Overview"])
def sources() -> dict[str, Any]:
    return {
        "sources": [
            {
                "name": "NASA NSSDC NEAR mission page",
                "url": NEAR_URL,
                "type": "HTML page parsed for spacecraft specifications and history",
            },
            {
                "name": "NASA Science NEAR Shoemaker",
                "url": NASA_NEAR_URL,
                "type": "Official mission overview",
            },
            {
                "name": "JPL Small-Body Database (SBDB) API",
                "url": "https://ssd-api.jpl.nasa.gov/doc/sbdb.html",
                "type": "Individual asteroid physical parameters, discovery metadata, and close approach data",
            },
            {
                "name": "JPL SBDB Query API",
                "url": "https://ssd-api.jpl.nasa.gov/doc/sbdb_query.html",
                "type": "Multi-asteroid search and discovery queries",
            },
            {
                "name": "JPL Close-Approach Data (CAD) API",
                "url": "https://ssd-api.jpl.nasa.gov/doc/cad.html",
                "type": "Earth close approaches with distances and relative velocities",
            },
            {
                "name": "JPL Mission Design API",
                "url": "https://ssd-api.jpl.nasa.gov/doc/mdesign.html",
                "type": "Ballistic mission screening and on-demand Porkchop transfer maps",
            },
            {
                "name": "JPL Horizons API",
                "url": "https://ssd-api.jpl.nasa.gov/doc/horizons.html",
                "type": "High-precision 3D Cartesian state vectors for planets, asteroids, and spacecraft",
            },
        ],
        "data_policy": (
            "Preserve source URLs, physical units and uncertainty metrics. "
            "Missing values signify unmeasured quantities, not zero. "
            "Keep game simulation assumptions strictly distinct from NASA/JPL scientific facts."
        ),
    }


@app.get("/missions", tags=["Historical missions"])
def missions() -> dict[str, Any]:
    return {
        "count": 1,
        "missions": [
            {
                "id": "near-shoemaker",
                "name": "NEAR Shoemaker",
                "target": "433 Eros",
                "launch_date": "1996-02-17",
                "first_asteroid_orbit": "2000-02-14",
                "landing_date": "2001-02-12",
                "source_url": NEAR_URL,
                "additional_official_source": NASA_NEAR_URL,
                "data_type": "historical mission summary",
            }
        ],
        "note": "Curated historical space exploration mission index.",
    }


@app.get("/missions/near", tags=["Historical missions"])
def near_mission() -> dict[str, Any]:
    return fetch_near_page()


@app.get("/missions/near/sections", tags=["Historical missions"])
def near_sections() -> dict[str, Any]:
    data = fetch_near_page()

    return {
        "mission": data["mission"],
        "specifications": data.get("specifications", {}),
        "sections": [
            {
                "heading": heading,
                "source_url": data["source_url"],
            }
            for heading in data["headings"]
        ],
        "paragraph_count": len(data["paragraphs"]),
        "table_count": len(data["tables"]),
        "source_url": data["source_url"],
    }


@app.get("/asteroids/search", tags=["Asteroid data"])
def search_asteroids(
    limit: int = Query(
        20,
        ge=1,
        le=100,
        description="Maximum number of asteroids to return (1-100)",
    ),
    offset: int = Query(
        0,
        ge=0,
        alias="offset",
        description="Pagination offset (limit-from index)",
    ),
    neo_only: bool = Query(
        True,
        description="Filter for Near-Earth Objects (NEOs). If false, queries all asteroids.",
    ),
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "fields": "spkid,full_name,pdes,neo,pha,class,diameter,H,albedo,rot_per",
        "limit": limit,
        "sort": "name",
    }

    if offset > 0:
        params["limit-from"] = offset

    if neo_only:
        params["sb-group"] = "neo"
    else:
        params["sb-kind"] = "a"

    data = cached_get(
        f"sbdb_query:{limit}:{offset}:{neo_only}",
        SBDB_QUERY_URL,
        params,
        ttl=1800,
    )

    fields = data.get("fields", []) if isinstance(data, dict) else []
    raw_data = data.get("data", []) if isinstance(data, dict) else []

    structured_asteroids = [dict(zip(fields, row)) for row in raw_data]

    return {
        "source_url": SBDB_QUERY_URL,
        "query": params,
        "count": len(structured_asteroids),
        "asteroids": structured_asteroids,
        "raw": data,
    }


@app.get("/asteroids/{designation}", tags=["Asteroid data"])
def asteroid_details(designation: str) -> dict[str, Any]:
    params = {
        "sstr": designation,
        "alt-des": "true",
        "phys-par": "true",
        "full-prec": "true",
        "discovery": "true",
        "ca-data": "true",
    }

    data = cached_get(
        f"sbdb:{designation.lower()}",
        SBDB_URL,
        params,
        ttl=1800,
    )

    if isinstance(data, dict):
        if data.get("code") == "300":
            return {
                "status": "multiple_matches",
                "message": (
                    "Multiple small bodies matched your query. "
                    "Please query with a specific name or designation from this list."
                ),
                "source_url": SBDB_URL,
                "requested_designation": designation,
                "matches": data.get("list", []),
                "count": data.get("count", len(data.get("list", []))),
            }

        if data.get("code") == "200" and "not found" in data.get("message", "").lower():
            raise HTTPException(
                status_code=404,
                detail={
                    "message": f"Asteroid or small body '{designation}' not found in JPL SBDB.",
                    "source_url": SBDB_URL,
                    "upstream": data,
                },
            )

    estimated_diameter_km = None
    if isinstance(data, dict):
        phys_par = data.get("phys_par", [])
        has_diameter = any(
            p.get("name") == "diameter" and p.get("value") is not None
            for p in phys_par
        )
        if not has_diameter:
            h_val = None
            albedo_val = 0.14
            for p in phys_par:
                if p.get("name") == "H" and p.get("value") is not None:
                    try:
                        h_val = float(p.get("value"))
                    except (ValueError, TypeError):
                        pass
                elif p.get("name") == "albedo" and p.get("value") is not None:
                    try:
                        albedo_val = float(p.get("value"))
                    except (ValueError, TypeError):
                        pass
            if h_val is not None and albedo_val > 0:
                estimated_diameter_km = round(
                    (1329.0 / (albedo_val**0.5)) * (10 ** (-0.2 * h_val)), 3
                )

    return {
        "source_url": SBDB_URL,
        "requested_designation": designation,
        "estimated_diameter_km": estimated_diameter_km,
        "discovery": data.get("discovery") if isinstance(data, dict) else None,
        "close_approach_encounters_count": len(data.get("ca_data", [])) if isinstance(data, dict) else 0,
        "close_approach_sample": data.get("ca_data", [])[:5] if isinstance(data, dict) else [],
        "data": data,
    }


@app.get("/close-approaches", tags=["Close approaches"])
def close_approaches(
    date_min: str = Query(
        "2026-01-01",
        alias="date-min",
        description="Start date in YYYY-MM-DD format",
    ),
    date_max: str = Query(
        "2027-12-31",
        alias="date-max",
        description="End date in YYYY-MM-DD format",
    ),
    dist_max_au: float = Query(
        0.2,
        gt=0,
        le=5,
        alias="dist-max",
        description="Maximum nominal approach distance in Astronomical Units (au)",
    ),
    designation: str | None = Query(
        None,
        alias="des",
        description="Optional asteroid designation (e.g. '433' or '99942')",
    ),
    limit: int = Query(
        20,
        ge=1,
        le=100,
        description="Maximum number of close approaches to return",
    ),
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "date-min": date_min,
        "date-max": date_max,
        "dist-max": str(dist_max_au),
        "limit": limit,
        "sort": "date",
        "fullname": "true",
    }

    if designation:
        params["des"] = designation

    cache_key = f"cad:{designation}:{date_min}:{date_max}:{dist_max_au}:{limit}"
    data = cached_get(cache_key, CAD_URL, params, ttl=900)

    fields = data.get("fields", []) if isinstance(data, dict) else []
    raw_data = data.get("data", []) if isinstance(data, dict) else []

    structured_events = [dict(zip(fields, row)) for row in raw_data]

    return {
        "source_url": CAD_URL,
        "query": params,
        "distance_unit": "au",
        "velocity_unit": "km/s",
        "count": len(structured_events),
        "events": structured_events,
        "raw": data,
    }


@app.get("/mission-design/accessible", tags=["Mission design"])
def accessible_mission_targets(
    years: str = Query(
        "2027,2028,2029,2030,2031",
        description="Launch year or comma-separated launch years (e.g. '2027,2028')",
    ),
    limit: int = Query(
        100,
        ge=1,
        le=500,
        description="Maximum mission targets to retrieve from screening",
    ),
    small_body_group: str = Query(
        "neo",
        alias="sb-group",
        pattern="^(neo|pha|all)$",
        description=(
            "Target asteroid group: 'neo' (Near-Earth Asteroids), 'pha' (Potentially Hazardous Asteroids), "
            "or 'all' (all small bodies)"
        ),
    ),
    criterion: int = Query(
        1,
        ge=1,
        le=6,
        alias="crit",
        description=(
            "Ballistic mission optimality criterion (1-6): "
            "1) min departure V-infinity, 2) min arrival V-infinity, 3) min total delta-V, "
            "4) min TOF + departure V-infinity, 5) min TOF + arrival V-infinity, 6) min TOF + total delta-V"
        ),
    ),
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "year": years,
        "lim": limit,
        "crit": criterion,
    }

    if small_body_group in ("neo", "pha"):
        params["sb-group"] = small_body_group

    data = cached_get(
        f"mdesign:{years}:{limit}:{small_body_group}:{criterion}",
        MDESIGN_URL,
        params,
        ttl=3600,
    )

    fields = data.get("fields", []) if isinstance(data, dict) else []
    raw_data = data.get("data", []) if isinstance(data, dict) else []

    structured_targets = [dict(zip(fields, row)) for row in raw_data]

    return {
        "source_url": MDESIGN_URL,
        "query": params,
        "units": {
            "c3_dep": "km^2/s^2 (Characteristic launch energy)",
            "vinf_dep": "km/s (Departure hyperbolic excess velocity)",
            "vinf_arr": "km/s (Arrival hyperbolic excess velocity)",
            "dv_tot": "km/s (Total mission delta-V)",
            "tof": "days (Time of flight)",
        },
        "count": len(structured_targets),
        "targets": structured_targets,
        "raw": data,
        "warning": (
            "These are precomputed mission-design screening results, "
            "not a complete flight plan or trajectory optimization. "
            "Check official JPL documentation for mission assumptions."
        ),
    }


@app.get("/mission-design/porkchop", tags=["Mission design"])
def mission_design_porkchop(
    designation: str = Query(
        "433",
        description="Asteroid designation or name (e.g. '433', 'Apophis')",
    ),
    mjd0: int = Query(
        61500,
        description="Starting launch date in Modified Julian Date (MJD). E.g. 61500 ~ April 2027",
    ),
    span: int = Query(
        60,
        ge=10,
        le=365,
        description="Launch window duration to explore in days (10 - 365)",
    ),
    tof_min: int = Query(
        150,
        ge=30,
        le=2000,
        alias="tof-min",
        description="Minimum transit flight time in days",
    ),
    tof_max: int = Query(
        450,
        ge=30,
        le=2000,
        alias="tof-max",
        description="Maximum transit flight time in days",
    ),
    step: int = Query(
        15,
        description="Grid calculation time step in days (1, 2, 5, 10, 15, 20, 30)",
    ),
) -> dict[str, Any]:
    params = {
        "sstr": designation,
        "mjd0": mjd0,
        "span": span,
        "tof-min": tof_min,
        "tof-max": tof_max,
        "step": step,
    }

    cache_key = f"mdesign_porkchop:{designation}:{mjd0}:{span}:{tof_min}:{tof_max}:{step}"
    data = cached_get(cache_key, MDESIGN_URL, params, ttl=3600)

    fields = data.get("fields", []) if isinstance(data, dict) else []
    raw_selected = data.get("selectedMissions", []) if isinstance(data, dict) else []

    selected_missions: list[dict[str, Any]] = []
    best_mission: dict[str, Any] | None = None
    min_dv = float("inf")

    for row in raw_selected:
        item = dict(zip(fields, row))
        vinf_dep = float(item.get("vinf_dep", 0) or 0)
        vinf_arr = float(item.get("vinf_arr", 0) or 0)
        dv_tot = round(vinf_dep + vinf_arr, 4)
        item["dv_tot_kms"] = dv_tot
        selected_missions.append(item)
        if dv_tot < min_dv:
            min_dv = dv_tot
            best_mission = item

    return {
        "source_url": MDESIGN_URL,
        "query": params,
        "target": designation,
        "evaluated_missions_count": len(selected_missions),
        "best_mission": best_mission,
        "departure_dates_mjd": data.get("dep_date", []) if isinstance(data, dict) else [],
        "flight_times_days": data.get("tof", []) if isinstance(data, dict) else [],
        "vinf_dep_grid": data.get("vinf_dep", []) if isinstance(data, dict) else [],
        "vinf_arr_grid": data.get("vinf_arr", []) if isinstance(data, dict) else [],
        "selected_missions": selected_missions[:50],
        "units": {
            "vinf_dep": "km/s (Departure hyperbolic excess velocity)",
            "vinf_arr": "km/s (Arrival hyperbolic excess velocity)",
            "dv_tot_kms": "km/s (Estimated ballistic total delta-V)",
            "tof": "days (Time of flight)",
        },
        "note": (
            "Computed on-demand by JPL Mission Design Lambert grid search (Mode M). "
            "Use vinf_dep_grid and flight_times_days for 2D contour / Porkchop plot rendering."
        ),
    }


@app.get("/ephemeris/vectors", tags=["Ephemeris (3D vectors)"])
def ephemeris_vectors(
    target: str = Query(
        "433",
        description="Target body ID, name, or designation (e.g. '433', '399' for Earth, '499' for Mars)",
    ),
    start_date: str = Query(
        "2026-10-29",
        description="Start date in YYYY-MM-DD format (or YYYY-MM-DD HH:MM)",
    ),
    stop_date: str = Query(
        "2026-11-05",
        description="Stop date in YYYY-MM-DD format",
    ),
    step_size: str = Query(
        "1 d",
        description="Ephemeris time step size (e.g. '1 d', '6 h', '12 h', '30 m')",
    ),
    center: str = Query(
        "@sun",
        description="Coordinate center body (e.g. '@sun' for heliocentric, '@399' for geocentric Earth)",
    ),
) -> dict[str, Any]:
    params = {
        "format": "json",
        "COMMAND": f"'{target}'",
        "OBJ_DATA": "YES",
        "MAKE_EPHEM": "YES",
        "EPHEM_TYPE": "VECTORS",
        "CENTER": f"'{center}'",
        "START_TIME": f"'{start_date}'",
        "STOP_TIME": f"'{stop_date}'",
        "STEP_SIZE": f"'{step_size}'",
    }

    cache_key = f"horizons_vectors:{target}:{start_date}:{stop_date}:{step_size}:{center}"
    data = cached_get(cache_key, HORIZONS_URL, params, ttl=3600)

    raw_result = data.get("result", "") if isinstance(data, dict) else str(data)
    vectors = parse_horizons_vectors(raw_result)

    return {
        "source_url": HORIZONS_URL,
        "target": target,
        "center": center,
        "start_date": start_date,
        "stop_date": stop_date,
        "step_size": step_size,
        "vectors_count": len(vectors),
        "units": {
            "position": "km (3D Cartesian coordinates X, Y, Z)",
            "velocity": "km/s (Velocity components VX, VY, VZ)",
            "range": "km and au (Distance from observer center)",
            "range_rate": "km/s (Radial velocity)",
        },
        "vectors": vectors,
        "note": (
            "Computed by NASA/JPL Horizons Ephemeris System with relativistic n-body dynamics."
        ),
    }


@app.get("/ephemeris/spacecraft/{mission_name}", tags=["Ephemeris (3D vectors)"])
def spacecraft_ephemeris(
    mission_name: str,
    start_date: str = Query(
        "2000-02-14",
        description="Start date in YYYY-MM-DD format",
    ),
    stop_date: str = Query(
        "2000-02-20",
        description="Stop date in YYYY-MM-DD format",
    ),
    step_size: str = Query(
        "1 d",
        description="Time step (e.g. '1 d', '6 h')",
    ),
) -> dict[str, Any]:
    mission_key = mission_name.lower().strip()
    if mission_key not in SPACECRAFT_MAP:
        available = ", ".join(SPACECRAFT_MAP.keys())
        raise HTTPException(
            status_code=404,
            detail={
                "message": f"Spacecraft '{mission_name}' is not in predefined list.",
                "available_spacecraft": list(SPACECRAFT_MAP.keys()),
            },
        )

    cmd, desc = SPACECRAFT_MAP[mission_key]
    params = {
        "format": "json",
        "COMMAND": f"'{cmd}'",
        "OBJ_DATA": "YES",
        "MAKE_EPHEM": "YES",
        "EPHEM_TYPE": "VECTORS",
        "CENTER": "'@sun'",
        "START_TIME": f"'{start_date}'",
        "STOP_TIME": f"'{stop_date}'",
        "STEP_SIZE": f"'{step_size}'",
    }

    cache_key = f"horizons_spacecraft:{cmd}:{start_date}:{stop_date}:{step_size}"
    data = cached_get(cache_key, HORIZONS_URL, params, ttl=86400)

    raw_result = data.get("result", "") if isinstance(data, dict) else str(data)
    vectors = parse_horizons_vectors(raw_result)

    return {
        "source_url": HORIZONS_URL,
        "spacecraft_id": cmd,
        "mission_name": desc,
        "start_date": start_date,
        "stop_date": stop_date,
        "step_size": step_size,
        "vectors_count": len(vectors),
        "vectors": vectors,
        "units": {
            "position": "km (Heliocentric 3D coordinates X, Y, Z)",
            "velocity": "km/s (VX, VY, VZ)",
            "range": "km and au (Distance from Sun)",
        },
        "note": "Official NASA flight telemetry trajectory from JPL Horizons archive.",
    }
