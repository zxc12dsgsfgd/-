"""Run an authorized real AI integration test in a disposable database."""
import os
import secrets
import subprocess
import sys

from cryptography.fernet import Fernet
from dotenv import dotenv_values
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.config import get_settings

api_key = os.environ.get("DEEPSEEK_API_KEY") or dotenv_values(".env").get("DEEPSEEK_API_KEY")
if not api_key:
    raise SystemExit("DEEPSEEK_API_KEY is not configured")

name = "zhiyan_test_ai_live_" + secrets.token_hex(6)
base = make_url(get_settings().database_url)
user = base.username.replace("'", "''")
created = granted = False
engine = None


def mysql(sql):
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", "mysql", "sh", "-c",
         'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -u root -N -B'],
        input=sql.encode(), capture_output=True, timeout=20,
    )
    if result.returncode:
        raise RuntimeError("Temporary database operation failed")
    return result.stdout.decode("utf-8")


try:
    mysql(f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;")
    created = True
    mysql(f"GRANT ALL PRIVILEGES ON `{name}`.* TO '{user}'@'%';")
    granted = True
    env = os.environ.copy()
    env["DATABASE_URL"] = base.set(database=name).render_as_string(hide_password=False)
    env["PYTHONPATH"] = "backend"
    result = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], env=env, capture_output=True, timeout=40)
    if result.returncode:
        raise RuntimeError("Temporary database migration failed")
    engine = create_engine(base.set(database=name))
    settings = get_settings()
    original_key = settings.ai_encryption_key
    settings.ai_encryption_key = Fernet.generate_key().decode()
    from app.auth import get_db
    from app.ai_worker import run_ai_once
    from app.main import app
    from app.models import AIJob

    def isolated_db():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = isolated_db
    headers = {"X-Requested-With": "zhiyan"}
    try:
        with TestClient(app) as client:
            account = {"email": "ai-live-fixture@example.org", "password": secrets.token_urlsafe(24),
                       "display_name": "Synthetic researcher"}
            assert client.post("/api/v1/auth/register", json=account, headers=headers).status_code == 201
            assert client.post("/api/v1/auth/login", json=account, headers=headers).status_code == 200
            config = {"base_url": "https://api.deepseek.com", "model_name": "deepseek-v4-pro",
                      "timeout_seconds": 120, "api_key": api_key}
            response = client.put("/api/v1/settings/ai", json=config, headers=headers)
            assert response.status_code == 200 and api_key not in response.text
            selection = {"task_type": "questions", "paper_ids": [], "card_ids": [],
                         "text": "Synthetic test: a plant grows 3 cm in one week. Suggest one research question."}
            preview = client.post("/api/v1/ai/preview", json=selection, headers=headers)
            assert preview.status_code == 200 and preview.json()["preview_token"]
            response = client.post("/api/v1/ai/tasks", json={**selection, "preview_token": preview.json()["preview_token"]}, headers=headers)
            assert response.status_code == 202
            job_id = response.json()["id"]
            assert run_ai_once(engine)
            job = next(item for item in client.get("/api/v1/ai/tasks").json() if item["id"] == job_id)
            if job["status"] != "success":
                raise RuntimeError("Provider integration failed with sanitized code: " + str(job["error_code"]))
            draft = next(item for item in client.get("/api/v1/drafts").json() if item["id"] == job["draft_id"])
            assert draft["content"].strip() and draft["sources"]
            accepted = client.post(f"/api/v1/drafts/{draft['id']}/accept",
                                   json={"title": draft["title"], "content": draft["content"]}, headers=headers)
            assert accepted.status_code == 200 and accepted.json()["status"] == "accepted"
            with Session(engine) as db:
                assert db.scalar(select(AIJob).where(AIJob.id == job_id)).key_ciphertext == b""
            print("PASS: authorized real AI request created a draft with sources and accepted review")

            # A deliberately unknown model checks the real service's failure path.
            invalid_config = {**config, "model_name": "invalid-synthetic-model-000000"}
            assert client.put("/api/v1/settings/ai", json=invalid_config, headers=headers).status_code == 200
            preview = client.post("/api/v1/ai/preview", json=selection, headers=headers)
            assert preview.status_code == 200
            failed = client.post("/api/v1/ai/tasks", json={**selection, "preview_token": preview.json()["preview_token"]}, headers=headers)
            assert failed.status_code == 202
            failed_id = failed.json()["id"]
            assert run_ai_once(engine)
            result = next(item for item in client.get("/api/v1/ai/tasks").json() if item["id"] == failed_id)
            assert result["status"] == "failed" and result["error_code"] == "provider_error"
            assert result["draft_id"] is None
            with Session(engine) as db:
                assert db.scalar(select(AIJob).where(AIJob.id == failed_id)).key_ciphertext == b""
            print("PASS: real provider rejected invalid model; failure recorded without a draft or saved task key")
    finally:
        app.dependency_overrides.pop(get_db, None)
        settings.ai_encryption_key = original_key
finally:
    if engine:
        engine.dispose()
    if granted:
        mysql(f"REVOKE ALL PRIVILEGES ON `{name}`.* FROM '{user}'@'%';")
    if created:
        mysql(f"DROP DATABASE `{name}`;")
        assert not mysql(f"SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME='{name}';").strip()
        assert name not in mysql(f"SHOW GRANTS FOR '{user}'@'%';")
        print("Temporary AI schema and grant cleaned")
