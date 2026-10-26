"""Create a local worker secret without printing it or replacing other .env settings."""
import argparse
import hashlib
import os
import secrets
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api-url', default='http://127.0.0.1:8002')
    parser.add_argument('--rotate', action='store_true', help='Explicitly invalidate the old worker credential')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    worker_file = root / '.local/worker.env'
    if worker_file.exists() and not args.rotate:
        parser.error('Worker configuration exists. Use it, or pass --rotate deliberately.')
    key = secrets.token_urlsafe(48)
    fingerprint = hashlib.sha256(key.encode()).hexdigest()
    env_path = root / '.env'
    lines = env_path.read_text(encoding='utf-8').splitlines() if env_path.exists() else []
    lines = [line for line in lines if not line.startswith('NAGARSAATHI_WORKER_TOKEN_SHA256=')]
    lines.append('NAGARSAATHI_WORKER_TOKEN_SHA256=' + fingerprint)
    worker_file.parent.mkdir(exist_ok=True)
    worker_file.write_text(f'NAGARSAATHI_API_URL={args.api_url}\nNAGARSAATHI_WORKER_KEY={key}\nNAGARSAATHI_WORKER_ID=admin-pc\n', encoding='utf-8')
    try:
        os.chmod(worker_file, 0o600)
    except OSError:
        pass
    env_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('Worker credential saved to ignored .local/worker.env; secret was not printed.')
    print('Restart the API to load its SHA-256 credential fingerprint.')
    print('For a remote API, configure NAGARSAATHI_WORKER_TOKEN_SHA256 on that server:')
    print(fingerprint)


if __name__ == '__main__':
    main()
