"""HTTP fetching with retries, throttling, and polite failure."""
import logging
import subprocess
import threading
import time

import requests

from . import config

log = logging.getLogger("radar.fetch")

_session = requests.Session()
_session.headers.update({
    "User-Agent": config.USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
})

# Per-host throttles so we never hammer a source (GDELT requires 5s spacing).
_HOST_MIN_INTERVAL = {"api.gdeltproject.org": 8.0, "api.bsky.app": 1.0,
                      "www.reddit.com": 7.0, "old.reddit.com": 7.0}
_last_hit: dict = {}
_lock = threading.Lock()


def _throttle(url: str) -> None:
    host = url.split("/")[2] if "://" in url else url
    interval = _HOST_MIN_INTERVAL.get(host, 0.0)
    if not interval:
        return
    with _lock:
        wait = interval - (time.time() - _last_hit.get(host, 0.0))
        if wait > 0:
            time.sleep(wait)
        _last_hit[host] = time.time()


class _CurlResponse:
    """Minimal Response stand-in for the curl fallback path."""

    def __init__(self, text: str, url: str):
        self.text = text
        self.status_code = 200
        self.url = url

    def json(self):
        import json as _json
        return _json.loads(self.text)


def _curl_get(url: str, timeout: int):
    """Fetch via the system curl.

    This Python links LibreSSL 2.8.3, which cannot negotiate TLS with some
    hosts (pauseai-us.org among them). macOS curl uses its own TLS stack and
    succeeds where requests raises SSLError, so it is the fallback rather than
    losing a core source entirely.
    """
    try:
        result = subprocess.run(
            ["curl", "-sL", "--max-time", str(timeout), "-A", config.USER_AGENT, url],
            capture_output=True, text=True, timeout=timeout + 10)
        if result.returncode == 0 and result.stdout.strip():
            log.info("curl fallback succeeded for %s", url)
            return _CurlResponse(result.stdout, url)
        log.warning("curl fallback failed for %s (rc=%s)", url, result.returncode)
    except Exception as exc:
        log.warning("curl fallback errored for %s: %s", url, exc)
    return None


def get(url: str, *, retries: int = 2, timeout: int = None, headers: dict = None):
    """GET a URL. Returns a Response, or None if it ultimately failed."""
    timeout = timeout or config.HTTP_TIMEOUT
    for attempt in range(retries + 1):
        _throttle(url)
        try:
            resp = _session.get(url, timeout=timeout, headers=headers,
                                allow_redirects=True)
            if resp.status_code == 200:
                return resp
            if resp.status_code in (429, 503) and attempt < retries:
                time.sleep(2 ** attempt * 3)
                continue
            log.warning("HTTP %s for %s", resp.status_code, url)
            return None
        except requests.exceptions.SSLError:
            return _curl_get(url, timeout)  # LibreSSL cannot reach this host
        except requests.RequestException as exc:
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            log.warning("fetch failed %s: %s", url, exc)
    return None


def get_text(url: str, **kw) -> str:
    resp = get(url, **kw)
    return resp.text if resp is not None else ""


def get_json(url: str, **kw):
    resp = get(url, **kw)
    if resp is None:
        return None
    try:
        return resp.json()
    except ValueError:
        log.warning("non-JSON response from %s", url)
        return None
