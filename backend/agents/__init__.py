"""
Agents package - each agent is a self-contained module.

To add a new agent:
1. Create a new .py file in this folder (e.g., validator.py)
2. Define these required attributes:
   - AGENT_NAME: str (unique name)
   - SYSTEM_PROMPT: str (instructions for the agent)
   - MODEL: str (OpenRouter model name)
   - DESCRIPTION: str (what the agent does)
3. Optionally define COMPLETION_PHRASES for workflow transitions
4. Update chat_orchestrator.py to wire it into your workflow

The agent will be automatically loaded by AgentRegistry.
"""
