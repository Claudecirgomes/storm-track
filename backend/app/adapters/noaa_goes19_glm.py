"""Bounded reader for the public NOAA GOES-19 GLM-L2-LCFA bucket.

This adapter is intentionally inert unless the local collection scheduler is
explicitly enabled and the source-product gates pass. It emits lightning
observations only; it does not detect storms or issue risk/forecast alerts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from io import BytesIO
from math import isfinite
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET
import re


BUCKET_URL = "https://noaa-goes19.s3.amazonaws.com/"
PRODUCT_PREFIX = "GLM-L2-LCFA/"
PRODUCT_CODE = "GLM-L2-LCFA"
MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024
MAX_FLASHES_PER_FILE = 50_000
USER_AGENT = "StormTrackLocalMVP/0.2 (NOAA GOES-19 GLM reader)"
KEY_TIME = re.compile(r"_s(?P<stamp>\d{14})_e")


class AdapterError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class SourceObject:
    key: str
    size: int
    last_modified: str
    observed_at: str


def _request_bytes(url: str, *, timeout: float = 12.0, max_bytes: int = 1_000_000) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=timeout) as response:
            declared = response.headers.get("Content-Length")
            if declared and int(declared) > max_bytes:
                raise AdapterError("RESPONSE_TOO_LARGE", "NOAA response exceeded the configured size limit")
            chunks, total = [], 0
            while True:
                chunk = response.read(min(64 * 1024, max_bytes + 1 - total))
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise AdapterError("RESPONSE_TOO_LARGE", "NOAA response exceeded the configured size limit")
                chunks.append(chunk)
            return b"".join(chunks)
    except AdapterError:
        raise
    except Exception as exc:
        raise AdapterError("SOURCE_UNAVAILABLE", "NOAA GOES-19 bucket could not be reached") from exc


def _hour_prefixes(now: datetime, *, lookback_minutes: int = 5) -> list[str]:
    now = now.astimezone(timezone.utc)
    cutoff = now - timedelta(minutes=lookback_minutes)
    hour = now.replace(minute=0, second=0, microsecond=0)
    prefixes = []
    while hour >= cutoff.replace(minute=0, second=0, microsecond=0):
        prefixes.append(f"{PRODUCT_PREFIX}{hour:%Y}/{hour:%j}/{hour:%H}/")
        hour -= timedelta(hours=1)
    return prefixes


def _time_from_key(key: str) -> str | None:
    match = KEY_TIME.search(key)
    if not match:
        return None
    stamp = match.group("stamp")
    try:
        base = datetime.strptime(stamp[:13], "%Y%j%H%M%S").replace(tzinfo=timezone.utc)
        tenths = int(stamp[13])
        return (base + timedelta(milliseconds=tenths * 100)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    except ValueError:
        return None


def list_recent_objects(*, now: datetime | None = None, after_key: str | None = None,
                        lookback_minutes: int = 5, max_objects: int = 30) -> list[SourceObject]:
    """List a bounded recent window; no full archive scan or bulk download."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    cutoff = now.astimezone(timezone.utc) - timedelta(minutes=lookback_minutes)
    objects: dict[str, SourceObject] = {}
    for prefix in _hour_prefixes(now, lookback_minutes=lookback_minutes):
        query = urlencode({"list-type": "2", "prefix": prefix, "max-keys": "500"})
        xml = _request_bytes(BUCKET_URL + "?" + query, max_bytes=2_000_000)
        try:
            root = ET.fromstring(xml)
        except ET.ParseError as exc:
            raise AdapterError("INVALID_SOURCE_CATALOG", "NOAA bucket listing was not valid XML") from exc
        if (root.findtext("{*}IsTruncated") or "false").lower() == "true":
            raise AdapterError("SOURCE_CATALOG_TRUNCATED", "NOAA bucket listing exceeded its bounded page")
        for entry in root.findall(".//{*}Contents"):
            key = entry.findtext("{*}Key") or ""
            size_raw = entry.findtext("{*}Size") or "0"
            modified = entry.findtext("{*}LastModified") or ""
            if not key.startswith(PRODUCT_PREFIX) or not key.endswith(".nc"):
                continue
            observed_at = _time_from_key(key)
            if observed_at is None:
                continue
            observed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
            if observed < cutoff or observed > now.astimezone(timezone.utc) + timedelta(minutes=1):
                continue
            if after_key and key <= after_key:
                continue
            try:
                size = int(size_raw)
            except ValueError:
                continue
            objects[key] = SourceObject(key, size, modified, observed_at)
    ordered = sorted(objects.values(), key=lambda item: item.key)
    if len(ordered) > max_objects:
        raise AdapterError("OBJECT_WINDOW_TRUNCATED", "Recent NOAA window exceeded the configured object limit")
    return ordered


