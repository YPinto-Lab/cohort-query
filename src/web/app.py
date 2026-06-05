from __future__ import annotations
import json
import os
import uuid
from pathlib import Path
from typing import Iterator

from fastapi import FastAPI, Form, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from agent.agent import Agent
from askslm.cli import workspace_new
from agent.workspace import Workspace
from agent.llm_client import LLMClient, AnthropicClient, GeminiClient
from agent.events import Event
from web.sessions_index import list_sessions, load_transcript
from web import biom_view
from web import biom_index
from web import os_open
from web.workspace_diff import snapshot, diff

from dotenv import load_dotenv

# Load GEMINI_API_KEY / GEMINI_MODEL (etc.) from a .env at the repo root if present,
# so the key is configured once on disk rather than exported in every shell.
# Does not override variables already set in the environment.
load_dotenv()

WORKSPACES_ROOT = Path(os.environ.get("ASKSLM_WORKSPACES", "./Workspaces"))


def _safe_workspace_dir(workspace: str) -> Path:
    root = WORKSPACES_ROOT.resolve()
    candidate = (WORKSPACES_ROOT / workspace).resolve()
    if not candidate.is_relative_to(root) or candidate == root:
        raise HTTPException(status_code=404, detail="workspace not found")
    return candidate


def _safe_session_path(agent_log_dir: Path, session_id: str) -> Path:
    log_root = agent_log_dir.resolve()
    candidate = (agent_log_dir / f"{session_id}.jsonl").resolve()
    if not candidate.is_relative_to(log_root) or not candidate.is_file():
        raise HTTPException(status_code=404, detail="session not found")
    return candidate


def _safe_biom_path(ws_dir: Path, rel: str) -> Path:
    candidate = (ws_dir / rel).resolve()
    if not candidate.is_relative_to(ws_dir.resolve()) or not candidate.is_file():
        raise HTTPException(status_code=404, detail="biom not found")
    return candidate


def _table_window(path: Path, tab: str, row_off: int, col_off: int):
    if tab == "samples":
        return biom_view.samples_window(path, row_off=row_off)
    if tab == "lineage":
        return biom_view.lineage_window(path, row_off=row_off)
    return biom_view.counts_window(path, row_off=row_off, col_off=col_off)


BASE = Path(__file__).parent
app = FastAPI()
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")

_AGENTS: dict[tuple[str, str], Agent] = {}


def build_llm() -> LLMClient:
    # Gemini is the default provider. Fall back to Anthropic only when its key is
    # present and Gemini's is not. With no key set, GeminiClient still constructs and
    # surfaces a clear "GEMINI_API_KEY" error on the first call.
    if os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("GEMINI_API_KEY"):
        return AnthropicClient()
    return GeminiClient()


def _cookie_session(request: Request, response: Response) -> str:
    sid = request.cookies.get("askslm_session")
    if not sid:
        sid = uuid.uuid4().hex
        response.set_cookie("askslm_session", sid, httponly=True, samesite="lax")
    return sid


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    if not WORKSPACES_ROOT.is_dir():
        workspaces = []
    else:
        workspaces = sorted([p.name for p in WORKSPACES_ROOT.iterdir() if p.is_dir()])
    return templates.TemplateResponse(request, "home.html", {"workspaces": workspaces})


@app.post("/workspaces")
def create_workspace(name: str = Form(...)):
    safe = name.strip()
    if not safe or "/" in safe or "\\" in safe or "\x00" in safe or safe.startswith("."):
        raise HTTPException(status_code=400, detail="invalid workspace name")
    if (WORKSPACES_ROOT / safe).exists():
        raise HTTPException(status_code=400, detail="workspace already exists")
    workspace_new(safe, root=WORKSPACES_ROOT)
    return RedirectResponse(url=f"/w/{safe}", status_code=303)


@app.get("/w/{workspace}", response_class=HTMLResponse)
def chat_page(workspace: str, request: Request, response: Response):
    ws_dir = _safe_workspace_dir(workspace)
    _cookie_session(request, response)
    tree = biom_index.biom_tree(ws_dir)
    first_biom = tree[0].entries[0].rel_path if tree else None
    return templates.TemplateResponse(
        request, "chat.html", {"workspace": workspace, "first_biom": first_biom})


@app.post("/w/{workspace}/messages")
def messages(workspace: str, request: Request, response: Response, message: str = Form(...)):
    ws_dir = _safe_workspace_dir(workspace)
    sid = _cookie_session(request, response)
    key = (workspace, sid)
    agent = _AGENTS.get(key)
    if agent is None:
        ws = Workspace.open(ws_dir)
        agent = Agent(workspace=ws, llm=build_llm())
        _AGENTS[key] = agent

    def event_stream() -> Iterator[bytes]:
        before = snapshot(ws_dir)
        for ev in agent.chat(message):
            data = json.dumps({"type": ev.type, **ev.payload})
            yield f"event: {ev.type}\ndata: {data}\n\n".encode()
            html = templates.get_template("_event.html").render(event=ev)
            yield f"event: html\ndata: {json.dumps(html)}\n\n".encode()
        changed = diff(before, snapshot(ws_dir))
        if changed:
            files_html = templates.get_template("_files.html").render(
                workspace=workspace, changed=changed)
            yield f"event: html\ndata: {json.dumps(files_html)}\n\n".encode()

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/w/{workspace}/open")
def open_in_app(workspace: str, path: str = Form(...)):
    ws_dir = _safe_workspace_dir(workspace)
    candidate = (ws_dir / path).resolve()
    if not candidate.is_relative_to(ws_dir.resolve()) or not candidate.exists():
        raise HTTPException(status_code=404, detail="path not found")
    return os_open.open_path(candidate)


@app.get("/w/{workspace}/sessions", response_class=HTMLResponse)
def sessions(workspace: str, request: Request):
    ws = Workspace.open(_safe_workspace_dir(workspace))
    entries = list_sessions(ws.agent_log_dir)
    return templates.TemplateResponse(request, "sessions.html", {"workspace": workspace, "entries": entries})


@app.get("/w/{workspace}/sessions/{session_id}", response_class=HTMLResponse)
def replay(workspace: str, session_id: str, request: Request):
    ws = Workspace.open(_safe_workspace_dir(workspace))
    path = _safe_session_path(ws.agent_log_dir, session_id)
    records = load_transcript(path)
    return templates.TemplateResponse(request, "replay.html", {"workspace": workspace, "records": records})


@app.get("/w/{workspace}/biom", response_class=HTMLResponse)
def biom_shell(workspace: str, request: Request, path: str, tab: str = "counts"):
    ws_dir = _safe_workspace_dir(workspace)
    biom_path = _safe_biom_path(ws_dir, path)
    window = _table_window(biom_path, tab, 0, 0)
    return templates.TemplateResponse(request, "_biom.html", {
        "workspace": workspace, "path": path, "tab": tab, "w": window,
        "tree": biom_index.biom_tree(ws_dir),
    })


@app.get("/w/{workspace}/biom/table", response_class=HTMLResponse)
def biom_table(workspace: str, request: Request, path: str,
               tab: str = "counts",
               row_off: int = Query(default=0, ge=0),
               col_off: int = Query(default=0, ge=0)):
    ws_dir = _safe_workspace_dir(workspace)
    biom_path = _safe_biom_path(ws_dir, path)
    window = _table_window(biom_path, tab, row_off, col_off)
    return templates.TemplateResponse(request, "_biom_table.html", {
        "workspace": workspace, "path": path, "tab": tab, "w": window,
    })
