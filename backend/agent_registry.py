"""Agent registry - loads and manages agents by name."""

import importlib
import logging
from pathlib import Path
from typing import Dict, Optional

from .llm_service import LLMAgent
from .config import Settings


class AgentRegistry:
    """Registry that loads agents from the agents/ folder and manages them by name."""

    def __init__(self, settings: Settings, logger: Optional[logging.Logger] = None):
        self.settings = settings
        self.logger = logger or logging.getLogger(__name__)
        self.agents: Dict[str, LLMAgent] = {}
        self.agent_modules: Dict[str, any] = {}
        
        self._load_agents()

    def _load_agents(self):
        """Load all agent definitions from the agents/ folder."""
        agents_dir = Path(__file__).parent / "agents"
        
        # Find all Python files in agents/ except __init__.py
        for agent_file in agents_dir.glob("*.py"):
            if agent_file.name == "__init__.py":
                continue
            
            module_name = agent_file.stem
            try:
                # Import the agent module
                module = importlib.import_module(f"backend.agents.{module_name}")
                
                # Validate required attributes
                required_attrs = ["AGENT_NAME", "SYSTEM_PROMPT", "MODEL", "DESCRIPTION"]
                for attr in required_attrs:
                    if not hasattr(module, attr):
                        self.logger.error(f"Agent {module_name} missing required attribute: {attr}")
                        continue
                
                agent_name = module.AGENT_NAME
                
                # Create agent configuration
                from .config import AgentConfig
                config = AgentConfig(
                    name=agent_name,
                    system_prompt=module.SYSTEM_PROMPT,
                    model=module.MODEL,
                    description=module.DESCRIPTION
                )
                
                # Create and register the agent
                agent = LLMAgent(config=config, settings=self.settings, logger=self.logger)
                self.agents[agent_name] = agent
                self.agent_modules[agent_name] = module
                
                self.logger.info(f"Registered agent: {agent_name}")
                
            except Exception as e:
                self.logger.error(f"Failed to load agent {module_name}: {e}")

    def get_agent(self, name: str) -> Optional[LLMAgent]:
        """Get an agent by name."""
        return self.agents.get(name)

    def get_agent_module(self, name: str) -> Optional[any]:
        """Get the agent module (for accessing NEXT_AGENT, COMPLETION_PHRASES, etc.)."""
        return self.agent_modules.get(name)

    def list_agents(self) -> Dict[str, dict]:
        """List all available agents with their metadata."""
        return {
            name: {
                "name": agent.name,
                "description": agent.description,
                "model": agent.config.model
            }
            for name, agent in self.agents.items()
        }

    def get_starting_agent(self) -> str:
        """Get the name of the starting agent."""
        # First agent is the inspector
        return "inspector"
