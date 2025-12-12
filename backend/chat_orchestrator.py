import json
import logging
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any, AsyncGenerator

from .agent_registry import AgentRegistry
from .session import ChatMessage
from .schemas import KVICategoryResponse, FinalKVICategoryResponse, KPIResponse, KVICalculationResponse, CollectedKPIResponse

class ChatOrchestrator:
    """
    Orchestrates the KPI to KVI mapping workflow.
    
    Workflow:
    1. Inspector agent asks questions to gather information
    2. When inspector completes, automatically triggers kvi_cat_extractor
    3. KVI Category Extractor identifies and returns relevant KVI categories
    4. KVI Category Evaluator conducts interactive chat to refine the categories
    5. When evaluator completes, automatically triggers kvi_cat_finalizer
    6. KVI Category Finalizer generates final structured output based on user feedback
    7. When finalizer completes, automatically triggers kpi_generator
    8. KPI Generator creates service-specific KPIs for calculating the extracted KVIs
    9. When KPI generator completes, automatically triggers kpi_collector
    10. KPI Collector (6th agent) interacts with user to collect actual values for each KPI (conversational, no structured output)
    11. When KPI collector completes, automatically triggers kpi_structurer
    12. KPI Structurer (7th agent) extracts collected KPI values from conversation into structured format
    13. When KPI structurer completes, automatically triggers kvi_calculator
    14. KVI Calculator (8th agent) loops through each KVI category and calculates values based on collected KPIs
    15. When KVI calculator completes, automatically triggers kvi_advisor
    16. KVI Advisor (9th agent) helps user with questions, clarifications, and recalculations
    
    Agent Response Storage:
    - Each agent's response is automatically saved when it completes its work
    - Stored data includes: response text, conversation history, and structured output (if applicable)
    - Responses can be accessed via get_agent_response(agent_name)
    - This enables subsequent agents to use outputs from previous agents as inputs
    
    Data Flow:
    - Inspector → Extractor: Complete Q&A conversation
    - Extractor → Evaluator: Structured KVI categories
    - Extractor + Evaluator → Finalizer: Initial categories + refinement conversation
    - Inspector + Finalizer → KPI Generator: Service understanding + final KVIs
    - KPI Generator → KPI Collector: Structured KPIs to collect values for (conversation only, no structured output)
    - KPI Generator + Collector conversation → KPI Structurer: Extracts structured KPI values from conversation
    - Finalizer + Structurer → KVI Calculator: KVI categories + structured KPI values → calculate exact/min/max for each KVI
    - Calculator → KVI Advisor: All calculated KVI results + context for user questions/clarifications
    """

    def __init__(
        self,
        agent_registry: AgentRegistry,
        logger: Optional[logging.Logger] = None
    ):
        self.registry = agent_registry
        self.logger = logger or logging.getLogger(__name__)
        self.kvi_data = self._load_kvi_data()
        self.extracted_categories: Optional[KVICategoryResponse] = None
        self.agent_responses: Dict[str, Dict[str, Any]] = {}
    
    def _load_kvi_data(self) -> List[Dict[str, Any]]:
        """Load KVI categories from kvi_cats.json."""
        kvi_file = Path(__file__).parent / "data" / "kvi_cats.json"
        try:
            with open(kvi_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            self.logger.error(f"Failed to load KVI data: {e}")
            return []
    
    def _save_agent_response(
        self,
        agent_name: str,
        response: Any,
        history: List[ChatMessage],
        structured_output: Optional[Any] = None
    ) -> None:
        """
        Save an agent's response for use in subsequent workflow steps.
        
        Args:
            agent_name: Name of the agent
            response: The agent's response (usually a string)
            history: Conversation history at the time of completion
            structured_output: Any structured output (e.g., KVICategoryResponse)
        """
        self.agent_responses[agent_name] = {
            'response': response,
            'history': [msg.dict() for msg in history],
            'structured_output': structured_output,
            'completed_at': None  # Could add timestamp if needed
        }
        self.logger.info(f"Saved response from {agent_name} agent")
    
    def get_agent_response(self, agent_name: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve a saved agent response.
        
        Args:
            agent_name: Name of the agent
            
        Returns:
            Dictionary containing the agent's response data or None if not found
        """
        return self.agent_responses.get(agent_name)
    
    def get_inspector_conversation_summary(self) -> str:
        """
        Get a formatted summary of the inspector's conversation.
        This can be used as context for subsequent agents.
        
        Returns:
            Formatted string with the inspector's conversation
        """
        inspector_data = self.get_agent_response("inspector")
        if not inspector_data:
            return "No inspector conversation available."
        
        history = inspector_data.get('history', [])
        summary = "# Inspector Conversation Summary\n\n"
        
        for msg in history:
            role = msg.get('role', 'unknown')
            content = msg.get('content', '')
            if role == 'user':
                summary += f"**User**: {content}\n\n"
            elif role == 'assistant':
                summary += f"**Assistant**: {content}\n\n"
        
        return summary
    
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
        
        response = "\n\n## 🎯 Identified KVI Categories\n\n"
        response += "Based on our conversation, here are the most relevant KVI categories for your service:\n\n"
        
        for idx, category_item in enumerate(kvi_response.categories, 1):
            main_name, sub_name = self._get_category_names(
                category_item.main_id,
                category_item.sub_id
            )
            response += f"**{idx}.** {main_name} → **{sub_name}**\n\n"
            # response += f"   _(Category ID: {category_item.main_id}, Subcategory ID: {category_item.sub_id})_\n\n"
        
        response += "---\n\n<br>\n\n"
        response += "💡 *These categories represent the key value indicators that align with your service.*\n\n<br>\n\n"
        return response
    
    def _build_extractor_prompt(self, history: List[ChatMessage]) -> str:
        """
        Build prompt for kvi_cat_extractor using the inspector's interview.
        
        Args:
            history: Conversation history from the inspector
            
        Returns:
            Formatted prompt with the inspector's conversation
        """
        # Get the saved inspector conversation
        inspector_data = self.get_agent_response("inspector")
        
        prompt = "# INSPECTOR INTERVIEW\n\n"
        prompt += "Below is the complete conversation between the inspector and the user:\n\n"
        
        if inspector_data:
            # Use the saved inspector history
            for msg in inspector_data['history']:
                role = msg.get('role', 'unknown')
                content = msg.get('content', '')
                if role == 'user':
                    prompt += f"**User**: {content}\n\n"
                elif role == 'assistant':
                    prompt += f"**Inspector**: {content}\n\n"
        else:
            # Fallback to current history
            for msg in history:
                if msg.role == 'user':
                    prompt += f"**User**: {msg.content}\n\n"
                elif msg.role == 'assistant':
                    prompt += f"**Inspector**: {msg.content}\n\n"
        
        prompt += "\n---\n\n"
        prompt += "Based on this conversation, identify the most relevant KVI categories for the user's service."
        
        return prompt
    
    def _build_evaluator_context(self) -> str:
        """
        Build context for kvi_cat_evaluator with extracted categories and full KVI data.
        Uses the structured output from kvi_cat_extractor.
        """
        context = "# EXTRACTED KVI CATEGORIES (STRUCTURED OUTPUT)\n\n"
        
        # Get the structured output from the extractor
        extractor_data = self.get_agent_response("kvi_cat_extractor")
        if extractor_data and extractor_data.get('structured_output'):
            structured_output = extractor_data['structured_output']
            context += "The following categories were extracted by the KVI Category Extractor:\n\n"
            
            for idx, category_item in enumerate(structured_output.categories, 1):
                main_name, sub_name = self._get_category_names(
                    category_item.main_id,
                    category_item.sub_id
                )
                # Find and include the description
                description = ""
                for main_cat in self.kvi_data:
                    if main_cat["id"] == category_item.main_id:
                        for sub_cat in main_cat["categories"]:
                            if sub_cat["id"] == category_item.sub_id:
                                description = sub_cat.get("description", "")
                                break
                        break
                
                context += f"{idx}. **{main_name} → {sub_name}**\n"
                context += f"   - Main ID: {category_item.main_id}, Sub ID: {category_item.sub_id}\n"
                if description:
                    context += f"   - Description: {description}\n"
                context += "\n"
        elif self.extracted_categories and self.extracted_categories.categories:
            # Fallback to the old way if saved response not available yet
            context += "The following categories were extracted based on the conversation:\n\n"
            for idx, category_item in enumerate(self.extracted_categories.categories, 1):
                main_name, sub_name = self._get_category_names(
                    category_item.main_id,
                    category_item.sub_id
                )
                # Find and include the description
                description = ""
                for main_cat in self.kvi_data:
                    if main_cat["id"] == category_item.main_id:
                        for sub_cat in main_cat["categories"]:
                            if sub_cat["id"] == category_item.sub_id:
                                description = sub_cat.get("description", "")
                                break
                        break
                
                context += f"{idx}. **{main_name} → {sub_name}**\n"
                context += f"   - Main ID: {category_item.main_id}, Sub ID: {category_item.sub_id}\n"
                if description:
                    context += f"   - Description: {description}\n"
                context += "\n"
        else:
            context += "No categories were extracted.\n\n"
        
        # Add full KVI taxonomy for reference
        context += "\n# COMPLETE KVI TAXONOMY\n\n"
        context += "Below is the complete taxonomy for your reference when discussing categories with the user:\n\n"
        
        for main_category in self.kvi_data:
            context += f"## {main_category['id']} - {main_category['name']}\n\n"
            for sub_category in main_category['categories']:
                context += f"### {sub_category['id']}: {sub_category['name']}\n"
                context += f"{sub_category.get('description', '')}\n\n"
        
        return context
    
    def _build_finalizer_prompt(self) -> str:
        """
        Build prompt for kvi_cat_finalizer using extractor's output and evaluator's conversation.
        
        Returns:
            Formatted prompt with initial categories and refinement conversation
        """
        prompt = "# INITIAL EXTRACTED CATEGORIES\n\n"
        
        # Get the extractor's structured output
        extractor_data = self.get_agent_response("kvi_cat_extractor")
        if extractor_data and extractor_data.get('structured_output'):
            structured_output = extractor_data['structured_output']
            prompt += "The following categories were initially extracted:\n\n"
            
            for idx, category_item in enumerate(structured_output.categories, 1):
                main_name, sub_name = self._get_category_names(
                    category_item.main_id,
                    category_item.sub_id
                )
                prompt += f"{idx}. {main_name} → {sub_name}\n"
                prompt += f"   (Main ID: {category_item.main_id}, Sub ID: {category_item.sub_id})\n\n"
        else:
            prompt += "No initial categories were extracted.\n\n"
        
        # Get the evaluator's conversation
        prompt += "\n# REFINEMENT CONVERSATION\n\n"
        prompt += "Below is the conversation where the user provided feedback on the categories:\n\n"
        
        evaluator_data = self.get_agent_response("kvi_cat_evaluator")
        if evaluator_data:
            # Use the saved evaluator history
            for msg in evaluator_data['history']:
                role = msg.get('role', 'unknown')
                content = msg.get('content', '')
                if role == 'user':
                    prompt += f"**User**: {content}\n\n"
                elif role == 'assistant':
                    prompt += f"**Evaluator**: {content}\n\n"
        else:
            prompt += "No refinement conversation available.\n\n"
        
        prompt += "\n---\n\n"
        prompt += "Based on the initial categories and the refinement conversation, "
        prompt += "generate the final list of KVI categories that incorporates all user feedback and changes."
        
        return prompt
    
    def _build_kpi_generator_prompt(self) -> str:
        """
        Build prompt for kpi_generator using inspector's conversation and finalizer's output.
        
        Returns:
            Formatted prompt with service understanding and final KVIs
        """
        prompt = "# SERVICE UNDERSTANDING (INSPECTOR CONVERSATION)\n\n"
        
        # Get the inspector's conversation
        inspector_data = self.get_agent_response("inspector")
        if inspector_data:
            prompt += "Below is the complete conversation where the user described their service:\n\n"
            for msg in inspector_data['history']:
                role = msg.get('role', 'unknown')
                content = msg.get('content', '')
                if role == 'user':
                    prompt += f"**User**: {content}\n\n"
                elif role == 'assistant':
                    prompt += f"**Inspector**: {content}\n\n"
        else:
            prompt += "No inspector conversation available.\n\n"
        
        # Get the final KVI categories
        prompt += "\n# FINAL KVI CATEGORIES\n\n"
        
        finalizer_data = self.get_agent_response("kvi_cat_finalizer")
        if finalizer_data and finalizer_data.get('structured_output'):
            structured_output = finalizer_data['structured_output']
            prompt += "The following KVI categories were finalized for this service:\n\n"
            
            for idx, category_item in enumerate(structured_output.categories, 1):
                main_name, sub_name = self._get_category_names(
                    category_item.main_id,
                    category_item.sub_id
                )
                # Find and include the description
                description = ""
                for main_cat in self.kvi_data:
                    if main_cat["id"] == category_item.main_id:
                        for sub_cat in main_cat["categories"]:
                            if sub_cat["id"] == category_item.sub_id:
                                description = sub_cat.get("description", "")
                                break
                        break
                
                prompt += f"{idx}. **{main_name} → {sub_name}**\n"
                prompt += f"   - Main ID: {category_item.main_id}, Sub ID: {category_item.sub_id}\n"
                if description:
                    prompt += f"   - Description: {description}\n"
                prompt += "\n"
        else:
            prompt += "No final KVI categories available.\n\n"
        
        prompt += "\n---\n\n"
        prompt += "Based on the service description and the final KVI categories, "
        prompt += "generate AT MOST 10 service-specific KPIs that should be collected to calculate these KVIs."
        
        return prompt
    
    def _format_kpis(self, kpi_response: KPIResponse) -> str:
        """Format KPIs into a readable response for the user."""
        if not kpi_response.kpis:
            return "\n\nNo KPIs were generated."
        
        response = "\n\n## Recommended KPIs for Your Service\n\n"
        response += "Based on your service description and the identified KVI categories, here are the key performance indicators you should collect:\n\n"
        
        for idx, kpi in enumerate(kpi_response.kpis, 1):
            response += f"### {idx}. {kpi.name}\n\n"
            response += f"**Description:** {kpi.description}\n\n"
            response += f"**Measure:** {kpi.measure}\n\n"
            response += "---\n\n"
        
        response += "<br>\n\n💡 These KPIs are tailored to your service and will help you measure the value indicators we identified."
        return response
    
    def _build_kpi_collector_prompt(self) -> str:
        """
        Build prompt for kpi_collector to start collecting KPI values.
        
        Returns:
            Formatted prompt with the KPIs that need values collected
        """
        prompt = "# KPIs TO COLLECT\n\n"
        
        # Get the KPI generator's output
        kpi_gen_data = self.get_agent_response("kpi_generator")
        if kpi_gen_data and kpi_gen_data.get('structured_output'):
            kpi_response: KPIResponse = kpi_gen_data['structured_output']
            prompt += "You need to collect values for the following KPIs:\n\n"
            
            for idx, kpi in enumerate(kpi_response.kpis, 1):
                prompt += f"{idx}. **{kpi.name}** (ID: {kpi.id})\n"
                prompt += f"   - Description: {kpi.description}\n"
                prompt += f"   - Measure: {kpi.measure}\n"
                prompt += "\n"
        else:
            prompt += "No KPIs available to collect.\n\n"
        
        prompt += "---\n\n"
        prompt += "Start by asking about the FIRST KPI. Ask ONE at a time. "
        prompt += "For each KPI, clearly state the name, what it measures, and the expected unit. "
        prompt += "Remind the user they can say 'AI will decide' if they don't have the value.\n\n"
        prompt += "This is a continuous conversation - DO NOT greet the user or introduce yourself. "
        prompt += "Simply start collecting the first KPI value."
        
        return prompt
    
    def _build_collector_context(self) -> str:
        """
        Build context for kpi_collector during conversation.
        
        Returns:
            Formatted context with the KPI list for reference
        """
        context = "# CONTEXT: KPIs TO COLLECT\n\n"
        
        # Get the KPI generator's output
        kpi_gen_data = self.get_agent_response("kpi_generator")
        if kpi_gen_data and kpi_gen_data.get('structured_output'):
            kpi_response: KPIResponse = kpi_gen_data['structured_output']
            context += "Here are all the KPIs you need to collect values for:\n\n"
            
            for idx, kpi in enumerate(kpi_response.kpis, 1):
                context += f"{idx}. **{kpi.name}** (ID: {kpi.id})\n"
                context += f"   - Description: {kpi.description}\n"
                context += f"   - Measure: {kpi.measure}\n"
                context += "\n"
        else:
            context += "No KPIs available.\n\n"
        
        context += "\nRemember: Ask about ONE KPI at a time, track which ones you've already collected, "
        context += "and complete when all KPIs have been addressed (either with values or marked as AI-decided)."
        
        return context
    
    def _build_advisor_prompt(self) -> str:
        """
        Build initial prompt for kvi_advisor with all calculation results and context.
        
        Returns:
            Formatted prompt with KVI results, KPI values, and service context
        """
        prompt = "# CONTEXT: ALL KVI CALCULATION RESULTS\n\n"
        
        # Get the final KVI categories
        finalizer_data = self.get_agent_response("kvi_cat_finalizer")
        if finalizer_data and finalizer_data.get('structured_output'):
            final_categories = finalizer_data['structured_output']
            prompt += "## KVI Categories Analyzed:\n\n"
            
            for idx, category_item in enumerate(final_categories.categories, 1):
                main_name, sub_name = self._get_category_names(
                    category_item.main_id,
                    category_item.sub_id
                )
                prompt += f"{idx}. {main_name} → {sub_name}\n"
            prompt += "\n"
        
        # Get collected KPI values
        prompt += "## Collected KPI Values:\n\n"
        structurer_data = self.get_agent_response("kpi_structurer")
        if structurer_data and structurer_data.get('structured_output'):
            structurer_output: CollectedKPIResponse = structurer_data['structured_output']
            for kpi in structurer_output.collected_kpis:
                if kpi.ai_decided:
                    prompt += f"- {kpi.kpi_name}: AI will decide\n"
                else:
                    prompt += f"- {kpi.kpi_name}: {kpi.value} {kpi.measure}\n"
            prompt += "\n"
        
        # Get all KVI calculation results
        prompt += "## Calculated KVI Results:\n\n"
        
        # Collect all calculator responses
        kvis_data = self._load_kvis_json()
        if finalizer_data and finalizer_data.get('structured_output'):
            final_categories = finalizer_data['structured_output']
            
            for category_item in final_categories.categories:
                # Load the corresponding kvi file
                kvi_file_data = self._load_kvi_file(category_item.main_id)
                
                # Find the sub_id item
                sub_item = None
                for item in kvi_file_data:
                    if item.get('id') == category_item.sub_id:
                        sub_item = item
                        break
                
                if not sub_item:
                    continue
                
                category_name = sub_item.get('name', 'Unknown Category')
                prompt += f"### {category_name}\n\n"
                
                # Get KVI codes
                kvi_codes = sub_item.get('kvis', [])
                
                for kvi_code in kvi_codes:
                    # Look up saved calculation result
                    calc_key = f"kvi_calculator_{category_item.sub_id}_{kvi_code}"
                    calc_data = self.get_agent_response(calc_key)
                    
                    if calc_data and calc_data.get('structured_output'):
                        calc_response: KVICalculationResponse = calc_data['structured_output']
                        if calc_response.calculations:
                            calc = calc_response.calculations[0]
                            
                            # Find KVI title from kvis.json
                            kvi_title = kvi_code
                            for kvi_item in kvis_data:
                                if kvi_item.get('code') == kvi_code:
                                    kvi_title = kvi_item.get('title', kvi_code)
                                    break
                            
                            prompt += f"**{kvi_code} - {kvi_title}**\n"
                            if calc.exact is not None:
                                prompt += f"- Exact: {calc.exact}\n"
                            else:
                                prompt += f"- Exact: Not available\n"
                            if calc.min is not None:
                                prompt += f"- Min: {calc.min}\n"
                            if calc.max is not None:
                                prompt += f"- Max: {calc.max}\n"
                            prompt += f"- Calculation: {calc.description}\n\n"
                
        # Add service context
        prompt += "\n## Service Context:\n\n"
        inspector_data = self.get_agent_response("inspector")
        if inspector_data:
            prompt += "User's service description:\n"
            for msg in inspector_data['history'][:6]:
                if msg.get('role') == 'user':
                    prompt += f"- {msg.get('content')}\n"
        
        prompt += "\n---\n\n"
        prompt += "The KVI calculations are complete. Now greet the user briefly and ask if they have any questions "
        prompt += "about the results, need clarifications, or want to recalculate anything.\n\n"
        prompt += "Keep your first message friendly and concise. Do not repeat all the results - they've already seen them."
        
        return prompt
    
    def _build_advisor_context(self) -> str:
        """
        Build context for kvi_advisor during conversation.
        
        Returns:
            Formatted context with all results for reference
        """
        # Use the same context as the initial prompt but shorter
        context = "# REFERENCE: CALCULATION RESULTS\n\n"
        
        # Quick summary of KVI results
        finalizer_data = self.get_agent_response("kvi_cat_finalizer")
        kvis_data = self._load_kvis_json()
        
        if finalizer_data and finalizer_data.get('structured_output'):
            final_categories = finalizer_data['structured_output']
            
            for category_item in final_categories.categories:
                kvi_file_data = self._load_kvi_file(category_item.main_id)
                sub_item = None
                for item in kvi_file_data:
                    if item.get('id') == category_item.sub_id:
                        sub_item = item
                        break
                
                if not sub_item:
                    continue
                
                category_name = sub_item.get('name', 'Unknown')
                kvi_codes = sub_item.get('kvis', [])
                
                for kvi_code in kvi_codes:
                    calc_key = f"kvi_calculator_{category_item.sub_id}_{kvi_code}"
                    calc_data = self.get_agent_response(calc_key)
                    
                    if calc_data and calc_data.get('structured_output'):
                        calc_response: KVICalculationResponse = calc_data['structured_output']
                        if calc_response.calculations:
                            calc = calc_response.calculations[0]
                            context += f"{kvi_code}: exact={calc.exact}, min={calc.min}, max={calc.max}\n"
        
        context += "\nUse this reference to answer user questions accurately.\n"
        return context
    
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
    
    def _is_evaluator_complete(self, response: str) -> bool:
        """Check if evaluator agent has finished the refinement conversation."""
        evaluator_module = self.registry.get_agent_module("kvi_cat_evaluator")
        if not evaluator_module or not hasattr(evaluator_module, "COMPLETION_PHRASES"):
            return False
        
        response_lower = response.lower()
        return any(phrase in response_lower for phrase in evaluator_module.COMPLETION_PHRASES)
    
    def _is_collector_complete(self, response: str) -> bool:
        """Check if collector agent has finished collecting all KPI values."""
        collector_module = self.registry.get_agent_module("kpi_collector")
        if not collector_module or not hasattr(collector_module, "COMPLETION_PHRASES"):
            return False
        
        response_lower = response.lower()
        return any(phrase in response_lower for phrase in collector_module.COMPLETION_PHRASES)
    
    def _is_advisor_complete(self, response: str) -> bool:
        """Check if advisor agent has finished helping the user."""
        advisor_module = self.registry.get_agent_module("kvi_advisor")
        if not advisor_module or not hasattr(advisor_module, "COMPLETION_PHRASES"):
            return False
        
        response_lower = response.lower()
        return any(phrase in response_lower for phrase in advisor_module.COMPLETION_PHRASES)
    
    def _load_kvi_file(self, main_id: str) -> List[Dict[str, Any]]:
        """Load KVI data from the corresponding JSON file based on main_id."""
        kvi_file = Path(__file__).parent / "data" / f"kvi{main_id}.json"
        try:
            with open(kvi_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            self.logger.error(f"Failed to load KVI file kvi{main_id}.json: {e}")
            return []
    
    def _load_kvis_json(self) -> List[Dict[str, Any]]:
        """Load the kvis.json file containing all KVI definitions."""
        kvis_file = Path(__file__).parent / "data" / "kvis.json"
        try:
            with open(kvis_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            self.logger.error(f"Failed to load kvis.json: {e}")
            return []
    
    def _build_kpi_structurer_prompt(self, history: List[ChatMessage]) -> str:
        """
        Build prompt for kpi_structurer to extract KPI values from conversation.
        
        Args:
            history: Conversation history from kpi_collector
            
        Returns:
            Formatted prompt with KPI list and conversation
        """
        prompt = "# KPIs THAT SHOULD HAVE BEEN COLLECTED\n\n"
        
        # Get the KPI generator's output
        kpi_gen_data = self.get_agent_response("kpi_generator")
        if kpi_gen_data and kpi_gen_data.get('structured_output'):
            kpi_response: KPIResponse = kpi_gen_data['structured_output']
            prompt += "The following KPIs were supposed to be collected:\n\n"
            
            for idx, kpi in enumerate(kpi_response.kpis, 1):
                prompt += f"{idx}. **{kpi.name}** (ID: {kpi.id})\n"
                prompt += f"   - Description: {kpi.description}\n"
                prompt += f"   - Measure: {kpi.measure}\n"
                prompt += "\n"
        else:
            prompt += "No KPIs available.\n\n"
        
        # Add the collector conversation
        prompt += "\n# CONVERSATION BETWEEN COLLECTOR AND USER\n\n"
        prompt += "Below is the complete conversation where the KPI values were collected:\n\n"
        
        for msg in history:
            role = msg.role
            content = msg.content
            if role == 'user':
                prompt += f"**User**: {content}\n\n"
            elif role == 'assistant':
                prompt += f"**Collector**: {content}\n\n"
        
        prompt += "\n---\n\n"
        prompt += "Parse the conversation above and extract the value provided for each KPI. "
        prompt += "Return the results in structured JSON format with all KPIs included."
        
        return prompt
    
    def _build_calculator_prompt(
        self,
        category_item: Dict[str, str],
        kvi_codes_with_details: List[Dict[str, str]],
        collected_kpis: List[Dict[str, Any]]
    ) -> str:
        """
        Build prompt for kvi_calculator for a specific KVI category.
        
        Args:
            category_item: Dictionary with main_id and sub_id
            kvi_codes_with_details: List of KVIs with their code, title, and description
            collected_kpis: List of collected KPI values
            
        Returns:
            Formatted prompt for the calculator
        """
        prompt = "# KVI CALCULATION REQUEST\n\n"
        
        # Add category context
        main_name, sub_name = self._get_category_names(
            category_item['main_id'],
            category_item['sub_id']
        )
        prompt += f"## Category: {main_name} → {sub_name}\n"
        prompt += f"Category ID: {category_item['main_id']}-{category_item['sub_id']}\n\n"
        
        # Add KVIs to calculate
        prompt += "## KVIs to Calculate:\n\n"
        for kvi in kvi_codes_with_details:
            prompt += f"### {kvi['code']}: {kvi['title']}\n"
            prompt += f"**Description**: {kvi['description']}\n\n"
        
        # Add collected KPI values
        prompt += "## Collected KPI Values:\n\n"
        if collected_kpis:
            for kpi in collected_kpis:
                prompt += f"- **{kpi['kpi_name']}**: "
                if kpi.get('ai_decided') or kpi.get('value') is None:
                    prompt += "(AI will decide - not provided by user)\n"
                else:
                    prompt += f"{kpi['value']} {kpi['measure']}\n"
                prompt += f"  _{kpi.get('description', '')}_\n"
        else:
            prompt += "No KPI values collected.\n"
        
        # Add service context from inspector
        inspector_data = self.get_agent_response("inspector")
        if inspector_data:
            prompt += "\n## Service Context:\n\n"
            prompt += "User's service description (from initial interview):\n"
            # Include a summary of the service from the inspector conversation
            for msg in inspector_data['history'][:6]:  # First few messages for context
                if msg.get('role') == 'user':
                    prompt += f"- {msg.get('content')}\n"
        
        prompt += "\n---\n\n"
        prompt += "Calculate the value for EACH KVI listed above. For each KVI, provide:\n"
        prompt += "- exact: value if all required KPIs provided (null if any are missing)\n"
        prompt += "- min: minimum value (worst-case scenario if some KPIs missing)\n"
        prompt += "- max: maximum value (best-case scenario if some KPIs missing)\n"
        prompt += "- description: brief explanation of your calculation formula\n"
        
        return prompt
    
    def _build_single_kvi_calculator_prompt(
        self,
        kvi_code: str,
        kvi_title: str,
        kvi_description: str,
        collected_kpis: List[Dict[str, Any]],
        category_info: str
    ) -> str:
        """
        Build prompt for calculating a SINGLE KVI.
        
        Args:
            kvi_code: The KVI code (e.g., 'IWCA')
            kvi_title: The KVI title
            kvi_description: The KVI description
            collected_kpis: List of collected KPI values
            category_info: Category context
            
        Returns:
            Formatted prompt for the calculator
        """
        prompt = "# SINGLE KVI CALCULATION REQUEST\n\n"
        
        prompt += f"## Category Context: {category_info}\n\n"
        
        # Add the ONE KVI to calculate
        prompt += "## KVI to Calculate:\n\n"
        prompt += f"**Code**: {kvi_code}\n"
        prompt += f"**Title**: {kvi_title}\n"
        prompt += f"**Description**: {kvi_description}\n\n"
        
        # Add collected KPI values
        prompt += "## Collected KPI Values:\n\n"
        if collected_kpis:
            for kpi in collected_kpis:
                prompt += f"- **{kpi['kpi_name']}**: "
                if kpi.get('ai_decided') or kpi.get('value') is None:
                    prompt += "(AI will decide - not provided by user)\n"
                else:
                    prompt += f"{kpi['value']} {kpi['measure']}\n"
                prompt += f"  _{kpi.get('description', '')}_\n"
        else:
            prompt += "No KPI values collected.\n"
        
        # Add service context from inspector
        inspector_data = self.get_agent_response("inspector")
        if inspector_data:
            prompt += "\n## Service Context:\n\n"
            prompt += "User's service description (from initial interview):\n"
            for msg in inspector_data['history'][:6]:
                if msg.get('role') == 'user':
                    prompt += f"- {msg.get('content')}\n"
        
        prompt += "\n---\n\n"
        prompt += f"Calculate the value for the KVI: {kvi_code}. Provide:\n"
        prompt += "- exact: value if all required KPIs provided (null if any are missing)\n"
        prompt += "- min: minimum value (worst-case scenario if some KPIs missing)\n"
        prompt += "- max: maximum value (best-case scenario if some KPIs missing)\n"
        prompt += "- description: brief explanation of your calculation formula\n"
        prompt += "\nIMPORTANT: Return ONLY this single KVI in the calculations array.\n"
        
        return prompt
    
    def _format_single_kvi_result(self, calc) -> str:
        """Format a single KVI calculation result."""
        # output = f"\nKVI: {calc.kvi_code} - {calc.kvi_title}\n"
        # output += f"{'-'*80}\n"
        output = ""
        
        if calc.exact is not None:
            output += f"  **Exact Value**: {calc.exact}\n\n"
        else:
            output += f"  **Exact Value**: Not available (missing KPIs)\n\n"
        
        if calc.min is not None:
            output += f"  **Minimum (Worst Case)**: {calc.min}\n\n"
        else:
            output += f"  **Minimum**: Not calculated\n\n"
        
        if calc.max is not None:
            output += f"  **Maximum (Best Case)**: {calc.max}\n\n"
        else:
            output += f"  **Maximum**: Not calculated\n\n"
        
        output += f"\n\n  **Calculation Method**:\n\n  {calc.description}\n\n"
        
        return output
    
    def _format_kvi_calculation(self, calculation_response: KVICalculationResponse, category_name: str) -> str:
        """Format KVI calculation results for display to the user."""
        if not calculation_response.calculations:
            return f"\n\n{category_name}: No calculations available.\n\n"
        
        output = ""
        
        for calc in calculation_response.calculations:
            output += f"### KVI: {calc.kvi_code} - {calc.kvi_title}\n\n"
            output += f"{'-'*80}\n\n"
            
            if calc.exact is not None:
                output += f"  **Exact Value**: {calc.exact}\n\n"
            else:
                output += f"  **Exact Value**: Not available (missing KPIs)\n\n"
            
            if calc.min is not None:
                output += f"  **Minimum (Worst Case)**: {calc.min}\n\n"
            else:
                output += f"  **Minimum**: Not calculated\n\n"
            
            if calc.max is not None:
                output += f"  **Maximum (Best Case)**: {calc.max}\n\n"
            else:
                output += f"  **Maximum**: Not calculated\n\n"
            
            output += f"\n\n  **Calculation Method**:\n\n  {calc.description}\n\n"
            output += f"\n\n"
        
        return output

    async def process_message_stream(
        self,
        message: str,
        history: List[ChatMessage],
        current_agent_name: str,
        session_logger: Optional[logging.Logger] = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Process a user message through the workflow with streaming updates.
        
        Yields dictionaries with different event types:
        - {'type': 'status', 'message': 'Processing with inspector...', 'agent': 'inspector'}
        - {'type': 'content', 'delta': 'partial text chunk', 'agent': 'inspector'}
        - {'type': 'agent_complete', 'agent': 'inspector', 'full_response': '...'}
        - {'type': 'transition', 'from_agent': 'inspector', 'to_agent': 'kvi_cat_extractor', 'message': '...'}
        - {'type': 'complete', 'final_response': '...', 'history': [...], 'current_agent': '...'}
        - {'type': 'error', 'message': '...'}
        
        Args:
            message: User's message
            history: Conversation history
            current_agent_name: Name of currently active agent
            session_logger: Optional session-specific logger
        """
        agent = self.registry.get_agent(current_agent_name)
        if not agent:
            yield {'type': 'error', 'message': f"Unknown agent: {current_agent_name}"}
            return
        
        log = session_logger or self.logger
        
        log.info(f"Processing message with agent: {current_agent_name}")
        log.info(f"User message: {message}")

        # Notify which agent is processing
        yield {
            'type': 'status',
            'message': f'Processing with {current_agent_name}...',
            'agent': current_agent_name
        }

        # Render prompt with conversation history
        prompt = self._render_prompt(history, message)
        
        # For kvi_cat_evaluator, prepend the context with extracted categories and taxonomy
        if current_agent_name == "kvi_cat_evaluator":
            evaluator_context = self._build_evaluator_context()
            prompt = f"{evaluator_context}\n\n---\n\n{prompt}"
        
        # For kpi_collector, prepend the context with KPI list
        if current_agent_name == "kpi_collector":
            collector_context = self._build_collector_context()
            prompt = f"{collector_context}\n\n---\n\n{prompt}"
        
        # For kvi_advisor, prepend the context with calculation results
        if current_agent_name == "kvi_advisor":
            advisor_context = self._build_advisor_context()
            prompt = f"{advisor_context}\n\n---\n\n{prompt}"
        
        # Run the current agent with streaming
        log.info(f"Calling {current_agent_name} agent with streaming")
        accumulated_response = ""
        
        # Check if agent supports streaming
        if hasattr(agent, 'run_stream'):
            async for chunk in agent.run_stream(prompt):
                accumulated_response += chunk
                yield {
                    'type': 'content',
                    'delta': chunk,
                    'agent': current_agent_name
                }
        else:
            # Fall back to non-streaming
            response_text = await agent.run(prompt)
            accumulated_response = response_text
            yield {
                'type': 'content',
                'delta': response_text,
                'agent': current_agent_name
            }
        
        response_text = accumulated_response
        log.info(f"Agent response length: {len(response_text)} chars")

        # Notify that agent completed
        log.info(f"Sending agent_complete event for {current_agent_name} with {len(response_text)} chars")
        yield {
            'type': 'agent_complete',
            'agent': current_agent_name,
            'full_response': response_text
        }

        # Update history with user message and agent response
        updated_history = list(history)
        updated_history.append(ChatMessage(role="user", content=message))
        updated_history.append(ChatMessage(role="assistant", content=response_text))

        # Workflow logic: inspector -> kvi_cat_extractor -> kvi_cat_evaluator -> kvi_cat_finalizer -> kpi_generator -> kpi_collector
        if current_agent_name == "kvi_cat_evaluator":
            # Check if evaluator has completed the refinement
            if self._is_evaluator_complete(response_text):
                log.info("KVI category evaluation completed, triggering kvi_cat_finalizer")
                
                # Save the evaluator's final response
                self._save_agent_response(
                    agent_name="kvi_cat_evaluator",
                    response=response_text,
                    history=updated_history,
                    structured_output=None
                )
                
                # Add transitional message to the user
                transition_msg = "\n\n---\n\n<br>\n\n✨ Now we are refining the list of selected KVI categories based on your comments...\n\n<br>\n\n"
                
                # Stream the transition message
                yield {
                    'type': 'transition',
                    'from_agent': 'kvi_cat_evaluator',
                    'to_agent': 'kvi_cat_finalizer',
                    'message': transition_msg
                }
                
                response_text += transition_msg
                
                # Automatically call kvi_cat_finalizer to generate final structured output
                kvi_finalizer = self.registry.get_agent("kvi_cat_finalizer")
                if kvi_finalizer:
                    # Build prompt using extractor's output and evaluator's conversation
                    finalizer_prompt = self._build_finalizer_prompt()
                    
                    yield {
                        'type': 'status',
                        'message': 'Generating final refined categories...',
                        'agent': 'kvi_cat_finalizer'
                    }
                    
                    log.info("Calling kvi_cat_finalizer agent")
                    log.info(f"Finalizer prompt length: {len(finalizer_prompt)} chars")
                    finalizer_response = await kvi_finalizer.run(finalizer_prompt)
                    
                    log.info(f"KVI finalizer response type: {type(finalizer_response).__name__}")
                    
                    if isinstance(finalizer_response, FinalKVICategoryResponse):
                        log.info(f"KVI finalizer returned {len(finalizer_response.categories)} final KVI categories")
                        
                        # Format the final KVI categories into a readable response
                        formatted_response = self._format_kvi_categories(finalizer_response)
                        
                        # Stream the formatted categories
                        yield {
                            'type': 'content',
                            'delta': formatted_response,
                            'agent': 'kvi_cat_finalizer'
                        }
                        
                        # Notify that finalizer completed
                        log.info(f"Sending agent_complete event for kvi_cat_finalizer with {len(formatted_response)} chars")
                        yield {
                            'type': 'agent_complete',
                            'agent': 'kvi_cat_finalizer',
                            'full_response': formatted_response
                        }
                        
                        response_text += formatted_response
                        
                        # Store the finalizer's response in history
                        updated_history.append(ChatMessage(
                            role="user",
                            content="Generate the final refined KVI categories based on our conversation."
                        ))
                        updated_history.append(ChatMessage(role="assistant", content=formatted_response))
                        
                        # Save the finalizer's response with structured output
                        self._save_agent_response(
                            agent_name="kvi_cat_finalizer",
                            response=formatted_response,
                            history=updated_history,
                            structured_output=finalizer_response
                        )
                        
                        # Automatically trigger kpi_generator
                        log.info("KVI finalizer completed, automatically triggering kpi_generator")
                        
                        transition_msg = "\n\n📝 Now let me generate the specific KPIs you should collect for your service...\n\n<br>\n\n"
                        yield {
                            'type': 'transition',
                            'from_agent': 'kvi_cat_finalizer',
                            'to_agent': 'kpi_generator',
                            'message': transition_msg
                        }
                        
                        response_text += transition_msg
                        
                        kpi_gen = self.registry.get_agent("kpi_generator")
                        if kpi_gen:
                            # Build prompt using inspector's conversation and finalizer's output
                            kpi_prompt = self._build_kpi_generator_prompt()
                            
                            yield {
                                'type': 'status',
                                'message': 'Generating service-specific KPIs...',
                                'agent': 'kpi_generator'
                            }
                            
                            log.info("Calling kpi_generator agent")
                            log.info(f"KPI generator prompt length: {len(kpi_prompt)} chars")
                            kpi_response = await kpi_gen.run(kpi_prompt)
                            
                            log.info(f"KPI generator response type: {type(kpi_response).__name__}")
                            
                            if isinstance(kpi_response, KPIResponse):
                                log.info(f"KPI generator returned {len(kpi_response.kpis)} KPIs")
                                
                                # Format the KPIs into a readable response
                                formatted_kpis = self._format_kpis(kpi_response)
                                
                                # Stream the formatted KPIs
                                yield {
                                    'type': 'content',
                                    'delta': formatted_kpis,
                                    'agent': 'kpi_generator'
                                }
                                
                                # Notify that KPI generator completed
                                log.info(f"Sending agent_complete event for kpi_generator with {len(formatted_kpis)} chars")
                                yield {
                                    'type': 'agent_complete',
                                    'agent': 'kpi_generator',
                                    'full_response': formatted_kpis
                                }
                                
                                response_text += formatted_kpis
                                
                                # Store the KPI generator's response in history
                                updated_history.append(ChatMessage(
                                    role="user",
                                    content="Generate service-specific KPIs for calculating the KVIs."
                                ))
                                updated_history.append(ChatMessage(role="assistant", content=formatted_kpis))
                                
                                # Save the KPI generator's response with structured output
                                self._save_agent_response(
                                    agent_name="kpi_generator",
                                    response=formatted_kpis,
                                    history=updated_history,
                                    structured_output=kpi_response
                                )
                                
                                # Automatically trigger kpi_collector
                                log.info("KPI generator completed, automatically triggering kpi_collector")
                                
                                transition_msg = "\n\n<br>\n\n📋 Now let's collect the actual values for these KPIs...\n\n<br>\n\n"
                                yield {
                                    'type': 'transition',
                                    'from_agent': 'kpi_generator',
                                    'to_agent': 'kpi_collector',
                                    'message': transition_msg
                                }
                                
                                response_text += transition_msg
                                
                                kpi_collector = self.registry.get_agent("kpi_collector")
                                if kpi_collector:
                                    # Build prompt for collecting KPI values
                                    collector_prompt = self._build_kpi_collector_prompt()
                                    
                                    yield {
                                        'type': 'status',
                                        'message': 'Preparing to collect KPI values...',
                                        'agent': 'kpi_collector'
                                    }
                                    
                                    log.info("Calling kpi_collector agent")
                                    log.info(f"KPI collector prompt length: {len(collector_prompt)} chars")
                                    
                                    # Stream collector response
                                    collector_accumulated = ""
                                    if hasattr(kpi_collector, 'run_stream'):
                                        async for chunk in kpi_collector.run_stream(collector_prompt):
                                            collector_accumulated += chunk
                                            yield {
                                                'type': 'content',
                                                'delta': chunk,
                                                'agent': 'kpi_collector'
                                            }
                                    else:
                                        collector_response = await kpi_collector.run(collector_prompt)
                                        collector_accumulated = collector_response
                                        yield {
                                            'type': 'content',
                                            'delta': collector_response,
                                            'agent': 'kpi_collector'
                                        }
                                    
                                    collector_response = collector_accumulated
                                    
                                    # Notify that collector started (first message sent)
                                    log.info(f"Sending agent_complete event for kpi_collector with {len(collector_response)} chars")
                                    yield {
                                        'type': 'agent_complete',
                                        'agent': 'kpi_collector',
                                        'full_response': collector_response
                                    }
                                    
                                    # Add collector's initial message to response
                                    response_text += "\n\n" + collector_response
                                    
                                    # Create a NEW, CLEAN history for the collector
                                    collector_history = [
                                        ChatMessage(role="assistant", content=formatted_kpis),
                                        ChatMessage(role="assistant", content=collector_response)
                                    ]
                                    
                                    log.info("Transitioned to kpi_collector agent with clean history")
                                    log.info(f"Collector history length: {len(collector_history)} messages")
                                    
                                    yield {
                                        'type': 'complete',
                                        'final_response': response_text,
                                        'history': [msg.dict() for msg in collector_history],
                                        'current_agent': 'kpi_collector'
                                    }
                                    return
                                else:
                                    log.warning("KPI collector agent not found")
                                    warning_msg = "\n\nWorkflow completed with KPIs generated."
                                    yield {
                                        'type': 'content',
                                        'delta': warning_msg,
                                        'agent': current_agent_name
                                    }
                                    response_text += warning_msg
                                    log.info("Workflow completed successfully with KPIs generated")
                            else:
                                log.error("KPI generator did not return a structured KPIResponse")
                                error_msg = "\n\nSorry, I encountered an issue generating the KPIs. The workflow completed with KVI categories."
                                yield {
                                    'type': 'content',
                                    'delta': error_msg,
                                    'agent': current_agent_name
                                }
                                response_text += error_msg
                        else:
                            log.warning("KPI generator agent not found")
                            warning_msg = "\n\nWorkflow completed with KVI categories."
                            yield {
                                'type': 'content',
                                'delta': warning_msg,
                                'agent': current_agent_name
                            }
                            response_text += warning_msg
                        
                        log.info("Workflow completed successfully")
                        
                        yield {
                            'type': 'complete',
                            'final_response': response_text,
                            'history': [msg.dict() for msg in updated_history],
                            'current_agent': current_agent_name
                        }
                        return
                    else:
                        log.error("KVI finalizer did not return a structured FinalKVICategoryResponse")
                        error_msg = "\n\nSorry, I encountered an issue generating the final categories. Please try again."
                        
                        yield {
                            'type': 'content',
                            'delta': error_msg,
                            'agent': current_agent_name
                        }
                        
                        response_text += error_msg
                        
                        yield {
                            'type': 'complete',
                            'final_response': response_text,
                            'history': [msg.dict() for msg in updated_history],
                            'current_agent': current_agent_name
                        }
                        return
                
        elif current_agent_name == "inspector":
            if self._is_inspector_complete(response_text):
                log.info("Inspector completed, automatically triggering kvi_cat_extractor")
                
                # Save the inspector's response
                self._save_agent_response(
                    agent_name="inspector",
                    response=response_text,
                    history=updated_history,
                    structured_output=None
                )
                
                # Notify transition
                transition_msg = "\n\n---\n\n<br>\n\n🔍 Let me now extract the list of relevant KVIs for you...\n\n<br>\n\n"
                yield {
                    'type': 'transition',
                    'from_agent': 'inspector',
                    'to_agent': 'kvi_cat_extractor',
                    'message': transition_msg
                }
                
                response_text += transition_msg
                
                # Automatically call kvi_cat_extractor with the gathered information
                kvi_extractor = self.registry.get_agent("kvi_cat_extractor")
                if kvi_extractor:
                    # Build prompt using the inspector's conversation
                    extractor_prompt = self._build_extractor_prompt(updated_history)
                    
                    yield {
                        'type': 'status',
                        'message': 'Extracting KVI categories...',
                        'agent': 'kvi_cat_extractor'
                    }
                    
                    log.info("Calling kvi_cat_extractor agent with inspector's interview")
                    log.info(f"Extractor prompt length: {len(extractor_prompt)} chars")
                    extractor_response = await kvi_extractor.run(extractor_prompt)
                    
                    log.info(f"KVI extractor response type: {type(extractor_response).__name__}")

                    if isinstance(extractor_response, KVICategoryResponse):
                        log.info(f"KVI extractor returned {len(extractor_response.categories)} KVI categories")

                        # Store the extracted categories for the evaluator
                        self.extracted_categories = extractor_response

                        # Format the KVI categories into a readable response
                        formatted_response = self._format_kvi_categories(extractor_response)
                        
                        # Stream the formatted categories
                        yield {
                            'type': 'content',
                            'delta': formatted_response,
                            'agent': 'kvi_cat_extractor'
                        }
                        
                        # Notify that extractor completed
                        log.info(f"Sending agent_complete event for kvi_cat_extractor with {len(formatted_response)} chars")
                        yield {
                            'type': 'agent_complete',
                            'agent': 'kvi_cat_extractor',
                            'full_response': formatted_response
                        }
                        
                        response_text += formatted_response

                        # Store the formatted response in history
                        updated_history.append(ChatMessage(
                            role="user",
                            content="Please identify the most relevant KVI categories based on this conversation."
                        ))
                        updated_history.append(ChatMessage(role="assistant", content=formatted_response))
                        
                        # Save the extractor's response
                        self._save_agent_response(
                            agent_name="kvi_cat_extractor",
                            response=formatted_response,
                            history=updated_history,
                            structured_output=extractor_response
                        )
                        
                        # Automatically trigger kvi_cat_evaluator
                        log.info("Inspector and extractor completed, automatically triggering kvi_cat_evaluator")
                        
                        yield {
                            'type': 'transition',
                            'from_agent': 'kvi_cat_extractor',
                            'to_agent': 'kvi_cat_evaluator',
                            'message': '\n\n'
                        }
                        
                        kvi_evaluator = self.registry.get_agent("kvi_cat_evaluator")
                        if kvi_evaluator:
                            # Build context with extractor's structured output and full taxonomy
                            evaluator_context = self._build_evaluator_context()
                            log.info("Built evaluator context with extractor's structured output")
                            log.info(f"Evaluator context length: {len(evaluator_context)} chars")
                            
                            # Create the initial evaluator prompt
                            evaluator_prompt = f"""{evaluator_context}
                            
                                ---

                                The user has just been presented with the extracted KVI categories above. 
                                
                                This is a continuous conversation - DO NOT greet the user or introduce yourself.
                                
                                Simply ask if they're happy with the extracted categories. Keep it simple and direct.
                                Do NOT provide any suggestions or alternatives yet.
                                Just ask if they're satisfied with the list or if they'd like to make changes.
                                
                                If they say they're not happy or want changes, THEN you can start providing suggestions and alternatives.

                                Begin the conversation now.
                            """
                            
                            yield {
                                'type': 'status',
                                'message': 'Preparing recommendations...',
                                'agent': 'kvi_cat_evaluator'
                            }
                            
                            log.info("Calling kvi_cat_evaluator agent")
                            
                            # Stream evaluator response
                            evaluator_accumulated = ""
                            if hasattr(kvi_evaluator, 'run_stream'):
                                async for chunk in kvi_evaluator.run_stream(evaluator_prompt):
                                    evaluator_accumulated += chunk
                                    yield {
                                        'type': 'content',
                                        'delta': chunk,
                                        'agent': 'kvi_cat_evaluator'
                                    }
                            else:
                                evaluator_response = await kvi_evaluator.run(evaluator_prompt)
                                evaluator_accumulated = evaluator_response
                                yield {
                                    'type': 'content',
                                    'delta': evaluator_response,
                                    'agent': 'kvi_cat_evaluator'
                                }
                            
                            evaluator_response = evaluator_accumulated
                            
                            # Notify that evaluator completed
                            log.info(f"Sending agent_complete event for kvi_cat_evaluator with {len(evaluator_response)} chars")
                            yield {
                                'type': 'agent_complete',
                                'agent': 'kvi_cat_evaluator',
                                'full_response': evaluator_response
                            }
                            
                            # Add evaluator's initial message to response
                            response_text += "\n\n" + evaluator_response
                            
                            # Create a NEW, CLEAN history for the evaluator
                            evaluator_history = [
                                ChatMessage(role="assistant", content=formatted_response),
                                ChatMessage(role="assistant", content=evaluator_response)
                            ]
                            
                            log.info("Transitioned to kvi_cat_evaluator agent with clean history")
                            log.info(f"Evaluator history length: {len(evaluator_history)} messages")
                            
                            yield {
                                'type': 'complete',
                                'final_response': response_text,
                                'history': [msg.dict() for msg in evaluator_history],
                                'current_agent': 'kvi_cat_evaluator'
                            }
                            return
                    else:
                        # If not the expected structured response, terminate with proper message
                        log.error("KVI extractor did not return a structured KVICategoryResponse")
                        error_msg = (
                            "\n\nSorry, I was unable to retrieve the KVI categories due to an unexpected response "
                            "from the extractor. Please try again later or contact support."
                        )
                        yield {
                            'type': 'content',
                            'delta': error_msg,
                            'agent': current_agent_name
                        }
                        
                        # Notify completion even on error
                        yield {
                            'type': 'agent_complete',
                            'agent': current_agent_name,
                            'full_response': error_msg
                        }
                        
                        response_text += error_msg
                        updated_history.append(ChatMessage(
                            role="user",
                            content="Please identify the most relevant KVI categories based on this conversation."
                        ))
                        updated_history.append(ChatMessage(role="assistant", content=error_msg))
                        
                        yield {
                            'type': 'complete',
                            'final_response': response_text,
                            'history': [msg.dict() for msg in updated_history],
                            'current_agent': current_agent_name
                        }
                        return
        
        # Check if kvi_advisor has completed helping the user
        elif current_agent_name == "kvi_advisor":
            if self._is_advisor_complete(response_text):
                log.info("KVI advisor completed, workflow finished")
                
                # Save the advisor's final response
                self._save_agent_response(
                    agent_name="kvi_advisor",
                    response=response_text,
                    history=updated_history,
                    structured_output=None
                )
                
                # End the workflow
                log.info("Workflow completed successfully")
                
                yield {
                    'type': 'complete',
                    'final_response': response_text,
                    'history': [msg.dict() for msg in updated_history],
                    'current_agent': current_agent_name
                }
                return
        
        # Check if kpi_collector has completed collecting all values
        elif current_agent_name == "kpi_collector":
            if self._is_collector_complete(response_text):
                log.info("KPI collector completed, triggering kpi_structurer")
                
                # Save the collector's final response
                self._save_agent_response(
                    agent_name="kpi_collector",
                    response=response_text,
                    history=updated_history,
                    structured_output=None
                )
                
                # Automatically trigger kpi_structurer to extract values
                log.info("KPI collector completed, automatically triggering kpi_structurer")
                
                transition_msg = "\n\n---\n\n<br>\n\n⚙️ Extracting your KPI values from the conversation...\n\n<br>\n\n"
                yield {
                    'type': 'transition',
                    'from_agent': 'kpi_collector',
                    'to_agent': 'kpi_structurer',
                    'message': transition_msg
                }
                
                response_text += transition_msg
                
                kpi_structurer = self.registry.get_agent("kpi_structurer")
                if kpi_structurer:
                    # Build prompt with KPI list and conversation
                    structurer_prompt = self._build_kpi_structurer_prompt(updated_history)
                    
                    yield {
                        'type': 'status',
                        'message': 'Extracting KPI values...',
                        'agent': 'kpi_structurer'
                    }
                    
                    log.info("Calling kpi_structurer agent")
                    log.info(f"Structurer prompt length: {len(structurer_prompt)} chars")
                    
                    structurer_response = await kpi_structurer.run(structurer_prompt)
                    
                    log.info(f"KPI structurer response type: {type(structurer_response).__name__}")
                    
                    if isinstance(structurer_response, CollectedKPIResponse):
                        log.info(f"KPI structurer extracted {len(structurer_response.collected_kpis)} KPI values")
                        
                        # Save the structurer's response with structured output
                        self._save_agent_response(
                            agent_name="kpi_structurer",
                            response="KPI values extracted successfully",
                            history=updated_history,
                            structured_output=structurer_response
                        )
                        
                        # Show summary of extracted values
                        summary_msg = "\n\n## 📊 Extracted KPI Values\n\n"
                        summary_msg += "Here are the KPI values we collected:\n\n"
                        for kpi in structurer_response.collected_kpis:
                            if kpi.ai_decided:
                                summary_msg += f"- **{kpi.kpi_name}**: AI will decide\n"
                            else:
                                summary_msg += f"- **{kpi.kpi_name}**: {kpi.value} {kpi.measure}\n"
                        summary_msg += "\n---\n\n"
                        
                        yield {
                            'type': 'content',
                            'delta': summary_msg,
                            'agent': 'kpi_structurer'
                        }
                        
                        response_text += summary_msg
                        
                        # Send agent_complete to ensure KPI summary is displayed immediately
                        yield {
                            'type': 'agent_complete',
                            'agent': 'kpi_structurer',
                            'full_response': response_text
                        }
                        
                        # Now trigger kvi_calculator
                        log.info("KPI structurer completed, automatically triggering kvi_calculator")
                        
                        transition_msg = "\n\n🔢 Now calculating your KVI values based on the collected data...\n\n"
                        yield {
                            'type': 'transition',
                            'from_agent': 'kpi_structurer',
                            'to_agent': 'kvi_calculator',
                            'message': transition_msg
                        }
                        
                        response_text += transition_msg
                        
                        # Send agent_complete to ensure transition message is displayed immediately
                        yield {
                            'type': 'agent_complete',
                            'agent': 'kvi_calculator',
                            'full_response': response_text
                        }
                        
                        kvi_calculator = self.registry.get_agent("kvi_calculator")
                        if kvi_calculator:
                            # Get the finalizer output (KVI categories)
                            finalizer_data = self.get_agent_response("kvi_cat_finalizer")
                            if finalizer_data and finalizer_data.get('structured_output'):
                                final_categories = finalizer_data['structured_output']
                                
                                # Get structured KPI values from structurer
                                structurer_data = self.get_agent_response("kpi_structurer")
                                collected_kpis = []
                                if structurer_data and structurer_data.get('structured_output'):
                                    structurer_output: CollectedKPIResponse = structurer_data['structured_output']
                                    # Convert to dict format for calculator
                                    for kpi in structurer_output.collected_kpis:
                                        collected_kpis.append({
                                            "kpi_id": kpi.kpi_id,
                                            "kpi_name": kpi.kpi_name,
                                            "measure": kpi.measure,
                                            "value": kpi.value,
                                            "ai_decided": kpi.ai_decided
                                        })
                                
                                # Load kvis.json for KVI details
                                kvis_data = self._load_kvis_json()
                                
                                # Loop through each KVI category
                                for idx, category_item in enumerate(final_categories.categories, 1):
                                    log.info(f"Processing KVI category: {category_item.main_id}-{category_item.sub_id}")
                                    
                                    # Load the corresponding kvi file
                                    kvi_file_data = self._load_kvi_file(category_item.main_id)
                                    
                                    # Find the sub_id item
                                    sub_item = None
                                    for item in kvi_file_data:
                                        if item.get('id') == category_item.sub_id:
                                            sub_item = item
                                            break
                                    
                                    if not sub_item:
                                        log.warning(f"Sub-category {category_item.sub_id} not found in kvi{category_item.main_id}.json")
                                        continue
                                    
                                    # Get category name
                                    category_name = sub_item.get('name', 'Unknown Category')
                                    
                                    # Send announcement message at START of iteration
                                    announcement_msg = f"\n\n{'='*80}\n\n"
                                    announcement_msg += f"## CATEGORY {idx}/{len(final_categories.categories)}: {category_name}\n\n"
                                    announcement_msg += f"{'='*80}\n\n"
                                    announcement_msg += f"Now calculating KVI values for this category...\n\n"
                                    
                                    yield {
                                        'type': 'content',
                                        'delta': announcement_msg,
                                        'agent': 'kvi_calculator'
                                    }
                                    
                                    response_text += announcement_msg
                                    
                                    # Send agent_complete to ensure banner is displayed immediately
                                    yield {
                                        'type': 'agent_complete',
                                        'agent': 'kvi_calculator',
                                        'full_response': response_text
                                    }
                                    
                                    # Get KVI codes from this sub-item
                                    kvi_codes = sub_item.get('kvis', [])
                                    
                                    if not kvi_codes:
                                        log.warning(f"No KVI codes found for {category_item.sub_id}")
                                        skip_msg = f"No KVI codes found for this category. Skipping...\n\n"
                                        yield {
                                            'type': 'content',
                                            'delta': skip_msg,
                                            'agent': 'kvi_calculator'
                                        }
                                        response_text += skip_msg
                                        
                                        # Send agent_complete so frontend displays the skip message
                                        yield {
                                            'type': 'agent_complete',
                                            'agent': 'kvi_calculator',
                                            'full_response': response_text
                                        }
                                        continue
                                    
                                    # Look up each KVI code in kvis.json
                                    kvi_codes_with_details = []
                                    for code in kvi_codes:
                                        for kvi_item in kvis_data:
                                            if kvi_item.get('code') == code:
                                                kvi_codes_with_details.append({
                                                    'code': code,
                                                    'title': kvi_item.get('title', 'Unknown'),
                                                    'description': kvi_item.get('description', 'No description')
                                                })
                                                break
                                    
                                    if not kvi_codes_with_details:
                                        log.warning(f"No KVI details found for codes in {category_item.sub_id}")
                                        skip_msg = f"No KVI details found for codes in this category. Skipping...\n\n"
                                        yield {
                                            'type': 'content',
                                            'delta': skip_msg,
                                            'agent': 'kvi_calculator'
                                        }
                                        response_text += skip_msg
                                        
                                        # Send agent_complete so frontend displays the skip message
                                        yield {
                                            'type': 'agent_complete',
                                            'agent': 'kvi_calculator',
                                            'full_response': response_text
                                        }
                                        continue
                                    
                                    # INNER LOOP: Calculate each KVI individually
                                    total_kvis = len(kvi_codes_with_details)
                                    for kvi_idx, kvi_detail in enumerate(kvi_codes_with_details, 1):
                                        kvi_code = kvi_detail['code']
                                        kvi_title = kvi_detail['title']
                                        kvi_description = kvi_detail['description']
                                        
                                        # Build prompt for THIS SINGLE KVI
                                        calculator_prompt = self._build_single_kvi_calculator_prompt(
                                            kvi_code=kvi_code,
                                            kvi_title=kvi_title,
                                            kvi_description=kvi_description,
                                            collected_kpis=collected_kpis,
                                            category_info=category_name
                                        )
                                        
                                        # Show status for this specific KVI
                                        yield {
                                            'type': 'status',
                                            'message': f'Calculating {kvi_code} ({kvi_idx}/{total_kvis} in {category_name})...',
                                            'agent': 'kvi_calculator'
                                        }
                                        
                                        # Show sub-banner with KVI name and description
                                        kvi_subbanner = f"\n\n  → **KVI {kvi_idx}/{total_kvis}**: {kvi_code} - {kvi_title}\n\n"
                                        kvi_subbanner += f"  {'-'*76}\n\n"
                                        kvi_subbanner += f"  {kvi_description}\n\n"
                                        kvi_subbanner += f"  {'-'*76}\n\n"
                                        
                                        yield {
                                            'type': 'content',
                                            'delta': kvi_subbanner,
                                            'agent': 'kvi_calculator'
                                        }
                                        
                                        response_text += kvi_subbanner
                                        
                                        # Send agent_complete to ensure sub-banner is displayed immediately
                                        yield {
                                            'type': 'agent_complete',
                                            'agent': 'kvi_calculator',
                                            'full_response': response_text
                                        }
                                        
                                        log.info(f"Calling kvi_calculator for KVI {kvi_code} ({kvi_idx}/{total_kvis})")
                                        log.info(f"Calculator prompt length: {len(calculator_prompt)} chars")
                                        
                                        calculator_response = await kvi_calculator.run(calculator_prompt)
                                        
                                        log.info(f"KVI calculator response type: {type(calculator_response).__name__}")
                                        
                                        if isinstance(calculator_response, KVICalculationResponse):
                                            if calculator_response.calculations:
                                                calc = calculator_response.calculations[0]  # Should only be one
                                                log.info(f"KVI calculator returned result for {calc.kvi_code}")
                                                
                                                # Format THIS SINGLE KVI result
                                                formatted_result = self._format_single_kvi_result(calc)
                                                
                                                # Stream the result immediately
                                                yield {
                                                    'type': 'content',
                                                    'delta': formatted_result,
                                                    'agent': 'kvi_calculator'
                                                }
                                                
                                                response_text += formatted_result
                                                
                                                # Send agent_complete after EACH KVI so frontend displays it immediately
                                                yield {
                                                    'type': 'agent_complete',
                                                    'agent': 'kvi_calculator',
                                                    'full_response': response_text
                                                }
                                                
                                                # Save this KVI's result
                                                self._save_agent_response(
                                                    agent_name=f"kvi_calculator_{category_item.sub_id}_{kvi_code}",
                                                    response=formatted_result,
                                                    history=updated_history,
                                                    structured_output=calculator_response
                                                )
                                            else:
                                                log.warning(f"No calculations returned for {kvi_code}")
                                                error_msg = f"✗ No result for {kvi_code}\n\n"
                                                yield {
                                                    'type': 'content',
                                                    'delta': error_msg,
                                                    'agent': 'kvi_calculator'
                                                }
                                                response_text += error_msg
                                                yield {
                                                    'type': 'agent_complete',
                                                    'agent': 'kvi_calculator',
                                                    'full_response': response_text
                                                }
                                        else:
                                            log.error(f"KVI calculator did not return structured response for {kvi_code}")
                                            error_msg = f"✗ Error calculating {kvi_code}\n\n"
                                            yield {
                                                'type': 'content',
                                                'delta': error_msg,
                                                'agent': 'kvi_calculator'
                                            }
                                            response_text += error_msg
                                            yield {
                                                'type': 'agent_complete',
                                                'agent': 'kvi_calculator',
                                                'full_response': response_text
                                            }
                                    
                                    # Category completed - add summary
                                    category_complete_msg = f"\n✓ Completed all {total_kvis} KVIs for: {category_name}\n\n"
                                    yield {
                                        'type': 'content',
                                        'delta': category_complete_msg,
                                        'agent': 'kvi_calculator'
                                    }
                                    response_text += category_complete_msg
                                    yield {
                                        'type': 'agent_complete',
                                        'agent': 'kvi_calculator',
                                        'full_response': response_text
                                    }
                                
                                # All categories processed
                                completion_msg = "\n\n" + "="*80 + "\n\n"
                                completion_msg += "**All KVI calculations completed!**\n\n"
                                completion_msg += "="*80 + "\n\n"
                                
                                yield {
                                    'type': 'content',
                                    'delta': completion_msg,
                                    'agent': 'kvi_calculator'
                                }
                                
                                yield {
                                    'type': 'agent_complete',
                                    'agent': 'kvi_calculator',
                                    'full_response': response_text
                                }
                                
                                response_text += completion_msg
                                
                                log.info("KVI calculator completed, automatically triggering kvi_advisor")
                                
                                # Automatically trigger kvi_advisor
                                transition_msg = "\n"
                                yield {
                                    'type': 'transition',
                                    'from_agent': 'kvi_calculator',
                                    'to_agent': 'kvi_advisor',
                                    'message': transition_msg
                                }
                                
                                response_text += transition_msg
                                
                                kvi_advisor = self.registry.get_agent("kvi_advisor")
                                if kvi_advisor:
                                    # Build prompt with all calculation results
                                    advisor_prompt = self._build_advisor_prompt()
                                    
                                    yield {
                                        'type': 'status',
                                        'message': 'Preparing advisor...',
                                        'agent': 'kvi_advisor'
                                    }
                                    
                                    log.info("Calling kvi_advisor agent")
                                    log.info(f"Advisor prompt length: {len(advisor_prompt)} chars")
                                    
                                    # Stream advisor response
                                    advisor_accumulated = ""
                                    if hasattr(kvi_advisor, 'run_stream'):
                                        async for chunk in kvi_advisor.run_stream(advisor_prompt):
                                            advisor_accumulated += chunk
                                            yield {
                                                'type': 'content',
                                                'delta': chunk,
                                                'agent': 'kvi_advisor'
                                            }
                                    else:
                                        advisor_response = await kvi_advisor.run(advisor_prompt)
                                        advisor_accumulated = advisor_response
                                        yield {
                                            'type': 'content',
                                            'delta': advisor_response,
                                            'agent': 'kvi_advisor'
                                        }
                                    
                                    advisor_response = advisor_accumulated
                                    
                                    # Notify that advisor started
                                    log.info(f"Sending agent_complete event for kvi_advisor with {len(advisor_response)} chars")
                                    yield {
                                        'type': 'agent_complete',
                                        'agent': 'kvi_advisor',
                                        'full_response': advisor_response
                                    }
                                    
                                    # Add advisor's initial message to response
                                    response_text += advisor_response
                                    
                                    # Create a NEW history for the advisor
                                    # Include a reference to the calculations being done
                                    advisor_history = [
                                        ChatMessage(role="assistant", content=advisor_response)
                                    ]
                                    
                                    log.info("Transitioned to kvi_advisor agent")
                                    log.info(f"Advisor history length: {len(advisor_history)} messages")
                                    
                                    yield {
                                        'type': 'complete',
                                        'final_response': response_text,
                                        'history': [msg.dict() for msg in advisor_history],
                                        'current_agent': 'kvi_advisor'
                                    }
                                    return
                                else:
                                    log.warning("KVI advisor agent not found")
                                    log.info("Workflow completed successfully with all KVIs calculated")
                                    
                                    yield {
                                        'type': 'complete',
                                        'final_response': response_text,
                                        'history': [msg.dict() for msg in updated_history],
                                        'current_agent': 'kvi_calculator'
                                    }
                                    return
                            else:
                                log.warning("No finalizer output available for calculator")
                                warning_msg = "\n\nWorkflow completed with KPI values collected."
                                yield {
                                    'type': 'content',
                                    'delta': warning_msg,
                                    'agent': current_agent_name
                                }
                                response_text += warning_msg
                        else:
                            log.warning("KVI calculator agent not found")
                            warning_msg = "\n\nWorkflow completed with KPI values collected."
                            yield {
                                'type': 'content',
                                'delta': warning_msg,
                                'agent': current_agent_name
                            }
                            response_text += warning_msg
                    else:
                        log.error("KPI structurer did not return a structured CollectedKPIResponse")
                        error_msg = "\n\nError extracting KPI values. Workflow completed."
                        yield {
                            'type': 'content',
                            'delta': error_msg,
                            'agent': current_agent_name
                        }
                        response_text += error_msg
                else:
                    log.warning("KPI structurer agent not found")
                    warning_msg = "\n\nWorkflow completed with KPI values collected."
                    yield {
                        'type': 'content',
                        'delta': warning_msg,
                        'agent': current_agent_name
                    }
                    response_text += warning_msg
                
                log.info("Workflow completed")
                
                yield {
                    'type': 'complete',
                    'final_response': response_text,
                    'history': [msg.dict() for msg in updated_history],
                    'current_agent': current_agent_name
                }
                return
        
        # Stay with current agent
        yield {
            'type': 'complete',
            'final_response': response_text,
            'history': [msg.dict() for msg in updated_history],
            'current_agent': current_agent_name
        }
