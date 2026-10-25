import hashlib
import re
import warnings
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from fastapi import HTTPException
from PIL import Image, ImageOps, UnidentifiedImageError

from app.settings import Settings


@dataclass(frozen=True)
class DecodedPhoto:
    mime: str
    width: int
    height: int
    derivative: bytes
    original_hash: str
    derivative_hash: str


def decode_photo(content: bytes, declared_mime: str, settings: Settings) -> DecodedPhoto:
    if not content or len(content) > settings.upload_max_bytes:
        raise HTTPException(413, "Photo exceeds the configured byte limit or is empty")
    if declared_mime not in {"image/jpeg", "image/png"}:
        raise HTTPException(415, "Upload a JPEG or PNG photo")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content), formats=["JPEG", "PNG"]) as probe:
                mime = "image/jpeg" if probe.format == "JPEG" else "image/png"
                if mime != declared_mime:
                    raise HTTPException(415, "Declared type does not match the decoded photo")
                if probe.width * probe.height > settings.image_max_pixels:
                    raise HTTPException(413, "Photo exceeds the decoded pixel limit")
                if getattr(probe, "n_frames", 1) != 1:
                    raise HTTPException(415, "Animated images are not supported")
                probe.verify()
            with Image.open(BytesIO(content), formats=["JPEG", "PNG"]) as image:
                image.load()
                display = ImageOps.exif_transpose(image).convert("RGB")
                # A fresh image drops EXIF, comments and embedded metadata.
                clean = Image.new("RGB", display.size)
                clean.paste(display)
                output = BytesIO()
                clean.save(output, format="JPEG", quality=85)
                derivative = output.getvalue()
                return DecodedPhoto(
                    mime=mime,
                    width=clean.width,
                    height=clean.height,
                    derivative=derivative,
                    original_hash=hashlib.sha256(content).hexdigest(),
                    derivative_hash=hashlib.sha256(derivative).hexdigest(),
                )
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise HTTPException(413, "Photo exceeds the safe decoded pixel limit") from error
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as error:
        raise HTTPException(422, "Photo could not be decoded") from error


class LocalMedia:
    """Private storage; keys are server-generated UUID paths, never user filenames."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def path(self, key: str) -> Path:
        if re.fullmatch(r"[0-9a-f]{32}/(original|display\.jpg)", key) is None:
            raise ValueError("Invalid private media key")
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Media path escaped the private storage root")
        return path

    def put(self, key: str, content: bytes) -> None:
        path = self.path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            try:
                stream.write(content)
                stream.flush()
            except OSError:
                stream.close()
                path.unlink(missing_ok=True)
                raise

    def read(self, key: str) -> bytes:
        return self.path(key).read_bytes()

    def delete(self, key: str) -> None:
        self.path(key).unlink(missing_ok=True)
