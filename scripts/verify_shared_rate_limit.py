"""Verify shared request limits using concurrent MySQL connections in a disposable schema."""
import os
import secrets
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

from fastapi import HTTPException
from sqlalchemy import create_engine, func, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from starlette.requests import Request
import httpx

from app.config import get_settings
from app.models import RateLimitBucket
from app.rate_limit import check_limit

name = "zhiyan_test_limits_" + secrets.token_hex(6)
base = make_url(get_settings().database_url)
user = base.username.replace("'", "''")
created = granted = False
engines = []
servers = []


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
    migration = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], env=env, capture_output=True, timeout=40)
    if migration.returncode:
        raise RuntimeError("Migration failed")
    engines = [create_engine(base.set(database=name)) for _ in range(2)]
    barrier = Barrier(12)

    def attempt(index):
        request = Request({"type": "http", "method": "GET", "path": "/", "headers": [], "client": ("192.0.2.1", 1234)})
        with Session(engines[index % 2]) as db:
            barrier.wait(timeout=15)
            try:
                check_limit(request, db, "login", 10)
                return 200
            except HTTPException as exc:
                return exc.status_code

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(attempt, range(12)))
    assert results.count(200) == 10 and results.count(429) == 2, results
    with Session(engines[0]) as db:
        bucket = db.scalar(select(RateLimitBucket))
        assert bucket.count == 12
        timestamp = db.scalar(select(func.utc_timestamp()))
        db.execute(update(RateLimitBucket).values(window_start=timestamp - timedelta(seconds=61)))
        db.commit()
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": [], "client": ("192.0.2.1", 1234)})
    with Session(engines[1]) as db:
        check_limit(request, db, "login", 10)
        check_limit(request, db, "share", 60)
        assert db.scalar(select(RateLimitBucket.count).where(RateLimitBucket.key.like("login:%"))) == 1
    print("PASS: 12 concurrent requests across two MySQL engines: 10 allowed, 2 limited; expired window recovers")

    # Exercise actual HTTP requests against two independent application processes.
    ports = []
    for _ in range(2):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            ports.append(sock.getsockname()[1])
    for port in ports:
        servers.append(subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--app-dir", "backend",
             "--host", "127.0.0.1", "--port", str(port)], env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        ))
    for port, server in zip(ports, servers):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if server.poll() is not None:
                raise RuntimeError("HTTP server exited unexpectedly")
            try:
                if httpx.get(f"http://127.0.0.1:{port}/api/v1/health", trust_env=False).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(.25)
        else:
            raise RuntimeError("HTTP server did not start")

    barrier = Barrier(12)
    def http_attempt(index):
        barrier.wait(timeout=15)
        return httpx.post(
            f"http://127.0.0.1:{ports[index % 2]}/api/v1/auth/login",
            json={"email": "synthetic@example.org", "password": "invalid-password"},
            headers={"X-Requested-With": "zhiyan"}, timeout=30, trust_env=False,
        ).status_code

    with ThreadPoolExecutor(max_workers=12) as pool:
        statuses = list(pool.map(http_attempt, range(12)))
    assert statuses.count(401) == 10 and statuses.count(429) == 2, statuses
    print("PASS: concurrent HTTP login requests across two application processes share the limit")
finally:
    for process in servers:
        if process.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=15)
            else:
                process.terminate()
            process.wait(timeout=10)
    for engine in engines:
        engine.dispose()
    if granted:
        mysql(f"REVOKE ALL PRIVILEGES ON `{name}`.* FROM '{user}'@'%';")
    if created:
        mysql(f"DROP DATABASE `{name}`;")
        assert not mysql(f"SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME='{name}';").strip()
        assert name not in mysql(f"SHOW GRANTS FOR '{user}'@'%';")
        print("Temporary schema and grant cleaned")
