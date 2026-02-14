import os
import time
import logging
import requests
import psycopg2
from psycopg2.extras import RealDictCursor

# ── CONFIG & LOGGING ────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")
try:
    SLEEP_SEC = int(os.getenv("WORKER_INTERVAL", "10"))
except ValueError:
    logger.warning("Invalid WORKER_INTERVAL; defaulting to 10 seconds")
    SLEEP_SEC = 10

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
HEADERS = {"User-Agent": "SpatialDB-Demo/1.0 (university project)"}
MAX_ATTEMPTS = 3

if not DATABASE_URL:
    logger.critical("DATABASE_URL must be set in environment")
    raise SystemExit(1)

# ── SCHEMA ENSURANCE ────────────────────────────────────────────────────────────
# ── ISO 3166-1 alpha-2 lookup for Nominatim countrycodes ────────────────────
COUNTRY_CODES = {
    "canada": "ca", "united states": "us", "usa": "us", "us": "us",
    "france": "fr", "switzerland": "ch", "austria": "at", "italy": "it",
    "germany": "de", "japan": "jp", "australia": "au", "norway": "no",
    "sweden": "se", "spain": "es", "chile": "cl", "argentina": "ar",
    "new zealand": "nz", "united kingdom": "gb", "uk": "gb",
}

def country_code(country: str) -> str | None:
    """Return 2-letter ISO code for a country name, or None."""
    return COUNTRY_CODES.get(country.strip().lower())

def ensure_tracking_columns(conn):
    """Create geocode_attempts, geocode_failed, and country if they don't exist."""
    with conn.cursor() as cur:
        cur.execute("""
            ALTER TABLE ski_resorts
              ADD COLUMN IF NOT EXISTS geocode_attempts INTEGER NOT NULL DEFAULT 0,
              ADD COLUMN IF NOT EXISTS geocode_failed   BOOLEAN NOT NULL DEFAULT FALSE,
              ADD COLUMN IF NOT EXISTS country          TEXT NOT NULL DEFAULT 'Canada';
        """)
    conn.commit()
    logger.info("Ensured tracking columns exist on ski_resorts.")

# ── GEOCODE CALL (Nominatim – free, no API key) ────────────────────────────────
def geocode(query: str, cc: str | None = None):
    """
    Geocode using OpenStreetMap Nominatim.
    Free, no API key required. Rate limit: 1 request/second.
    cc = optional ISO 3166-1 alpha-2 country code for Nominatim.
    Returns (lon_wgs84, lat_wgs84) or (None, None).
    """
    params = {
        "q": query,
        "format": "json",
        "limit": 1,
    }
    if cc:
        params["countrycodes"] = cc
    try:
        resp = requests.get(NOMINATIM_URL, params=params, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        results = resp.json()
        if results:
            lon = float(results[0]["lon"])
            lat = float(results[0]["lat"])
            return lon, lat
        logger.warning("No geocode result for '%s'", query)
    except requests.RequestException as e:
        logger.error("HTTP error during geocode(%s): %s", query, e)
    except (ValueError, KeyError) as e:
        logger.error("Error parsing geocode response for '%s': %s", query, e)
    return None, None

# ── WORKER ─────────────────────────────────────────────────────────────────────
def update_ski_resorts(conn):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # select rows that need geocoding
        cur.execute("""
            SELECT id, name, province, nearest_city, country, geocode_attempts
              FROM ski_resorts
             WHERE geom_wgs84 IS NULL
               AND geocode_failed   = FALSE
               AND geocode_attempts <  %s
             LIMIT 10;
        """, (MAX_ATTEMPTS,))
        rows = cur.fetchall()
        if not rows:
            logger.info("No more records to geocode.")
            return

        for row in rows:
            pid      = row["id"]
            attempts = row["geocode_attempts"] + 1

            # bump attempt counter
            cur.execute("""
                UPDATE ski_resorts
                   SET geocode_attempts = %s
                 WHERE id = %s;
            """, (attempts, pid))

            name     = row.get("name") or ""
            province = row.get("province") or ""
            city     = row.get("nearest_city") or ""
            cntry    = row.get("country") or "Canada"
            cc       = country_code(cntry)
            query    = f"{name}, {province}, {cntry}"

            lon, lat = geocode(query, cc=cc)
            if lon is None:
                # fallback: try with nearest city
                query2 = f"{name}, {city}, {cntry}"
                lon, lat = geocode(query2, cc=cc)
                time.sleep(1.1)

            if lon is None:
                if attempts >= MAX_ATTEMPTS:
                    cur.execute("""
                        UPDATE ski_resorts
                           SET geocode_failed = TRUE
                         WHERE id = %s;
                    """, (pid,))
                    logger.warning("Resort %s marked permanently failed after %s attempts.", pid, attempts)
                continue

            cur.execute("""
                UPDATE ski_resorts
                   SET lon_wgs84  = %s,
                       lat_wgs84  = %s,
                       geom_wgs84 = ST_SetSRID(ST_MakePoint(%s, %s), 4326)
                 WHERE id = %s;
            """, (lon, lat, lon, lat, pid))
            logger.info(
                "Updated resort %s '%s' with WGS-84 (%.6f, %.6f)",
                pid, name, lon, lat
            )
            time.sleep(1.1)  # Nominatim rate limit: 1 req/sec

        conn.commit()

# ── MAIN ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # one-time schema migration
    with psycopg2.connect(DATABASE_URL) as conn:
        ensure_tracking_columns(conn)

    while True:
        try:
            with psycopg2.connect(DATABASE_URL) as conn:
                update_ski_resorts(conn)
        except Exception as e:
            logger.exception("Worker loop encountered fatal error: %s", e)
        time.sleep(SLEEP_SEC)