def download_object(item: SourceObject, *, max_bytes: int = MAX_DOWNLOAD_BYTES) -> bytes:
    if not item.key.startswith(PRODUCT_PREFIX) or ".." in item.key.split("/"):
        raise AdapterError("INVALID_OBJECT_KEY", "Object key is outside the configured NOAA product")
    if item.size <= 0 or item.size > max_bytes:
        raise AdapterError("OBJECT_SIZE_REJECTED", "NOAA object is empty or above the configured download limit")
    payload = _request_bytes(BUCKET_URL + item.key, max_bytes=max_bytes)
    if not payload:
        raise AdapterError("EMPTY_OBJECT", "NOAA object contained no bytes")
    return payload


def _as_float(value) -> float | None:
    try:
        # netCDF4 masked values expose a truthy mask attribute.
        mask = getattr(value, "mask", False)
        if bool(mask):
            return None
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if isfinite(number) else None


def normalize_flashes(longitudes, latitudes, *, max_features: int = MAX_FLASHES_PER_FILE) -> dict:
    """Convert NOAA GLM flash coordinates to GeoJSON without deriving hazard."""
    if len(longitudes) != len(latitudes):
        raise AdapterError("INVALID_NETCDF", "GLM latitude and longitude arrays have different lengths")
    if len(longitudes) > max_features:
        raise AdapterError("FEATURE_LIMIT_EXCEEDED", "GLM file exceeds the configured flash feature limit")
    features = []
    for index, (lon_raw, lat_raw) in enumerate(zip(longitudes, latitudes)):
        lon, lat = _as_float(lon_raw), _as_float(lat_raw)
        if lon is None or lat is None or not -180 <= lon <= 180 or not -90 <= lat <= 90:
            continue
        features.append({
            "type": "Feature",
            "id": index,
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {"data_type": "LIGHTNING_FLASH", "source": "NOAA GOES-19 GLM"},
        })
    return {"type": "FeatureCollection", "features": features}


def parse_netcdf(payload: bytes) -> dict:
    try:
        from netCDF4 import Dataset
    except ImportError as exc:
        raise AdapterError("NETCDF_DEPENDENCY_MISSING", "Install requirements.txt to parse NOAA NetCDF files") from exc
    try:
        with Dataset("stormtrack-glm-in-memory.nc", mode="r", memory=payload) as dataset:
            longitude_name = "flash_lon"
            latitude_name = "flash_lat"
            if longitude_name not in dataset.variables or latitude_name not in dataset.variables:
                raise AdapterError("INVALID_NETCDF_SCHEMA", "GLM file does not contain flash_lon and flash_lat")
            geometry = normalize_flashes(dataset.variables[longitude_name][:], dataset.variables[latitude_name][:])
            return {
                "geometry": geometry,
                "flash_count": len(geometry["features"]),
                "provider_product": PRODUCT_CODE,
            }
    except AdapterError:
        raise
    except Exception as exc:
        raise AdapterError("INVALID_NETCDF", "NOAA GLM file could not be decoded") from exc
