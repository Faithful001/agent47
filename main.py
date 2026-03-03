"""
A weather forecasting agent using Langgraph and Gemini.
Things to implement:
1. model switching
2. dynamic prompt
3. handling tool errors

"""

import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from dataclasses import dataclass

from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain.agents.middleware import wrap_model_call, wrap_tool_call, dynamic_prompt, ModelRequest, ModelResponse
from langchain.chat_models import init_chat_model
from langchain.tools import ToolRuntime, tool
from langchain.messages import ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel

SYSTEM_PROMPT = """You are an expert weather forecaster, who speaks in puns.

You have access to two tools:

- get_weather_for_location: use this to get the weather for a specific location
- get_user_location: use this to get the user's location

If a user asks you for the weather, make sure you know the location. 
If you can tell from the question that they mean wherever they are, 
use the get_user_location tool to find their location."""

# context
@dataclass
class Context:
    """Custom runtime context schema"""
    user_id: str
    user_role: str

# response
class ResponseFormat(BaseModel):
    """class for the response format"""
    weather_condition: str | None = None

checkpointer = InMemorySaver()

# tools
@tool
def get_weather_for_location(city: str) -> str:
    """Get the weather in a city"""
    return f"The weather is sunny in {city}"

@tool
def get_user_location(runtime: ToolRuntime[Context]):
    """Get user location"""
    user_id = runtime.context.user_id
    return "Nigeria" if user_id == "1" else "SF"


# dynamic prompt
@dynamic_prompt
def user_role_prompt(request: ModelRequest) -> str:
    """Dynamically switch prompts based on the user role"""
    user_role = getattr(request.runtime.context, "user_role", "user")

    match user_role:
        case "expert":
            return f"{SYSTEM_PROMPT} Provide detailed technical responses"
        case "beginner":
            return f"{SYSTEM_PROMPT} Explain concepts simply and avoid jargon."
        case _:
            return SYSTEM_PROMPT


GOOGLE_API_KEY=os.getenv("GOOGLE_API_KEY")

basic_model = init_chat_model(
    model="gemini-3-flash-preview",
    model_provider="google_genai",
    temperature=0.5,
    timeout=10,
    max_tokens=1000
    )

advanced_model = init_chat_model(
    model="gemini-3.1-pro",
    model_provider="google_genai",
    temperature=0.5,
    timeout=10,
    max_tokens=1000
    )

@wrap_model_call
def model_selection(request: ModelRequest, handler) -> ModelResponse:
    """Model selection handler"""
    message_count = len(request.state["messages"])
    selected = advanced_model if message_count > 10 else basic_model
    model_name = "advanced" if selected is advanced_model else "basic"
    print(f"[middleware] Messages: {message_count}, using: {model_name}")
    return handler(request.override(model=selected))

@wrap_tool_call
def handle_tool_errors(request: ModelRequest, handler):
    """Handle errors from tool calls"""
    try:
        return handler(request)
    except Exception as e:
        return ToolMessage(
            content=f"Tool error: Please check your input and try again. ({str(e)})",
            tool_call_id=request.tool_call["id"]
            )

# agents
agent = create_agent(
    model=basic_model,
    tools=[get_weather_for_location, get_user_location],
    system_prompt=SYSTEM_PROMPT,
    context_schema=Context,
    response_format=ToolStrategy(ResponseFormat),
    checkpointer=checkpointer,
    middleware=[model_selection, user_role_prompt]
)

config = {"configurable": {"thread_id": "1"}}

result = agent.invoke(
        {"messages": [
            {"role": "user",
            "content": "what is the weather outside?"
            }
        ]},
        config=config,
        context=Context(user_id="1", user_role="expert")
    )


print(result["structured_response"].weather_condition)
