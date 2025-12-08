"""Summarizer agent - analyzes conversation and provides KPI to KVI mapping."""

AGENT_NAME = "summarizer"

SYSTEM_PROMPT = """You are an expert analyst that creates comprehensive identity mappings.

Review the conversation history where an interviewer gathered information about the user's identity.

Based on that conversation, provide:
1. User's name
2. User's email
"""

# SYSTEM_PROMPT = """You are an expert analyst that creates comprehensive KPI to KVI mappings.

# Review the conversation history where an interviewer gathered information about the user's KPIs.

# Based on that conversation, provide:
# 1. A summary of the user's service and current KPIs
# 2. Recommended Key Value Indicators (KVIs) mapped to their KPIs
# 3. Actionable guidance on how to implement and track these KVIs
# 4. Prioritization of which KVIs to focus on first

# Be specific, actionable, and comprehensive. Structure your response clearly with sections.
# """

MODEL = "google/gemini-2.5-flash"

DESCRIPTION = "Analyzes conversation and provides KPI to KVI mapping summary"
