from typing import Literal

from langgraph.constants import END, START
from langgraph.graph import StateGraph
from langgraph.prebuilt import tools_condition

from src.agent.common.context import ContextSchema
from src.agent.node.reserve import (
    add_reserve_message,
    call_order,
    check_required_fields,
    finalize_reserve_result,
    tool_node,
)
from src.agent.state.reserve import ReserveState

builder = StateGraph(ReserveState, context_schema=ContextSchema)
builder.add_node(check_required_fields)
builder.add_node(add_reserve_message)
builder.add_node(call_order)
builder.add_node(finalize_reserve_result)
builder.add_node("tool_node", tool_node)

builder.add_edge(START, "check_required_fields")


def route_reserve_inputs(state: ReserveState) -> Literal["add_reserve_message", "__end__"]:
    if str(state.get("reserve_missing_field") or "").strip():
        return END
    return "add_reserve_message"


builder.add_conditional_edges(
    "check_required_fields",
    route_reserve_inputs,
    ["add_reserve_message", END],
)
builder.add_edge("add_reserve_message", "call_order")
builder.add_conditional_edges(
    "call_order",
    tools_condition,
    {
        "tools": "tool_node",
        "__end__": END,
    },
)
builder.add_edge("tool_node", "finalize_reserve_result")
builder.add_edge("finalize_reserve_result", END)

reserve_graph = builder.compile()
