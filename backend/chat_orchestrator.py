import json
import logging
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any

from .agent_registry import AgentRegistry
from .session import ChatMessage
from .schemas import KVICategoryResponse


class ChatOrchestrator:
    """
    Orchestrates the KPI to KVI mapping workflow.
    
    Workflow:
    1. Inspector agent asks questions to gather information
    2. When inspector completes, automatically triggers kvi_cat_extractor
    3. KVI Category Extractor identifies and returns relevant KVI categories
    """

    def __init__(
        self,
        agent_registry: AgentRegistry,
        logger: Optional[logging.Logger] = None
    ):
        self.registry = agent_registry
        self.logger = logger or logging.getLogger(__name__)
        self.kvi_data = self._load_kvi_data()
    
    def _load_kvi_data(self) -> List[Dict[str, Any]]:
        """Load KVI categories from kvis.json."""
        kvi_file = Path(__file__).parent / "data" / "kvis.json"
        try:
            with open(kvi_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            self.logger.error(f"Failed to load KVI data: {e}")
            return []
    
    def _get_category_names(self, main_id: str, sub_id: str) -> Tuple[str, str]:
        """Get the names of main category and subcategory by their IDs."""
        for main_category in self.kvi_data:
            if main_category["id"] == main_id:
                main_name = main_category["name"]
                for sub_category in main_category["categories"]:
                    if sub_category["id"] == sub_id:
                        return main_name, sub_category["name"]
        return f"Unknown ({main_id})", f"Unknown ({sub_id})"
    
    def _format_kvi_categories(self, kvi_response: KVICategoryResponse) -> str:
        """Format KVI categories into a readable response for the user."""
        if not kvi_response.categories:
            return "\n\nNo relevant KVI categories identified."
        
        response = "\n\nBased on our conversation, here are the most relevant KVI categories for your service:\n\n"
        
        for idx, category_item in enumerate(kvi_response.categories, 1):
            main_name, sub_name = self._get_category_names(
                category_item.main_id,
                category_item.sub_id
            )
            response += f"{idx}. {main_name} → {sub_name}\n"
            # response += f"   _(Category ID: {category_item.main_id}, Subcategory ID: {category_item.sub_id})_\n\n"
        
        response += "\n💡 These categories represent the key value indicators that align with your service."
        return response
    
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

        # Workflow logic: inspector -> kvi_cat_extractor
        if current_agent_name == "inspector":
            if self._is_inspector_complete(response_text):
                log.info("Inspector completed, automatically triggering kvi_cat_extractor")
                
                # Automatically call kvi_cat_extractor with the gathered information
                kvi_extractor = self.registry.get_agent("kvi_cat_extractor")
                if kvi_extractor:
                    extractor_prompt = self._render_prompt(
                        updated_history,
                        "Please identify the most relevant KVI categories based on this conversation."
                    )
                    
                    log.info("Calling kvi_cat_extractor agent")
                    extractor_response = await kvi_extractor.run(extractor_prompt)
                    
                    # Log the response type and content for debugging
                    log.info(f"KVI extractor response type: {type(extractor_response).__name__}")
                    if isinstance(extractor_response, str):
                        log.debug(f"Response is string (first 200 chars): {extractor_response[:200]}")

                    # The correct path is only when we have KVICategoryResponse, otherwise terminate with a message
                    if isinstance(extractor_response, KVICategoryResponse):
                        log.info(f"KVI extractor returned {len(extractor_response.categories)} KVI categories")

                        # Format the KVI categories into a readable response
                        formatted_response = self._format_kvi_categories(extractor_response)
                        response_text += formatted_response

                        # Store the formatted response in history
                        updated_history.append(ChatMessage(
                            role="user",
                            content="Please identify the most relevant KVI categories based on this conversation."
                        ))
                        updated_history.append(ChatMessage(role="assistant", content=formatted_response))
                    else:
                        # If not the expected structured response, terminate with proper message
                        log.error("KVI extractor did not return a structured KVICategoryResponse. Terminating workflow.")
                        response_text += (
                            "\n\nSorry, I was unable to retrieve the KVI categories due to an unexpected response "
                            "from the extractor. Please try again later or contact support."
                        )
                        updated_history.append(ChatMessage(
                            role="user",
                            content="Please identify the most relevant KVI categories based on this conversation."
                        ))
                        updated_history.append(ChatMessage(
                            role="assistant",
                            content=(
                                "Sorry, I was unable to retrieve the KVI categories due to an unexpected response "
                                "from the extractor. Please try again later or contact support."
                            )
                        ))
                        return response_text, updated_history, current_agent_name
                    # Move to kvi_cat_extractor agent for any follow-up questions
                    log.info("Transitioned to kvi_cat_extractor agent")
                    return response_text, updated_history, "kvi_cat_extractor"
        
        # Stay with current agent (or already transitioned above)
        return response_text, updated_history, current_agent_name
