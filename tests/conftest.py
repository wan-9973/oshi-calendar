import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from src import db


@pytest.fixture()
def test_db(tmp_path):
    db.get_engine(f"sqlite:///{tmp_path}/test.db")
    yield db
