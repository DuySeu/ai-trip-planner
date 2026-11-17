from __future__ import annotations

import pytest

from db.queries import load_queries


def test_load_queries_splits_named_blocks(tmp_path):
    path = tmp_path / "users.sql"
    path.write_text(
        "-- name: get_user\nSELECT * FROM users\nWHERE id = %(id)s;\n\n"
        "-- name: delete_user\nDELETE FROM users WHERE id = %(id)s;\n"
    )
    assert load_queries(path) == {
        "get_user": "SELECT * FROM users\nWHERE id = %(id)s;",
        "delete_user": "DELETE FROM users WHERE id = %(id)s;",
    }


def test_load_queries_rejects_duplicate_name(tmp_path):
    path = tmp_path / "users.sql"
    path.write_text("-- name: a\nSELECT 1;\n-- name: a\nSELECT 2;\n")
    with pytest.raises(ValueError, match="duplicate"):
        load_queries(path)


def test_load_queries_rejects_empty_block(tmp_path):
    path = tmp_path / "users.sql"
    path.write_text("-- name: a\n\n-- name: b\nSELECT 2;\n")
    with pytest.raises(ValueError, match="empty"):
        load_queries(path)


def test_load_queries_rejects_sql_before_first_name(tmp_path):
    path = tmp_path / "users.sql"
    path.write_text("SELECT 1;\n-- name: a\nSELECT 2;\n")
    with pytest.raises(ValueError):
        load_queries(path)
