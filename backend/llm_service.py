import logging
import os
from typing import Any, Optional

from pydantic_ai import Agent

from .config import AgentConfig, Settings


class LLMAgent:
    """Individual LLM agent wrapper for PydanticAI."""

    def __init__(
        self,
        config: AgentConfig,
        settings: Settings,
        logger: Optional[logging.Logger] = None,
        result_type: Optional[type] = None
    ):
        self.config = config
        self.settings = settings
        self.logger = logger or logging.getLogger(__name__)
        self.result_type = result_type

        # In pydantic-ai 0.0.19, configure OpenAI-compatible API via environment variables
        # Set environment variables for OpenRouter
        os.environ['OPENAI_API_KEY'] = settings.openrouter_api_key
        os.environ['OPENAI_BASE_URL'] = settings.openrouter_base_url
        
        # Use model string with openai: prefix for OpenAI-compatible APIs
        model_str = f"openai:{config.model}"
        
        # Create agent with result_type if specified for structured output
        # In pydantic-ai 0.0.19, result_type is a constructor parameter
        if result_type:
            self.agent = Agent(
                model_str,
                result_type=result_type,
                system_prompt=config.system_prompt
            )
        else:
            self.agent = Agent(model_str, system_prompt=config.system_prompt)
        
        self.logger.info(
            f"Initialized agent: {config.name}",
            extra={"agent": config.name, "model": config.model, "structured_output": result_type is not None}
        )

    async def run(self, prompt: str) -> str | Any:
        """Run the agent with the given prompt and return the response."""
        # If result_type is specified, agent was created with structured output
        if self.result_type:
            self.logger.info(f"Agent {self.config.name} using structured output with result_type: {self.result_type.__name__}")
            result = await self.agent.run(prompt)
            # In pydantic-ai 0.0.19, structured output is in result.data
            self.logger.info(f"Structured output received, type: {type(result.data).__name__}")
            return result.data
        else:
            result = await self.agent.run(prompt)
            # Plain text output is also in result.data
            return str(result.data)


    @property
    def name(self) -> str:
        """Get the agent's name."""
        return self.config.name

    @property
    def description(self) -> str:
        """Get the agent's description."""
        return self.config.description
