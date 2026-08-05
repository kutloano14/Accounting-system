from pathlib import Path

from app import database


def test_database_path_is_absolute_and_workspace_scoped():
    db_path = Path(database.engine.url.database)
    assert db_path.is_absolute()
    assert db_path.name == "accounting.db"
