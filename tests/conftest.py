import pytest

from pft import db, seed
from pft.data import load_frames


@pytest.fixture
def db_file(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    monkeypatch.setenv("PFT_DB_PATH", str(path))
    seed.ensure_database(path)
    return path


@pytest.fixture
def conn(db_file):
    c = db.connect(db_file)
    yield c
    c.close()


@pytest.fixture
def frames(conn):
    return load_frames(conn)
