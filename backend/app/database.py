from sqlalchemy import create_engine, text

from app.config import get_settings


def check_database() -> str:
    url = get_settings().database_url
    if not url:
        return "not_configured"
    engine = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 3})
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return "connected"
    finally:
        engine.dispose()
