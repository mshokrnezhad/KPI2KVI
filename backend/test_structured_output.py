"""
Test script to verify PydanticAI structured output with OpenRouter
"""
import asyncio
import os
import json
import re
from typing import Any
from pydantic import BaseModel, Field
from pydantic_ai import Agent

# Define a simple Pydantic model for testing
class TestCategory(BaseModel):
    """A test category with id and name."""
    id: str = Field(..., description="Category ID")
    name: str = Field(..., description="Category name")

class TestResponse(BaseModel):
    """Test response with a list of categories."""
    categories: list[TestCategory] = Field(..., description="List of categories")

async def test_structured_output():
    """Test structured output with OpenRouter."""
    
    # Load environment variables
    from dotenv import load_dotenv
    load_dotenv(".env")
    
    api_key = os.getenv("OPENROUTER_API_KEY")
    base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    model_name = "openai/gpt-5-mini"
    
    print(f"API Key loaded: {bool(api_key)}")
    print(f"Model: {model_name}")
    print(f"Base URL: {base_url}")
    print("-" * 60)
    
    # In pydantic-ai 0.0.19, configure via environment variables
    os.environ['OPENAI_API_KEY'] = api_key
    os.environ['OPENAI_BASE_URL'] = base_url
    
    # Use model string with openai: prefix for OpenAI-compatible APIs
    model = f"openai:{model_name}"
    print(f"Using model string: {model}")
    
    # # --- TEST A: Constructor with result_type (pydantic-ai 0.0.19) ---
    # print("\n=== TEST A: Constructor `Agent(model, result_type=Type)` ===")
    # try:
    #     # In pydantic-ai 0.0.19, result_type is a constructor parameter
    #     agent = Agent(
    #         model,
    #         result_type=TestResponse,
    #         system_prompt="You are a helpful assistant. Return your response in JSON format."
    #     )
        
    #     print("✓ Agent created successfully with result_type parameter")
        
    #     result = await agent.run("List 2 primary colors (Red, Blue)")
    #     print(f"Result type: {type(result.output)}")
        
    #     if isinstance(result.output, TestResponse):
    #         print("✓ SUCCESS: Received structured TestResponse object directly")
    #         print(f"  Data: {result.output}")
    #     elif isinstance(result.output, str):
    #         print("⚠ RECEIVED STRING: Provider returned text instead of object")
    #         print(f"  Raw output: {result.output[:100]}...")
    #         _try_parse_json(result.output)
            
    # except Exception as e:
    #     print(f"✗ ERROR: {e}")

    # --- TEST B: Verify structured output works end-to-end ---
    print("\n=== TEST B: End-to-end structured output test ===")
    try:
        # Create agent matching the working example from user
        agent = Agent(
            model,
            result_type=TestResponse,
            system_prompt="Extract categories from the user's request. Return a JSON with structure: {\"categories\": [{\"id\": \"string\", \"name\": \"string\"}]}"
        )
        print("✓ Agent created with result_type")
        
        result = await agent.run("Give me two primary colors: Red and Blue")
        
        print(f"Result type: {type(result.data)}")
        print(f"Result data: {result.data}")
        
        if isinstance(result.data, TestResponse):
            print("✓ SUCCESS: Structured output is working!")
            print(f"  Categories received: {len(result.data.categories)}")
            for cat in result.data.categories:
                print(f"    - {cat.id}: {cat.name}")
        elif isinstance(result.data, str):
            print("⚠ RECEIVED STRING: Needs manual parsing")
            print(f"  Raw: {result.data[:150]}")
            _try_parse_json(result.data)
             
    except Exception as e:
        print(f"✗ ERROR: {e}")

def _try_parse_json(text: str):
    """Helper to check if string output is valid JSON."""
    try:
        # Clean markdown code blocks
        cleaned = re.sub(r'^```(?:json)?\s*\n?', '', text, flags=re.MULTILINE)
        cleaned = re.sub(r'\n?```\s*$', '', cleaned, flags=re.MULTILINE)
        cleaned = cleaned.strip()
        
        data = json.loads(cleaned)
        print(f"  ✓ String contains valid JSON")
        try:
            obj = TestResponse(**data)
            print(f"  ✓ JSON matches Pydantic model structure")
        except Exception as ve:
            print(f"  ✗ JSON does NOT match model: {ve}")
    except json.JSONDecodeError:
        print(f"  ✗ String is NOT valid JSON")

if __name__ == "__main__":
    asyncio.run(test_structured_output())
