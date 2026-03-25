from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

import tomllib

from kdx.config import KdxSettings
from kdx.indexer import tokenize
from kdx.keiro import (
    KeiroClient,
    cached_search,
    extract_result_items,
    result_snippet,
    result_title,
    result_url,
)

DOC_TERMS = {"docs", "documentation", "api", "reference", "sdk", "endpoint", "endpoints", "manual"}
NEWS_TERMS = {"latest", "recent", "today", "news", "announcement"}
RELEASE_TERMS = {"release", "releases", "changelog", "migration", "breaking", "version", "versions"}
ERROR_TERMS = {"error", "exception", "traceback", "failed", "failure", "errno", "typeerror", "valueerror", "syntaxerror"}
RESEARCH_TERMS = {"compare", "comparison", "research", "analyze", "analysis", "versus", "vs"}
OFFICIAL_HIGH_CONFIDENCE_DOMAINS = {
    "github.com": 0.82,
    "pypi.org": 0.84,
    "npmjs.com": 0.84,
    "pkg.go.dev": 0.84,
    "crates.io": 0.84,
    "readthedocs.io": 0.86,
}
LOW_TRUST_HOST_MARKERS = {"medium.com", "dev.to", "hashnode.dev", "substack.com"}
DEPENDENCY_VERSION_RE = re.compile(r"([0-9]+(?:\.[0-9A-Za-z*+-]+)+)")
DOMAIN_HINT_RE = re.compile(r"\b(?:https?://)?([A-Za-z0-9.-]+\.[A-Za-z]{2,})(?:/[\S]*)?")
GENERIC_QUERY_TERMS = DOC_TERMS | NEWS_TERMS | RELEASE_TERMS | ERROR_TERMS | RESEARCH_TERMS | {
    "official",
    "overview",
    "guide",
    "guides",
    "usage",
    "search",
    "query",
    "queries",
    "request",
    "requests",
    "response",
    "responses",
    "field",
    "fields",
    "parameter",
    "parameters",
}


@dataclass(slots=True)
class DependencyHint:
    name: str
    version: str
    ecosystem: str
    source_file: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SearchPlan:
    intent: str
    mode: str
    query: str
    limit: int
    ttl_seconds: int
    should_crawl: bool
    crawl_limit: int
    evidence_items: int = 2
    evidence_char_budget: int = 750
    included_urls: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    request_kwargs: dict[str, Any] = field(default_factory=dict)
    dependency: DependencyHint | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["dependency"] = self.dependency.to_dict() if self.dependency else None
        return payload


@dataclass(slots=True)
class SearchEvidence:
    title: str
    url: str
    domain: str
    snippet: str
    source_type: str
    trust_score: float
    relevance_score: float
    freshness_score: float
    total_score: float
    reason: str
    published_at: str = ""
    crawled_excerpt: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in ("trust_score", "relevance_score", "freshness_score", "total_score"):
            payload[key] = round(float(payload[key]), 3)
        return payload


def execute_context_search(
    settings: KdxSettings,
    query: str,
    *,
    limit: int = 5,
    client: KeiroClient | None = None,
) -> dict[str, Any]:
    plan = build_search_plan(settings.repo_root, query, limit=limit)
    active_client = client or KeiroClient(api_key=settings.keiro_api_key, base_url=settings.keiro_base_url)
    cache_key = json.dumps(
        {
            "mode": plan.mode,
            "query": plan.query,
            "request_kwargs": plan.request_kwargs,
            "included_urls": plan.included_urls,
            "workspace": settings.workspace_id,
        },
        sort_keys=True,
    )
    payload = cached_search(
        settings.search_cache_path,
        f"search:{cache_key}",
        plan.ttl_seconds,
        lambda: _execute_plan(active_client, settings, plan),
    )
    evidence = rank_search_results(payload, query, plan)
    if plan.should_crawl:
        enrich_with_crawl(active_client, settings, evidence, query, plan)
    evidence = dedupe_evidence(evidence)[:limit]
    return {
        "plan": plan.to_dict(),
        "evidence": [item.to_dict() for item in evidence],
        "compact": render_web_evidence_block(
            evidence,
            char_budget=plan.evidence_char_budget,
            max_items=plan.evidence_items,
        ),
        "raw": payload,
    }


