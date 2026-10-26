"""Outbound-only worker. Run on the admin PC with python -m backend.pc_worker."""
import argparse
import io
import logging
import os
import threading
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv
from PIL import Image

from backend.grouping import fingerprints

logger = logging.getLogger('nagarsaathi.worker')


class PCWorker:
    def __init__(self, base_url, key, worker_id, client=None, detector=None):
        self.client = client or httpx.Client(base_url=base_url.rstrip('/'), headers={'X-Worker-Key':key}, timeout=60,
                                              follow_redirects=False)
        self.client.headers['X-Worker-Key'] = key
        self.worker_id = worker_id
        if detector is None:
            from backend.inference import detect_potholes, load_model, METADATA
            load_model()  # Once at worker startup; never in the API process.
            self.detector = detect_potholes
            self.model_hash = METADATA['model_sha256']
        else:
            self.detector = detector
            self.model_hash = '748e47702e7fa7068ab64a9005cbefb02873e0190eff67496dbd2ef2a8f6a676'

    def post(self, path, body):
        response = self.client.post(path, json=body)
        response.raise_for_status()
        return response.json()

    def download(self, path, token):
        # Worker never follows arbitrary URLs returned by a server or an image.
        if not path.startswith('/worker/jobs/') or '..' in path or '?' in path or '#' in path:
            raise ValueError('Invalid job input path')
        with self.client.stream('GET', path, headers={'X-Lease-Token':token}) as response:
            response.raise_for_status()
            chunks, size = [], 0
            for part in response.iter_bytes():
                size += len(part)
                if size > 100_000_000:
                    raise ValueError('Input exceeds limit')
                chunks.append(part)
        raw = b''.join(chunks)
        with Image.open(io.BytesIO(raw), formats=['PNG']) as photo:
            if photo.width * photo.height > 24_000_000:
                raise ValueError('Image exceeds pixel limit')
            return photo.convert('RGB')

    def run_once(self):
        job = self.post('/worker/jobs/claim', {'worker_id':self.worker_id})['job']
        if job is None:
            return False
        stop, lease_lost = threading.Event(), threading.Event()
        def renew():
            while not stop.wait(max(1, job['lease_seconds'] // 3)):
                try:
                    self.post(f"/worker/jobs/{job['id']}/heartbeat", {'lease_token':job['lease_token']})
                except (httpx.HTTPError, ValueError):
                    lease_lost.set()
                    return
        heartbeat = threading.Thread(target=renew, daemon=True)
        heartbeat.start()
        try:
            photo = self.download(job['input_path'], job['lease_token'])
            sha, _ = fingerprints(photo)
            if sha != job['image_sha256'] or photo.size != (job['image_width'], job['image_height']):
                raise ValueError('Saved photo integrity mismatch')
            with TemporaryDirectory(prefix='nagarsaathi-worker-') as temporary:
                path = Path(temporary) / 'input.png'
                photo.save(path)
                analysis = self.detector(path)
                matches = []
                from backend.visual_matching import compare_defects
                for candidate in job['candidates']:
                    if lease_lost.is_set():
                        raise RuntimeError('Lease lost')
                    other = self.download(candidate['input_path'], job['lease_token'])
                    if fingerprints(other)[0] != candidate['image_sha256']:
                        raise ValueError('Candidate photo integrity mismatch')
                    evidence = compare_defects(photo, analysis['detections'], other, candidate['analysis'].get('detections', []))
                    matches.append({'report_id':candidate['report_id'], **evidence})
                result = {'lease_token':job['lease_token'], 'image_sha256':sha, 'model_sha256':self.model_hash,
                          'model_version':analysis['model_version'], 'image_width':photo.width,'image_height':photo.height,
                          'detections':[{k:d[k] for k in ('label','confidence','bbox_xyxy')} for d in analysis['detections']],
                          'matches':matches}
                if not lease_lost.is_set():
                    # Retry ambiguous network failures with the exact same result payload.
                    for attempt in range(3):
                        try:
                            self.post(f"/worker/jobs/{job['id']}/result", result)
                            break
                        except httpx.TransportError:
                            if attempt == 2:
                                raise
                            time.sleep(1)
                else:
                    raise RuntimeError('Lease lost')
            logger.info('Processed job %s', job['id'])
        except Exception as error:
            logger.warning('Job %s failed (%s); evidence is retained', job['id'], type(error).__name__)
            if not lease_lost.is_set():
                try:
                    self.post(f"/worker/jobs/{job['id']}/failure", {'lease_token':job['lease_token'],
                              'error_code':'input_error' if isinstance(error, ValueError) else 'inference_error'})
                except httpx.HTTPError:
                    pass  # Lease timeout will recover it; never log credentials or request bodies.
        finally:
            stop.set()
            heartbeat.join(timeout=5)
        return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', default='.local/worker.env')
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    load_dotenv(Path(__file__).resolve().parents[1] / '.env')
    load_dotenv(args.env_file, override=True)
    base = os.getenv('NAGARSAATHI_API_URL', 'http://127.0.0.1:8002')
    parsed = urlparse(base)
    if parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in ('127.0.0.1','localhost')):
        parser.error('Use HTTPS outside localhost')
    key = os.getenv('NAGARSAATHI_WORKER_KEY', '')
    if len(key) < 32:
        parser.error('Configure a worker credential first; see backend/PROCESSING.md')
    logging.basicConfig(level=logging.INFO)
    worker_id = os.getenv('NAGARSAATHI_WORKER_ID', 'admin-pc')
    worker = PCWorker(base, key, worker_id)
    try:
        while True:
            try:
                work = worker.run_once()
            except httpx.HTTPError as error:
                logger.warning('API unavailable (%s); will reconnect', type(error).__name__)
                work = False
            if args.once:
                break
            if not work:
                time.sleep(5)
    except KeyboardInterrupt:
        logger.info('Worker stopped; interrupted jobs recover after lease expiry')
    finally:
        worker.client.close()


if __name__ == '__main__':
    main()
