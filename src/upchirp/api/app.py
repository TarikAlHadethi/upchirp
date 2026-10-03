"""FastAPI: REST for queries and chat, a WebSocket for the live view.

    GET  /api/health
    GET  /api/sessions
    GET  /api/summary?session=latest
    GET  /api/tracks?session=latest&label=drone_like&last_minutes=10
    POST /api/ask                     {"question": "..."}
    POST /api/ask/{thread_id}/decision {"approve": true|false}
    WS   /ws/live                     tracks, detections and range-Doppler images as they arrive

The built UI (ui/dist) is served at /. In public mode (UPCHIRP_PUBLIC=1) the
agent only has read tools, so there is nothing to approve.
"""

import asyncio
import contextlib
import json
import os
import threading
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from upchirp import metrics, stream, telemetry
from upchirp.agent import data
from upchirp.agent.costs import cost_usd, tokens
from upchirp.api.guard import Limited, PublicGuard

UI_DIST = Path(os.environ.get("UPCHIRP_UI_DIST",
                              Path(__file__).resolve().parents[3] / "ui" / "dist"))
LIVE_TOPICS = [stream.TRACKS, stream.DETECTIONS, stream.RDMAPS]


class Broadcaster:
    """Reads the live topics on a thread and fans the newest messages out to WebSockets.

    Slow clients drop old messages instead of building a backlog."""

    def __init__(self) -> None:
        self.clients: set[asyncio.Queue[str]] = set()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.stop = threading.Event()
        self.thread: threading.Thread | None = None

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        self.thread = threading.Thread(target=self._run, daemon=True, name="broadcaster")
        self.thread.start()

    def _run(self) -> None:
        try:
            stream.ensure_topics()
        except Exception:
            pass  # broker not up yet; the consumer below retries
        cons = stream.consumer(f"upchirp-api-{uuid.uuid4().hex[:8]}", LIVE_TOPICS)
        try:
            for item in stream.messages(cons, timeout_s=0.2):
                if self.stop.is_set():
                    return
                if item is None or self.loop is None:
                    continue
                topic, value = item
                text = json.dumps({"type": topic, **json.loads(value)})
                self.loop.call_soon_threadsafe(self._fan_out, text)
        except Exception:  # broker gone: the REST API keeps working without live data
            return
        finally:
            cons.close()

    def _fan_out(self, text: str) -> None:
        for q in self.clients:
            if q.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    q.get_nowait()
            q.put_nowait(text)


class Question(BaseModel):
    question: str = Field(min_length=2, max_length=1000)


class Decision(BaseModel):
    approve: bool


def _turn(turn: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in turn.items() if k != "messages"}


def create_app(data_dir: Path, live: bool = True, public: bool | None = None) -> FastAPI:
    broadcaster = Broadcaster()
    agent_box: dict[str, Any] = {}
    if public is None:
        public = os.environ.get("UPCHIRP_PUBLIC") == "1"
    guard = PublicGuard() if public else None

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if live:
            broadcaster.start(asyncio.get_running_loop())
        yield
        broadcaster.stop.set()

    app = FastAPI(title="Upchirp", lifespan=lifespan)
    telemetry.setup("api")
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
    except ImportError:
        pass

    def agent() -> Any:
        if "agent" not in agent_box:
            from upchirp.agent.graph import Agent

            agent_box["agent"] = Agent(data_dir, public=public)
        return agent_box["agent"]

    def guarded(fn: Any, *args: Any) -> Any:
        try:
            return fn(*args)
        except FileNotFoundError as e:
            raise HTTPException(404, str(e)) from None
        except ValueError as e:
            raise HTTPException(400, str(e)) from None

    from prometheus_client import make_asgi_app

    app.mount("/metrics", make_asgi_app())

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        out: dict[str, Any] = {"ok": True, "public": public,
                               "live_clients": len(broadcaster.clients)}
        if guard is not None:
            out.update(guard.status())
        return out

    @app.get("/api/sessions")
    def sessions() -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = guarded(data.list_sessions, data_dir)
        return result

    @app.get("/api/summary")
    def summary(session: str = "latest") -> dict[str, Any]:
        result: dict[str, Any] = guarded(data.session_summary, data_dir, session)
        return result

    @app.get("/api/tracks")
    def tracks(session: str = "latest", label: str | None = None,
               last_minutes: float | None = Query(None, gt=0)) -> dict[str, Any]:
        result: dict[str, Any] = guarded(data.track_summaries, data_dir, session, label,
                                         last_minutes)
        return result

    @app.post("/api/ask")
    async def ask(q: Question, request: Request) -> dict[str, Any]:
        with metrics.ANSWER_SECONDS.time():
            try:
                turn = await _ask(q, request)
            except HTTPException:
                metrics.QUESTIONS.labels("refused").inc()
                raise
            except Exception:
                metrics.QUESTIONS.labels("error").inc()
                raise
        metrics.QUESTIONS.labels(turn["status"]).inc()
        return turn

    async def _ask(q: Question, request: Request) -> dict[str, Any]:
        if guard is None:
            return _turn(await agent().start(q.question))
        visitor = request.client.host if request.client else "unknown"
        try:
            guard.check(visitor)
        except Limited as e:
            raise HTTPException(e.status, e.message) from None
        from upchirp.agent.graph import model_id

        inp = out = 0
        cost = guard.reserve_usd  # if the answer fails part way, its tokens were still spent
        try:
            turn = await agent().start(q.question)
            inp, out = tokens(turn.get("messages", []))
            cost = cost_usd(model_id(), inp, out)
        finally:
            guard.record(inp, out, cost)
        return _turn(turn)

    @app.post("/api/ask/{thread_id}/decision")
    async def decide(thread_id: str, d: Decision) -> dict[str, Any]:
        if public:
            raise HTTPException(403, "Nothing to approve on the public demo.")
        return _turn(await agent().resume(thread_id, d.approve))

    @app.websocket("/ws/live")
    async def live_ws(ws: WebSocket) -> None:
        await ws.accept()
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=30)
        broadcaster.clients.add(q)
        metrics.LIVE_CLIENTS.set(len(broadcaster.clients))
        try:
            while True:
                await ws.send_text(await q.get())
        except WebSocketDisconnect:
            pass
        finally:
            broadcaster.clients.discard(q)
            metrics.LIVE_CLIENTS.set(len(broadcaster.clients))

    if UI_DIST.exists():
        app.mount("/", StaticFiles(directory=UI_DIST, html=True), name="ui")
    return app
