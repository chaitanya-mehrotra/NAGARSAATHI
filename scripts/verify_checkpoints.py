"""Verify cumulative source archives against their immutable SHA-256 manifests."""

import hashlib
import json
import zipfile

from app.settings import PROJECT_ROOT


def main() -> None:
    directory = (PROJECT_ROOT.parent / "Checkpoints").resolve()
    manifests = sorted(directory.glob("checkpoint-*.json"))
    if not manifests:
        raise SystemExit("No saved checkpoint manifests found")
    for path in manifests:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        archive = (directory / manifest["archive"]).resolve()
        if archive.parent != directory:
            raise SystemExit("Archive manifest points outside the checkpoint directory")
        if hashlib.sha256(archive.read_bytes()).hexdigest() != manifest["archive_sha256"]:
            raise SystemExit(f"Archive checksum mismatch: {archive.name}")
        with zipfile.ZipFile(archive) as bundle:
            if bundle.testzip() is not None:
                raise SystemExit(f"Archive CRC failed: {archive.name}")
            records = manifest["source_files"]
            names = ["nagarsaathi/" + record["path"] for record in records]
            if sorted(bundle.namelist()) != sorted(names) or len(set(names)) != len(names):
                raise SystemExit(f"Archive contents differ from manifest: {archive.name}")
            for record, name in zip(records, names, strict=True):
                if hashlib.sha256(bundle.read(name)).hexdigest() != record["sha256"]:
                    raise SystemExit(f"Source checksum mismatch: {archive.name}/{name}")
        print(f"Verified {archive.name}: {len(records)} source files, CRC and SHA-256 passed")


if __name__ == "__main__":
    main()
