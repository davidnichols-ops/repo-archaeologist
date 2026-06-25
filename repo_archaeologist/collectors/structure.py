"""Collect structural facts about a repository: languages, LOC, entry points, tree."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

# Directories we never descend into. These are noise for architecture analysis.
SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "venv",
    ".venv",
    "env",
    "dist",
    "build",
    "target",
    "__pycache__",
    ".next",
    ".cache",
    ".pytest_cache",
    "vendor",
    ".idea",
    ".vscode",
    "site-packages",
    ".mypy_cache",
    ".ruff_cache",
    "coverage",
    ".coverage",
    "htmlcov",
}

# Extension -> language name. Keep conservative; unknown extensions are ignored.
EXT_LANG = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".go": "Go",
    ".rs": "Rust",
    ".rb": "Ruby",
    ".java": "Java",
    ".kt": "Kotlin",
    ".swift": "Swift",
    ".c": "C",
    ".h": "C",
    ".cpp": "C++",
    ".cc": "C++",
    ".hpp": "C++",
    ".cs": "C#",
    ".php": "PHP",
    ".scala": "Scala",
    ".sh": "Shell",
    ".bash": "Shell",
    ".zsh": "Shell",
    ".lua": "Lua",
    ".r": "R",
    ".sql": "SQL",
    ".html": "HTML",
    ".css": "CSS",
    ".scss": "CSS",
    ".less": "CSS",
    ".vue": "Vue",
    ".svelte": "Svelte",
    ".dart": "Dart",
    ".elixir": "Elixir",
    ".ex": "Elixir",
    ".exs": "Elixir",
    ".clj": "Clojure",
    ".erl": "Erlang",
    ".hs": "Haskell",
    ".ml": "OCaml",
    ".nim": "Nim",
    ".pl": "Perl",
    ".pm": "Perl",
}

# Files that are almost always source even without a known extension (by exact name).
SOURCE_BASENAMES = {
    "Makefile",
    "Dockerfile",
    "Justfile",
    "Rakefile",
    "Gemfile",
    "Procfile",
    "WORKSPACE",
    "BUILD",
    "BUILD.bazel",
}


@dataclass
class Structure:
    root: Path
    languages: Dict[str, int] = field(default_factory=dict)  # lang -> LOC
    file_count: int = 0
    source_file_count: int = 0
    top_level_dirs: List[str] = field(default_factory=list)
    top_level_files: List[str] = field(default_factory=list)
    entry_points: List[str] = field(default_factory=list)  # repo-relative paths
    has_tests: bool = False
    has_readme: bool = False
    has_license: bool = False
    has_ci: bool = False
    has_dockerfile: bool = False
    has_lockfile: bool = False
    largest_source_files: List[tuple] = field(default_factory=list)  # (relpath, loc)
    dir_module_counts: Dict[str, int] = field(default_factory=dict)  # dir -> source file count

    @property
    def total_loc(self) -> int:
        return sum(self.languages.values())

    @property
    def primary_language(self) -> Optional[str]:
        if not self.languages:
            return None
        return max(self.languages.items(), key=lambda kv: kv[1])[0]


def _is_source(path: Path) -> bool:
    if path.suffix.lower() in EXT_LANG:
        return True
    return path.name in SOURCE_BASENAMES


def _count_loc(path: Path) -> int:
    """Count non-blank lines. Binary-safe: decode utf-8 with errors ignored."""
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as fh:
            loc = 0
            for line in fh:
                if line.strip():
                    loc += 1
            return loc
    except (OSError, UnicodeError):
        return 0


def _detect_entry_points(root: Path, source_files: List[Path]) -> List[str]:
    """Find likely entry points. Returns repo-relative paths, ordered by likelihood."""
    entries: List[str] = []
    seen = set()

    def add(rel: str) -> None:
        if rel not in seen:
            seen.add(rel)
            entries.append(rel)

    # Python: main.py at root or in src/, app.py, run.py, manage.py, wsgi.py, asgi.py
    py_candidates = ["main.py", "app.py", "run.py", "manage.py", "wsgi.py", "asgi.py", "__main__.py"]
    for rel_dir in ["", "src", "app", "server"]:
        for name in py_candidates:
            cand = root / rel_dir / name
            if cand.exists():
                add(str(cand.relative_to(root)))

    # Python: [project.scripts] in pyproject.toml -> resolve the module to a file
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        try:
            text = pyproject.read_text(encoding="utf-8", errors="ignore")
            # find [project.scripts] block
            idx = text.find("[project.scripts]")
            if idx >= 0:
                block = text[idx:]
                end = block.find("\n[")
                if end >= 0:
                    block = block[:end]
                # lines like: name = "pkg.module:func"
                for m in re.finditer(r'^[\w-]+\s*=\s*"([\w.]+)(?::[\w.]+)?"', block, re.MULTILINE):
                    module_path = m.group(1)
                    # pkg.mod -> pkg/mod.py or pkg/mod/__init__.py
                    rel = module_path.replace(".", os.sep)
                    for cand in [root / (rel + ".py"), root / rel / "__init__.py"]:
                        if cand.exists():
                            add(str(cand.relative_to(root)))
                            break
        except OSError:
            pass

    # JS/TS: package.json "main"/"bin", index.js, server.js, app.js, src/index.ts
    pkg = root / "package.json"
    if pkg.exists():
        try:
            import json

            data = json.loads(pkg.read_text(encoding="utf-8", errors="ignore"))
            main = data.get("main")
            if main:
                cand = root / main
                if cand.exists():
                    add(str(cand.relative_to(root)))
            bins = data.get("bin")
            if isinstance(bins, str):
                cand = root / bins
                if cand.exists():
                    add(str(cand.relative_to(root)))
            elif isinstance(bins, dict):
                for b in list(bins.values())[:2]:
                    cand = root / b
                    if cand.exists():
                        add(str(cand.relative_to(root)))
        except (json.JSONDecodeError, OSError):
            pass

    for rel_dir in ["", "src", "server", "app"]:
        for name in ["index.js", "index.ts", "server.js", "server.ts", "app.js", "app.ts"]:
            cand = root / rel_dir / name
            if cand.exists():
                add(str(cand.relative_to(root)))

    # Go: cmd/*/main.go or main.go at root
    go_main = root / "main.go"
    if go_main.exists():
        add("main.go")
    cmd_dir = root / "cmd"
    if cmd_dir.is_dir():
        for sub in sorted(cmd_dir.iterdir()):
            mg = sub / "main.go"
            if mg.exists():
                add(str(mg.relative_to(root)))

    # Rust: src/main.rs
    rs_main = root / "src" / "main.rs"
    if rs_main.exists():
        add("src/main.rs")

    # Ruby: config.ru, Rakefile, bin/* (first executable)
    ru = root / "config.ru"
    if ru.exists():
        add("config.ru")
    bin_dir = root / "bin"
    if bin_dir.is_dir():
        for f in sorted(bin_dir.iterdir())[:2]:
            if f.is_file():
                add(str(f.relative_to(root)))

    # Fallback: largest source file of the primary language if nothing found.
    # Exclude test files — they are never an entry point.
    if not entries and source_files:
        def _is_test(p: Path) -> bool:
            low = str(p.relative_to(root)).lower()
            return (
                "test" in low
                or p.name.startswith("test_")
                or p.name.endswith("_test.go")
                or p.name.endswith(".test.js")
                or p.name.endswith(".test.ts")
                or p.name.endswith(".spec.js")
                or p.name.endswith(".spec.ts")
            )

        candidates = [
            p for p in source_files
            if p.suffix in {".py", ".js", ".ts", ".go", ".rs"} and not _is_test(p)
        ]
        if candidates:
            candidates.sort(key=lambda p: (len(p.parts), -p.stat().st_size))
            add(str(candidates[0].relative_to(root)))

    return entries


def collect(root: Path) -> Structure:
    """Walk the tree and collect structural facts."""
    root = root.resolve()
    struct = Structure(root=root)

    if not root.is_dir():
        return struct

    # Top-level entries
    for entry in sorted(root.iterdir()):
        if entry.name in SKIP_DIRS or entry.name.startswith(".git"):
            continue
        if entry.is_dir():
            struct.top_level_dirs.append(entry.name)
        else:
            struct.top_level_files.append(entry.name)

    # Sentinel files
    struct.has_readme = any(
        (root / n).exists() for n in ["README.md", "README.rst", "README", "readme.md"]
    )
    struct.has_license = any(
        (root / n).exists() for n in ["LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING"]
    )
    struct.has_ci = (root / ".github" / "workflows").is_dir() or (root / ".gitlab-ci.yml").exists()
    struct.has_dockerfile = (root / "Dockerfile").exists() or any(
        p.name.lower().startswith("dockerfile.") for p in root.iterdir() if p.is_file()
    )
    struct.has_lockfile = any(
        (root / n).exists()
        for n in [
            "package-lock.json",
            "yarn.lock",
            "pnpm-lock.yaml",
            "poetry.lock",
            "Pipfile.lock",
            "Cargo.lock",
            "go.sum",
            "Gemfile.lock",
            "uv.lock",
        ]
    )

    source_files: List[Path] = []
    largest: List[tuple] = []

    for dirpath, dirnames, filenames in os.walk(root):
        # Prune skip dirs in-place
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".git"))
        rel_dir = Path(dirpath).relative_to(root)

        for fname in filenames:
            fpath = Path(dirpath) / fname
            struct.file_count += 1

            if _is_source(fpath):
                struct.source_file_count += 1
                source_files.append(fpath)
                loc = _count_loc(fpath)
                lang = EXT_LANG.get(fpath.suffix.lower(), "Other")
                struct.languages[lang] = struct.languages.get(lang, 0) + loc

                rel = str(fpath.relative_to(root))
                largest.append((rel, loc))

                # Module count per top-level dir
                top = rel.split(os.sep, 1)[0]
                struct.dir_module_counts[top] = struct.dir_module_counts.get(top, 0) + 1

                # Tests detection
                low = rel.lower()
                if "test" in low or rel.startswith("tests") or fname.startswith("test_") or fname.endswith("_test.go") or fname.endswith(".test.js") or fname.endswith(".spec.js") or fname.endswith(".spec.ts"):
                    struct.has_tests = True

    # Top 10 largest source files
    largest.sort(key=lambda t: t[1], reverse=True)
    struct.largest_source_files = largest[:10]

    struct.entry_points = _detect_entry_points(root, source_files)
    return struct