def build_search_plan(repo_root: Path, query: str, *, limit: int = 5) -> SearchPlan:
    terms = set(tokenize(query))
    dependency = resolve_dependency_hint(repo_root, query)
    explicit_domains = extract_domain_hints(query)
    reasons: list[str] = []
    included_urls = sorted(explicit_domains)
    normalized_limit = max(3, min(limit, 8))

    if ERROR_TERMS & terms or _looks_like_error(query):
        reasons.append("error-style lookup")
        rewritten = rewrite_query(query, dependency=dependency, intent="error_lookup")
        return SearchPlan(
            intent="error_lookup",
            mode="search_pro",
            query=rewritten,
            limit=normalized_limit,
            ttl_seconds=5_400,
            should_crawl=True,
            crawl_limit=1,
            evidence_items=1,
            evidence_char_budget=420,
            included_urls=included_urls,
            reasons=reasons,
            request_kwargs={"cache_search": True},
            dependency=dependency,
        )

    if RELEASE_TERMS & terms:
        reasons.append("release or changelog lookup")
        rewritten = rewrite_query(query, dependency=dependency, intent="release_notes")
        return SearchPlan(
            intent="release_notes",
            mode="search_pro",
            query=rewritten,
            limit=normalized_limit,
            ttl_seconds=3_600,
            should_crawl=True,
            crawl_limit=1,
            evidence_items=1,
            evidence_char_budget=420,
            included_urls=included_urls,
            reasons=reasons,
            request_kwargs={"cache_search": True},
            dependency=dependency,
        )

    if DOC_TERMS & terms or dependency is not None:
        intent = "package_api" if dependency else "official_docs"
        reasons.append("documentation/API lookup")
        rewritten = rewrite_query(query, dependency=dependency, intent=intent)
        return SearchPlan(
            intent=intent,
            mode="search_pro",
            query=rewritten,
            limit=normalized_limit,
            ttl_seconds=10_800,
            should_crawl=True,
            crawl_limit=1,
            evidence_items=1,
            evidence_char_budget=420,
            included_urls=included_urls,
            reasons=reasons,
            request_kwargs={"cache_search": True},
            dependency=dependency,
        )

    if NEWS_TERMS & terms:
        reasons.append("freshness-sensitive query")
        return SearchPlan(
            intent="latest_news",
            mode="search_engine",
            query=query.strip(),
            limit=normalized_limit,
            ttl_seconds=900,
            should_crawl=False,
            crawl_limit=0,
            evidence_items=2,
            evidence_char_budget=520,
            included_urls=included_urls,
            reasons=reasons,
            request_kwargs={
                "content_type": "news",
                "time_range": "month",
                "top_n": max(6, normalized_limit + 1),
                "language": "en",
            },
            dependency=dependency,
        )

    if RESEARCH_TERMS & terms or len(query.split()) >= 14:
        reasons.append("broad research query")
        rewritten = rewrite_query(query, dependency=dependency, intent="background_research")
        return SearchPlan(
            intent="background_research",
            mode="research",
            query=rewritten,
            limit=min(normalized_limit, 4),
            ttl_seconds=7_200,
            should_crawl=True,
            crawl_limit=1,
            evidence_items=2,
            evidence_char_budget=650,
            included_urls=included_urls,
            reasons=reasons,
            request_kwargs={"cache_search": True},
            dependency=dependency,
        )

    return SearchPlan(
        intent="general_web",
        mode="memory_search",
        query=query.strip(),
        limit=normalized_limit,
        ttl_seconds=21_600,
        should_crawl=False,
        crawl_limit=0,
        evidence_items=2,
        evidence_char_budget=520,
        included_urls=included_urls,
        reasons=["general external lookup"],
        request_kwargs={"task_type": "web_search"},
        dependency=dependency,
    )


