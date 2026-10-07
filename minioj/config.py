from pathlib import Path
import os, secrets, shutil

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
if not DOCKER_CONTEXT and Path.home().joinpath('.colima/minioj/docker.sock').exists():
    DOCKER_CONTEXT = 'colima-minioj'
