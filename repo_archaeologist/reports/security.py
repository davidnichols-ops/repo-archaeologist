"""Write SECURITY.md: best-effort findings from the security collector."""

from __future__ import annotations

from pathlib import Path
from typing import List

from repo_archaeologist.facts import Facts


_SEVERITY_BADGE = {
    "CRITICAL": "🔴 CRITICAL",
    "HIGH": "🟠 HIGH",
    "MEDIUM": "🟡 MEDIUM",
    "LOW": "🔵 LOW",
    "INFO": "⚪ INFO",
}


def render(facts: Facts) -> str:
    parts: List[str] = []
    sec = facts.security

    parts.append(f"# Security Scan — `{facts.repo_name}`\n")
    parts.append(
        "> Best-effort static scan by `repo-archaeologist`. This is **not** a substitute "
        "for a real SAST/DAST tool (bandit, semgrep, gitleaks, dependabot). It is a "
        "first-pass 'is there anything obviously scary here?' check.\n"
    )

    # Summary
    parts.append("## Summary\n")
    if sec.count == 0:
        parts.append("_No findings. This does **not** mean the repo is secure — only that no obvious static signals fired._\n")
        return "\n".join(parts)

    parts.append("| Severity | Count |")
    parts.append("|---|---:|")
    for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"):
        c = getattr(sec, f"{sev.lower()}_count")
        if c:
            parts.append(f"| {_SEVERITY_BADGE[sev]} | {c} |")
    parts.append(f"\n**Total findings:** {sec.count}\n")

    # Findings grouped by severity
    parts.append("## Findings\n")
    by_sev = sec.by_severity()
    for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"):
        items = by_sev.get(sev, [])
        if not items:
            continue
        parts.append(f"### {_SEVERITY_BADGE[sev]} ({len(items)})\n")
        parts.append("| File | Line | Category | Message |")
        parts.append("|---|---:|---|---|")
        for f in items:
            loc = str(f.line) if f.line else "—"
            parts.append(f"| `{f.relpath}` | {loc} | {f.category} | {f.message} |")
        parts.append("")

    parts.append("## What this scan checks\n")
    parts.append("- **Secrets**: AWS access keys, AWS secret keys, GitHub tokens, Slack tokens, "
                 "Google API keys, JWT literals, private key blocks, and high-entropy strings "
                 "assigned to secret-looking variable names.")
    parts.append("- **Deprecated packages**: a small offline list of widely-abandoned packages "
                 "from `requirements.txt`, `pyproject.toml`, and `package.json`.")
    parts.append("- **Dangerous calls**: `eval`, `exec`, `os.system`, `subprocess` with "
                 "`shell=True`, `pickle.load`, `mktemp`, and JS `new Function` / "
                 "`child_process` with `shell: true`.")
    parts.append("")
    parts.append("_False positives are expected. Triage by severity, then verify each hit._\n")

    return "\n".join(parts)


def write(facts: Facts, out_dir: Path) -> Path:
    out = out_dir / "SECURITY.md"
    out.write_text(render(facts), encoding="utf-8")
    return out
