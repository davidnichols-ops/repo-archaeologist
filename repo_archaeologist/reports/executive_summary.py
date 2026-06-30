"""Write EXECUTIVE_SUMMARY.md: the opinionated 60-second briefing.

This is the report that makes or breaks the tool. It is intentionally short,
opinionated, and written like a human reviewer's first impression — not a data dump.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from repo_archaeologist.facts import Facts


# Keyword -> likely purpose label. Checked against dependency names, filenames, and dirs.
PURPOSE_KEYWORDS = [
    ({"fastapi", "flask", "django", "starlette", "express", "gin", "echo", "actix-web", "axum",
      "rocket", "tornado", "sanic", "aiohttp", "rails", "sinatra", "spring-boot", "laravel",
      "aspnetcore", "phoenix", "next", "nuxt"},
     "web API or web service"),
    ({"react", "vue", "svelte", "next", "nuxt", "svelte", "solid-js"}, "frontend web app"),
    ({"click", "typer", "cobra", "clap", "argparse", "rich", "prompt-toolkit", "inquirer"},
     "command-line tool"),
    ({"pandas", "numpy", "scipy", "scikit-learn", "tensorflow", "torch", "pytorch",
      "transformers", "langchain", "ollama", "openai", "anthropic", "jupyter", "notebook"},
     "data / ML pipeline"),
    ({"celery", "redis", "kafka", "rabbitmq", "rq", "dramatiq", "bull", "sidekiq"},
     "background job / queue worker"),
    ({"sqlalchemy", "prisma", "sequelize", "typeorm", "mongoose", "alembic", "pymongo"},
     "data layer / ORM library"),
]


def _estimate_time_to_understand(facts: Facts) -> str:
    """Rough heuristic: map size + complexity to a human-readable estimate."""
    loc = facts.structure.total_loc
    n_langs = len(facts.structure.languages)
    n_deps = facts.dependencies.count

    if loc == 0:
        return "unknown — no source detected"
    if loc < 500:
        base = 10
    elif loc < 2000:
        base = 20
    elif loc < 8000:
        base = 45
    elif loc < 30000:
        base = 90
    elif loc < 100000:
        base = 240  # 4 hours
    else:
        base = 600  # 10 hours

    # Complexity multipliers
    if n_langs >= 3:
        base = int(base * 1.2)
    if n_deps > 30:
        base = int(base * 1.15)
    if not facts.structure.has_readme:
        base = int(base * 1.2)

    if base < 60:
        return f"~{base} minutes"
    hours, mins = divmod(base, 60)
    if hours < 8:
        return f"~{hours}h {mins:02d}m" if mins else f"~{hours} hour(s)"
    days = round(hours / 8, 1)
    return f"~{days} working day(s)"


def _risk_level(facts: Facts) -> str:
    """LOW / MEDIUM / HIGH from a handful of honest signals."""
    score = 0
    s = facts.structure
    d = facts.dependencies

    if not s.has_readme:
        score += 2  # no README is a real onboarding risk
    if not s.has_tests:
        score += 2  # no tests is a real change risk
    if not s.has_lockfile:
        score += 1  # unpinned deps
    if d.count > 50:
        score += 2
    elif d.count > 20:
        score += 1
    if s.total_loc > 30000:
        score += 1
    if not s.has_ci:
        score += 1
    if not s.has_license:
        score += 1  # unclear license is a legal risk

    if score <= 2:
        return "LOW"
    if score <= 5:
        return "MEDIUM"
    return "HIGH"


def _likely_purpose(facts: Facts) -> str:
    dep_names = {d.name for d in facts.dependencies.deps}
    # Also scan top-level dir and file names for hints
    name_hints = set(facts.structure.top_level_dirs) | set(facts.structure.top_level_files)
    name_hints_lower = {n.lower() for n in name_hints}
    combined = dep_names | name_hints_lower

    for keywords, label in PURPOSE_KEYWORDS:
        if combined & keywords:
            return label

    # Fallbacks by structure
    if facts.structure.entry_points:
        return "application (entry points detected; purpose not obvious from deps)"
    if facts.dependencies.deps:
        return "library or tool (dependencies present but no clear framework signal)"
    if facts.structure.source_file_count > 0:
        return "standalone code project (no dependency manifests detected)"
    return "unknown — too little signal to guess"


def _first_file_to_read(facts: Facts) -> str:
    if facts.structure.entry_points:
        return facts.structure.entry_points[0]
    if facts.structure.has_readme:
        return "README.md"
    if facts.structure.largest_source_files:
        return facts.structure.largest_source_files[0][0]
    return "(no obvious starting file — repo may be empty or non-code)"


def _most_important_dependency(facts: Facts) -> str:
    dep = facts.dependencies.most_important
    if dep:
        return f"{dep.name} ({dep.ecosystem})"
    return "none detected"


def _suggested_first_contribution(facts: Facts) -> str:
    """Opinionated, templated suggestion based on what's missing."""
    s = facts.structure
    if not s.has_readme:
        return "Write a README.md — there isn't one, and onboarding is impossible without it."
    if not s.has_tests:
        # point at the largest source file
        target = s.largest_source_files[0][0] if s.largest_source_files else "the main module"
        return f"Add tests. There are no tests detected. Start with `{target}`."
    if not s.has_ci:
        return "Add a CI workflow (.github/workflows/) to run the existing tests on push."
    if not s.has_license:
        return "Add a LICENSE file — the repo's legal status is unclear."
    if not s.has_lockfile:
        return "Pin dependencies with a lockfile (e.g. requirements.txt with hashes, poetry.lock, package-lock.json)."
    # Everything looks healthy — suggest improving the largest module
    if s.largest_source_files:
        target = s.largest_source_files[0][0]
        return f"Refactor `{target}` — it's the largest source file and likely a complexity hotspot."
    return "Pick a 'good first issue' from the tracker, or improve error handling in the entry point."