def render_web_evidence_block(evidence: Iterable[dict[str, Any]] | Iterable[SearchEvidence], *, char_budget: int = 1_200, max_items: int = 3) -> str:
    used = 0
    parts: list[str] = []
    count = 0
    for item in evidence:
        payload = item if isinstance(item, dict) else item.to_dict()
        if count >= max_items:
            break
        excerpt = str(payload.get("crawled_excerpt") or payload.get("snippet") or "").strip()
        excerpt = compact_text(excerpt, max_chars=220)
        title = compact_text(str(payload.get("title") or "Untitled"), max_chars=80)
        domain = str(payload.get("domain") or "")
        source_type = str(payload.get("source_type") or "web")
        url = str(payload.get("url") or "")
        trust = float(payload.get("trust_score", 0.0))
        freshness = str(payload.get("published_at") or "")
        line = f"- {title} | {domain} | {source_type} | trust={trust:.2f}"
        if freshness:
            line += f" | date={freshness}"
        entry = "\n".join(filter(None, [line, f"  {url}" if url else "", f"  {excerpt}" if excerpt else ""]))
        if used + len(entry) > char_budget and parts:
            break
        parts.append(entry[: max(0, char_budget - used)])
        used += len(parts[-1]) + 2
        count += 1
    return "\n\n".join(parts)


def extract_domain_hints(query: str) -> set[str]:
    hints = {match.group(1).lower().lstrip("www.") for match in DOMAIN_HINT_RE.finditer(query)}
    return {hint for hint in hints if "." in hint}


def resolve_dependency_hint(repo_root: Path, query: str) -> DependencyHint | None:
    query_terms = set(tokenize(query))
    best: tuple[float, DependencyHint] | None = None
    for dependency in discover_dependencies(repo_root):
        dep_terms = set(tokenize(dependency.name))
        overlap = query_terms & dep_terms
        score = float(len(overlap) * 3)
        if dependency.name.lower() in query.lower():
            score += 4.0
        if dependency.version and any(version_term in query.lower() for version_term in tokenize(dependency.version)):
            score += 1.0
        if score <= 0:
            continue
        if best is None or score > best[0]:
            best = (score, dependency)
    return best[1] if best else None


def discover_dependencies(repo_root: Path) -> list[DependencyHint]:
    signature = _dependency_manifest_signature(repo_root)
    return list(_discover_dependencies_cached(str(repo_root), signature))


@lru_cache(maxsize=32)
def _discover_dependencies_cached(repo_root_str: str, signature: tuple[tuple[str, int, int], ...]) -> tuple[DependencyHint, ...]:
    repo_root = Path(repo_root_str)
    candidates: list[DependencyHint] = []
    candidates.extend(_parse_package_json(repo_root / "package.json"))
    candidates.extend(_parse_requirements(repo_root / "requirements.txt"))
    candidates.extend(_parse_pyproject(repo_root / "pyproject.toml"))
    candidates.extend(_parse_cargo_toml(repo_root / "Cargo.toml"))
    candidates.extend(_parse_go_mod(repo_root / "go.mod"))
    deduped: dict[tuple[str, str], DependencyHint] = {}
    for item in candidates:
        deduped[(item.ecosystem, item.name.lower())] = item
    return tuple(sorted(deduped.values(), key=lambda item: (item.ecosystem, item.name)))


def _dependency_manifest_signature(repo_root: Path) -> tuple[tuple[str, int, int], ...]:
    signature: list[tuple[str, int, int]] = []
    for relative in ("package.json", "requirements.txt", "pyproject.toml", "Cargo.toml", "go.mod"):
        path = repo_root / relative
        try:
            stat = path.stat()
        except OSError:
            continue
        signature.append((relative, stat.st_mtime_ns, stat.st_size))
    return tuple(signature)


def rewrite_query(query: str, *, dependency: DependencyHint | None, intent: str) -> str:
    base = compact_text(" ".join(query.split()), max_chars=180)
    if dependency is None:
        if intent == "official_docs":
            return f"{base} official documentation"
        if intent == "release_notes":
            return f"{base} official release notes changelog"
        if intent == "error_lookup":
            return f'{base} official documentation issue'
        return base
    version = f" {dependency.version}" if dependency.version else ""
    if intent in {"official_docs", "package_api"}:
        return f"{dependency.name}{version} official documentation {base}".strip()
    if intent == "release_notes":
        return f"{dependency.name}{version} release notes changelog {base}".strip()
    if intent == "error_lookup":
        return f'{dependency.name}{version} "{compact_text(query, max_chars=120)}" official docs issue'.strip()
    return f"{dependency.name}{version} {base}".strip()


