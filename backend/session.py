import asyncio
import time
import uuid
from typing import Dict, List, Optional
import logging

from pydantic import BaseModel

from .logging_config import get_session_logger, close_session_logger


class ChatMessage(BaseModel):
    role: str
    content: str


class SessionState(BaseModel):
    session_id: str
    messages: List[ChatMessage]
    updated_at: float
    current_agent: str  # Track which agent is currently active by name


class SessionStore:
    """In-memory session store with TTL cleanup."""

    def __init__(self, ttl_seconds: int, logger):
        self.ttl_seconds = ttl_seconds
        self.sessions: Dict[str, SessionState] = {}
        self.lock = asyncio.Lock()
        self.logger = logger  # Main app logger
        self.session_loggers: Dict[str, logging.Logger] = {}  # Session-specific loggers

    async def get_or_create(self, session_id: Optional[str] = None, starting_agent: str = None) -> SessionState:
        async with self.lock:
            self._prune()
            if session_id and session_id in self.sessions:
                session = self.sessions[session_id]
                session.updated_at = time.time()
                return session

            if not starting_agent:
                raise ValueError("starting_agent must be provided when creating a new session")

            new_session = SessionState(
                session_id=session_id or str(uuid.uuid4()),
                messages=[],
                updated_at=time.time(),
                current_agent=starting_agent,
            )
            self.sessions[new_session.session_id] = new_session
            
            # Create session-specific logger
            session_logger = get_session_logger(new_session.session_id)
            self.session_loggers[new_session.session_id] = session_logger
            
            # Log to both main app logger and session logger
            self.logger.info("Created new chat session", extra={"session_id": new_session.session_id, "starting_agent": starting_agent})
            session_logger.info(f"New session created with starting agent: {starting_agent}")
            
            return new_session

    async def append(self, session_id: str, role: str, content: str) -> SessionState:
        async with self.lock:
            self._prune()
            if session_id not in self.sessions:
                raise KeyError(f"session {session_id} not found")
            session = self.sessions[session_id]
            session.messages.append(ChatMessage(role=role, content=content))
            session.updated_at = time.time()
            
            # Log to session-specific logger
            if session_id in self.session_loggers:
                session_logger = self.session_loggers[session_id]
                session_logger.info(f"Message added - Role: {role}, Content length: {len(content)} chars")
            
            return session

    async def replace_history(self, session_id: str, messages: List[ChatMessage]) -> SessionState:
        async with self.lock:
            self._prune()
            if session_id not in self.sessions:
                raise KeyError(f"session {session_id} not found")
            session = self.sessions[session_id]
            session.messages = list(messages)
            session.updated_at = time.time()
            
            # Log to session-specific logger
            if session_id in self.session_loggers:
                session_logger = self.session_loggers[session_id]
                session_logger.info(f"History replaced - Total messages: {len(messages)}")
            
            return session

    def _prune(self) -> None:
        if not self.ttl_seconds:
            return
        cutoff = time.time() - self.ttl_seconds
        expired = [sid for sid, data in self.sessions.items() if data.updated_at < cutoff]
        for sid in expired:
            self.sessions.pop(sid, None)
            self.logger.info("Pruned expired session", extra={"session_id": sid})
            
            # Close session logger
            if sid in self.session_loggers:
                close_session_logger(sid)
                del self.session_loggers[sid]
    
    def get_session_logger(self, session_id: str) -> Optional[logging.Logger]:
        """Get the logger for a specific session."""
        return self.session_loggers.get(session_id)
