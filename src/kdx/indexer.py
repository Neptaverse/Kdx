from __future__ import annotations

import ast
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Iterable

from kdx.models import FileRecord, ProjectIndex, SymbolRecord

INDEX_VERSION = 5

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
GENERIC_IMPORT_PATTERNS = [
    re.compile(r"^\s*import\s+.+?from\s+[\"']([^\"']+)[\"']", re.MULTILINE),
    re.compile(r"^\s*import\s+[\"']([^\"']+)[\"']", re.MULTILINE),
    re.compile(r"^\s*from\s+([A-Za-z0-9_\.]+)\s+import\s+", re.MULTILINE),
    re.compile(r"^\s*use\s+([A-Za-z0-9_:]+)", re.MULTILINE),
    re.compile(r"require\([\"']([^\"']+)[\"']\)"),
]

# ── JS/TS ────────────────────────────────────────
JS_TS_SYMBOL_PATTERNS = [
    ("class", re.compile(r"^\s*(?:export\s+(?:default\s+)?)?class\s+([A-Za-z_$][A-Za-z0-9_$]*)", re.MULTILINE)),
    ("function", re.compile(r"^\s*(?:export\s+(?:default\s+)?)?(?:async\s+)?function\s+([A-Za-z_$][A-Za-z0-9_$]*)", re.MULTILINE)),
    ("arrow", re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*(?:async\s+)?(?:\([^)]*\)|[A-Za-z_$][A-Za-z0-9_$]*)\s*=>", re.MULTILINE)),
    ("component", re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Z][A-Za-z0-9_$]*)\s*[=:]\s*(?:React\.(?:memo|forwardRef|lazy)|styled)", re.MULTILINE)),
    ("hook", re.compile(r"^\s*(?:export\s+)?(?:const|let|var|(?:async\s+)?function)\s+(use[A-Z][A-Za-z0-9_$]*)", re.MULTILINE)),
    ("const", re.compile(r"^\s*(?:export\s+)?const\s+([A-Z][A-Z0-9_]{2,})\s*=", re.MULTILINE)),
    ("interface", re.compile(r"^\s*(?:export\s+)?interface\s+([A-Za-z_$][A-Za-z0-9_$]*)", re.MULTILINE)),
    ("type", re.compile(r"^\s*(?:export\s+)?type\s+([A-Za-z_$][A-Za-z0-9_$]*)", re.MULTILINE)),
    ("enum", re.compile(r"^\s*(?:export\s+)?(?:const\s+)?enum\s+([A-Za-z_$][A-Za-z0-9_$]*)", re.MULTILINE)),
]

