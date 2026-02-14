"""
FastAPI backend – serves GeoJSON for the Cesium 3D globe frontend.
Table: ski_resorts (Canadian ski resorts with PostGIS geometry)
"""

import json
import os
import re

import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL must be set")

app = FastAPI(title="SkiSpatialDB API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── helpers ──────────────────────────────────────────────────────────────────

def get_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def rows_to_geojson(rows, geom_col="geometry"):
    """Convert DB rows (with a GeoJSON-text geometry column) to a FeatureCollection."""
    features = []
    for row in rows:
        geom_text = row.pop(geom_col, None)
        geom = json.loads(geom_text) if geom_text else None
        features.append({
            "type": "Feature",
            "geometry": geom,
            "properties": {k: _serialise(v) for k, v in row.items()},
        })
    return {"type": "FeatureCollection", "features": features}


def _serialise(v):
    """Make values JSON-safe (Decimal → float, etc.)."""
    from decimal import Decimal
    if isinstance(v, Decimal):
        return float(v)
    return v


# ── endpoints ────────────────────────────────────────────────────────────────

@app.get("/api/geojson/ski_resorts")
def ski_resorts_geojson():
    """All ski resorts that have a geometry."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT id, name, province, nearest_city, country,
                   vertical_drop_m, num_runs, num_lifts,
                   ST_AsGeoJSON(geom_wgs84) AS geometry
              FROM ski_resorts
             WHERE geom_wgs84 IS NOT NULL;
        """)
        rows = cur.fetchall()
    return JSONResponse(rows_to_geojson(rows))


@app.get("/api/geojson/{table}")
def generic_geojson(table: str):
    """
    Return GeoJSON for any table/view that has a `geom_wgs84` column.
    Only alphanumeric + underscore names allowed (SQL-injection safe).
    """
    if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", table):
        return JSONResponse({"error": "invalid table name"}, status_code=400)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT column_name FROM information_schema.columns
             WHERE table_schema = 'public'
               AND table_name   = %s
               AND column_name  = 'geom_wgs84';
        """, (table,))
        if not cur.fetchone():
            return JSONResponse({"error": f"table '{table}' not found or has no geom_wgs84"}, status_code=404)

        cur.execute(f"""
            SELECT *, ST_AsGeoJSON(geom_wgs84) AS geometry
              FROM public.{table}
             WHERE geom_wgs84 IS NOT NULL;
        """)
        rows = cur.fetchall()
        for r in rows:
            r.pop("geom_wgs84", None)
    return JSONResponse(rows_to_geojson(rows))


@app.get("/api/tables")
def list_tables():
    """List tables/views that have a geom_wgs84 column."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT table_name
              FROM information_schema.columns
             WHERE table_schema = 'public'
               AND column_name  = 'geom_wgs84'
             ORDER BY table_name;
        """)
        tables = [r["table_name"] for r in cur.fetchall()]
    return {"tables": tables}