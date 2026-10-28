"""Private photo storage in a Supabase Storage bucket, with the same interface as LocalMedia.

Keys are the same server-generated UUID paths. Failures surface as OSError subclasses, which the
API already turns into a 503 (storage unavailable) or a 404 (missing object).
"""

import re

import httpx

from app.settings import Settings

KEY_PATTERN = re.compile(r"[0-9a-f]{32}/(original|display\.jpg)")


class SupabaseMedia:
    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        secret = settings.supabase_service_role_key.get_secret_value()
        # New-style secret keys are opaque and go in `apikey`; legacy service_role keys are JWTs
        # that the storage service also expects as a bearer token.
        headers = {"apikey": secret}
        if secret.count(".") == 2:
            headers["Authorization"] = f"Bearer {secret}"
        self.bucket = settings.supabase_storage_bucket
        self.client = client or httpx.Client(
            base_url=f"{settings.supabase_url.rstrip('/')}/storage/v1",
            headers=headers,
            timeout=30,
        )

    def _check_key(self, key: str) -> str:
        if KEY_PATTERN.fullmatch(key) is None:
            raise ValueError("Invalid private media key")
        return key

    def _request(self, method: str, url: str, **kwargs: object) -> httpx.Response:
        try:
            return self.client.request(method, url, **kwargs)  # type: ignore[arg-type]
        except httpx.HTTPError as error:
            raise ConnectionError(f"Photo storage request failed: {error.__class__.__name__}") from error

    @staticmethod
    def _missing(response: httpx.Response) -> bool:
        # Storage reports a missing object as 404, or 400 with a "not_found" body on some versions.
        return response.status_code == 404 or (
            response.status_code == 400 and "not_found" in response.text.lower()
        )

    def put(self, key: str, content: bytes) -> None:
        response = self._request(
            "POST",
            f"/object/{self.bucket}/{self._check_key(key)}",
            content=content,
            headers={"Content-Type": "application/octet-stream", "x-upsert": "false"},
        )
        if response.status_code == 409 or (
            response.status_code == 400 and "duplicate" in response.text.lower()
        ):
            raise FileExistsError(key)
        if response.status_code not in (200, 201):
            raise OSError(f"Photo storage rejected the upload ({response.status_code})")

    def read(self, key: str) -> bytes:
        response = self._request(
            "GET", f"/object/authenticated/{self.bucket}/{self._check_key(key)}"
        )
        if self._missing(response):
            raise FileNotFoundError(key)
        if response.status_code != 200:
            raise OSError(f"Photo storage read failed ({response.status_code})")
        return response.content

    def delete(self, key: str) -> None:
        response = self._request("DELETE", f"/object/{self.bucket}/{self._check_key(key)}")
        if response.status_code in (200, 204) or self._missing(response):
            return
        raise OSError(f"Photo storage delete failed ({response.status_code})")

    def ping(self) -> bool:
        """True when the configured bucket exists and the credentials can reach it."""
        try:
            return self._request("GET", f"/bucket/{self.bucket}").status_code == 200
        except OSError:
            return False
