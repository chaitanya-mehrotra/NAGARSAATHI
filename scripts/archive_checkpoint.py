"""Save a source-only checkpoint snapshot alongside the live project."""

import argparse
import hashlib
import json
import os
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from app.settings import PROJECT_ROOT

EXCLUDED = {
    ".git",
    ".venv",
    ".uv-cache",
    "node_modules",
    "dist",
    ".local",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "test-results",
    "playwright-report",
}
EXTENSIONS = {
    ".py",
    ".ts",
    ".tsx",
    ".json",
    ".yaml",
    ".toml",
    ".lock",
    ".ini",
    ".mako",
    ".md",
    ".css",
    ".html",
    ".geojson",
    ".sql",
}


def source_files() -> list[Path]:
    paths: list[Path] = []
    for directory, folders, files in os.walk(PROJECT_ROOT):
        folders[:] = sorted(folder for folder in folders if folder not in EXCLUDED)
        for name in sorted(files):
            path = Path(directory) / name
            if name.startswith(".env") and name != ".env.example":
                continue
            if path.suffix in EXTENSIONS or name in {
                ".env.example",
                ".gitignore",
                ".prettierignore",
            }:
                paths.append(path)
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkpoint", type=int, choices=range(11))
    args = parser.parse_args()
    destination = PROJECT_ROOT.parent / "Checkpoints"
    destination.mkdir(exist_ok=True)
    prefix = f"checkpoint-{args.checkpoint:02d}"
    archive = destination / f"{prefix}.zip"
    manifest_path = destination / f"{prefix}.json"
    if archive.exists() or manifest_path.exists():
        raise SystemExit(
            f"Snapshot {prefix} already exists; completed snapshots are not overwritten."
        )
    records = []
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in source_files():
            content = path.read_bytes()
            relative = path.relative_to(PROJECT_ROOT).as_posix()
            records.append({"path": relative, "sha256": hashlib.sha256(content).hexdigest()})
            bundle.writestr(f"nagarsaathi/{relative}", content)
    with zipfile.ZipFile(archive) as bundle:
        if bundle.testzip() is not None:
            raise SystemExit("Archive integrity check failed")
    manifest = {
        "checkpoint": args.checkpoint,
        "created_at": datetime.now(UTC).isoformat(),
        "archive": archive.name,
        "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "source_files": records,
        "results": "nagarsaathi/docs/checkpoint-results.md",
        "excluded": "installed dependencies, private .env files, media, caches and build output",
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    snapshots = sorted(destination.glob("checkpoint-*.zip"))
    links = "\n".join(
        f"- [{path.stem}]({path.name}) · [{path.stem} manifest]({path.stem}.json)"
        for path in snapshots
    )
    (destination / "README.md").write_text(
        "# Completed NAGARSAATHI checkpoints\n\n"
        "The live application stays in `../nagarsaathi`. Each ZIP is a cumulative source "
        "snapshot, with dependency lockfiles, configuration and checkpoint results. "
        "Extract it and follow its README to install/build. Runtime dependencies, private "
        "environment files, media and database volumes are excluded. Snapshots are never "
        "overwritten. JSON manifests record SHA-256 checksums.\n\n" + links + "\n",
        encoding="utf-8",
    )
    print(f"Saved {archive} ({len(records)} source files); archive integrity passed.")


if __name__ == "__main__":
    main()
