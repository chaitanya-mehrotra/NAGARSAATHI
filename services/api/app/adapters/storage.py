from pathlib import Path
from typing import Protocol

from app.adapters.local_media import LocalMedia
from app.adapters.supabase_media import SupabaseMedia
from app.settings import Settings


class MediaStore(Protocol):
    """What the API needs from photo storage; LocalMedia and SupabaseMedia both provide it."""

    def put(self, key: str, content: bytes) -> None: ...
    def read(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...


def build_media_storage(settings: Settings) -> LocalMedia | SupabaseMedia:
    if settings.storage_backend == "supabase":
        return SupabaseMedia(settings)
    return LocalMedia(Path(settings.storage_root))