def rank_search_results(payload: dict[str, Any], query: str, plan: SearchPlan) -> list[SearchEvidence]:
    query_terms = set(tokenize(query))
    anchor_terms = extract_anchor_terms(query)
    evidence: list[SearchEvidence] = []
    for raw in extract_result_items(payload):
        if not isinstance(raw, dict):
            continue
        title = result_title(raw)
        url = result_url(raw)
        snippet = result_snippet(raw)
        domain = normalize_domain(url)
        source_type = detect_source_type(domain, url, title, snippet, plan)
        published_at = extract_published_at(raw)
        trust_score = compute_trust_score(domain, source_type, plan)
        relevance_score = compute_relevance_score(query_terms, anchor_terms, title, snippet, url)
        freshness_score = compute_freshness_score(published_at, plan)
        total_score = (trust_score * 0.45) + (relevance_score * 0.4) + (freshness_score * 0.15)
        reason = reason_for_result(domain, source_type, plan)
        evidence.append(
            SearchEvidence(
                title=title,
                url=url,
                domain=domain,
                snippet=compact_text(snippet, max_chars=320),
                source_type=source_type,
                trust_score=trust_score,
                relevance_score=relevance_score,
                freshness_score=freshness_score,
                total_score=total_score,
                reason=reason,
                published_at=published_at,
            )
        )
    evidence.sort(key=lambda item: (item.total_score, item.trust_score, item.relevance_score), reverse=True)
    return evidence


def enrich_with_crawl(
    client: KeiroClient,
    settings: KdxSettings,
    evidence: list[SearchEvidence],
    query: str,
    plan: SearchPlan,
) -> None:
    remaining = plan.crawl_limit
    if remaining <= 0:
        return
    for item in evidence:
        if remaining <= 0:
            break
        if not item.url or item.source_type in {"news", "blog"}:
            continue
        cache_key = f"crawl:{item.url}"
        try:
            payload = cached_search(
                settings.search_cache_path,
                cache_key,
                min(plan.ttl_seconds, 21_600),
                lambda url=item.url: client.crawl(url),
            )
        except Exception:
            continue
        excerpt = extract_crawl_excerpt(payload, query)
        if not excerpt:
            continue
        item.crawled_excerpt = compact_text(excerpt, max_chars=420)
        item.total_score += 0.05
        remaining -= 1


def dedupe_evidence(evidence: Iterable[SearchEvidence]) -> list[SearchEvidence]:
    seen: set[tuple[str, str]] = set()
    output: list[SearchEvidence] = []
    for item in evidence:
        key = (item.url or item.title, item.domain)
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def _execute_plan(client: KeiroClient, settings: KdxSettings, plan: SearchPlan) -> dict[str, Any]:
    if plan.mode == "search_engine":
        return client.search_engine(plan.query, **plan.request_kwargs)
    if plan.mode == "search_pro":
        return client.search_pro(plan.query, included_urls=plan.included_urls or None, **plan.request_kwargs)
    if plan.mode == "search":
        return client.search(plan.query, included_urls=plan.included_urls or None, **plan.request_kwargs)
    if plan.mode == "research":
        return client.research(plan.query, included_urls=plan.included_urls or None, **plan.request_kwargs)
    if plan.mode == "research_pro":
        return client.research_pro(plan.query, included_urls=plan.included_urls or None, **plan.request_kwargs)
    if plan.mode == "memory_search":
        return client.memory_search(plan.query, workspace_id=settings.workspace_id, **plan.request_kwargs)
    return client.search(plan.query, included_urls=plan.included_urls or None, cache_search=True)


def extract_published_at(payload: dict[str, Any]) -> str:
    for key in ("published_at", "publishedAt", "date", "published", "created_at"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:32]
    return ""


