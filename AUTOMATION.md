# Profile README automation

## Requirements & Installation

- GitHub account `Zerd0n`
- A public repository named exactly `Zerd0n`
- Python 3.11 or newer
- Git

No third-party Python packages are required. Clone the profile repository, or copy this project into it:

```bash
git clone https://github.com/Zerd0n/Zerd0n.git
cd Zerd0n
python3 --version
```

## Configuration Guide

Edit `profile.toml`. It contains the displayed name, headline, introduction, HTTPS links, skill icons, and featured projects. Icon names must exist on [Skill Icons](https://skillicons.dev/).

Optional environment variables override file locations:

```bash
export PROFILE_CONFIG=/absolute/path/to/profile.toml
export PROFILE_TEMPLATE=/absolute/path/to/profile.md.tmpl
export PROFILE_OUTPUT=/absolute/path/to/README.md
```

Do not add tokens, passwords, email credentials, or other secrets to the config. The workflow uses GitHub's short-lived built-in `GITHUB_TOKEN` with only `contents: write` permission.

## How to Run

Generate the profile:

```bash
python3 scripts/generate_readme.py
```

Validate without changing files:

```bash
python3 scripts/generate_readme.py --check
```

Use `--verbose` for diagnostic logging. Console output shows progress, and timestamped logs are written to `logs/`.

## How to Schedule / Deploy

Commit all files to the public `Zerd0n/Zerd0n` repository on the `main` branch. GitHub automatically displays its root `README.md` on the profile.

The `Generate contribution snake` workflow runs daily at 03:17 UTC, on pushes to `main`, and manually from the Actions tab. The first successful run creates the `output` branch used by the animation. The validation workflow checks every push and pull request.

For a local cron refresh every Monday at 09:00:

```cron
0 9 * * 1 cd /absolute/path/to/Zerd0n && /usr/bin/python3 scripts/generate_readme.py --no-backup
```

## How to Rollback / Undo

Before replacing an existing README, the generator copies it to `backups/README-<UTC timestamp>.md`. Restore one with:

```bash
cp backups/README-YYYYMMDDTHHMMSSZ.md README.md
```

Git also provides a complete history after commit. To remove the snake, delete its `<picture>` block from the template, regenerate, and delete `.github/workflows/snake.yml`.

## Troubleshooting

- **README is out of date:** run `python3 scripts/generate_readme.py`, then commit both the config/template changes and `README.md`.
- **Python reports `tomllib` missing:** upgrade to Python 3.11 or newer.
- **Snake is blank or missing:** open the Actions tab, run `Generate contribution snake`, and confirm workflow permissions allow read/write access.
- **An icon is missing:** verify its lowercase identifier on Skill Icons, update `profile.toml`, and regenerate.
- **Stats card is temporarily unavailable:** it is served by a third-party public service; the README itself remains valid and usually recovers without action.
- **Generation fails:** inspect the newest timestamped file in `logs/`; errors are sanitized and do not include secrets.
