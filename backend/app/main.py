from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.database import check_database
from app.auth import profile_router, router as auth_router
from app.papers import router as papers_router
from app.paper_files import router as paper_files_router
from app.config import get_settings
from app.knowledge import router as knowledge_router
from app.tags import router as tags_router
from app.relations import router as relations_router
from app.workflows import router as workflows_router
from app.plans import router as plans_router
from app.ai import router as ai_router
from app.exports import router as exports_router
from app.shares import router as shares_router
from app.projects import router as projects_router
from app.evidence import router as evidence_router
from app.personal_backup import router as personal_backup_router
from app.trash import router as trash_router
from app.reading_templates import router as reading_templates_router
from app.batch import router as batch_router
from app.pdf_backup import router as pdf_backup_router

app = FastAPI(title="知研云枢 API", version="0.1.0")
app.include_router(auth_router)
app.include_router(profile_router)
app.include_router(papers_router)
app.include_router(paper_files_router)
app.include_router(knowledge_router)
app.include_router(tags_router)
app.include_router(relations_router)
app.include_router(workflows_router)
app.include_router(plans_router)
app.include_router(ai_router)
app.include_router(exports_router)
app.include_router(shares_router)
app.include_router(projects_router)
app.include_router(evidence_router)
app.include_router(personal_backup_router)
app.include_router(trash_router)
app.include_router(reading_templates_router)
app.include_router(batch_router)
app.include_router(pdf_backup_router)


def error_response(status: int, detail, *, headers=None):
    code = detail.get("code", f"http_{status}") if isinstance(detail, dict) else f"http_{status}"
    message = detail if isinstance(detail, str) else "请求未能完成"
    return JSONResponse(
        status_code=status,
        content={"detail": jsonable_encoder(detail), "error": {
            "code": code, "message": message, "request_id": uuid4().hex,
        }},
        headers=headers,
    )


@app.exception_handler(StarletteHTTPException)
async def handle_http_error(request: Request, exc: StarletteHTTPException):
    return error_response(exc.status_code, exc.detail, headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def handle_validation_error(request: Request, exc: RequestValidationError):
    # Never include the submitted value or exception context, which can contain secrets.
    detail = [{"loc": e["loc"], "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
    return error_response(422, detail)


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception):
    return error_response(500, "服务暂时不可用，请稍后重试")


@app.middleware("http")
async def require_same_origin_header(request: Request, call_next):
    if request.method == 'POST' and request.url.path in ('/api/v1/personal-backup/pdf-preview','/api/v1/personal-backup/pdf-mapping-preview'):
        length = request.headers.get('content-length')
        if not length or not length.isdigit():
            return error_response(411, '上传请求需要有效的内容长度')
        if int(length) > 52 * 1024 * 1024:
            return error_response(413, '上传内容超过大小限制')
    if request.method == 'POST' and request.url.path in ('/api/v1/personal-backup/preview', '/api/v1/personal-backup/restore'):
        length = request.headers.get('content-length')
        if not length or not length.isdigit():
            return error_response(411, '上传请求需要有效的内容长度')
        if int(length) > 11 * 1024 * 1024:
            return error_response(413, '上传内容超过大小限制')
    if request.method == 'POST' and request.url.path.startswith('/api/v1/papers/') and request.url.path.endswith('/files'):
        length = request.headers.get('content-length')
        if not length or not length.isdigit():
            return error_response(411, '上传请求需要有效的内容长度')
        if int(length) > get_settings().pdf_max_bytes + 1024 * 1024:
            return error_response(413, '上传内容超过大小限制')
    if request.url.path.startswith("/api/v1/") and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        if request.headers.get("x-requested-with") != "zhiyan":
            return error_response(403, "请求校验失败")
        origin = request.headers.get("origin")
        allowed_origins = {"http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:8000", "http://127.0.0.1:8000"}
        if get_settings().public_origin:
            allowed_origins.add(get_settings().public_origin)
        if origin and origin not in allowed_origins:
            return error_response(403, "请求来源不允许")
    response = await call_next(request)
    if request.url.path.startswith('/api/v1/public/shares') or request.url.path == '/api/v1/shares':
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
    return response


@app.get("/api/v1/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/health/database")
def database_health() -> dict[str, str]:
    try:
        return {"status": check_database()}
    except (SQLAlchemyError, ValueError):
        return {"status": "unavailable"}
