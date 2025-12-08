import logging
from typing import Optional, Tuple, List

from .agent_registry import AgentRegistry
from .session import ChatMessage


class ChatOrchestrator:
    """
    Orchestrates the KPI to KVI mapping workflow.
    
    Workflow:
    1. Inspector agent asks questions to gather information
    2. When inspector completes, automatically triggers summarizer
    3. Summarizer provides comprehensive KPI to KVI mapping
    """

    def __init__(
        self,
        agent_registry: AgentRegistry,
        logger: Optional[logging.Logger] = None
    ):
        self.registry = agent_registry
        self.logger = logger or logging.getLogger(__name__)
    
    def get_starting_agent(self) -> str:
        """Return the name of the agent that starts the workflow."""
        return "inspector"

    def _render_prompt(self, history: List[ChatMessage], latest: str) -> str:
        """Render conversation history as a prompt."""
        if not history:
            return latest
        
        preamble = "Conversation so far:\n"
        lines = [f"{m.role}: {m.content}" for m in history]
        lines.append(f"user: {latest}")
        return preamble + "\n".join(lines)

    def _is_inspector_complete(self, response: str) -> bool:
        """Check if inspector agent has finished gathering information."""
        inspector_module = self.registry.get_agent_module("inspector")
        if not inspector_module or not hasattr(inspector_module, "COMPLETION_PHRASES"):
            return False
        
        response_lower = response.lower()
        return any(phrase in response_lower for phrase in inspector_module.COMPLETION_PHRASES)

    async def process_message(
        self,
        message: str,
        history: List[ChatMessage],
        current_agent_name: str,
        session_logger: Optional[logging.Logger] = None
    ) -> Tuple[str, List[ChatMessage], str]:
        """
        Process a user message through the workflow.
        
        Args:
            message: User's message
            history: Conversation history
            current_agent_name: Name of currently active agent
            session_logger: Optional session-specific logger
            
        Returns:
            Tuple of (response_text, updated_history, new_agent_name)
        """
        agent = self.registry.get_agent(current_agent_name)
        if not agent:
            raise ValueError(f"Unknown agent: {current_agent_name}")
        
        # Use session logger if available, otherwise use default
        log = session_logger or self.logger
        
        log.info(f"Processing message with agent: {current_agent_name}")
        log.info(f"User message: {message}")

        # Render prompt with conversation history
        prompt = self._render_prompt(history, message)
        
        # Run the current agent
        log.info(f"Calling {current_agent_name} agent")
        response_text = await agent.run(prompt)
        log.info(f"Agent response length: {len(response_text)} chars")

        # Update history with user message and agent response
        updated_history = list(history)
        updated_history.append(ChatMessage(role="user", content=message))
        updated_history.append(ChatMessage(role="assistant", content=response_text))

        # Workflow logic: inspector -> summarizer
        if current_agent_name == "inspector":
            if self._is_inspector_complete(response_text):
                log.info("Inspector completed, automatically triggering summarizer")
                
                # Automatically call summarizer with the gathered information
                summarizer = self.registry.get_agent("summarizer")
                if summarizer:
                    summary_prompt = self._render_prompt(
                        updated_history,
                        "Please provide a comprehensive summary of the given conversation."
                    )
                    
                    log.info("Calling summarizer agent")
                    summary_response = await summarizer.run(summary_prompt)
                    log.info(f"Summarizer response length: {len(summary_response)} chars")
                    
                    # Add system transition message
                    response_text += summary_response
                    
                    # Update history with summarizer's response
                    updated_history.append(ChatMessage(
                        role="user",
                        content="Please provide a comprehensive summary of the given conversation."
                    ))
                    updated_history.append(ChatMessage(role="assistant", content=summary_response))
                    
                    # Move to summarizer agent for any follow-up questions
                    log.info("Transitioned to summarizer agent")
                    return response_text, updated_history, "summarizer"
        
        # Stay with current agent (or already transitioned above)
        return response_text, updated_history, current_agent_name
