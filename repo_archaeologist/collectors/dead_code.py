"""Detect unreferenced Python modules and JS files.

A module is considered "referenced" if some other source file imports or requires
it. This is a best-effort static heuristic — it does not execute code, so dynamic
imports (``importlib.import_module`` with string literals are still caught), entry
points, and test files are treated as always-referenced to reduce false positives.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Set

from repo_archaeologist.collectors.structure import SKIP_DIRS, _is_source


@dataclass
class DeadModule:
    """A source module that appears to never be imported or required."""

    relpath: str  # repo-relative path
    language: str  # "Python" or "JavaScript"


@dataclass
class DeadCodeReport:
    modules: List[DeadModule] = field(default_factory=list)
    total_modules: int = 0  # number of candidate modules considered
    referenced: Set[str] = field(default_factory=set)  # module dotted paths seen referenced

    @property
    def count(self) -> int:
        return len(self.modules)


# --- Python -------------------------------------------------------------

# import foo / import foo.bar / import foo as baz
_PY_IMPORT_RE = re.compile(r"^\s*import\s+([\w.]+)", re.MULTILINE)
# from foo import x / from foo.bar import x as y / from . import x / from .foo import x
_PY_FROM_IMPORT_RE = re.compile(r"^\s*from\s+([\w.]+)\s+import", re.MULTILINE)
# importlib.import_module("foo.bar")
_PY_IMPORTLIB_RE = re.compile(r'import_module\s*\(\s*["\']([\w.]+)["\']', re.MULTILINE)


def _py_module_dotted(rel: str) -> str:
    """Convert a repo-relative .py path to a dotted module path.

    ``pkg/sub/mod.py`` -> ``pkg.sub.mod``
    ``pkg/sub/__init__.py`` -> ``pkg.sub``
    """
    parts = rel.split(os.sep)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1][:-3]  # strip .py
    return ".".join(parts)


def _collect_py_references(text: str) -> Set[str]:
    refs: Set[str] = set()
    for m in _PY_IMPORT_RE.finditer(text):
        refs.add(m.group(1))
    for m in _PY_FROM_IMPORT_RE.finditer(text):
        target = m.group(1)
        # relative imports ("from . import x") start with a dot; record the root
        # absolute path only when it has a name. Relative refs are handled by
        # also treating sibling modules as referenced.
        if target and target != ".":
            refs.add(target.lstrip("."))
        # `from pkg import mod` may import submodule pkg.mod — record that too.
        # We capture the imported names and combine with the package below.
    # `from pkg import mod, other` -> also mark pkg.mod, pkg.other as referenced.
    for m in re.finditer(r"^\s*from\s+([\w.]+)\s+import\s+([^\n]+)", text, re.MULTILINE):
        target = m.group(1).lstrip(".")
        # Strip trailing comments and parens; split on commas.
        raw_names = m.group(2).split("#", 1)[0].replace("(", "").replace(")", "")
        for piece in raw_names.split(","):
            n = piece.strip()
            # only accept simple identifiers (skip "x as y" -> take x)
            n = n.split(" as ")[0].strip()
            if n and n != "*" and re.match(r"^[A-Za-z_]\w*$", n):
                refs.add(f"{target}.{n}")
    for m in _PY_IMPORTLIB_RE.finditer(text):
        refs.add(m.group(1))
    return refs


# --- JavaScript ---------------------------------------------------------

# require("./foo") / require("../foo/bar") / require("foo")
_JS_REQUIRE_RE = re.compile(r'require\s*\(\s*["\']([^"\']+)["\']', re.MULTILINE)
# import foo from "./foo" / import {x} from "./foo"
_JS_IMPORT_RE = re.compile(
    r'\bimport\s+(?:[\w*{}\s,]+\s+from\s+)?["\']([^"\']+)["\']', re.MULTILINE
)


def _resolve_js_spec(spec: str, rel_file: str) -> str:
    """Resolve a JS require/import spec to a repo-relative path (best-effort).

    Only relative specs (starting with ``./`` or ``../``) are resolvable without
    a node_modules lookup. Returns "" if not resolvable.
    """
    if not (spec.startswith("./") or spec.startswith("../")):
        return ""
    base_dir = os.path.dirname(rel_file)
    target = os.path.normpath(os.path.join(base_dir, spec))
    # try with extensions
    for ext in ("", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"):
        cand = target + ext
        if cand.startswith(".."):
            continue
        return cand
    return target


def _collect_js_references(text: str, rel_file: str) -> Set[str]:
    refs: Set[str] = set()
    for m in _JS_REQUIRE_RE.finditer(text):
        resolved = _resolve_js_spec(m.group(1), rel_file)
        if resolved:
            refs.add(resolved)
    for m in _JS_IMPORT_RE.finditer(text):
        resolved = _resolve_js_spec(m.group(1), rel_file)
        if resolved:
            refs.add(resolved)
    return refs


# --- Entry-point / test allowlist --------------------------------------

_PY_ENTRY_NAMES = {
    "main.py",
    "app.py",
    "run.py",
    "manage.py",
    "wsgi.py",
    "asgi.py",
    "__main__.py",
    "setup.py",
    "conftest.py",
}

_JS_ENTRY_NAMES = {
    "index.js",
    "index.ts",
    "server.js",
    "server.ts",
    "app.js",
    "app.ts",
    "main.js",
    "main.ts",
}


def _is_entry_or_test(rel: str) -> bool:
    low = rel.lower()
    name = os.path.basename(rel)
    if name in _PY_ENTRY_NAMES or name in _JS_ENTRY_NAMES:
        return True
    if name.startswith("test_") or name.endswith("_test.go"):
        return True
    if low.startswith("tests/") or low.startswith("test/"):
        return True
    if name.endswith(".test.js") or name.endswith(".test.ts"):
        return True
    if name.endswith(".spec.js") or name.endswith(".spec.ts"):
        return True
    if name == "__init__.py":
        # package markers are structural, not dead code
        return True
    return False


def collect(root: Path) -> DeadCodeReport:
    """Walk the repo and return unreferenced Python/JS modules."""
    root = root.resolve()
    report = DeadCodeReport()

    if not root.is_dir():
        return report

    py_files: List[str] = []
    js_files: List[str] = []
    py_refs: Set[str] = set()
    js_refs: Set[str] = set()

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".git"))
        for fname in filenames:
            fpath = Path(dirpath) / fname
            if not _is_source(fpath):
                continue
            rel = str(fpath.relative_to(root))
            ext = fpath.suffix.lower()
            try:
                text = fpath.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            if ext == ".py":
                py_files.append(rel)
                py_refs |= _collect_py_references(text)
            elif ext in (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"):
                js_files.append(rel)
                js_refs |= _collect_js_references(text, rel)

    # Build the set of referenced dotted py modules, expanding prefixes so that
    # `import foo.bar` marks both `foo` and `foo.bar` as referenced.
    py_ref_modules: Set[str] = set()
    for ref in py_refs:
        parts = ref.split(".")
        for i in range(1, len(parts) + 1):
            py_ref_modules.add(".".join(parts[:i]))

    # Resolve JS refs to actual candidate file paths (with extensions).
    js_ref_paths: Set[str] = set()
    for ref in js_refs:
        js_ref_paths.add(ref)
        for ext in (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"):
            js_ref_paths.add(ref + ext)
        # index files inside a referenced directory
        js_ref_paths.add(ref + "/index.js")
        js_ref_paths.add(ref + "/index.ts")

    candidates = 0
    for rel in py_files:
        if _is_entry_or_test(rel):
            continue
        candidates += 1
        dotted = _py_module_dotted(rel)
        # referenced if the module or any ancestor package is imported
        if dotted in py_ref_modules:
            continue
        # also check ancestor: `import pkg` references `pkg/mod.py` implicitly? No —
        # that only references the package, not the submodule. Keep conservative.
        report.modules.append(DeadModule(relpath=rel, language="Python"))

    for rel in js_files:
        if _is_entry_or_test(rel):
            continue
        candidates += 1
        if rel in js_ref_paths:
            continue
        report.modules.append(DeadModule(relpath=rel, language="JavaScript"))

    report.total_modules = candidates
    report.referenced = py_ref_modules | js_ref_paths
    # sort for stable output
    report.modules.sort(key=lambda m: (m.language, m.relpath))
    return report
