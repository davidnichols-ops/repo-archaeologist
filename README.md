# repo-archaeologist

> Point it at an abandoned repo. Get an opinionated briefing in seconds.

Developers inherit abandoned GitHub repositories all the time. Nobody knows what works, what's broken, where the dependencies are risky, or what the architecture even is. `repo-archaeologist` reads the repo for you and writes four markdown files you can actually skim:

- **`EXECUTIVE_SUMMARY.md`** — a 60-second briefing: time-to-understand, risk level, likely purpose, first file to read, most important dependency, suggested first contribution.
- **`ARCHITECTURE.md`** — tech stack, entry points, dependency table, top-level file tree, module breakdown, a Mermaid dependency diagram, and a dead code estimate.
- **`SECURITY.md`** — a best-effort static security scan: likely secrets, deprecated packages, and dangerous calls, grouped by severity.
- **`FIRST_15_MINUTES.md`** — the killer feature for juniors: "read these files", "ignore these", "run this".

No website. No signup. No dashboard. No API key.

```bash
pip install repo-archaeologist
repo-archaeologist analyze .
```

## Install

```bash
pip install repo-archaeologist
```

Or from source:

```bash
git clone https://github.com/davidnichols-ops/repo-archaeologist.git
cd repo-archaeologist
pip install -e .
```

## Usage

Analyze the current directory:

```bash
repo-archaeologist analyze
```

Analyze a local path:

```bash
repo-archaeologist analyze /path/to/some/repo
```

Analyze a GitHub URL (clones to a temp dir):

```bash
repo-archaeologist analyze https://github.com/fastapi/fastapi
```

Write reports to a different directory:

```bash
repo-archaeologist analyze . --out-dir ./reports
```

Reports are written to the target directory by default (or `--out-dir`).

Skip optional scans (they run by default):

```bash
repo-archaeologist analyze . --no-security        # skip SECURITY.md
repo-archaeologist analyze . --no-dead-code       # skip dead code estimate
```

## Features

- **Dead code estimation** — detects Python modules and JS files that are never imported or required by any other source file. Findings are surfaced in the *Dead Code Estimate* section of `ARCHITECTURE.md`. Entry points and test files are excluded to reduce false positives.
- **Security scan** — a static, offline scan for likely secrets (AWS keys, GitHub tokens, Slack tokens, Google API keys, JWTs, private key blocks, high-entropy strings assigned to secret-looking names), deprecated/abandoned packages (from `requirements.txt`, `pyproject.toml`, `package.json`), and dangerous calls (`eval`, `exec`, `os.system`, `subprocess` with `shell=True`, `pickle.load`, `mktemp`, JS `new Function`, `child_process` with `shell: true`). Findings are written to `SECURITY.md` grouped by severity (CRITICAL / HIGH / MEDIUM / LOW / INFO).
- **Mermaid architecture diagrams** — `ARCHITECTURE.md` includes a best-effort `mermaid` graph of local module dependencies derived from static imports. External dependencies are collapsed into a single node to keep the diagram readable.

## What it detects (v1)

- Languages and LOC distribution
- Entry points (`main.py`, `index.js`, `package.json#main`, `bin/`, `cmd/`, `Cargo.toml[[bin]]`)
- Dependencies from `requirements.txt`, `pyproject.toml`, `package.json`, `go.mod`, `Cargo.toml`, `Gemfile`
- Likely purpose (web API, CLI, library, automation, data pipeline) via keyword heuristics
- Risk level (LOW / MEDIUM / HIGH) from dep count, lockfile presence, test presence, LOC
- Time-to-understand estimate from repo size and language spread
- Suggested first contribution (templated from what's missing)

## Why no AI / LLM in v1

A working heuristic version is more useful than a broken AI version. v1 is deterministic, offline, and zero-config. LLM-enriched prose is on the roadmap.

## Roadmap

- [ ] Optional LLM enrichment (OpenAI / Anthropic) for narrative prose
- [ ] GitHub Action: auto-comment on PRs with architecture/risk diff
- [ ] VS Code extension: right-click folder → "Explain Repository"

## How it works

1. Resolves the target (local path or GitHub URL → `git clone` to tempdir).
2. Walks the tree, skipping `.git`, `node_modules`, `venv`, `dist`, `build`, `__pycache__`.
3. Parses dependency manifests and detects entry points.
4. Applies opinionated heuristics to estimate risk, purpose, and time-to-understand.
5. Writes three markdown files. Prints the executive summary path.

All heuristics are intentionally simple and labeled as estimates. No fake precision.

## License

MIT
