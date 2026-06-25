"""Collect dependencies from common manifest files across ecosystems."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Heuristic priority for "most important dependency": higher = more central to the project's purpose.
# Web frameworks and ORMs beat utilities because they tell you what the repo *is*.
IMPORTANCE_TIERS = {
    # tier 1: web frameworks / app servers — strongest signal of purpose
    "fastapi": 100, "flask": 100, "django": 100, "starlette": 95, "express": 100,
    "next": 95, "nuxt": 95, "react": 90, "vue": 90, "svelte": 90, "gin": 100,
    "echo": 95, "fiber": 95, "actix-web": 100, "axum": 100, "rocket": 100,
    "tornado": 90, "sanic": 90, "aiohttp": 85, "bottle": 85, "rails": 100,
    "sinatra": 90, "spring-boot": 100, "spring-web": 95, "laravel": 100,
    "aspnetcore": 100, "phoenix": 100, "plug": 90,
    # tier 2: data / ORM / ML — also purposeful
    "sqlalchemy": 80, "orm": 75, "prisma": 80, "sequelize": 75, "typeorm": 75,
    "mongoose": 75, "alembic": 70, "pymongo": 70, "redis": 70, "celery": 75,
    "kafka": 70, "pandas": 80, "numpy": 75, "scipy": 75, "scikit-learn": 85,
    "tensorflow": 90, "torch": 90, "pytorch": 90, "transformers": 85,
    "langchain": 85, "ollama": 80, "openai": 80, "anthropic": 80,
    # tier 3: CLI / tooling — moderate signal
    "click": 60, "typer": 60, "argparse": 40, "cobra": 65, "clap": 65,
    "inquirer": 55, "rich": 50, "prompt-toolkit": 50,
    # tier 4: everything else defaults to 10
}


@dataclass
class Dependency:
    name: str
    ecosystem: str  # "pypi", "npm", "go", "cargo", "gem"
    version_spec: str = ""


@dataclass
class DependencyReport:
    deps: List[Dependency] = field(default_factory=list)
    by_ecosystem: Dict[str, List[Dependency]] = field(default_factory=dict)
    primary_ecosystem: Optional[str] = None
    most_important: Optional[Dependency] = None

    @property
    def count(self) -> int:
        return len(self.deps)


def _normalize_pypi_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _parse_requirements(path: Path) -> List[Dependency]:
    deps: List[Dependency] = []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return deps
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-") or line.startswith("git+"):
            continue
        # strip environment markers and extras
        line = re.sub(r"\[.*?\]", "", line)
        line = re.sub(r";.*$", "", line)
        m = re.match(r"^([A-Za-z0-9_.-]+)\s*(.*)$", line)
        if m:
            name = m.group(1).strip()
            spec = m.group(2).strip()
            deps.append(Dependency(name=_normalize_pypi_name(name), ecosystem="pypi", version_spec=spec))
    return deps


def _parse_pyproject(path: Path) -> List[Dependency]:
    deps: List[Dependency] = []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return deps
    # Lightweight TOML parsing: extract [project] dependencies and [tool.poetry.dependencies]
    # Avoids a tomllib dependency for cross-version compat; we only need simple arrays.
    # Match: dependencies = [ "a", "b>=1.0", ... ]
    for section in (
        r"dependencies\s*=\s*\[(.*?)\]",
        r"dev-dependencies\s*=\s*\[(.*?)\]",
    ):
        for m in re.finditer(section, text, re.DOTALL):
            block = m.group(1)
            for sm in re.finditer(r'"([^"]+)"|\'([^\']+)\'', block):
                dep_str = sm.group(1) or sm.group(2)
                # split name and version spec
                parts = re.split(r"(==|>=|<=|~=|!=|>|<|===)", dep_str, maxsplit=1)
                name = parts[0].strip()
                spec = "".join(parts[1:]).strip()
                if name and name.lower() != "python":
                    deps.append(Dependency(name=_normalize_pypi_name(name), ecosystem="pypi", version_spec=spec))
    # Poetry-style table: [tool.poetry.dependencies] python = "...", foo = "^1.0"
    poetry_match = re.search(r"\[tool\.poetry\.dependencies\](.*?)(\n\[|\Z)", text, re.DOTALL)
    if poetry_match:
        for line in poetry_match.group(1).splitlines():
            m = re.match(r'^([A-Za-z0-9_.-]+)\s*=\s*"?([^"\n]*)"?\s*$', line.strip())
            if m:
                name = m.group(1)
                if name.lower() != "python":
                    deps.append(Dependency(name=_normalize_pypi_name(name), ecosystem="pypi", version_spec=m.group(2)))
    return deps


def _parse_package_json(path: Path) -> List[Dependency]:
    deps: List[Dependency] = []
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except (json.JSONDecodeError, OSError):
        return deps
    for section in ("dependencies", "devDependencies", "peerDependencies"):
        section_deps = data.get(section, {}) or {}
        for name, spec in section_deps.items():
            deps.append(Dependency(name=name.lower(), ecosystem="npm", version_spec=str(spec)))
    return deps


def _parse_go_mod(path: Path) -> List[Dependency]:
    deps: List[Dependency] = []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return deps
    in_require_block = False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("require ("):
            in_require_block = True
            continue
        if in_require_block and s == ")":
            in_require_block = False
            continue
        if in_require_block:
            m = re.match(r"^(\S+)\s+(\S+)", s)
            if m:
                deps.append(Dependency(name=m.group(1).lower(), ecosystem="go", version_spec=m.group(2)))
        elif s.startswith("require "):
            m = re.match(r"^require\s+(\S+)\s+(\S+)", s)
            if m:
                deps.append(Dependency(name=m.group(1).lower(), ecosystem="go", version_spec=m.group(2)))
    return deps


def _parse_cargo_toml(path: Path) -> List[Dependency]:
    deps: List[Dependency] = []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return deps
    for section in ("[dependencies]", "[dev-dependencies]"):
        idx = text.find(section)
        if idx < 0:
            continue
        block = text[idx + len(section):]
        end = block.find("\n[")
        if end >= 0:
            block = block[:end]
        for line in block.splitlines():
            m = re.match(r'^([A-Za-z0-9_-]+)\s*=\s*"([^"]+)"', line.strip())
            if m:
                deps.append(Dependency(name=m.group(1).lower(), ecosystem="cargo", version_spec=m.group(2)))
            else:
                # table form: foo = { version = "1.0", ... }
                m2 = re.match(r'^([A-Za-z0-9_-]+)\s*=\s*\{.*?version\s*=\s*"([^"]+)"', line.strip())
                if m2:
                    deps.append(Dependency(name=m2.group(1).lower(), ecosystem="cargo", version_spec=m2.group(2)))
    return deps


def _parse_gemfile(path: Path) -> List[Dependency]:
    deps: List[Dependency] = []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return deps
    for line in text.splitlines():
        s = line.strip()
        m = re.match(r'^gem\s+["\']([^"\']+)["\'](?:,\s*["\']([^"\']+)["\'])?', s)
        if m:
            deps.append(Dependency(name=m.group(1).lower(), ecosystem="gem", version_spec=m.group(2) or ""))
    return deps


def _pick_most_important(deps: List[Dependency]) -> Optional[Dependency]:
    if not deps:
        return None
    best: Optional[Dependency] = None
    best_score = -1
    for d in deps:
        score = IMPORTANCE_TIERS.get(d.name, 10)
        if score > best_score:
            best_score = score
            best = d
    return best


def collect(root: Path) -> DependencyReport:
    """Parse all manifest files present in the repo root."""
    root = root.resolve()
    report = DependencyReport()

    parsers: List[Tuple[str, Path]] = []
    if (root / "requirements.txt").exists():
        parsers.append(("pypi", root / "requirements.txt"))
    if (root / "pyproject.toml").exists():
        parsers.append(("pypi", root / "pyproject.toml"))
    if (root / "package.json").exists():
        parsers.append(("npm", root / "package.json"))
    if (root / "go.mod").exists():
        parsers.append(("go", root / "go.mod"))
    if (root / "Cargo.toml").exists():
        parsers.append(("cargo", root / "Cargo.toml"))
    if (root / "Gemfile").exists():
        parsers.append(("gem", root / "Gemfile"))

    seen = set()
    for ecosystem, path in parsers:
        if ecosystem == "pypi" and path.name == "requirements.txt":
            parsed = _parse_requirements(path)
        elif ecosystem == "pypi":
            parsed = _parse_pyproject(path)
        elif ecosystem == "npm":
            parsed = _parse_package_json(path)
        elif ecosystem == "go":
            parsed = _parse_go_mod(path)
        elif ecosystem == "cargo":
            parsed = _parse_cargo_toml(path)
        else:
            parsed = _parse_gemfile(path)
        for d in parsed:
            key = (d.ecosystem, d.name)
            if key in seen:
                continue
            seen.add(key)
            report.deps.append(d)
            report.by_ecosystem.setdefault(d.ecosystem, []).append(d)

    # Primary ecosystem = the one with the most deps
    if report.by_ecosystem:
        report.primary_ecosystem = max(report.by_ecosystem.items(), key=lambda kv: len(kv[1]))[0]

    report.most_important = _pick_most_important(report.deps)
    return report
