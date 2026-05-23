from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage, filter_messages
from langgraph.runtime import Runtime
from langgraph.store.base import BaseStore
from langgraph.types import interrupt
from pydantic import BaseModel, Field

from src.agent.common.context import ContextSchema
from src.agent.common.llm import model
from src.agent.state.main import NeedReserveOutput, State


def _normalize_budget_preferences(prefs: dict) -> dict:
    normalized = dict(prefs or {})
    budget_min = normalized.get("budget_min")
    budget_max = normalized.get("budget_max")

    if budget_min is not None and budget_min <= 0:
        normalized["budget_min"] = None
        budget_min = None
    if budget_max is not None and budget_max <= 0:
        normalized["budget_max"] = None
        budget_max = None

    if budget_min is not None and budget_max is not None and budget_max < budget_min:
        normalized["budget_max"] = None

    return normalized


def get_store_info(state: State, runtime: Runtime[ContextSchema], *, store: BaseStore) -> dict:
    user_id = runtime.context.get("user_id")
    namespace = (user_id, "preferences")
    prefs_result = store.search(namespace)
    if prefs_result and prefs_result[0]:
        return {"user_preferences": _normalize_budget_preferences(prefs_result[0].value)}
    return {"user_preferences": {}}


class UserMessage(BaseModel):
    type: Literal["recommend_house", "reserve_house", "get_info", "others"] = Field(
        description="根据用户当前消息判断意图：推荐房源、预约房源、查询个人信息或其他闲聊。"
    )


def identify_question(state: State) -> dict[str, str]:
    user_intent = model.with_structured_output(UserMessage).invoke(
        [
            SystemMessage(
                content=(
                    "你是租房助手的意图识别器。"
                    "请只根据用户当前这一条消息判断意图，返回以下四类之一："
                    "`recommend_house`：用户想找房、看房、筛选房源、推荐房源；"
                    "`reserve_house`：用户想预约、预定、确认下单某个房源；"
                    "`get_info`：用户想查询自己的预算偏好、历史预约记录、已预约房源；"
                    "`others`：打招呼、闲聊、笑话、与租房无关的问题。"
                    "像“给我推荐房子”“我想租房”“帮我找房子”都应判为 `recommend_house`。"
                    "像“查询我的信息”“我预约了几个房子”“我的历史预约”都应判为 `get_info`。"
                    "像“需要”“我要预约这套”“帮我预约”都应判为 `reserve_house`。"
                )
            ),
            state["messages"][-1],
        ]
    )
    return {"user_intent": user_intent.type}


def need_reserve(state: State) -> NeedReserveOutput:
    prompt = (
        "已经为您推荐了合适的房源，是否需要我继续帮您预约房源？\n"
        "如果不需要，请回复“不需要”。\n"
        "如果需要，请回复“需要”。"
    )
    answer = interrupt(prompt)
    return {"reserve": str(answer).strip()}


def _reserved_item_to_text(item: object, index: int) -> str:
    if isinstance(item, dict):
        order_id = item.get("order_id", "")
        title = item.get("title", "")
        phone_number = item.get("phone_number", "")
    else:
        order_id = getattr(item, "order_id", "")
        title = getattr(item, "title", "")
        phone_number = getattr(item, "phone_number", "")
    return (
        f"{index}. 预约工单ID：{order_id}"
        f"，房源标题：{title}"
        f"，预约电话：{phone_number}\n"
    )


def get_user_preferences(state: State) -> dict[str, list]:
    prefs = _normalize_budget_preferences(state.get("user_preferences", {}) or {})
    user_messages = filter_messages(state["messages"], include_types="human")
    reserved_info = prefs.get("reserved_info", [])

    if reserved_info:
        reserved_str = "\n" + "".join(
            _reserved_item_to_text(item, index)
            for index, item in enumerate(reserved_info, start=1)
        )
    else:
        reserved_str = "暂无预约记录"

    result = model.invoke(
        [
            SystemMessage(
                content=(
                    "你是一个租房助手。"
                    "请基于用户的预算偏好和历史预约信息回答问题。"
                    "如果相关信息为空，就明确说明暂无数据，不要编造。"
                )
            ),
            HumanMessage(
                content=(
                    "用户的历史偏好信息如下：\n"
                    f"1. 最低预算：{prefs.get('budget_min')}\n"
                    f"2. 最高预算：{prefs.get('budget_max')}\n"
                    f"3. 已预约房源：{reserved_str}"
                )
            ),
            user_messages[-1],
        ]
    )
    return {"messages": [result]}
