"""Start a fresh API process while ML imports are explicitly forbidden."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class APIRuntimeTests(unittest.TestCase):
    def test_api_startup_and_readiness_do_not_import_machine_learning(self):
        program = '''
import builtins
original_import = builtins.__import__
def guarded(name, *args, **kwargs):
    if name in ('backend.inference','inference') or name.split('.')[0] in ('torch','ultralytics','cv2','numpy'):
        raise AssertionError('Machine-learning import in intake API: '+name)
    return original_import(name,*args,**kwargs)
builtins.__import__ = guarded
from fastapi.testclient import TestClient
from backend.main import app
with TestClient(app) as client:
    assert client.get('/ready').status_code == 200
    assert client.get('/health').json()['processing_mode'] == 'external_worker'
'''
        with tempfile.TemporaryDirectory() as directory:
            completed = subprocess.run([sys.executable,'-c',program],cwd=Path(__file__).resolve().parents[1],
                env={**os.environ,'NAGARSAATHI_DATA_DIR':directory},capture_output=True,text=True,timeout=30)
            self.assertEqual(completed.returncode,0,completed.stderr)
