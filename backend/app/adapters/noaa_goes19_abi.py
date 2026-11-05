"""Bounded proxy for public NOAA GOES-19 ABI GeoColor JPEG imagery.

This serves timestamped NOAA images inside the StormTrack UI. It does not archive
images or derive meteorological alerts. NOAA labels the imagery informational
and not for operational or emergency-response use.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from threading import Lock
from time import monotonic
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
import re


PROVIDER_CODE = "NOAA"
PRODUCT_CODE = "ABI-L2-MCMIPF"
BASE_URL = "https://cdn.star.nesdis.noaa.gov/GOES19/ABI/FD/GEOCOLOR/"
ALLOWED_HOST = "cdn.star.nesdis.noaa.gov"
IMAGE_FILENAME = re.compile(r"^(?P<stamp>\d{11})_GOES19-ABI-FD-GEOCOLOR-1808x1808\.jpg$")
USER_AGENT = "StormTrackLocalMVP/0.3 (NOAA public ABI image proxy)"
MAX_INDEX_BYTES = 8 * 1024 * 1024
MAX_IMAGE_BYTES = 5 * 1024 * 1024
INDEX_CACHE_SECONDS = 20
MAX_FRAME_COUNT = 24


class SatelliteSourceError(RuntimeError):
    """NOAA imagery could not be safely listed or fetched."""


@dataclass(frozen=True)
class SatelliteFrame:
    filename: str
    observed_at_utc: str
    image_path: str


class _IndexParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.filenames: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href")
        if href and IMAGE_FILENAME.fullmatch(href):
            self.filenames.add(href)


_cache_lock = Lock()
_cached_frames: list[SatelliteFrame] = []
_cache_until = 0.0


def _read_response(url: str, *, max_bytes: int, timeout: float = 12.0,
                   expected_content_type: str) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": expected_content_type})
    try:
        with urlopen(request, timeout=timeout) as response:
            final = urlparse(response.geturl())
            if final.scheme != "https" or final.hostname != ALLOWED_HOST:
                raise SatelliteSourceError("NOAA redirected outside the approved image host")
            content_type = response.headers.get_content_type().lower()
            if content_type != expected_content_type:
                raise SatelliteSourceError("NOAA returned an unexpected content type")
            declared_size = response.headers.get("Content-Length")
            if declared_size and int(declared_size) > max_bytes:
                raise SatelliteSourceError("NOAA response exceeded the configured size limit")
            data = response.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise SatelliteSourceError("NOAA response exceeded the configured size limit")
            return data
    except SatelliteSourceError:
        raise
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        raise SatelliteSourceError("NOAA GOES-19 ABI imagery is temporarily unavailable") from exc


def _parse_frame_time(filename: str) -> datetime | None:
    match = IMAGE_FILENAME.fullmatch(filename)
    if match is None:
        return None
    try:
        return datetime.strptime(match.group("stamp"), "%Y%j%H%M").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _fetch_index() -> list[SatelliteFrame]:
    html = _read_response(BASE_URL, max_bytes=MAX_INDEX_BYTES,
                          expected_content_type="text/html")
    parser = _IndexParser()
    try:
        parser.feed(html.decode("utf-8", errors="replace"))
    except Exception as exc:
        raise SatelliteSourceError("NOAA image catalog could not be parsed") from exc
    frames = []
    for filename in parser.filenames:
        observed = _parse_frame_time(filename)
        if observed is None:
            continue
        frames.append(SatelliteFrame(
            filename=filename,
            observed_at_utc=observed.isoformat(timespec="minutes").replace("+00:00", "Z"),
            image_path=f"/api/satellite/goes19/abi/image/{filename}",
        ))
    frames.sort(key=lambda frame: frame.observed_at_utc, reverse=True)
    if not frames:
        raise SatelliteSourceError("NOAA image catalog did not contain valid recent frames")
    return frames


def list_frames(limit: int = 12) -> dict:
    """Return a recent bounded loop manifest; cache the source index briefly."""
    global _cached_frames, _cache_until
    if not 1 <= limit <= MAX_FRAME_COUNT:
        raise ValueError(f"limit must be between 1 and {MAX_FRAME_COUNT}")
    now_tick = monotonic()
    with _cache_lock:
        if _cached_frames and now_tick < _cache_until:
            frames = list(_cached_frames)
        else:
            frames = _fetch_index()
            _cached_frames = frames
            _cache_until = now_tick + INDEX_CACHE_SECONDS
    selected = frames[:limit]
    newest = _parse_frame_time(selected[0].filename)
    now = datetime.now(timezone.utc)
    age_seconds = max(0, int((now - newest).total_seconds())) if newest else None
    return {
        "provider_code": PROVIDER_CODE,
        "product_code": PRODUCT_CODE,
        "satellite": "GOES-19",
        "product": "ABI GeoColor Full Disk 1808x1808",
        "cadence_minutes": 10,
        "source_status": "AVAILABLE" if age_seconds is not None and age_seconds <= 30 * 60 else "DEGRADED",
        "latest_frame_age_seconds": age_seconds,
        "attribution": "GeoColor imagery: credit CIRA/NOAA",
        "frames": [asdict(frame) for frame in selected],
        "archived_by_stormtrack": False,
        "limitations": [
            "Informational satellite imagery only; NOAA does not designate this web product for operational or emergency-response use.",
            "Cloud-image loop does not identify storm cells, estimate impact, or issue a forecast or alert.",
            "This proxy displays NOAA images in the app but does not persist them locally.",
        ],
        "refreshed_at_utc": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
    }


def fetch_frame(filename: str) -> bytes:
    """Fetch one whitelisted, moderate-resolution, timestamped NOAA JPEG."""
    if not IMAGE_FILENAME.fullmatch(filename):
        raise ValueError("Invalid NOAA ABI image filename")
    observed = _parse_frame_time(filename)
    if observed is None:
        raise ValueError("Invalid NOAA ABI image timestamp")
    url = urljoin(BASE_URL, filename)
    if urlparse(url).hostname != ALLOWED_HOST:
        raise ValueError("Invalid NOAA image host")
    return _read_response(url, max_bytes=MAX_IMAGE_BYTES,
                          expected_content_type="image/jpeg")


def viewer_metadata() -> dict:
    """Metadata for direct in-app images; no outbound link is required."""
    return {
        "provider_code": PROVIDER_CODE,
        "product_code": PRODUCT_CODE,
        "satellite": "GOES-19",
        "instrument": "Advanced Baseline Imager (ABI)",
        "product": "GeoColor Full Disk 1808x1808",
        "cadence": "10 minutes",
        "coverage": "Full disk, including South America",
        "attribution": "GeoColor imagery: credit CIRA/NOAA",
        "mode": "direct_image_proxy_inside_stormtrack",
        "display_enabled": True,
        "archived_by_stormtrack": False,
        "limitations": [
            "NOAA labels this web product informational and not for operational or emergency-response use.",
            "Images show clouds; they do not replace radar or validated storm analysis.",
        ],
    }
