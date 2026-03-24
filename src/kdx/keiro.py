from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

DEFAULT_HTTP_USER_AGENT = "KDX/0.1 (+https://kierolabs.space/api)"
RESULT_LIST_KEYS = ("results", "organic", "items", "sources", "links", "result", "extracted_content")
NESTED_PAYLOAD_KEYS = ("data", "result", "response", "payload")
TITLE_KEYS = ("title", "search_title", "name", "source", "label")
URL_KEYS = ("url", "search_url", "link", "source_url", "href", "page_url", "origin_url")
SNIPPET_KEYS = ("snippet", "description", "summary", "content", "text", "body", "markdown")
SUMMARY_KEYS = ("answer", "summary", "message", "content", "text", "description", "body")


class KeiroError(RuntimeError):
    """Raised when the Keiro API returns an error or is misconfigured."""


@dataclass(slots=True)
class KeiroClient:
    api_key: str
    base_url: str = "https://kierolabs.space/api"
    timeout_seconds: int = 30

    def configured(self) -> bool:
        return bool(self.api_key)

    def health(self) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.base_url}/health",
            method="GET",
            headers=self._headers(),
        )
        return self._decode(urllib.request.urlopen(request, timeout=self.timeout_seconds).read())

    def search(self, query: str, cache_search: bool = True, included_urls: list[str] | None = None) -> dict[str, Any]:
        return self._post("/search", {
            "query": query,
            "cache_search": cache_search,
            "included_urls": included_urls or [],
        })

    def search_pro(self, query: str, cache_search: bool = True, included_urls: list[str] | None = None) -> dict[str, Any]:
        return self._post("/search-pro", {
            "query": query,
            "cache_search": cache_search,
            "included_urls": included_urls or [],
        })

    def research(self, query: str, cache_search: bool = True, included_urls: list[str] | None = None) -> dict[str, Any]:
        return self._post("/research", {
            "query": query,
            "cache_search": cache_search,
            "included_urls": included_urls or [],
        })

    def research_pro(self, query: str, cache_search: bool = True, included_urls: list[str] | None = None) -> dict[str, Any]:
        return self._post("/research-pro", {
            "query": query,
            "cache_search": cache_search,
            "included_urls": included_urls or [],
        })

    def answer(self, query: str) -> dict[str, Any]:
        return self._post("/answer", {"query": query})

    def crawl(self, url: str) -> dict[str, Any]:
        return self._post("/web-crawler", {"url": url})

    def search_engine(
        self,
        query: str,
        *,
        content_type: str = "general",
        language: str = "en",
        region: str | None = None,
        time_range: str | None = None,
        top_n: int = 10,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "query": query,
            "type": content_type,
            "language": language,
            "top_n": top_n,
        }
        if region:
            payload["region"] = region
        if time_range:
            payload["time_range"] = time_range
        return self._post("/search-engine", payload)

    def memory_search(self, query: str, workspace_id: str, task_type: str = "web_search") -> dict[str, Any]:
        return self._post("/memory-search", {
            "query": query,
            "workspace_id": workspace_id,
            "task_type": task_type,
        })

    def _post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.configured():
            raise KeiroError("Missing KEIRO API key. Set KEIRO_API_KEY or KDX_KEIRO_API_KEY.")
        body = dict(payload)
        body["apiKey"] = self.api_key
        raw = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}{endpoint}",
            data=raw,
            method="POST",
            headers=self._headers(content_type="application/json"),
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return self._decode(response.read())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            if exc.code == 403 and "1010" in detail:
                detail = f"{detail} | request blocked at the edge; the client signature was rejected"
            raise KeiroError(f"Keiro HTTP {exc.code}: {detail or exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise KeiroError(f"Keiro request failed: {exc.reason}") from exc

    @staticmethod
    def _headers(*, content_type: str | None = None) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": DEFAULT_HTTP_USER_AGENT,
        }
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    @staticmethod
    def _decode(payload: bytes) -> dict[str, Any]:
        text = payload.decode("utf-8", errors="ignore")
        if not text.strip():
            return {}
        data = json.loads(text)
        if isinstance(data, dict):
            return data
        return {"data": data}


def normalize_results(payload: dict[str, Any], limit: int = 5) -> list[dict[str, str]]:
    raw_items = extract_result_items(payload)
    normalized: list[dict[str, str]] = []
    for item in raw_items[:limit]:
        if not isinstance(item, dict):
            normalized.append({"title": str(item), "url": "", "snippet": ""})
            continue
        normalized.append({
            "title": result_title(item),
            "url": result_url(item),
            "snippet": result_snippet(item),
        })
    if not normalized:
        answer = summary_text(payload)
        if answer:
            normalized.append({"title": "summary", "url": "", "snippet": answer})
    return normalized[:limit]


def extract_result_items(payload: dict[str, Any]) -> list[Any]:
    return _extract_result_items(payload, visited=set())


def result_title(item: dict[str, Any]) -> str:
    return _first_string(item, TITLE_KEYS) or "Untitled"


def result_url(item: dict[str, Any]) -> str:
    return _first_string(item, URL_KEYS)


def result_snippet(item: dict[str, Any]) -> str:
    return _first_string(item, SNIPPET_KEYS)


def summary_text(payload: dict[str, Any]) -> str:
    for mapping in _payload_mappings(payload):
        text = _first_string(mapping, SUMMARY_KEYS)
        if text:
            return text
    return ""


def cached_search(
    cache_path: Path,
    cache_key: str,
    ttl_seconds: int,
    fetch: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    cache = _load_cache(cache_path)
    entry = cache.get(cache_key)
    if isinstance(entry, dict):
        expires_at = _parse_timestamp(str(entry.get("expires_at", "")))
        payload = entry.get("payload")
        if expires_at is not None and expires_at > now and isinstance(payload, dict):
            return payload
    payload = fetch()
    cache[cache_key] = {
        "expires_at": (now + timedelta(seconds=max(1, ttl_seconds))).isoformat(),
        "payload": payload,
    }
    cache_path.write_text(json.dumps(cache, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def _load_cache(cache_path: Path) -> dict[str, Any]:
    if not cache_path.exists():
        return {}
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _extract_result_items(payload: Any, *, visited: set[int]) -> list[Any]:
    if not isinstance(payload, dict):
        return []
    marker = id(payload)
    if marker in visited:
        return []
    visited.add(marker)
    for key in RESULT_LIST_KEYS:
        candidate = payload.get(key)
        if isinstance(candidate, list):
            return candidate
    for key in NESTED_PAYLOAD_KEYS:
        candidate = payload.get(key)
        if isinstance(candidate, dict):
            nested = _extract_result_items(candidate, visited=visited)
            if nested:
                return nested
    return []


def _payload_mappings(payload: dict[str, Any]) -> list[dict[str, Any]]:
    mappings = [payload]
    for key in NESTED_PAYLOAD_KEYS:
        candidate = payload.get(key)
        if isinstance(candidate, dict):
            mappings.append(candidate)
    return mappings


def _first_string(mapping: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str):
            trimmed = value.strip()
            if trimmed:
                return trimmed
    return ""
