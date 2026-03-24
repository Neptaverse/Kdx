from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class SymbolRecord:
    name: str
    kind: str
    line_start: int
    line_end: int

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SymbolRecord":
        return cls(
            name=str(data.get("name", "")),
            kind=str(data.get("kind", "symbol")),
            line_start=int(data.get("line_start", 1)),
            line_end=int(data.get("line_end", 1)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class FileRecord:
    path: str
    language: str
    size_bytes: int
    sha1: str
    mtime_ns: int
    role: str = "source"
    is_test: bool = False
    summary: str = ""
    imports: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    symbols: list[SymbolRecord] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FileRecord":
        return cls(
            path=str(data.get("path", "")),
            language=str(data.get("language", "unknown")),
            size_bytes=int(data.get("size_bytes", 0)),
            sha1=str(data.get("sha1", "")),
            mtime_ns=int(data.get("mtime_ns", 0)),
            role=str(data.get("role", "source")),
            is_test=bool(data.get("is_test", False)),
            summary=str(data.get("summary", "")),
            imports=[str(item) for item in data.get("imports", [])],
            keywords=[str(item) for item in data.get("keywords", [])],
            symbols=[SymbolRecord.from_dict(item) for item in data.get("symbols", [])],
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["symbols"] = [symbol.to_dict() for symbol in self.symbols]
        return payload


@dataclass(slots=True)
class ProjectIndex:
    version: int
    root: str
    generated_at: str
    file_count: int
    files: list[FileRecord] = field(default_factory=list)

    @classmethod
    def empty(cls, root: str) -> "ProjectIndex":
        return cls(version=4, root=root, generated_at="", file_count=0, files=[])

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProjectIndex":
        return cls(
            version=int(data.get("version", 1)),
            root=str(data.get("root", "")),
            generated_at=str(data.get("generated_at", "")),
            file_count=int(data.get("file_count", 0)),
            files=[FileRecord.from_dict(item) for item in data.get("files", [])],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "root": self.root,
            "generated_at": self.generated_at,
            "file_count": self.file_count,
            "files": [item.to_dict() for item in self.files],
        }


@dataclass(slots=True)
class RetrievedSnippet:
    path: str
    score: float
    reason: str
    content: str
    symbol: str = ""
    line_start: int = 1
    line_end: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class QueryRoute:
    mode: str
    needs_web: bool
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class HistoryEntry:
    created_at: str
    query: str
    route: str
    files: list[str] = field(default_factory=list)
    search_queries: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HistoryEntry":
        return cls(
            created_at=str(data.get("created_at", "")),
            query=str(data.get("query", "")),
            route=str(data.get("route", "unknown")),
            files=[str(item) for item in data.get("files", [])],
            search_queries=[str(item) for item in data.get("search_queries", [])],
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
