"""Local demo maintenance; dry-run by default, retaining all report/repair evidence."""

import argparse
import json
import re
import time
from pathlib import Path
from uuid import UUID

from app.adapters.local_media import LocalMedia
from app.database import create_database_engine
from app.demo_seed import require_local_demo
from app.settings import Settings
from sqlalchemy import Engine, text


def maintain(engine: Engine, storage: LocalMedia, apply: bool = False) -> dict[str, int]:
    totals = {"expired_uploads": 0, "orphan_files": 0, "expired_queue_captures": 0}
    with engine.begin() as connection:
        rows = (
            connection.execute(
                text("""SELECT * FROM media m WHERE report_id IS NULL
          AND repair_issue_id IS NULL AND expires_at<now()
          AND NOT EXISTS(SELECT 1 FROM resolution_records r
            WHERE r.evidence_media_ids @> jsonb_build_array(m.id::text))
          ORDER BY id FOR UPDATE SKIP LOCKED""")
            )
            .mappings()
            .all()
        )
        totals["expired_uploads"] = len(rows)
        for row in rows:
            if apply:
                storage.delete(row["storage_key"])
                storage.delete(row["derivative_key"])
                connection.execute(text("DELETE FROM media WHERE id=:id"), {"id": row["id"]})
        media_ids: list[UUID] = list(connection.execute(text("SELECT id FROM media")).scalars())
        known = {v.hex for v in media_ids}
        if storage.root.exists():
            for directory in storage.root.iterdir():
                if (
                    not directory.is_dir()
                    or not re.fullmatch(r"[0-9a-f]{32}", directory.name)
                    or directory.name in known
                ):
                    continue
                for filename in ["original", "display.jpg"]:
                    path: Path = storage.path(f"{directory.name}/{filename}")
                    if path.exists() and path.stat().st_mtime < time.time() - 3600:
                        totals["orphan_files"] += 1
                        if apply:
                            path.unlink()
        totals["expired_queue_captures"] = connection.execute(
            text("SELECT count(*) FROM staff_queue_sessions WHERE expires_at<now()")
        ).scalar_one()
        if apply:
            connection.execute(text("DELETE FROM staff_queue_sessions WHERE expires_at<now()"))
    return totals


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    settings = Settings()
    require_local_demo(settings)
    engine = create_database_engine(settings)
    try:
        print(
            json.dumps(
                {
                    "applied": args.apply,
                    **maintain(engine, LocalMedia(settings.storage_root), args.apply),
                },
                indent=2,
            )
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
