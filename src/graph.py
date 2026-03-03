from langgraph.graph import StateGraph
from src.state import ContractState
from src.agents.handler import handler_agent


graph = StateGraph(ContractState)

def handler_node(state: ContractState):
    bug = state.bug_description
    repo = state.repo_path

    result = handler_agent.invoke({"messages": [
        {"role": "user", 
        "content": f"Analyze this bug in {repo}: {bug}"
        }
    ]
    })

    response = result["structured_response"]
    return {"relevant_files": response.relevant_files}

graph.add_node("handler", handler_node)

graph.add_edge("handler")