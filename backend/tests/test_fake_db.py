from __future__ import annotations

import os
import secrets

import pymysql
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.synthetic import generate_environment


def test_generated_credentials_query_mysql_protocol_tables() -> None:
    database_host = os.environ.get("FAKE_DB_TEST_HOST")
    if not database_host:
        pytest.skip("FAKE_DB_TEST_HOST is not configured")

    session_id = str(secrets.randbelow(1_000_000_000) + 1_000_000_000)
    response = TestClient(app).post(f"/env/{session_id}/add-trail", json={"trail": "db_trail"})
    assert response.status_code == 200

    database = generate_environment(session_id)["database"]
    connection = pymysql.connect(
        host=database_host,
        port=database["port"],
        user=database["user"],
        password=database["password"],
        database=database["name"],
        connect_timeout=5,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id, username, email, role FROM users")
            users = cursor.fetchall()
            cursor.execute("SELECT id, user_id, product, status, total FROM orders")
            orders = cursor.fetchall()
    finally:
        connection.close()

    assert len(users) == len(database["users"])
    assert {row[1] for row in users} == {user["username"] for user in database["users"]}
    assert len(orders) == len(database["orders"])