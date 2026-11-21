"""Shared fixed-window request limits for login and public shares."""
import hashlib
from datetime import timedelta

from fastapi import HTTPException, Request
from sqlalchemy import case, delete, func, select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models import RateLimitBucket


def check_limit(request: Request, db: Session, scope: str, limit: int) -> None:
    address = request.client.host if request.client else "unknown"
    bucket_key = scope + ":" + hashlib.sha256(address.encode()).hexdigest()
    engine = db.get_bind()
    # Commit counters independently of the endpoint's eventual transaction.
    with Session(engine) as counter:
        dialect = counter.get_bind().dialect.name
        timestamp = counter.scalar(select(func.utc_timestamp() if dialect == "mysql" else func.current_timestamp()))
        expired = RateLimitBucket.window_start <= timestamp - timedelta(seconds=60)
        values = {"key": bucket_key, "window_start": timestamp, "count": 1}
        if dialect == "mysql":
            stmt = mysql_insert(RateLimitBucket).values(**values)
            # MySQL evaluates assignments from left to right. Update count before
            # changing window_start, so both conditions inspect the old window.
            stmt = stmt.on_duplicate_key_update([
                ("count", case((expired, 1), else_=RateLimitBucket.count + 1)),
                ("window_start", case((expired, timestamp), else_=RateLimitBucket.window_start)),
            ])
        elif dialect == "sqlite":
            stmt = sqlite_insert(RateLimitBucket).values(**values)
            stmt = stmt.on_conflict_do_update(
                index_elements=["key"],
                set_={
                    "count": case((expired, 1), else_=RateLimitBucket.count + 1),
                    "window_start": case((expired, timestamp), else_=RateLimitBucket.window_start),
                },
            )
        else:
            raise RuntimeError("Unsupported database for shared rate limiting")
        counter.execute(stmt)
        count = counter.scalar(select(RateLimitBucket.count).where(RateLimitBucket.key == bucket_key))
        counter.commit()
    if count > limit:
        raise HTTPException(429, "请求过于频繁，请稍后重试", headers={"Retry-After": "60"})


def cleanup_expired_limits(engine) -> int:
    with Session(engine) as db:
        dialect = db.get_bind().dialect.name
        timestamp = db.scalar(select(func.utc_timestamp() if dialect == "mysql" else func.current_timestamp()))
        result = db.execute(delete(RateLimitBucket).where(
            RateLimitBucket.window_start < timestamp - timedelta(days=1)
        ))
        db.commit()
        return result.rowcount
