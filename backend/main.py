import json
import time
from typing import Any, AsyncGenerator, Dict

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .agent_registry import AgentRegistry
from .chat_orchestrator import ChatOrchestrator
from .config import get_settings
from .logging_config import setup_logging
from .schemas import ChatRequest, ChatResponse
from .session import ChatMessage, SessionStore

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


@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest):
    """Streaming chat endpoint that sends real-time updates via Server-Sent Events."""
    
    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            # Get starting agent from orchestrator (only used for new sessions)
            starting_agent = chat_orchestrator.get_starting_agent()
            session = await session_store.get_or_create(request.session_id, starting_agent=starting_agent)
            
            # Get session-specific logger
            session_logger = session_store.get_session_logger(session.session_id)
            
            # Send initial connection event with session ID
            yield f"data: {json.dumps({'type': 'connected', 'session_id': session.session_id, 'agent': session.current_agent})}\n\n"
            
            # Track the complete response and history for final update
            final_response = ""
            final_history = None
            final_agent = session.current_agent
            
            # Process message through chat orchestrator with streaming
            async for event in chat_orchestrator.process_message_stream(
                request.message,
                session.messages,
                session.current_agent,
                session_logger=session_logger
            ):
                # Forward all events to client
                yield f"data: {json.dumps(event)}\n\n"
                
                # Track final state
                if event.get('type') == 'complete':
                    final_response = event.get('final_response', '')
                    final_history = event.get('history', [])
                    final_agent = event.get('current_agent', session.current_agent)
            
            # Update session with new history and agent
            if final_history is not None:
                # Convert dict back to ChatMessage objects
                history_objects = [ChatMessage(**msg) for msg in final_history]
                await session_store.replace_history(session.session_id, history_objects)
                
                # Update the current agent in the session
                async with session_store.lock:
                    if session.session_id in session_store.sessions:
                        session_store.sessions[session.session_id].current_agent = final_agent
            
            logger.info(
                "Streaming chat turn complete",
                extra={
                    "session_id": session.session_id,
                    "history_len": len(final_history) if final_history else 0,
                    "agent_name": final_agent,
                },
            )
            
            if session_logger:
                session_logger.info(
                    f"Streaming chat turn complete - Total messages: {len(final_history) if final_history else 0}, "
                    f"Current agent: {final_agent}"
                )
            
            # Send final done event
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            
        except Exception as exc:
            logger.exception("Streaming chat request failed")
            yield f"data: {json.dumps({'type': 'error', 'message': 'Processing failed. Please try again.'})}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable buffering for nginx
        }
    )


@app.get("/")
async def root():
    return {"message": "KPI2KVI backend is running"}
