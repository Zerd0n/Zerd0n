#!/usr/bin/env python3
"""Generate a safe, reproducible GitHub profile README from profile.toml."""

from __future__ import annotations

import argparse
import html
import logging
import os
import re
import shutil
import sys
import tempfile
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from string import Template
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "profile.toml"
DEFAULT_TEMPLATE = ROOT / "templates" / "profile.md.tmpl"
DEFAULT_OUTPUT = ROOT / "README.md"
LOG_DIR = ROOT / "logs"
BACKUP_DIR = ROOT / "backups"
USERNAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
ICON_RE = re.compile(r"^[a-z0-9-]+$")
MAX_FILE_OPERATION_ATTEMPTS = 3


class ProfileError(ValueError):
    """Raised when configuration cannot safely generate a profile."""


def retry_file_operation(operation, description: str) -> None:
    """Retry transient filesystem failures with bounded exponential backoff."""
    for attempt in range(1, MAX_FILE_OPERATION_ATTEMPTS + 1):
        try:
            operation()
            return
        except OSError:
            if attempt == MAX_FILE_OPERATION_ATTEMPTS:
                raise
            delay = 0.25 * (2 ** (attempt - 1))
            logging.warning(
                "%s failed (attempt %d/%d); retrying in %.2fs",
                description,
                attempt,
                MAX_FILE_OPERATION_ATTEMPTS,
                delay,
            )
            time.sleep(delay)


def configure_logging(verbose: bool) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_path = LOG_DIR / f"generate-{stamp}.log"
    level = logging.DEBUG if verbose else logging.INFO
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    for handler in (logging.StreamHandler(), logging.FileHandler(log_path, encoding="utf-8")):
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)
    return log_path


def require_text(value: object, field: str, max_length: int = 240) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProfileError(f"'{field}' must be a non-empty string")
    cleaned = " ".join(value.split())
    if len(cleaned) > max_length:
        raise ProfileError(f"'{field}' exceeds {max_length} characters")
    return cleaned


def safe_url(value: object, field: str) -> str:
    url = require_text(value, field, 500)
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ProfileError(f"'{field}' must be a public HTTPS URL without credentials")
    return url


def load_config(path: Path) -> dict:
    try:
        with path.open("rb") as stream:
            data = tomllib.load(stream)
    except FileNotFoundError as exc:
        raise ProfileError(f"Configuration file not found: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ProfileError(f"Invalid TOML in {path}: {exc}") from exc

    profile = data.get("profile")
    if not isinstance(profile, dict):
        raise ProfileError("Missing [profile] section")
    username = require_text(profile.get("username"), "profile.username", 39)
    if not USERNAME_RE.fullmatch(username):
        raise ProfileError("'profile.username' is not a valid GitHub username")
    return data


def icon_rows(values: object, field: str) -> str:
    if not isinstance(values, list) or not values:
        raise ProfileError(f"'{field}' must be a non-empty array")
    icons: list[str] = []
    for value in values:
        if not isinstance(value, str) or not ICON_RE.fullmatch(value):
            raise ProfileError(f"Invalid skill icon '{value}' in '{field}'")
        icon = html.escape(value, quote=True)
        icons.append(
            f'  <img src="https://skillicons.dev/icons?i={icon}" height="42" alt="{icon} icon" />'
        )
    return "\n  <img width=\"10\" />\n".join(icons)


def render_projects(projects: object) -> str:
    if not isinstance(projects, list) or not projects:
        raise ProfileError("At least one [[projects]] entry is required")
    cards: list[str] = []
    for index, project in enumerate(projects, start=1):
        if not isinstance(project, dict):
            raise ProfileError(f"Project #{index} must be a table")
        name = html.escape(require_text(project.get("name"), f"projects[{index}].name", 80))
        description = html.escape(
            require_text(project.get("description"), f"projects[{index}].description", 220)
        )
        url = html.escape(safe_url(project.get("url"), f"projects[{index}].url"), quote=True)
        cards.append(f'<p align="center"><a href="{url}"><strong>{name}</strong></a><br />{description}</p>')
    return "\n\n".join(cards)


def render(data: dict, template_path: Path) -> str:
    profile = data["profile"]
    skills = data.get("skills", {})
    links = data.get("links", {})
    username = require_text(profile.get("username"), "profile.username", 39)

    badges: list[str] = []
    for label, key, color in (("GitHub", "github", "181717"), ("Portfolio", "portfolio", "7c3aed")):
        if key in links:
            url = html.escape(safe_url(links[key], f"links.{key}"), quote=True)
            badges.append(
                f'  <a href="{url}"><img src="https://img.shields.io/badge/{label}-{color}?style=for-the-badge&logo={label.lower()}&logoColor=white" alt="{label}" /></a>'
            )

    try:
        template = Template(template_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ProfileError(f"Template not found: {template_path}") from exc

    return template.substitute(
        username=html.escape(username, quote=True),
        display_name=html.escape(require_text(profile.get("display_name"), "profile.display_name", 80)),
        headline=html.escape(require_text(profile.get("headline"), "profile.headline", 120)),
        intro=html.escape(require_text(profile.get("intro"), "profile.intro")),
        link_badges="\n".join(badges),
        language_icons=icon_rows(skills.get("languages"), "skills.languages"),
        tool_icons=icon_rows(skills.get("tools"), "skills.tools"),
        projects=render_projects(data.get("projects")),
    ).rstrip() + "\n"


def atomic_write(output: Path, content: str, backup: bool) -> Path | None:
    backup_path = None
    output.parent.mkdir(parents=True, exist_ok=True)
    if backup and output.exists():
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = BACKUP_DIR / f"README-{stamp}.md"
        retry_file_operation(lambda: shutil.copy2(output, backup_path), "README backup")

    fd, temp_name = tempfile.mkstemp(prefix=".README.", dir=output.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        retry_file_operation(lambda: os.replace(temp_name, output), "Atomic README replacement")
    except Exception:
        Path(temp_name).unlink(missing_ok=True)
        raise
    return backup_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path(os.getenv("PROFILE_CONFIG", DEFAULT_CONFIG)))
    parser.add_argument("--template", type=Path, default=Path(os.getenv("PROFILE_TEMPLATE", DEFAULT_TEMPLATE)))
    parser.add_argument("--output", type=Path, default=Path(os.getenv("PROFILE_OUTPUT", DEFAULT_OUTPUT)))
    parser.add_argument("--check", action="store_true", help="Fail if README.md differs from generated content")
    parser.add_argument("--no-backup", action="store_true", help="Do not back up an existing output file")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    log_path = configure_logging(args.verbose)
    try:
        logging.info("[1/3] Loading and validating profile configuration")
        data = load_config(args.config.resolve())
        logging.info("[2/3] Rendering profile README")
        content = render(data, args.template.resolve())
        output = args.output.resolve()

        if args.check:
            if not output.exists() or output.read_text(encoding="utf-8") != content:
                logging.error("README is out of date; run scripts/generate_readme.py")
                return 1
            logging.info("[3/3] README is up to date")
        else:
            backup_path = atomic_write(output, content, backup=not args.no_backup)
            logging.info("[3/3] Wrote %s", output)
            if backup_path:
                logging.info("Previous README backed up to %s", backup_path)
        logging.info("Log saved to %s", log_path)
        return 0
    except (OSError, ProfileError, KeyError) as exc:
        logging.error("Generation failed: %s", exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
