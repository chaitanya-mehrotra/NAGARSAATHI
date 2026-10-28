"""Submit a small set of demo complaints through the real API (needs API + worker running).

Usage: python scripts/seed_demo_complaints.py --photo path/to/road-photo.jpg

The photo is never stored in the repository; pass any photo of a pothole. Each case is
submitted with a distinct re-encoded copy so every upload has its own hash.
"""

import argparse
import io
import uuid
from pathlib import Path

import httpx
from PIL import Image

# (description, claimed category, photo kind, (longitude, latitude)); pins are inside the pilot.
CASES = [
    ("Deep pothole near Silk Board service road", "pothole", "photo", (77.6230, 12.9170)),
    ("Same pothole, second citizen report", "pothole", "photo", (77.6231, 12.9172)),
    ("Water stagnation after rain (photo shows a pothole)", "waterlogging", "photo", (77.6270, 12.9340)),
    ("Large crater on the road (photo is blank)", "pothole", "blank", (77.6450, 12.9120)),
    ("Fallen electric pole (photo shows a pothole)", "electric_pole_fallen", "photo", (77.6120, 12.9250)),
    ("Pothole and flooding together (photo shows only a pothole)", "both", "photo", (77.6550, 12.9400)),
]


def encode(image: Image.Image, quality: int) -> bytes:
    out = io.BytesIO()
    image.convert("RGB").save(out, "JPEG", quality=quality)
    return out.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--photo", required=True, type=Path)
    parser.add_argument("--api", default="http://127.0.0.1:8000/api/v1")
    args = parser.parse_args()
    photo = Image.open(args.photo)
    blank = Image.new("RGB", (640, 480), (255, 255, 255))

    client = httpx.Client(timeout=90)
    login = client.post(f"{args.api}/auth/demo-login", json={"account_type": "citizen"})
    login.raise_for_status()
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    for number, (description, category, kind, (lon, lat)) in enumerate(CASES, start=1):
        body = encode(photo if kind == "photo" else blank, 95 - number)
        upload = client.post(
            f"{args.api}/uploads", content=body, headers={**headers, "Content-Type": "image/jpeg"}
        )
        upload.raise_for_status()
        media_id = upload.json()["id"]
        client.post(f"{args.api}/uploads/{media_id}/complete", headers=headers).raise_for_status()
        report = client.post(
            f"{args.api}/reports",
            headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
            json={
                "description": description,
                "claimed_category": category,
                "media_ids": [media_id],
                "location": {"longitude": lon, "latitude": lat, "confirmed": True},
                "location_source": "confirmed_pin",
                "address_text": "Demo location",
            },
        )
        print(f"{number}. {category:<22} -> HTTP {report.status_code}")
    print("Submitted. The worker validates them over the next minute.")


if __name__ == "__main__":
    main()
