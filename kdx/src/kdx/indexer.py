from __future__ import annotations

import ast
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from kdx.models import FileRecord, ProjectIndex, SymbolRecord

INDEX_VERSION = 4

SKIP_DIRS = {
    ".git",
    ".kdx",
    ".bench",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "target",
    "coverage",
    ".next",
    ".turbo",
    "__pycache__",
}
SUPPORTED_EXTENSIONS = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".rs",
    ".go",
    ".java",
    ".kt",
    ".rb",
    ".php",
    ".c",
    ".cc",
    ".cpp",
    ".h",
    ".hpp",
    ".cs",
    ".scala",
    ".md",
    ".toml",
    ".yaml",
    ".yml",
    ".json",
    ".sh",
}
MAX_FILE_BYTES = 512_000
WORD_RE = re.compile(r"[A-Za-z0-9]+")
JS_TS_SYMBOL_PATTERNS = [
    ("class", re.compile(r"^\s*export\s+class\s+([A-Za-z_][A-Za-z0-9_]*)|^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)),
    ("function", re.compile(r"^\s*export\s+async\s+function\s+([A-Za-z_][A-Za-z0-9_]*)|^\s*export\s+function\s+([A-Za-z_][A-Za-z0-9_]*)|^\s*async\s+function\s+([A-Za-z_][A-Za-z0-9_]*)|^\s*function\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)),
    ("const", re.compile(r"^\s*(?:export\s+)?const\s+([A-Za-z_][A-Za-z0-9_]*)\s*=", re.MULTILINE)),
    ("interface", re.compile(r"^\s*export\s+interface\s+([A-Za-z_][A-Za-z0-9_]*)|^\s*interface\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)),
    ("type", re.compile(r"^\s*export\s+type\s+([A-Za-z_][A-Za-z0-9_]*)|^\s*type\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)),
]
RUST_SYMBOL_PATTERNS = [
    ("function", re.compile(r"^\s*(?:pub\s+)?fn\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)),
    ("struct", re.compile(r"^\s*(?:pub\s+)?struct\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)),
    ("enum", re.compile(r"^\s*(?:pub\s+)?enum\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)),
    ("trait", re.compile(r"^\s*(?:pub\s+)?trait\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)),
    ("impl", re.compile(r"^\s*impl(?:<[^>]+>)?\s+([A-Za-z_][A-Za-z0-9_:]*)", re.MULTILINE)),
]
GO_SYMBOL_PATTERNS = [
    ("function", re.compile(r"^\s*func\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)),
    ("type", re.compile(r"^\s*type\s+([A-Za-z_][A-Za-z0-9_]*)\s+", re.MULTILINE)),
]
GENERIC_IMPORT_PATTERNS = [
    re.compile(r"^\s*import\s+.+?from\s+[\"']([^\"']+)[\"']", re.MULTILINE),
    re.compile(r"^\s*import\s+[\"']([^\"']+)[\"']", re.MULTILINE),
    re.compile(r"^\s*from\s+([A-Za-z0-9_\.]+)\s+import\s+", re.MULTILINE),
    re.compile(r"^\s*use\s+([A-Za-z0-9_:]+)", re.MULTILINE),
    re.compile(r"require\([\"']([^\"']+)[\"']\)"),
]


def infer_language(path: Path) -> str:
    mapping = {
        ".py": "python",
        ".ts": "typescript",
        ".tsx": "tsx",
        ".js": "javascript",
        ".jsx": "jsx",
        ".rs": "rust",
        ".go": "go",
        ".java": "java",
        ".kt": "kotlin",
        ".rb": "ruby",
        ".php": "php",
        ".c": "c",
        ".cc": "cpp",
        ".cpp": "cpp",
        ".h": "c-header",
        ".hpp": "cpp-header",
        ".cs": "csharp",
        ".scala": "scala",
        ".md": "markdown",
        ".toml": "toml",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".json": "json",
        ".sh": "shell",
    }
    return mapping.get(path.suffix.lower(), "unknown")


def tokenize(text: str) -> list[str]:
    if not text:
        return []
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    normalized = re.sub(r"[_./:\\-]+", " ", normalized)
    return [token.lower() for token in WORD_RE.findall(normalized)]


def _is_test_path(rel_path: str) -> bool:
    low = rel_path.lower()
    return any(marker in low for marker in ("/test", "/tests", "_test.", ".spec.", ".test."))


def classify_file_role(rel_path: str, language: str) -> str:
    low = rel_path.lower()
    if _is_test_path(rel_path):
        return "test"
    if low.startswith("bench/") or "/bench/" in low or low.startswith("benchmarks/") or "/benchmarks/" in low:
        return "bench"
    if language == "markdown" or low.endswith(("readme.md", "changelog.md")) or "/docs/" in low:
        return "docs"
    if language in {"json", "toml", "yaml"} or low.endswith((".env", ".ini", ".cfg", ".conf")):
        return "config"
    if language == "shell" or low.startswith(("scripts/", "bin/")):
        return "script"
    return "source"


def _keyword_set(rel_path: str, text: str, symbols: list[SymbolRecord], imports: list[str]) -> list[str]:
    items = set(tokenize(rel_path))
    items.update(tokenize(" ".join(imports[:20])))
    for symbol in symbols[:40]:
        items.update(tokenize(symbol.name))
    head = "\n".join(text.splitlines()[:40])
    items.update(tokenize(head))
    stop = {
        "the", "and", "for", "with", "from", "this", "that", "true", "false", "null", "none",
        "const", "class", "function", "return", "async", "await", "import", "export", "public", "private",
    }
    return sorted(token for token in items if len(token) >= 3 and token not in stop)[:200]


class _PySymbolVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.symbols: list[SymbolRecord] = []
        self.imports: list[str] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.symbols.append(SymbolRecord(node.name, "class", node.lineno, getattr(node, "end_lineno", node.lineno)))
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.symbols.append(SymbolRecord(node.name, "function", node.lineno, getattr(node, "end_lineno", node.lineno)))
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.symbols.append(SymbolRecord(node.name, "async-function", node.lineno, getattr(node, "end_lineno", node.lineno)))
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        self.imports.extend(alias.name for alias in node.names)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        if module:
            self.imports.append(module)


def _line_from_index(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def _extract_symbols_regex(text: str, patterns: list[tuple[str, re.Pattern[str]]]) -> list[SymbolRecord]:
    symbols: list[SymbolRecord] = []
    seen: set[tuple[str, int]] = set()
    for kind, pattern in patterns:
        for match in pattern.finditer(text):
            groups = [group for group in match.groups() if group]
            if not groups:
                continue
            name = groups[0]
            line = _line_from_index(text, match.start())
            key = (name, line)
            if key in seen:
                continue
            seen.add(key)
            symbols.append(SymbolRecord(name=name, kind=kind, line_start=line, line_end=line))
    return sorted(symbols, key=lambda item: (item.line_start, item.name))


def _extract_imports_regex(text: str) -> list[str]:
    found: set[str] = set()
    for pattern in GENERIC_IMPORT_PATTERNS:
        found.update(match.group(1) for match in pattern.finditer(text) if match.group(1))
    return sorted(found)[:80]


def extract_symbols(language: str, text: str) -> tuple[list[SymbolRecord], list[str]]:
    if language == "python":
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return [], []
        visitor = _PySymbolVisitor()
        visitor.visit(tree)
        return visitor.symbols[:200], sorted(set(visitor.imports))[:80]
    if language in {"typescript", "tsx", "javascript", "jsx"}:
        return _extract_symbols_regex(text, JS_TS_SYMBOL_PATTERNS)[:200], _extract_imports_regex(text)
    if language == "rust":
        return _extract_symbols_regex(text, RUST_SYMBOL_PATTERNS)[:200], _extract_imports_regex(text)
    if language == "go":
        return _extract_symbols_regex(text, GO_SYMBOL_PATTERNS)[:200], _extract_imports_regex(text)
    return [], _extract_imports_regex(text)


def _build_summary(rel_path: str, language: str, role: str, symbols: list[SymbolRecord], imports: list[str]) -> str:
    symbol_part = ", ".join(f"{item.kind}:{item.name}" for item in symbols[:6]) or "no major symbols"
    import_part = ", ".join(imports[:4]) or "no notable imports"
    return f"{language} {role} file; symbols: {symbol_part}; imports: {import_part}"


def _iter_source_files(root: Path) -> Iterable[Path]:
    for current_root, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in SKIP_DIRS]
        base = Path(current_root)
        for filename in filenames:
            path = base / filename
            if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            if stat.st_size <= 0 or stat.st_size > MAX_FILE_BYTES:
                continue
            yield path


def _file_record(root: Path, path: Path, previous: dict[str, FileRecord]) -> FileRecord | None:
    rel_path = path.relative_to(root).as_posix()
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in raw:
        return None
    sha1 = hashlib.sha1(raw).hexdigest()
    stat = path.stat()
    old = previous.get(rel_path)
    if old and old.sha1 == sha1 and old.mtime_ns == stat.st_mtime_ns:
        return old
    text = raw.decode("utf-8", errors="ignore")
    language = infer_language(path)
    symbols, imports = extract_symbols(language, text)
    role = classify_file_role(rel_path, language)
    summary = _build_summary(rel_path, language, role, symbols, imports)
    return FileRecord(
        path=rel_path,
        language=language,
        size_bytes=stat.st_size,
        sha1=sha1,
        mtime_ns=stat.st_mtime_ns,
        role=role,
        is_test=role == "test",
        summary=summary,
        imports=imports,
        keywords=_keyword_set(rel_path, text, symbols, imports),
        symbols=symbols,
    )


def load_index(index_path: Path) -> ProjectIndex:
    if not index_path.exists():
        return ProjectIndex.empty(root="")
    return ProjectIndex.from_dict(json.loads(index_path.read_text(encoding="utf-8")))


def save_index(index_path: Path, index: ProjectIndex) -> None:
    index_path.write_text(json.dumps(index.to_dict(), indent=2, sort_keys=True), encoding="utf-8")


def scan_project(root: Path, index_path: Path) -> ProjectIndex:
    previous_index = load_index(index_path)
    previous = {file.path: file for file in previous_index.files} if previous_index.version == INDEX_VERSION else {}
    records: list[FileRecord] = []
    for path in sorted(_iter_source_files(root)):
        record = _file_record(root, path, previous)
        if record is not None:
            records.append(record)
    index = ProjectIndex(
        version=INDEX_VERSION,
        root=str(root),
        generated_at=datetime.now(timezone.utc).isoformat(),
        file_count=len(records),
        files=records,
    )
    save_index(index_path, index)
    return index


def index_is_stale(root: Path, index: ProjectIndex) -> bool:
    indexed = {record.path: record for record in index.files}
    seen: set[str] = set()
    for path in _iter_source_files(root):
        rel_path = path.relative_to(root).as_posix()
        seen.add(rel_path)
        record = indexed.get(rel_path)
        if record is None:
            return True
        try:
            stat = path.stat()
        except OSError:
            return True
        if stat.st_mtime_ns != record.mtime_ns or stat.st_size != record.size_bytes:
            return True
    return seen != set(indexed)


def ensure_project_index(root: Path, index_path: Path) -> ProjectIndex:
    index = load_index(index_path)
    if not index.files:
        return scan_project(root, index_path)
    if index.version != INDEX_VERSION:
        return scan_project(root, index_path)
    if index.root and index.root != str(root):
        return scan_project(root, index_path)
    if index_is_stale(root, index):
        return scan_project(root, index_path)
    return index
