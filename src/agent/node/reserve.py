import uuid
from typing import Any, Annotated

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage, filter_messages
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedStore, ToolNode, ToolRuntime

from src.agent.common.llm import model
from src.agent.common.store import ReservedInfo, UserPreferences

RESERVE_REQUIRED_FIELDS = (
    ("title", "请输入要预约的房源名称"),
    ("phone", "请输入您的手机号"),
    ("id_card", "请输入您的身份证号"),
)

RESERVE_REQUEST_KEY = "reserve_input_request"
RESERVE_RESPONSE_KEY = "reserve_input_response"


def _extract_resume_update(state: dict[str, Any]) -> dict[str, str]:
    human_messages = filter_messages(state["messages"], include_types="human")
    updates: dict[str, str] = {}
    for human_message in human_messages:
        payload = human_message.additional_kwargs.get(RESERVE_RESPONSE_KEY)
        if not payload:
            continue

        field = str(payload.get("field") or "").strip()
        value = str(payload.get("value") or "").strip()
        if field and value:
            updates[field] = value
    return updates


def _title_exists_in_history(state: dict[str, Any], title: str) -> bool:
    if not title:
        return False

    for message in state["messages"]:
        content = getattr(message, "content", "")
        if isinstance(content, list):
            text = "".join(str(part) for part in content)
        else:
            text = str(content)
        if title in text:
            return True
    return False


def check_required_fields(state: dict[str, Any]) -> dict[str, str | None]:
    resume_update = _extract_resume_update(state)
    for field, question in RESERVE_REQUIRED_FIELDS:
        current_value = str(resume_update.get(field) or state.get(field) or "").strip()
        if field == "title" and current_value and not _title_exists_in_history(state, current_value):
            return {
                **resume_update,
                "title": "",
                "reserve_missing_field": field,
                "reserve_missing_question": "未找到该房源，请从当前会话中已推荐的房源标题里选择一项重新输入",
                "messages": [
                    AIMessage(
                        content="",
                        additional_kwargs={
                            RESERVE_REQUEST_KEY: {
                                "field": field,
                                "question": "未找到该房源，请从当前会话中已推荐的房源标题里选择一项重新输入",
                            }
                        },
                    )
                ],
            }
        if not current_value:
            return {
                **resume_update,
                "reserve_missing_field": field,
                "reserve_missing_question": question,
                "messages": [
                    AIMessage(
                        content="",
                        additional_kwargs={
                            RESERVE_REQUEST_KEY: {
                                "field": field,
                                "question": question,
                            }
                        },
                    )
                ],
            }
    return {
        **resume_update,
        "reserve_missing_field": "",
        "reserve_missing_question": "",
    }


def add_reserve_message(state: dict[str, Any]) -> dict[str, list[HumanMessage]]:
    reserve_prompt = """
请根据以下信息为用户生成预约工单：
- 房源标题：{title}
- 手机号：{phone}
- 身份证号：{id_card}
"""
    return {
        "messages": [
            HumanMessage(
                content=reserve_prompt.format(
                    title=state["title"],
                    phone=state["phone"],
                    id_card=state["id_card"],
                )
            )
        ]
    }


@tool
def generate_orders(
    phone: str,
    id_card: str,
    house_title: str,
    runtime: ToolRuntime,
    store: Annotated[Any, InjectedStore()],
) -> str:
    """根据手机号、身份证号和房源标题生成预约工单。"""

    order_id = str(uuid.uuid4())
    reserved_info = ReservedInfo(
        order_id=order_id,
        title=house_title,
        phone_number=phone,
    )

    user_id = runtime.context.get("user_id")
    namespace = (user_id, "preferences")
    prefs_result = store.search(namespace)

    if not prefs_result:
        prefs = UserPreferences(reserved_info=[reserved_info]).model_dump(exclude_none=True)
        store.put(namespace, str(uuid.uuid4()), prefs)
    else:
        prefs = prefs_result[0].value or {}
        if hasattr(prefs, "model_dump"):
            prefs = prefs.model_dump(exclude_none=True)

        reserved_items = prefs.setdefault("reserved_info", [])
        reserved_items.append(reserved_info.model_dump(exclude_none=True))
        store.put(namespace, prefs_result[0].key, prefs)

    return f"已经成功预约房源：{house_title}，预约工单号为：{order_id}"


tool_node = ToolNode([generate_orders])


def call_order(state: dict[str, Any]) -> dict[str, list[Any]]:
    system_prompt = (
        "你是一个预约工单生成助手。"
        "现在所有预约信息都已经齐全，必须立刻调用 generate_orders 工具。"
        "不要输出额外解释。"
    )
    return {
        "messages": [
            model.bind_tools([generate_orders], tool_choice="generate_orders").invoke(
                [SystemMessage(content=system_prompt)] + state["messages"]
            )
        ]
    }


def finalize_reserve_result(state: dict[str, Any]) -> dict[str, Any]:
    tool_messages = [msg for msg in state["messages"] if isinstance(msg, ToolMessage)]
    if not tool_messages:
        return {
            "messages": [AIMessage(content="预约流程已完成，但没有读取到工单结果，请稍后重试。")],
            "title": "",
            "phone": "",
            "id_card": "",
            "reserve_missing_field": "",
            "reserve_missing_question": "",
        }

    latest_tool_message = tool_messages[-1]
    return {
        "messages": [AIMessage(content=str(latest_tool_message.content))],
        "title": "",
        "phone": "",
        "id_card": "",
        "reserve_missing_field": "",
        "reserve_missing_question": "",
    }
