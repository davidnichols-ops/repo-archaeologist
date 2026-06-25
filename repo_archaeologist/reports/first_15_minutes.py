"""Write FIRST_15_MINUTES.md: the killer feature for juniors.

Tells a new contributor exactly which files to read, which to ignore, and what to run
in their first 15 minutes with the repo. Opinionated and short.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Set

from repo_archaeologist.facts import Facts


# Directories that are almost always safe to ignore on a first read.
IGNORE_DIR_PATTERNS = {
    "tests", "test", "__tests__", "spec", "specs",
    "migrations", "db/migrations",
    "docs", "doc", "documentation",
    "dist", "build", "target", "out",
    "vendor", "third_party", "node_modules",
    "scripts", "ci", ".github",
    "examples", "demo", "samples",
    "static", "assets", "public",
    "coverage", ".cache",
}


def _read_these(facts: Facts) -> List[str]:
    """Pick up to 5 files for a 15-minute first read."""
    s = facts.structure
    picks: List[str] = []
    seen: Set[str] = set()

    def add(rel: str) -> None:
        if rel and rel not in seen:
            seen.add(rel)
            picks.append(rel)

    # 1. README first if present
    for name in ("README.md", "README.rst", "README", "readme.md"):
        if (facts.root / name).exists():
            add(name)
            break

    # 2. The primary entry point
    if s.entry_points:
        add(s.entry_points[0])

    # 3. The two largest source files (excluding the entry point already added)
    for rel, _loc in s.largest_source_files:
        if len(picks) >= 5:
            break
        add(rel)

    # 4. If still short, add a manifest file so they see the deps
    if len(picks) < 3:
        for name in ("pyproject.toml", "package.json", "go.mod", "Cargo.toml", "requirements.txt", "Gemfile"):
            if (facts.root / name).exists():
                add(name)
                break

    return picks[:5]


def _ignore_these(facts: Facts) -> List[str]:
    """List top-level dirs that are noise on a first read."""
    ignored: List[str] = []
    for d in sorted(facts.structure.top_level_dirs):
        low = d.lower()
        if low in IGNORE_DIR_PATTERNS or any(low.startswith(p) for p in ("test", "doc", "migration")):
            ignored.append(f"{d}/")
    # Always suggest ignoring these if present
    for static in (".git", "node_modules", "venv", ".venv", "dist", "build"):
        if (facts.root / static).exists():
            ignored.append(f"{static}/")
    # Dedup preserving order
    seen = set()
    out = []
    for x in ignored:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _run_this(facts: Facts) -> List[str]:
    """Detect install + run commands from manifests."""
    root = facts.root
    cmds: List[str] = []

    # Python
    if (root / "pyproject.toml").exists():
        text = (root / "pyproject.toml").read_text(encoding="utf-8", errors="ignore")
        if "poetry" in text:
            cmds.append("poetry install")
        elif "uv" in text or (root / "uv.lock").exists():
            cmds.append("uv sync")
        else:
            cmds.append("pip install -e .")
    if (root / "requirements.txt").exists() and not cmds:
        cmds.append("pip install -r requirements.txt")
    if (root / "Pipfile").exists() and not cmds:
        cmds.append("pipenv install")

    # Node
    if (root / "package.json").exists():
        if (root / "yarn.lock").exists():
            cmds.append("yarn install")
        elif (root / "pnpm-lock.yaml").exists():
            cmds.append("pnpm install")
        else:
            cmds.append("npm install")
        try:
            import json
            data = json.loads((root / "package.json").read_text(encoding="utf-8", errors="ignore"))
            scripts = data.get("scripts", {}) or {}
            for key in ("dev", "start", "build"):
                if key in scripts:
                    runner = "yarn" if (root / "yarn.lock").exists() else ("pnpm" if (root / "pnpm-lock.yaml").exists() else "npm run")
                    cmds.append(f"{runner} {key}")
                    break
        except (json.JSONDecodeError, OSError):
            pass

    # Go
    if (root / "go.mod").exists():
        cmds.append("go mod download")
        # find main package
        if (root / "main.go").exists():
            cmds.append("go run .")
        elif (root / "cmd").is_dir():
            first_cmd = sorted((root / "cmd").iterdir())[0].name
            cmds.append(f"go run ./cmd/{first_cmd}")

    # Rust
    if (root / "Cargo.toml").exists():
        cmds.append("cargo build")
        cmds.append("cargo run")

    # Ruby
    if (root / "Gemfile").exists():
        cmds.append("bundle install")

    # Test commands
    test_cmd = None
    if (root / "pyproject.toml").exists() or (root / "pytest.ini").exists() or (root / "tests").is_dir():
        test_cmd = "pytest"
    elif (root / "package.json").exists():
        try:
            import json
            data = json.loads((root / "package.json").read_text(encoding="utf-8", errors="ignore"))
            if "test" in (data.get("scripts", {}) or {}):
                runner = "yarn" if (root / "yarn.lock").exists() else ("pnpm" if (root / "pnpm-lock.yaml").exists() else "npm run")
                test_cmd = f"{runner} test"
        except (json.JSONDecodeError, OSError):
            pass
    elif (root / "go.mod").exists():
        test_cmd = "go test ./..."
    elif (root / "Cargo.toml").exists():
        test_cmd = "cargo test"
    elif (root / "Gemfile").exists():
        test_cmd = "bundle exec rake test"

    if test_cmd:
        cmds.append(f"# run tests: {test_cmd}")

    if not cmds:
        cmds.append("# No install/run commands detected. Check the README or look for a Makefile.")

    return cmds


def render(facts: Facts) -> str:
    lines: List[str] = []
    lines.append(f"# First 15 Minutes — `{facts.repo_name}`\n")
    lines.append('> The fastest path to "I roughly understand this repo." Auto-generated by `repo-archaeologist`.\n')

    lines.append("## Read these files (in order)\n")
    for i, rel in enumerate(_read_these(facts), 1):
        lines.append(f"{i}. `{rel}`")
    lines.append("")

    lines.append("## Ignore these (for now)\n")
    ignored = _ignore_these(facts)
    if ignored:
        for d in ignored:
            lines.append(f"- `{d}`")
    else:
        lines.append("_Nothing obvious to skip — the repo is small or unusually tidy._")
    lines.append("")

    lines.append("## Run this\n")
    lines.append("```bash")
    for cmd in _run_this(facts):
        lines.append(cmd)
    lines.append("```\n")

    lines.append("## Then\n")
    lines.append("- Skim `ARCHITECTURE.md` for the dependency list and module map.")
    lines.append("- Read `EXECUTIVE_SUMMARY.md` for the risk level and a suggested first contribution.")
    lines.append("- Pick a small file, trace one call path from the entry point to it. That's understanding.\n")

    return "\n".join(lines)


def write(facts: Facts, out_dir: Path) -> Path:
    out = out_dir / "FIRST_15_MINUTES.md"
    out.write_text(render(facts), encoding="utf-8")
    return out
