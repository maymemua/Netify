"""Máy chủ web VNSHOP Memory: API + giao diện tĩnh.

    uvicorn server.main:app --port 8000      (mở http://localhost:8000)

Không có đăng nhập: chỉ chạy trên máy cá nhân hoặc mạng nội bộ tin cậy.
"""

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from kg.env import load_env

load_env()  # phải chạy trước khi import agent (đọc tên model từ biến môi trường)

from .agent import available_models, chat_mode, discover_gemini_models, model_for, run_chat, set_discovered  # noqa: E402
from . import auth  # noqa: E402
from .db import GraphDB  # noqa: E402

WEB = Path(__file__).resolve().parent.parent / "web"


log = logging.getLogger("uvicorn.error")
_gemini_checked = False


async def ensure_ready():
    """Kết nối Neo4j và lấy danh sách model Gemini ở lần dùng đầu tiên.

    Chạy lúc khởi động khi dùng uvicorn, hoặc ở request đầu tiên trên môi trường serverless
    (Vercel) nơi bước khởi động có thể không được gọi. Kết nối Neo4j gắn với event loop đã
    tạo ra nó, nên nếu môi trường chạy request trên loop khác thì tạo kết nối mới.
    """
    global _gemini_checked
    loop = asyncio.get_running_loop()
    if getattr(app.state, "db", None) is not None and app.state.db_loop is loop:
        return
    graph_db = GraphDB()
    await graph_db.init_schema()
    app.state.db, app.state.db_loop = graph_db, loop
    if not _gemini_checked and (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
        _gemini_checked = True
        try:
            models = await asyncio.wait_for(asyncio.to_thread(discover_gemini_models), timeout=15)
            set_discovered("gemini", models)
            log.info("Gemini models: %s", ", ".join(models))
        except Exception as exc:  # không lấy được danh sách thì dùng danh sách có sẵn
            log.warning("Không lấy được danh sách model Gemini: %s", exc)


@asynccontextmanager
async def lifespan(app):
    await ensure_ready()
    yield
    if getattr(app.state, "db", None) is not None:
        await app.state.db.close()


app = FastAPI(title="VNSHOP Memory", lifespan=lifespan)


@app.middleware("http")
async def ready(request: Request, call_next):
    if request.url.path.startswith("/api/"):
        await ensure_ready()
    return await call_next(request)


# Đăng ký sau nên chạy trước: chưa đăng nhập thì không chạm tới Neo4j.
app.middleware("http")(auth.middleware)


@app.get("/login")
async def login_form():
    return auth.login_page() if auth.password() else RedirectResponse("/", status_code=303)


@app.post("/login")
async def login(request: Request):
    return await auth.login(request)


@app.get("/logout")
async def logout():
    return auth.logout()


@app.get("/healthz")
async def healthz():
    return {"ok": True}


def db() -> GraphDB:
    return app.state.db


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = None
    mode: str | None = None    # gemini | claude | search; bỏ trống = mặc định
    model: str | None = None


@app.get("/api/info")
async def info():
    data = await db().info()
    mode = chat_mode()
    return {**data, "chat_mode": mode, "model": model_for(mode), "models": available_models(),
            "auth": auth.password() is not None}


@app.get("/api/search")
async def search(q: str = Query(min_length=1), limit: int = Query(10, ge=1, le=50)):
    return await db().search(q, limit=limit)


@app.get("/api/entity/{entity_id}")
async def entity(entity_id: str):
    ent = await db().entity(entity_id)
    if ent is None:
        raise HTTPException(404, "Không có node này")
    return ent


@app.get("/api/graph")
async def graph(ids: str = Query(min_length=1), expand: bool = True):
    return await db().subgraph([i for i in ids.split(",") if i], expand=expand)


@app.get("/api/modules")
async def modules():
    return await db().modules()


@app.get("/api/modules/{module_key:path}/entities")
async def module_entities(module_key: str, label: str | None = None):
    return await db().module_entities(module_key, label, limit=200)


@app.get("/api/conversations")
async def conversations():
    return await db().list_conversations()


@app.get("/api/conversations/{conv_id}")
async def conversation(conv_id: str):
    conv = await db().get_conversation(conv_id)
    if conv is None:
        raise HTTPException(404, "Không có hội thoại này")
    conv.pop("api_messages", None)
    return conv


@app.delete("/api/conversations/{conv_id}")
async def delete_conversation(conv_id: str):
    await db().delete_conversation(conv_id)
    return {"ok": True}


@app.get("/api/traces/{trace_id}")
async def trace(trace_id: str):
    t = await db().get_trace(trace_id)
    if t is None:
        raise HTTPException(404, "Không có vết suy luận này")
    return t


@app.post("/api/chat")
async def chat(req: ChatRequest):
    async def events():
        async for event in run_chat(db(), req.message.strip(), req.conversation_id,
                                    mode=req.mode, model=req.model):
            yield f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


app.mount("/static", StaticFiles(directory=WEB), name="static")


@app.get("/")
async def index():
    return FileResponse(WEB / "index.html")