# ── Rust ─────────────────────────────────────────
RUST_SYMBOL_PATTERNS = [
    ("function", re.compile(r"^\s*(?:pub(?:\([^)]+\))?\s+)?(?:async\s+)?(?:unsafe\s+)?fn\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)),
    ("struct", re.compile(r"^\s*(?:pub(?:\([^)]+\))?\s+)?struct\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)),
    ("enum", re.compile(r"^\s*(?:pub(?:\([^)]+\))?\s+)?enum\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)),
    ("trait", re.compile(r"^\s*(?:pub(?:\([^)]+\))?\s+)?trait\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)),
    ("impl", re.compile(r"^\s*impl(?:<[^>]+>)?\s+([A-Za-z_][A-Za-z0-9_:]*)", re.MULTILINE)),
    ("macro", re.compile(r"^\s*(?:#\[macro_export\]\s*\n)?\s*macro_rules!\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)),
    ("const", re.compile(r"^\s*(?:pub(?:\([^)]+\))?\s+)?const\s+([A-Z_][A-Z0-9_]*)\s*:", re.MULTILINE)),
    ("static", re.compile(r"^\s*(?:pub(?:\([^)]+\))?\s+)?static\s+(?:mut\s+)?([A-Z_][A-Z0-9_]*)\s*:", re.MULTILINE)),
]
RUST_DERIVE_RE = re.compile(r"#\[derive\(([^)]+)\)\]", re.MULTILINE)
RUST_VIS_RE = re.compile(r"^\s*(pub(?:\([^)]+\))?)", re.MULTILINE)

# ── Go ───────────────────────────────────────────
GO_SYMBOL_PATTERNS = [
    ("function", re.compile(r"^func\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", re.MULTILINE)),
    ("method", re.compile(r"^func\s+\([^)]+\)\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", re.MULTILINE)),
    ("type", re.compile(r"^type\s+([A-Za-z_][A-Za-z0-9_]*)\s+(?:struct|interface)\b", re.MULTILINE)),
    ("const", re.compile(r"^\s*([A-Z][A-Za-z0-9_]*)\s*(?:=|[A-Za-z])", re.MULTILINE)),
    ("var", re.compile(r"^var\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)),
]
GO_METHOD_RECEIVER_RE = re.compile(r"^func\s+\(\s*\w+\s+\*?([A-Za-z_][A-Za-z0-9_]*)\s*\)\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", re.MULTILINE)
GO_INTERFACE_RE = re.compile(r"^type\s+([A-Za-z_][A-Za-z0-9_]*)\s+interface\b", re.MULTILINE)

# ── Java ─────────────────────────────────────────
JAVA_SYMBOL_PATTERNS = [
    ("class", re.compile(r"^\s*(?:public|private|protected)?\s*(?:abstract|final|static)?\s*class\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)),
    ("interface", re.compile(r"^\s*(?:public|private|protected)?\s*interface\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)),
    ("enum", re.compile(r"^\s*(?:public|private|protected)?\s*enum\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)),
    ("method", re.compile(r"^\s*(?:public|private|protected)?\s*(?:static|final|abstract|synchronized)?\s*(?:<[^>]+>\s+)?(?:[A-Za-z_][A-Za-z0-9_<>\[\],\s]*?)\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", re.MULTILINE)),
    ("annotation", re.compile(r"^\s*@([A-Z][A-Za-z0-9_]*)(?:\([^)]*\))?", re.MULTILINE)),
]
JAVA_IMPORT_RE = re.compile(r"^\s*import\s+(?:static\s+)?([A-Za-z0-9_.]+)", re.MULTILINE)

# ── Kotlin ───────────────────────────────────────
KOTLIN_SYMBOL_PATTERNS = [
    ("class", re.compile(r"^\s*(?:(?:open|abstract|sealed|data|enum|inner|private|internal|public)\s+)*class\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)),
    ("object", re.compile(r"^\s*(?:(?:private|internal|public)\s+)*object\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)),
    ("function", re.compile(r"^\s*(?:(?:override|open|abstract|private|internal|public|suspend|inline)\s+)*fun\s+(?:<[^>]+>\s+)?([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)),
    ("property", re.compile(r"^\s*(?:(?:override|open|abstract|private|internal|public|const|lateinit)\s+)*(?:val|var)\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)),
    ("interface", re.compile(r"^\s*(?:(?:private|internal|public|sealed)\s+)*interface\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)),
]

# ── C/C++ ────────────────────────────────────────
C_CPP_SYMBOL_PATTERNS = [
    ("function", re.compile(r"^\s*(?:(?:static|inline|extern|virtual)?\s+)?(?:(?:unsigned|signed|const|volatile)?\s+)?(?:void|int|char|float|double|bool|auto|[A-Z][A-Za-z0-9_]*(?:<[^>]+>)?(?:\s*[*&])?)\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", re.MULTILINE)),
    ("class", re.compile(r"^\s*(?:template\s*<[^>]+>\s*)?class\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)),
    ("struct", re.compile(r"^\s*(?:typedef\s+)?struct\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)),
    ("enum", re.compile(r"^\s*(?:typedef\s+)?enum\s+(?:class\s+)?([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)),
    ("define", re.compile(r"^\s*#define\s+([A-Z_][A-Z0-9_]*)(?:\(|\s)", re.MULTILINE)),
    ("typedef", re.compile(r"^\s*typedef\s+.+?\s+([A-Za-z_][A-Za-z0-9_]*)\s*;", re.MULTILINE)),
    ("namespace", re.compile(r"^\s*namespace\s+([A-Za-z_][A-Za-z0-9_:]*)", re.MULTILINE)),
]
C_INCLUDE_RE = re.compile(r'^\s*#include\s+["<]([^">\']+)[">\':]', re.MULTILINE)

# ── C# ───────────────────────────────────────────
CSHARP_SYMBOL_PATTERNS = [
    ("class", re.compile(r"^\s*(?:public|private|protected|internal)?\s*(?:static|abstract|sealed|partial)?\s*class\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)),
    ("interface", re.compile(r"^\s*(?:public|private|protected|internal)?\s*interface\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)),
    ("struct", re.compile(r"^\s*(?:public|private|protected|internal)?\s*(?:readonly\s+)?struct\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)),
    ("enum", re.compile(r"^\s*(?:public|private|protected|internal)?\s*enum\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)),
    ("method", re.compile(r"^\s*(?:public|private|protected|internal)?\s*(?:static|virtual|override|abstract|async)?\s*(?:[A-Za-z_][A-Za-z0-9_<>\[\],\s]*?)\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", re.MULTILINE)),
]
CSHARP_USING_RE = re.compile(r"^\s*using\s+(?:static\s+)?([A-Za-z0-9_.]+)\s*;", re.MULTILINE)

# ── Ruby ─────────────────────────────────────────
RUBY_SYMBOL_PATTERNS = [
    ("class", re.compile(r"^\s*class\s+([A-Z][A-Za-z0-9_]*)", re.MULTILINE)),
    ("module", re.compile(r"^\s*module\s+([A-Z][A-Za-z0-9_]*)", re.MULTILINE)),
    ("function", re.compile(r"^\s*def\s+((?:self\.)?[A-Za-z_][A-Za-z0-9_!?]*)", re.MULTILINE)),
    ("attr", re.compile(r"^\s*attr_(?:accessor|reader|writer)\s+:([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)),
]
RUBY_REQUIRE_RE = re.compile(r"require(?:_relative)?\s+[\"']([^\"']+)[\"']", re.MULTILINE)
RUBY_BASES_RE = re.compile(r"^\s*class\s+[A-Z][A-Za-z0-9_]*\s*<\s*([A-Z][A-Za-z0-9_:]*)", re.MULTILINE)

# ── PHP ──────────────────────────────────────────
PHP_SYMBOL_PATTERNS = [
    ("class", re.compile(r"^\s*(?:abstract\s+|final\s+)?class\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)),
    ("interface", re.compile(r"^\s*interface\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)),
    ("trait", re.compile(r"^\s*trait\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)),
    ("function", re.compile(r"^\s*(?:public|private|protected|static)?\s*function\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)),
    ("namespace", re.compile(r"^\s*namespace\s+([A-Za-z_][A-Za-z0-9_\\]*)", re.MULTILINE)),
]
PHP_USE_RE = re.compile(r"^\s*use\s+([A-Za-z_][A-Za-z0-9_\\]*)", re.MULTILINE)

# ── Semantic role detection patterns ─────────────
_ENTRY_PATTERNS = [
    re.compile(r'if\s+__name__\s*==\s*[\"\']__main__[\"\']'),
    re.compile(r'^func\s+main\s*\(', re.MULTILINE),
    re.compile(r'public\s+static\s+void\s+main\s*\(', re.MULTILINE),
]
_HANDLER_DECORATORS = {"route", "get", "post", "put", "delete", "patch", "api_view", "app.route", "router.get", "router.post", "RequestMapping", "GetMapping", "PostMapping"}
_MIDDLEWARE_MARKERS = {"middleware", "before_request", "after_request", "before_action", "after_action"}
_MODEL_MARKERS = {"Model", "Schema", "BaseModel", "DataClass", "dataclass", "Entity", "Table", "Column"}


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


def classify_file_role(rel_path: str, language: str, text: str = "") -> str:
    low = rel_path.lower()
    if _is_test_path(rel_path):
        return "test"
    if low.startswith("bench/") or "/bench/" in low or low.startswith("benchmarks/") or "/benchmarks/" in low:
        return "bench"
    if language == "markdown" or Path(low).name in ("readme.md", "changelog.md") or "/docs/" in low:
        return "docs"
    if language in {"json", "toml", "yaml"} or low.endswith((".env", ".ini", ".cfg", ".conf")):
        return "config"
    if language == "shell" or low.startswith(("scripts/", "bin/")):
        return "script"
    if text:
        for pattern in _ENTRY_PATTERNS:
            if pattern.search(text):
                return "entry"
        if any(marker in text for marker in _MIDDLEWARE_MARKERS):
            return "middleware"
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
        self._class_stack: list[str] = []

    def _decorator_names(self, node: ast.AST) -> list[str]:
        result: list[str] = []
        for dec in getattr(node, "decorator_list", []):
            if isinstance(dec, ast.Name):
                result.append(dec.id)
            elif isinstance(dec, ast.Attribute):
                parts: list[str] = []
                current: ast.AST = dec
                while isinstance(current, ast.Attribute):
                    parts.append(current.attr)
                    current = current.value
                if isinstance(current, ast.Name):
                    parts.append(current.id)
                result.append(".".join(reversed(parts)))
            elif isinstance(dec, ast.Call):
                func = dec.func
                if isinstance(func, ast.Name):
                    result.append(func.id)
                elif isinstance(func, ast.Attribute):
                    parts2: list[str] = []
                    cur2: ast.AST = func
                    while isinstance(cur2, ast.Attribute):
                        parts2.append(cur2.attr)
                        cur2 = cur2.value
                    if isinstance(cur2, ast.Name):
                        parts2.append(cur2.id)
                    result.append(".".join(reversed(parts2)))
        return result

    def _signature(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        args: list[str] = []
        for arg in node.args.args:
            name = arg.arg
            if name == "self" or name == "cls":
                continue
            annotation = ""
            if arg.annotation and isinstance(arg.annotation, ast.Name):
                annotation = f": {arg.annotation.id}"
            elif arg.annotation and isinstance(arg.annotation, ast.Constant):
                annotation = f": {arg.annotation.value}"
            args.append(f"{name}{annotation}")
        ret = ""
        if node.returns:
            if isinstance(node.returns, ast.Name):
                ret = f" -> {node.returns.id}"
            elif isinstance(node.returns, ast.Constant):
                ret = f" -> {node.returns.value}"
        return f"({', '.join(args)}){ret}"

    def _visibility(self, name: str) -> str:
        if name.startswith("__") and name.endswith("__"):
            return "dunder"
        if name.startswith("__"):
            return "private"
        if name.startswith("_"):
            return "internal"
        return "public"

    def _base_names(self, node: ast.ClassDef) -> list[str]:
        result: list[str] = []
        for base in node.bases:
            if isinstance(base, ast.Name):
                result.append(base.id)
            elif isinstance(base, ast.Attribute):
                result.append(base.attr)
        return result

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        docstring = ast.get_docstring(node) or ""
        self.symbols.append(SymbolRecord(
            name=node.name,
            kind="class",
            line_start=node.lineno,
            line_end=getattr(node, "end_lineno", node.lineno),
            decorators=self._decorator_names(node),
            bases=self._base_names(node),
            docstring=docstring.split("\n")[0][:120] if docstring else "",
            visibility=self._visibility(node.name),
            parent=self._class_stack[-1] if self._class_stack else "",
        ))
        self._class_stack.append(node.name)
        self.generic_visit(node)
        self._class_stack.pop()

    def _visit_func(self, node: ast.FunctionDef | ast.AsyncFunctionDef, kind: str) -> None:
        docstring = ast.get_docstring(node) or ""
        parent = self._class_stack[-1] if self._class_stack else ""
        decos = self._decorator_names(node)
        actual_kind = kind
        if parent:
            if "staticmethod" in decos:
                actual_kind = "staticmethod"
            elif "classmethod" in decos:
                actual_kind = "classmethod"
            elif "property" in decos:
                actual_kind = "property"
            else:
                actual_kind = "method"
        if any(d in _HANDLER_DECORATORS or d.split(".")[-1] in _HANDLER_DECORATORS for d in decos):
            actual_kind = "handler"
        self.symbols.append(SymbolRecord(
            name=node.name,
            kind=actual_kind,
            line_start=node.lineno,
            line_end=getattr(node, "end_lineno", node.lineno),
            signature=self._signature(node),
            decorators=decos,
            docstring=docstring.split("\n")[0][:120] if docstring else "",
            visibility=self._visibility(node.name),
            parent=parent,
        ))
        self._class_stack_copy = list(self._class_stack)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_func(node, "function")

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_func(node, "async-function")

    def visit_Import(self, node: ast.Import) -> None:
        self.imports.extend(alias.name for alias in node.names)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        if module:
            self.imports.append(module)


def _line_from_index(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def _extract_symbols_regex(
    text: str,
    patterns: list[tuple[str, re.Pattern[str]]],
    *,
    vis_extractor: re.Pattern[str] | None = None,
) -> list[SymbolRecord]:
    symbols: list[SymbolRecord] = []
    seen: set[tuple[str, int]] = set()
    lines = text.splitlines()
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
            vis = "public"
            if vis_extractor:
                vis_match = vis_extractor.match(match.group())
                if vis_match:
                    raw_vis = vis_match.group(1)
                    if "crate" in raw_vis:
                        vis = "crate"
                    elif "super" in raw_vis:
                        vis = "super"
                    elif "pub" in raw_vis:
                        vis = "public"
                    else:
                        vis = "internal"
                elif name.startswith("_"):
                    vis = "internal"
            elif name.startswith("_"):
                vis = "internal"
            # Extract line_end by looking for the next symbol or block end
            line_end = line
            for future_line_idx in range(line, min(line + 100, len(lines))):
                content = lines[future_line_idx] if future_line_idx < len(lines) else ""
                if future_line_idx > line and content and not content[0].isspace() and content.strip():
                    line_end = future_line_idx
                    break
            if line_end == line:
                line_end = min(line + 10, len(lines))
            symbols.append(SymbolRecord(
                name=name,
                kind=kind,
                line_start=line,
                line_end=line_end,
                visibility=vis,
            ))
    return sorted(symbols, key=lambda item: (item.line_start, item.name))


def _extract_imports_regex(text: str, extra_patterns: list[re.Pattern[str]] | None = None) -> list[str]:
    found: set[str] = set()
    all_patterns = list(GENERIC_IMPORT_PATTERNS)
    if extra_patterns:
        all_patterns.extend(extra_patterns)
    for pattern in all_patterns:
        found.update(match.group(1) for match in pattern.finditer(text) if match.group(1))
    return sorted(found)[:80]


def _extract_go_methods(text: str) -> list[SymbolRecord]:
    symbols: list[SymbolRecord] = []
    for match in GO_METHOD_RECEIVER_RE.finditer(text):
        receiver, name = match.group(1), match.group(2)
        line = _line_from_index(text, match.start())
        symbols.append(SymbolRecord(
            name=name,
            kind="method",
            line_start=line,
            line_end=line + 10,
            parent=receiver,
            visibility="public" if name[0].isupper() else "internal",
        ))
    return symbols


def _extract_rust_derives(text: str, symbols: list[SymbolRecord]) -> None:
    derive_locations: dict[int, list[str]] = {}
    for match in RUST_DERIVE_RE.finditer(text):
        line = _line_from_index(text, match.start())
        traits = [t.strip() for t in match.group(1).split(",")]
        derive_locations[line] = traits
    for symbol in symbols:
        if symbol.kind in ("struct", "enum"):
            for derive_line, traits in derive_locations.items():
                if derive_line <= symbol.line_start <= derive_line + 3:
                    symbol.decorators = traits
                    break


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
        symbols = _extract_symbols_regex(text, RUST_SYMBOL_PATTERNS, vis_extractor=RUST_VIS_RE)[:200]
        _extract_rust_derives(text, symbols)
        return symbols, _extract_imports_regex(text)
    if language == "go":
        symbols = _extract_symbols_regex(text, GO_SYMBOL_PATTERNS)[:200]
        methods = _extract_go_methods(text)
        all_go = sorted(symbols + methods, key=lambda s: (s.line_start, s.name))[:200]
        return all_go, _extract_imports_regex(text)
    if language == "java":
        return _extract_symbols_regex(text, JAVA_SYMBOL_PATTERNS)[:200], _extract_imports_regex(text, [JAVA_IMPORT_RE])
    if language == "kotlin":
        return _extract_symbols_regex(text, KOTLIN_SYMBOL_PATTERNS)[:200], _extract_imports_regex(text)
    if language in {"c", "cpp", "c-header", "cpp-header"}:
        return _extract_symbols_regex(text, C_CPP_SYMBOL_PATTERNS)[:200], _extract_imports_regex(text, [C_INCLUDE_RE])
    if language == "csharp":
        return _extract_symbols_regex(text, CSHARP_SYMBOL_PATTERNS)[:200], _extract_imports_regex(text, [CSHARP_USING_RE])
    if language == "ruby":
        return _extract_symbols_regex(text, RUBY_SYMBOL_PATTERNS)[:200], _extract_imports_regex(text, [RUBY_REQUIRE_RE])
    if language == "php":
        return _extract_symbols_regex(text, PHP_SYMBOL_PATTERNS)[:200], _extract_imports_regex(text, [PHP_USE_RE])
    return [], _extract_imports_regex(text)


def _build_summary(rel_path: str, language: str, role: str, symbols: list[SymbolRecord], imports: list[str]) -> str:
    symbol_part = ", ".join(f"{item.kind}:{item.name}" for item in symbols[:6]) or "no major symbols"
    import_part = ", ".join(imports[:4]) or "no notable imports"
    return f"{language} {role} file; symbols: {symbol_part}; imports: {import_part}"


def _iter_source_files(root: Path) -> Iterable[tuple[Path, os.stat_result]]:
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
            yield path, stat


def _file_record(root: Path, path: Path, stat: os.stat_result, previous: dict[str, FileRecord]) -> FileRecord | None:
    rel_path = path.relative_to(root).as_posix()
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in raw:
        return None
    sha = hashlib.sha256(raw).hexdigest()
    old = previous.get(rel_path)
    if old and old.sha1 == sha and old.mtime_ns == stat.st_mtime_ns:
        return old
    text = raw.decode("utf-8", errors="ignore")
    language = infer_language(path)
    symbols, imports = extract_symbols(language, text)
    role = classify_file_role(rel_path, language, text)
    summary = _build_summary(rel_path, language, role, symbols, imports)
    return FileRecord(
        path=rel_path,
        language=language,
        size_bytes=stat.st_size,
        sha1=sha,
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
    index_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(index.to_dict(), indent=2, sort_keys=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=index_path.parent, delete=False, suffix=".tmp") as handle:
        handle.write(serialized)
        temp_path = Path(handle.name)
    temp_path.replace(index_path)


def scan_project(root: Path, index_path: Path) -> ProjectIndex:
    previous_index = load_index(index_path)
    previous = {file.path: file for file in previous_index.files} if previous_index.version == INDEX_VERSION else {}
    records: list[FileRecord] = []
    any_changed = False
    for path, stat in sorted(_iter_source_files(root), key=lambda item: item[0]):
        record = _file_record(root, path, stat, previous)
        if record is not None:
            records.append(record)
            if record is not previous.get(record.path):
                any_changed = True
    if not any_changed and len(records) == len(previous):
        return previous_index
    build_dependency_graph(records)
    index = ProjectIndex(
        version=INDEX_VERSION,
        root=str(root),
        generated_at=datetime.now(timezone.utc).isoformat(),
        file_count=len(records),
        files=records,
    )
    save_index(index_path, index)
    return index


def build_dependency_graph(records: list[FileRecord]) -> None:
    path_index: dict[str, int] = {}
    stem_index: dict[str, list[int]] = {}
    for idx, record in enumerate(records):
        path_index[record.path] = idx
        stem = Path(record.path).stem.lower()
        stem_index.setdefault(stem, []).append(idx)
        without_ext = record.path.rsplit(".", 1)[0]
        path_index[without_ext] = idx
    importers: dict[int, set[int]] = {i: set() for i in range(len(records))}
    for src_idx, record in enumerate(records):
        for imp in record.imports:
            resolved = _resolve_import(imp, path_index, stem_index)
            if resolved is not None and resolved != src_idx:
                importers[resolved].add(src_idx)
    for idx, record in enumerate(records):
        direct = importers[idx]
        record.imported_by = sorted({records[i].path for i in direct})
        transitive: set[int] = set()
        for d in direct:
            transitive |= importers[d]
        transitive -= direct
        transitive.discard(idx)
        record.import_score = round(len(direct) + 0.5 * len(transitive), 1)


def _resolve_import(imp: str, path_index: dict[str, int], stem_index: dict[str, list[int]]) -> int | None:
    normalized = imp.replace(".", "/").replace("::", "/").replace("\\", "/")
    if normalized in path_index:
        return path_index[normalized]
    for suffix in ("/index", "/mod", "/__init__"):
        candidate = normalized + suffix
        if candidate in path_index:
            return path_index[candidate]
    stem = normalized.rsplit("/", 1)[-1].lower()
    matches = stem_index.get(stem, [])
    if len(matches) == 1:
        return matches[0]
    return None


def index_is_stale(root: Path, index: ProjectIndex) -> bool:
    indexed = {record.path: record for record in index.files}
    seen: set[str] = set()
    for path, _ in _iter_source_files(root):
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