def extract_anchor_terms(query: str) -> set[str]:
    return {term for term in tokenize(query) if len(term) >= 4 and term not in GENERIC_QUERY_TERMS}


def compute_relevance_score(query_terms: set[str], anchor_terms: set[str], title: str, snippet: str, url: str) -> float:
    title_terms = set(tokenize(title))
    snippet_terms = set(tokenize(snippet))
    url_terms = set(tokenize(url))
    combined_terms = title_terms | snippet_terms | url_terms
    if not query_terms:
        return 0.5
    score = 0.0
    score += 0.6 * (len(query_terms & title_terms) / max(1, len(query_terms)))
    score += 0.3 * (len(query_terms & snippet_terms) / max(1, len(query_terms)))
    score += 0.1 * (len(query_terms & url_terms) / max(1, len(query_terms)))
    if anchor_terms:
        anchor_overlap = len(anchor_terms & combined_terms) / max(1, len(anchor_terms))
        score = (score * 0.72) + (anchor_overlap * 0.28)
        if anchor_overlap == 0:
            score *= 0.35
    return min(1.0, score)


def compute_trust_score(domain: str, source_type: str, plan: SearchPlan) -> float:
    if not domain:
        return 0.35
    if domain in plan.included_urls or any(domain.endswith(hint) for hint in plan.included_urls):
        return 0.98
    if domain in OFFICIAL_HIGH_CONFIDENCE_DOMAINS:
        return OFFICIAL_HIGH_CONFIDENCE_DOMAINS[domain]
    if domain.startswith("docs.") or ".docs." in domain:
        return 0.92
    if any(marker in domain for marker in LOW_TRUST_HOST_MARKERS):
        return 0.4
    if source_type in {"docs", "reference"}:
        return 0.88
    if source_type == "registry":
        return 0.84
    if source_type == "code":
        return 0.8
    if source_type == "news":
        return 0.72
    return 0.62


def compute_freshness_score(published_at: str, plan: SearchPlan) -> float:
    if not published_at:
        return 0.85 if plan.intent in {"official_docs", "package_api"} else 0.5
    if plan.intent in {"latest_news", "release_notes"}:
        return 0.95
    return 0.7


def detect_source_type(domain: str, url: str, title: str, snippet: str, plan: SearchPlan) -> str:
    lowered_url = url.lower()
    lowered_title = title.lower()
    lowered_snippet = snippet.lower()
    if any(token in lowered_url for token in ("/docs", "documentation", "/reference")) or domain.startswith("docs.") or "readthedocs.io" in domain:
        return "docs"
    if domain in {"pypi.org", "npmjs.com", "pkg.go.dev", "crates.io"}:
        return "registry"
    if domain == "github.com":
        return "code"
    if plan.intent == "latest_news" or any(term in lowered_url for term in ("/news", "/blog", "/posts")):
        return "news"
    if any(marker in domain for marker in LOW_TRUST_HOST_MARKERS):
        return "blog"
    if "api" in lowered_title or "api" in lowered_snippet:
        return "reference"
    return "web"


def reason_for_result(domain: str, source_type: str, plan: SearchPlan) -> str:
    if domain in plan.included_urls or any(domain.endswith(hint) for hint in plan.included_urls):
        return "explicit domain hint"
    if source_type == "docs":
        return "documentation-style source"
    if source_type == "registry":
        return "package registry source"
    if source_type == "code":
        return "source repository"
    if source_type == "news":
        return "fresh/news source"
    return "high-ranked web result"


