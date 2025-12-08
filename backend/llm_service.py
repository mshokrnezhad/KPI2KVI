import logging
from typing import Optional

from openai import AsyncOpenAI
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openrouter import OpenRouterProvider

from .config import AgentConfig, Settings


class LLMAgent:
    """Individual LLM agent wrapper for PydanticAI."""

    def __init__(
        self,
        config: AgentConfig,
        settings: Settings,
        logger: Optional[logging.Logger] = None
    ):
        self.config = config
        self.settings = settings
        self.logger = logger or logging.getLogger(__name__)

        # Create OpenRouter provider with custom client
        client = AsyncOpenAI(
            api_key=settings.openrouter_api_key,
            base_url=settings.openrouter_base_url,
            timeout=120.0,
        )
        provider = OpenRouterProvider(
            api_key=settings.openrouter_api_key,
            openai_client=client,
        )
        
        # Initialize the agent
        model = OpenAIModel(
            model_name=config.model,
            provider=provider,
        )
        self.agent = Agent(model=model, system_prompt=config.system_prompt)
        
        self.logger.info(
            f"Initialized agent: {config.name}",
            extra={"agent": config.name, "model": config.model}
        )

    async def run(self, prompt: str) -> str:
        """Run the agent with the given prompt and return the response."""
        result = await self.agent.run(prompt)
        # PydanticAI's AgentRunResult has an 'output' attribute containing the actual message
        response_text = str(result.output)
        return response_text

    @property
    def name(self) -> str:
        """Get the agent's name."""
        return self.config.name

    @property
    def description(self) -> str:
        """Get the agent's description."""
        return self.config.description
