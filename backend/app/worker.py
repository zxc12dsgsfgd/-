import time
import logging
from app.auth import get_engine
from app.workflows import run_scheduled_once
from app.ai_worker import run_ai_once
from app.rate_limit import cleanup_expired_limits
from sqlalchemy.orm import Session


def main():
    next_scan=0.0
    next_cleanup=0.0
    while True:
        if time.monotonic() >= next_cleanup:
            try:
                cleanup_expired_limits(get_engine())
            except Exception:
                logging.error('限流记录清理失败；下一次清理将重试')
            next_cleanup = time.monotonic() + 3600
        if time.monotonic()>=next_scan:
            try:
                with Session(get_engine()) as db:run_scheduled_once(db)
            except Exception:logging.error('定时扫描失败；下一次扫描将重试未处理项')
            next_scan=time.monotonic()+60
        try:run_ai_once(get_engine())
        except Exception:logging.error('AI 任务处理失败；请检查任务状态')
        time.sleep(5)


if __name__=='__main__':main()
