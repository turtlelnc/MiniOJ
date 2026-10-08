from pathlib import Path
import os, secrets, shutil, sys

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get('MINIOJ_DATA', ROOT / 'data')).resolve()
DATA.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA / 'minioj.sqlite3'
TOKEN_PATH = DATA / 'api-token'
if not TOKEN_PATH.exists():
    fd = os.open(TOKEN_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write(secrets.token_urlsafe(32))
TOKEN = os.environ.get('MINIOJ_TOKEN') or TOKEN_PATH.read_text().strip()
COMPILER = os.environ.get('MINIOJ_COMPILER') or shutil.which('g++-16') or shutil.which('g++')
DOCKER = shutil.which('docker')
IMAGE = os.environ.get('MINIOJ_IMAGE', 'minioj-sandbox:1')
JUDGE_BACKEND = os.environ.get('MINIOJ_JUDGE_BACKEND', 'docker')
OUTPUT_LIMIT = 1024 * 1024
SOURCE_LIMIT = 256 * 1024

DOCKER_CONTEXT = os.environ.get('MINIOJ_DOCKER_CONTEXT')
if sys.platform=='darwin' and not DOCKER_CONTEXT and Path.home().joinpath('.colima/minioj/docker.sock').exists():
    DOCKER_CONTEXT = 'colima-minioj'

SUBMISSION_LEASE_SECONDS=max(10,int(os.environ.get('MINIOJ_SUBMISSION_LEASE_SECONDS','60')))

# Capture the code loaded by this server, including uncommitted new modules.
import hashlib, platform
_runtime_hash=hashlib.sha256()
for _file in sorted([*(ROOT/'minioj').glob('*.py'),*(ROOT/'benchmark').rglob('*.py'),*(ROOT/'scripts').glob('container_*.py'),ROOT/'Dockerfile']):
    _runtime_hash.update(str(_file.relative_to(ROOT)).encode());_runtime_hash.update(_file.read_bytes())
SOURCE_FINGERPRINT=_runtime_hash.hexdigest()
RUNTIME_INFORMATION={'python':platform.python_version(),'system':platform.system(),'machine':platform.machine(),'source_fingerprint':SOURCE_FINGERPRINT}