def normalize_domain(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    host = (parsed.netloc or parsed.path).lower()
    return host[4:] if host.startswith("www.") else host


def extract_crawl_excerpt(payload: dict[str, Any], query: str) -> str:
    texts = []
    for key in ("content", "text", "markdown", "summary", "description", "body"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            texts.append(value)
    data = payload.get("data")
    if isinstance(data, dict):
        for key in ("content", "text", "markdown", "summary", "description", "body"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                texts.append(value)
    if not texts:
        return ""
    text = max(texts, key=len)
    return best_excerpt(text, set(tokenize(query)), max_chars=420)


def best_excerpt(text: str, query_terms: set[str], max_chars: int) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return compact_text(text, max_chars=max_chars)
    best_line = lines[0]
    best_score = -1
    for line in lines:
        score = len(query_terms & set(tokenize(line)))
        if score > best_score:
            best_score = score
            best_line = line
    return compact_text(best_line, max_chars=max_chars)


def compact_text(text: str, *, max_chars: int) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= max_chars:
        return collapsed
    return collapsed[: max_chars - 1].rstrip() + "…"


def _looks_like_error(query: str) -> bool:
    return bool(re.search(r"\b(?:Error|Exception|Traceback|failed|failure)\b", query))


def _parse_package_json(path: Path) -> list[DependencyHint]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    output: list[DependencyHint] = []
    for section in ("dependencies", "devDependencies", "peerDependencies"):
        data = payload.get(section)
        if not isinstance(data, dict):
            continue
        for name, version in data.items():
            output.append(DependencyHint(name=str(name), version=normalize_version(str(version)), ecosystem="npm", source_file=path.name))
    return output


def _parse_requirements(path: Path) -> list[DependencyHint]:
    if not path.exists():
        return []
    output: list[DependencyHint] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        stripped = line.split("#", 1)[0].strip()
        if not stripped or stripped.startswith("-"):
            continue
        name, _, version = stripped.partition("==")
        normalized_name = name.split("[", 1)[0].split(">=", 1)[0].split("<=", 1)[0].split("~=", 1)[0].split("!=", 1)[0].split("<", 1)[0].split(">", 1)[0].strip()
        if not normalized_name:
            continue
        output.append(DependencyHint(name=normalized_name, version=normalize_version(version or stripped), ecosystem="python", source_file=path.name))
    return output


def _parse_pyproject(path: Path) -> list[DependencyHint]:
    if not path.exists():
        return []
    try:
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return []
    output: list[DependencyHint] = []
    project = payload.get("project", {})
    if isinstance(project, dict):
        dependencies = project.get("dependencies")
        if isinstance(dependencies, list):
            for item in dependencies:
                if not isinstance(item, str):
                    continue
                name = item.split("[", 1)[0].split(" ", 1)[0].split(">=", 1)[0].split("==", 1)[0].strip()
                output.append(DependencyHint(name=name, version=normalize_version(item), ecosystem="python", source_file=path.name))
    poetry = payload.get("tool", {}).get("poetry", {}) if isinstance(payload.get("tool"), dict) else {}
    dependencies = poetry.get("dependencies") if isinstance(poetry, dict) else None
    if isinstance(dependencies, dict):
        for name, version in dependencies.items():
            if name == "python":
                continue
            output.append(DependencyHint(name=str(name), version=normalize_version(str(version)), ecosystem="python", source_file=path.name))
    return output


def _parse_cargo_toml(path: Path) -> list[DependencyHint]:
    if not path.exists():
        return []
    try:
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return []
    dependencies = payload.get("dependencies")
    if not isinstance(dependencies, dict):
        return []
    output: list[DependencyHint] = []
    for name, version in dependencies.items():
        if isinstance(version, dict):
            output.append(DependencyHint(name=str(name), version=normalize_version(str(version.get("version", ""))), ecosystem="rust", source_file=path.name))
        else:
            output.append(DependencyHint(name=str(name), version=normalize_version(str(version)), ecosystem="rust", source_file=path.name))
    return output


def _parse_go_mod(path: Path) -> list[DependencyHint]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    output: list[DependencyHint] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith(("module ", "go ", "replace ")):
            continue
        if stripped.startswith("require "):
            stripped = stripped[len("require "):].strip("() ")
        parts = stripped.split()
        if len(parts) >= 2 and "." in parts[0]:
            output.append(DependencyHint(name=parts[0], version=normalize_version(parts[1]), ecosystem="go", source_file=path.name))
    return output


def normalize_version(value: str) -> str:
    match = DEPENDENCY_VERSION_RE.search(value)
    return match.group(1) if match else value.strip().strip("^~>=< ")
