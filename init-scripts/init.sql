-- init.sql – SkiSpatialDB
-- Seeds the ski_resorts table from CSV and builds geometry.

CREATE EXTENSION IF NOT EXISTS postgis;

-- ── Ski Resorts ─────────────────────────────────────────────────────────────

CREATE TABLE ski_resorts (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    province        TEXT,
    nearest_city    TEXT,
    vertical_drop_m INTEGER,
    num_runs        INTEGER,
    num_lifts       INTEGER,
    lon_wgs84       DOUBLE PRECISION,
    lat_wgs84       DOUBLE PRECISION,
    geom_wgs84      GEOMETRY(Point, 4326),
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

COPY ski_resorts (id, name, province, nearest_city, vertical_drop_m, num_runs, num_lifts, lon_wgs84, lat_wgs84)
FROM '/docker-entrypoint-initdb.d/ski_resorts.csv'
DELIMITER ','
CSV HEADER;

-- Populate geometry from lon/lat
UPDATE ski_resorts
   SET geom_wgs84 = ST_SetSRID(ST_MakePoint(lon_wgs84, lat_wgs84), 4326)
 WHERE lon_wgs84 IS NOT NULL AND lat_wgs84 IS NOT NULL;

-- Sync the sequence so INSERT without explicit id works
SELECT setval('ski_resorts_id_seq', COALESCE(MAX(id), 0) + 1) FROM ski_resorts;
