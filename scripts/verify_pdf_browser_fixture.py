"""Serve a disposable MySQL dataset for manual browser PDF acceptance."""
import hashlib
import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import PaperFile

root = Path.cwd().resolve()
fixture = root / "docs/evidence/test-results/pdf-layout-20261120/fixture.pdf"
name = "zhiyan_test_pdf_" + secrets.token_hex(6)
base = make_url(get_settings().database_url)
user = base.username.replace("'", "''")
stop = root / ("." + name + ".stop")
created = granted = False
engine = None
processes = []


def mysql(sql):
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", "mysql", "sh", "-c",
         'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -u root -N -B'],
        input=sql.encode(), capture_output=True, timeout=20,
    )
    if result.returncode:
        raise RuntimeError("Temporary database operation failed")
    return result.stdout.decode("utf-8").strip()


try:
    assert fixture.is_file(), "Compile the PDF fixture first"
    for port in (8000, 5173):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", port))
    mysql(f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;")
    created = True
    mysql(f"GRANT ALL PRIVILEGES ON `{name}`.* TO '{user}'@'%';")
    granted = True
    env = os.environ.copy()
    env["DATABASE_URL"] = base.set(database=name).render_as_string(hide_password=False)
    env["SECURE_COOKIES"] = "false"
    env["PYTHONPATH"] = str(root / "backend")
    result = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"],
                            env=env, capture_output=True, timeout=40)
    if result.returncode:
        raise RuntimeError("Temporary migration failed")
    engine = create_engine(base.set(database=name))
    commands = [
        ([sys.executable, "-m", "uvicorn", "app.main:app", "--app-dir", "backend",
          "--host", "127.0.0.1", "--port", "8000"], root),
        (["node", "node_modules/vite/bin/vite.js", "--host", "127.0.0.1", "--port", "5173",
          "--strictPort"], root / "frontend"),
    ]
    for command, cwd in commands:
        processes.append(subprocess.Popen(command, cwd=cwd, env=env, stdout=subprocess.DEVNULL,
                                          stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW))
    with httpx.Client(base_url="http://127.0.0.1:5173", trust_env=False, timeout=3,
                      headers={"X-Requested-With": "zhiyan"}) as client:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if any(process.poll() is not None for process in processes):
                raise RuntimeError("A test service exited")
            try:
                if client.get("/api/v1/health/database").json()["status"] == "connected":
                    break
            except (httpx.HTTPError, ValueError, KeyError):
                pass
            time.sleep(.25)
        else:
            raise RuntimeError("Test services did not start")
        account = {"email": "pdf-layout@example.org", "password": "synthetic-pdf-layout-123",
                   "display_name": "PDF tester"}
        assert client.post("/api/v1/auth/register", json=account).status_code == 201
        assert client.post("/api/v1/auth/login", json=account).status_code == 200
        response = client.post("/api/v1/papers", json={"title": "Synthetic multi-page PDF"})
        assert response.status_code == 201
        with fixture.open("rb") as source:
            uploaded = client.post(f"/api/v1/papers/{response.json()['id']}/files",
                                   files={"file": ("fixture.pdf", source, "application/pdf")})
        assert uploaded.status_code == 201
    print("READY", stop.name, flush=True)
    deadline = time.monotonic() + 300
    while not stop.exists() and time.monotonic() < deadline:
        time.sleep(.25)
finally:
    stop.unlink(missing_ok=True)
    for process in reversed(processes):
        if process.poll() is None:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           capture_output=True, timeout=15)
            process.wait(timeout=10)
    try:
        if engine:
            with Session(engine) as db:
                files = [(item.storage_key, item.sha256) for item in db.scalars(select(PaperFile))]
            storage = (root / "data/pdfs").resolve()
            for key, expected in files:
                if len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
                    raise RuntimeError("Unexpected test storage key")
                path = (storage / (key + ".pdf")).resolve()
                if path.parent != storage or not path.is_file():
                    raise RuntimeError("Test PDF path unavailable")
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                if digest != expected or digest != hashlib.sha256(fixture.read_bytes()).hexdigest():
                    raise RuntimeError("Test PDF checksum mismatch; leaving file in place")
                path.unlink()
            engine.dispose()
    finally:
        try:
            if granted:
                mysql(f"REVOKE ALL PRIVILEGES ON `{name}`.* FROM '{user}'@'%';")
        finally:
            if created:
                mysql(f"DROP DATABASE `{name}`;")
    if created:
        assert not mysql(f"SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME='{name}';")
        assert name not in mysql(f"SHOW GRANTS FOR '{user}'@'%';")
        print("PASS: temporary PDF copy, schema, grant and services cleaned", flush=True)
