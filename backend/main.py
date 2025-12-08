import time
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from .agent_registry import AgentRegistry
from .chat_orchestrator import ChatOrchestrator
from .config import get_settings
from .logging_config import setup_logging
from .schemas import ChatRequest, ChatResponse
from .session import SessionStore

settings = get_settings()
logger = setup_logging(settings.log_level)

app = FastAPI(
    title="KPI2KVI Backend",
    version="0.1.0",
    description="Receives frontend requests and proxies chat traffic to an LLM via OpenRouter.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize session store
session_store = SessionStore(ttl_seconds=settings.session_ttl_seconds, logger=logger)

# Initialize agent registry (loads all agents from agents/ folder)
agent_registry = AgentRegistry(settings=settings, logger=logger)

# Initialize chat orchestrator
chat_orchestrator = ChatOrchestrator(agent_registry=agent_registry, logger=logger)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Request logging middleware with latency capture."""

    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    logger.info(
        "Handled request",
        extra={
            "path": request.url.path,
            "method": request.method,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
            "client": request.client.host if request.client else None,
        },
    )
    return response


@app.get("/api/health")
async def healthcheck() -> Dict[str, str]:
    return {"status": "ok", "service": "kpi2kvi-backend"}


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Chat endpoint that keeps session context and forwards to the multi-agent LLM pipeline."""

    try:
        # Get starting agent from orchestrator (only used for new sessions)
        starting_agent = chat_orchestrator.get_starting_agent()
        session = await session_store.get_or_create(request.session_id, starting_agent=starting_agent)
        
        # Get session-specific logger
        session_logger = session_store.get_session_logger(session.session_id)
        
        # Process message through chat orchestrator
        reply, history, new_agent_name = await chat_orchestrator.process_message(
            request.message,
            session.messages,
            session.current_agent,
            session_logger=session_logger
        )
        
        # Update session with new history and agent name
        await session_store.replace_history(session.session_id, history)
        
        # Update the current agent in the session
        async with session_store.lock:
            if session.session_id in session_store.sessions:
                session_store.sessions[session.session_id].current_agent = new_agent_name

        logger.info(
            "Chat turn complete",
            extra={
                "session_id": session.session_id,
                "history_len": len(history),
                "agent_name": new_agent_name,
            },
        )
        
        if session_logger:
            session_logger.info(f"Chat turn complete - Total messages: {len(history)}, Current agent: {new_agent_name}")
        
        return ChatResponse(session_id=session.session_id, reply=reply, history=history)
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Chat request failed")
        raise HTTPException(status_code=500, detail="LLM request failed") from exc


@app.get("/api/agents")
async def get_agents() -> Dict[str, Any]:
    """Get information about all available agents."""
    agents_info = agent_registry.list_agents()
    return {
        "agents": [
            {
                "name": info["name"],
                "description": info["description"],
                "model": info["model"]
            }
            for info in agents_info.values()
        ],
        "total_agents": len(agents_info)
    }


@app.get("/api/session/{session_id}/agent")
async def get_current_agent(session_id: str) -> Dict[str, Any]:
    """Get the current agent for a session."""
    try:
        session = await session_store.get_or_create(session_id)
        current_agent_name = session.current_agent
        
        all_agents = agent_registry.list_agents()
        
        return {
            "current_agent": current_agent_name,
            "agent_info": all_agents.get(current_agent_name, {}),
            "all_agents": list(all_agents.keys())
        }
    except Exception as exc:
        logger.exception("Failed to get agent status")
        raise HTTPException(status_code=500, detail="Failed to get agent status") from exc


@app.get("/")
async def root():
    return {"message": "KPI2KVI backend is running"}
