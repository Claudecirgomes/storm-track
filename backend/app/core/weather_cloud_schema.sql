-- Additive private schema. No changes to accounts, sessions or operational events.
CREATE SCHEMA IF NOT EXISTS stormtrack_weather;
REVOKE ALL ON SCHEMA stormtrack_weather FROM PUBLIC;
CREATE TABLE IF NOT EXISTS stormtrack_weather.objects (
 key TEXT PRIMARY KEY, observed TEXT NOT NULL, "end" TEXT NOT NULL,
 processed TEXT NOT NULL, kind TEXT NOT NULL, metadata TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS weather_objects_time ON stormtrack_weather.objects(kind,"end");
CREATE TABLE IF NOT EXISTS stormtrack_weather.flashes (
 id TEXT PRIMARY KEY, observed TEXT NOT NULL, lon DOUBLE PRECISION, lat DOUBLE PRECISION);
CREATE INDEX IF NOT EXISTS weather_flash_time ON stormtrack_weather.flashes(observed);
CREATE TABLE IF NOT EXISTS stormtrack_weather.status (
 product TEXT PRIMARY KEY, checked TEXT NOT NULL, error TEXT);
CREATE TABLE IF NOT EXISTS stormtrack_weather.satellite_queue (
 key TEXT PRIMARY KEY, product TEXT NOT NULL, kind TEXT NOT NULL, size BIGINT NOT NULL,
 observed TEXT NOT NULL, discovered TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
 attempts INTEGER NOT NULL DEFAULT 0, retry_at TEXT, error TEXT, completed TEXT, source_sha256 TEXT);
CREATE TABLE IF NOT EXISTS stormtrack_weather.satellite_discovery (
 product TEXT PRIMARY KEY, checked TEXT NOT NULL, recovery_gap TEXT, started TEXT);
CREATE TABLE IF NOT EXISTS stormtrack_weather.assets (
 name TEXT PRIMARY KEY, scene_id TEXT NOT NULL, payload BYTEA NOT NULL,
 sha256 TEXT NOT NULL, created TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS weather_assets_scene ON stormtrack_weather.assets(scene_id);
CREATE TABLE IF NOT EXISTS stormtrack_weather.cache (
 id INTEGER PRIMARY KEY, payload TEXT, fetched DOUBLE PRECISION, attempt DOUBLE PRECISION, error TEXT);
CREATE TABLE IF NOT EXISTS stormtrack_weather.point_cache (
 id TEXT PRIMARY KEY, payload TEXT, fetched DOUBLE PRECISION, attempt DOUBLE PRECISION, error TEXT);
CREATE TABLE IF NOT EXISTS stormtrack_weather.budget (period TEXT PRIMARY KEY, units INTEGER NOT NULL);
