from typing import Any, Literal

from langchain_core.messages import HumanMessage
from langgraph.constants import END, START
from langgraph.graph import StateGraph
from langgraph.types import interrupt

from src.agent.common.context import ContextSchema
from src.agent.extend import extend_graph
from src.agent.node.main import (
    get_store_info,
    get_user_preferences,
    identify_question,
    need_reserve,
)
from src.agent.node.recommend import RECOMMEND_REQUEST_KEY, RECOMMEND_RESPONSE_KEY
from src.agent.node.reserve import RESERVE_REQUEST_KEY, RESERVE_RESPONSE_KEY
from src.agent.recommend import recommend_graph
from src.agent.reserve import reserve_graph
from src.agent.state.main import NeedReserveOutput, State

builder = StateGraph(State, context_schema=ContextSchema)
builder.add_node(get_store_info)
builder.add_node(identify_question)
builder.add_node("recommend_graph", recommend_graph)
builder.add_node("reserve_graph", reserve_graph)
builder.add_node("extend_graph", extend_graph)
builder.add_node(get_user_preferences)
builder.add_node(need_reserve)


def _normalize_resume_value(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("value", "answer", "text"):
            candidate = value.get(key)
            if candidate:
                return str(candidate).strip()
    if value is None:
        return ""
    return str(value).strip()


def recommend_input_gateway(state: State) -> dict[str, Any]:
    last_message = state["messages"][-1]
    payload = last_message.additional_kwargs.get(RECOMMEND_REQUEST_KEY, {})
    question = str(payload.get("question") or "").strip()
    if not question:
        return {}

    answer = _normalize_resume_value(
        interrupt({"field": "recommend_requirements", "question": question})
    )
    if not answer:
        answer = _normalize_resume_value(
            interrupt({"field": "recommend_requirements", "question": f"{question}（不能为空）"})
        )

    return {
        "messages": [
            HumanMessage(
                content=answer,
                additional_kwargs={
                    RECOMMEND_RESPONSE_KEY: {
                        "field": "recommend_requirements",
                        "value": answer,
                    }
                },
            )
        ]
    }


def reserve_input_gateway(state: State) -> dict[str, str]:
    last_message = state["messages"][-1]
    payload = last_message.additional_kwargs.get(RESERVE_REQUEST_KEY, {})
    field = str(payload.get("field") or "").strip()
    question = str(payload.get("question") or "").strip()
    if not field or not question:
        return {}

    answer = _normalize_resume_value(interrupt({"field": field, "question": question}))
    if not answer:
        answer = _normalize_resume_value(
            interrupt({"field": field, "question": f"{question}（不能为空）"})
        )

    return {
        "messages": [
            HumanMessage(
                content=answer,
                additional_kwargs={
                    RESERVE_RESPONSE_KEY: {
                        "field": field,
                        "value": answer,
                    }
                },
            )
        ]
    }


builder.add_node(recommend_input_gateway)
builder.add_node(reserve_input_gateway)
builder.add_edge(START, "get_store_info")
builder.add_edge("get_store_info", "identify_question")


def router_messages(
    state: State,
) -> Literal["recommend_graph", "reserve_graph", "extend_graph", "get_user_preferences"]:
    user_intent = state["user_intent"]
    if user_intent == "recommend_house":
        return "recommend_graph"
    if user_intent == "reserve_house":
        return "reserve_graph"
    if user_intent == "get_info":
        return "get_user_preferences"
    return "extend_graph"


builder.add_conditional_edges(
    "identify_question",
    router_messages,
    ["recommend_graph", "reserve_graph", "extend_graph", "get_user_preferences"],
)


def route_after_recommend(
    state: State,
) -> Literal["recommend_input_gateway", "need_reserve"]:
    payload = state["messages"][-1].additional_kwargs.get(RECOMMEND_REQUEST_KEY, {})
    if str(payload.get("field") or "").strip():
        return "recommend_input_gateway"
    return "need_reserve"


builder.add_conditional_edges(
    "recommend_graph",
    route_after_recommend,
    ["recommend_input_gateway", "need_reserve"],
)
builder.add_edge("recommend_input_gateway", "recommend_graph")


def should_reserve(state: NeedReserveOutput) -> Literal["reserve_graph", "__end__"]:
    if str(state["reserve"]).strip() == "需要":
        return "reserve_graph"
    return END


builder.add_conditional_edges(
    "need_reserve",
    should_reserve,
    ["reserve_graph", END],
)


def route_after_reserve(state: State) -> Literal["reserve_input_gateway", "__end__"]:
    payload = state["messages"][-1].additional_kwargs.get(RESERVE_REQUEST_KEY, {})
    if str(payload.get("field") or "").strip():
        return "reserve_input_gateway"
    return END


builder.add_conditional_edges(
    "reserve_graph",
    route_after_reserve,
    ["reserve_input_gateway", END],
)
builder.add_edge("reserve_input_gateway", "reserve_graph")

builder.add_edge("get_user_preferences", END)
builder.add_edge("extend_graph", END)

graph = builder.compile()