def render(facts: Facts) -> str:
    lines: List[str] = []
    lines.append(f"# Executive Summary — `{facts.repo_name}`\n")
    lines.append("> 60-second briefing. Auto-generated by `repo-archaeologist`. All assessments are heuristic estimates.\n")

    lines.append("## At a glance\n")
    lines.append(f"- **Time to understand repository:** {_estimate_time_to_understand(facts)}")
    lines.append(f"- **Risk level:** {_risk_level(facts)}")
    lines.append(f"- **Likely purpose:** {_likely_purpose(facts)}")
    lines.append(f"- **First file to read:** `{_first_file_to_read(facts)}`")
    lines.append(f"- **Most important dependency:** {_most_important_dependency(facts)}")
    lines.append(f"- **Suggested first contribution:** {_suggested_first_contribution(facts)}\n")

    # Quick numbers
    s = facts.structure
    d = facts.dependencies
    lines.append("## Numbers\n")
    lines.append(f"- Source files: {s.source_file_count}  ({s.file_count} files total)")
    lines.append(f"- Total source LOC: {s.total_loc:,}")
    if s.primary_language:
        lines.append(f"- Primary language: {s.primary_language}")
    lines.append(f"- Dependencies: {d.count}" + (f" ({d.primary_ecosystem})" if d.primary_ecosystem else ""))
    lines.append(f"- Entry points: {len(s.entry_points)}")
    lines.append(f"- Tests detected: {'yes' if s.has_tests else 'no'}")
    lines.append(f"- README: {'yes' if s.has_readme else 'no'}")
    lines.append(f"- CI: {'yes' if s.has_ci else 'no'}")
    lines.append(f"- Lockfile: {'yes' if s.has_lockfile else 'no'}\n")

    lines.append("## Read next\n")
    lines.append("- `ARCHITECTURE.md` — full tech stack, dependency table, module breakdown, dependency diagram, dead code estimate.")
    lines.append("- `FIRST_15_MINUTES.md` — exactly which files to read, which to ignore, and what to run.")
    if facts.security is not None and facts.security.count:
        lines.append(f"- `SECURITY.md` — security scan with {facts.security.count} finding(s) ({facts.security.critical_count} critical, {facts.security.high_count} high).\n")
    else:
        lines.append("- `SECURITY.md` — security scan (secrets, deprecated packages, dangerous calls).\n")

    return "\n".join(lines)


def write(facts: Facts, out_dir: Path) -> Path:
    out = out_dir / "EXECUTIVE_SUMMARY.md"
    out.write_text(render(facts), encoding="utf-8")
    return out
