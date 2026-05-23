import os
import re
import uuid
from typing import Any, Optional

from dotenv import load_dotenv
from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langchain_community.utilities import SQLDatabase
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, filter_messages
from langgraph.prebuilt import ToolNode
from langgraph.runtime import Runtime
from langgraph.store.base import BaseStore
from pydantic import BaseModel, Field

from src.agent.common.context import ContextSchema
from src.agent.common.llm import model
from src.agent.common.store import UserPreferences
from src.agent.state.recommend import RecommendState, get_recommend_info

RECOMMEND_REQUEST_KEY = "recommend_input_request"
RECOMMEND_RESPONSE_KEY = "recommend_input_response"


class UserInfo(BaseModel):
    city: Optional[str] = Field(default=None, description="用户明确提到的租房城市。")
    district: Optional[str] = Field(default=None, description="用户明确提到的租房区域。")
    budget_min: Optional[float] = Field(default=None, description="最低预算，单位为元/月。")
    budget_max: Optional[float] = Field(default=None, description="最高预算，单位为元/月。")
    room_type: Optional[str] = Field(default=None, description="房屋类型，例如整租、合租。")
    orientation: Optional[str] = Field(default=None, description="房屋朝向。")
    room_count: Optional[int] = Field(default=None, description="希望推荐的房源数量。")
    others: Optional[str] = Field(default=None, description="其他补充要求。")


RECOMMEND_STATE_KEYS = (
    "city",
    "district",
    "budget_min",
    "budget_max",
    "room_type",
    "orientation",
    "room_count",
    "others",
)

COMMON_CITY_NAMES = (
    "北京",
    "上海",
    "广州",
    "深圳",
    "杭州",
    "成都",
    "重庆",
    "武汉",
    "南京",
    "苏州",
    "天津",
    "西安",
    "长沙",
    "郑州",
    "青岛",
    "宁波",
    "东莞",
    "佛山",
    "合肥",
    "福州",
    "厦门",
    "济南",
    "昆明",
    "沈阳",
    "大连",
    "无锡",
)

BUDGET_PATTERNS = (
    r"\d+\s*[-~到至]\s*\d+\s*(元|块|k|K|千)?",
    r"预算\s*\d+",
    r"\d+\s*(元|块|k|K|千)\s*/\s*月",
    r"\d+\s*(元|块|k|K|千)\s*每月",
    r"\d+\s*(元|块|k|K|千)\s*(以下|以内|以上)",
)

LOWER_BOUND_BUDGET_PATTERNS = (
    r"\d+\s*(元|块|k|K|千)\s*(以上|起|起步|至少|不低于|大于等于|>=)",
)

UPPER_BOUND_BUDGET_PATTERNS = (
    r"\d+\s*(元|块|k|K|千)\s*(以下|以内|不超过|最多|小于等于|<=)",
)


def _extract_info(messages: list[HumanMessage | SystemMessage]) -> UserInfo:
    system_message = SystemMessage(
        content=(
            "你是一个租房需求信息提取专家。"
            "只提取用户明确说过的信息，不要猜测。"
            "如果用户没有明确提供城市或预算范围，必须返回 null。"
            "预算统一换算为元/月。"
        )
    )
    return model.with_structured_output(schema=UserInfo).invoke([system_message] + messages)


def _carry_recommend_state(state: RecommendState) -> dict[str, Any]:
    carried = {
        key: state.get(key)
        for key in RECOMMEND_STATE_KEYS
        if state.get(key) is not None
    }
    if state.get("user_preferences") is not None:
        carried["user_preferences"] = state.get("user_preferences")
    return carried


def _apply_defaults_for_missing_info(state: dict[str, Any]) -> None:
    if not state.get("city"):
        state["city"] = "西安"
    if state.get("budget_min") is None:
        state["budget_min"] = 500.0
    if state.get("budget_max") is None:
        state["budget_max"] = 5000.0
    if not state.get("room_count"):
        state["room_count"] = 3


def _normalize_budget_info(latest_text: str, updated_state: dict[str, Any]) -> None:
    cur_min = updated_state.get("budget_min")
    cur_max = updated_state.get("budget_max")
    lower_only = any(re.search(pattern, latest_text) for pattern in LOWER_BOUND_BUDGET_PATTERNS)
    upper_only = any(re.search(pattern, latest_text) for pattern in UPPER_BOUND_BUDGET_PATTERNS)

    if cur_min is not None and cur_min <= 0:
        updated_state["budget_min"] = None
        cur_min = None
    if cur_max is not None and cur_max <= 0:
        updated_state["budget_max"] = None
        cur_max = None

    if lower_only and cur_min is not None:
        updated_state["budget_max"] = None
        cur_max = None
    if upper_only and cur_max is not None:
        updated_state["budget_min"] = None
        cur_min = None

    if cur_min is not None and cur_max is not None and cur_max < cur_min:
        if lower_only:
            updated_state["budget_max"] = None
        elif upper_only:
            updated_state["budget_min"] = None
        else:
            updated_state["budget_min"], updated_state["budget_max"] = cur_max, cur_min


def _build_missing_question(updated_state: dict[str, Any]) -> str:
    missing_info = []
    if not updated_state.get("city"):
        missing_info.append("城市")
    if updated_state.get("budget_min") is None and updated_state.get("budget_max") is None:
        missing_info.append("预算范围")
    return (
        "为了给您推荐合适的房源，请补充以下信息："
        + "、".join(missing_info)
        + "。如果您愿意接受默认条件，也可以回复“不提供”。"
    )


def _persist_budget_preferences(
    updated_state: dict[str, Any],
    runtime: Runtime[ContextSchema],
    store: BaseStore,
) -> None:
    if updated_state.get("budget_min") is None and updated_state.get("budget_max") is None:
        return

    user_id = runtime.context.get("user_id")
    namespace = (user_id, "preferences")
    prefs_result = store.search(namespace)

    if not prefs_result:
        prefs = UserPreferences(
            budget_min=updated_state.get("budget_min"),
            budget_max=updated_state.get("budget_max"),
        ).model_dump(exclude_none=True)
        store.put(namespace, str(uuid.uuid4()), prefs)
        updated_state["user_preferences"] = prefs
        return

    prefs = prefs_result[0].value or {}
    if hasattr(prefs, "model_dump"):
        prefs = prefs.model_dump(exclude_none=True)

    store_min = prefs.get("budget_min")
    store_max = prefs.get("budget_max")
    cur_min = updated_state.get("budget_min")
    cur_max = updated_state.get("budget_max")

    if store_min is None or (cur_min is not None and cur_min < store_min):
        prefs["budget_min"] = cur_min
    if store_max is None or (cur_max is not None and cur_max > store_max):
        prefs["budget_max"] = cur_max

    store.put(namespace, prefs_result[0].key, prefs)
    updated_state["user_preferences"] = prefs


def _extract_resume_response(state: RecommendState) -> str:
    human_messages = filter_messages(state["messages"], include_types="human")
    if not human_messages:
        return ""

    latest_human = human_messages[-1]
    payload = latest_human.additional_kwargs.get(RECOMMEND_RESPONSE_KEY)
    if not payload:
        return ""
    return str(payload.get("value") or "").strip()


def _user_explicitly_provided_city(text: str) -> bool:
    if any(city in text for city in COMMON_CITY_NAMES):
        return True
    return bool(re.search(r"[\u4e00-\u9fff]{2,6}(市|区|县)", text))


def _user_explicitly_provided_budget(text: str) -> bool:
    return any(re.search(pattern, text) for pattern in BUDGET_PATTERNS)


def _enforce_strong_constraints(
    latest_text: str,
    updated_state: dict[str, Any],
) -> None:
    if not _user_explicitly_provided_city(latest_text):
        updated_state.pop("city", None)
        updated_state.pop("district", None)

    if not _user_explicitly_provided_budget(latest_text):
        updated_state.pop("budget_min", None)
        updated_state.pop("budget_max", None)
        return

    _normalize_budget_info(latest_text, updated_state)


def collect_user_info(
    state: RecommendState,
    runtime: Runtime[ContextSchema],
    *,
    store: BaseStore,
) -> dict[str, Any]:
    user_messages = filter_messages(state["messages"], include_types="human")
    latest_user_message = user_messages[-1]
    latest_text = str(latest_user_message.content).strip()
    resumed_text = _extract_resume_response(state)
    pref = state.get("user_preferences") or {}

    extract_messages: list[HumanMessage] = [latest_user_message]
    if pref.get("budget_min") is not None or pref.get("budget_max") is not None:
        extract_messages.insert(
            0,
            HumanMessage(
                content=(
                    "用户的历史预算偏好如下："
                    f"最低预算：{pref.get('budget_min')}；"
                    f"最高预算：{pref.get('budget_max')}"
                )
            ),
        )

    updated_state = _carry_recommend_state(state)

    if resumed_text == "不提供" or latest_text == "不提供":
        _apply_defaults_for_missing_info(updated_state)
    else:
        extracted_info = _extract_info(extract_messages).model_dump(exclude_none=True)
        _enforce_strong_constraints(latest_text, extracted_info)
        updated_state.update(extracted_info)

    if not updated_state.get("city") or (
        updated_state.get("budget_min") is None and updated_state.get("budget_max") is None
    ):
        return {
            **updated_state,
            "messages": [
                AIMessage(
                    content="",
                    additional_kwargs={
                        RECOMMEND_REQUEST_KEY: {
                            "field": "recommend_requirements",
                            "question": _build_missing_question(updated_state),
                        }
                    },
                )
            ],
        }

    _persist_budget_preferences(updated_state, runtime, store)
    updated_state["messages"] = [HumanMessage(content=get_recommend_info(updated_state))]
    return updated_state


load_dotenv()
db_user = os.getenv("DB_USER") or os.getenv("db_user")
db_password = os.getenv("DB_PASSWORD") or os.getenv("db_password")
db_host = os.getenv("DB_HOST") or os.getenv("db_host")
db_port = os.getenv("DB_PORT") or os.getenv("db_port")
db_name = os.getenv("DB_NAME") or os.getenv("db_name")
db_dialect = os.getenv("DB_DIALECT") or os.getenv("db_dialect") or "mysql+pymysql"
db = SQLDatabase.from_uri(f"{db_dialect}://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}")
toolkit = SQLDatabaseToolkit(db=db, llm=model)
tools = toolkit.get_tools()

get_schema_tool = next(tool for tool in tools if tool.name == "sql_db_schema")
get_schema_node = ToolNode([get_schema_tool], name="get_schema")
run_query_tool = next(tool for tool in tools if tool.name == "sql_db_query")
run_query_node = ToolNode([run_query_tool], name="sql_db_query")


def list_tables(state: RecommendState) -> dict[str, list[Any]]:
    tool_call = {
        "name": "sql_db_list_tables",
        "args": {},
        "id": "sql_db_list_tables_call",
        "type": "tool_call",
    }
    tool_call_message = AIMessage(content="", tool_calls=[tool_call])
    list_tables_tool = next(tool for tool in tools if tool.name == "sql_db_list_tables")
    tool_message = list_tables_tool.invoke(tool_call)
    response = AIMessage(content=f"可用的数据表有：{tool_message.content}")
    return {"messages": [tool_call_message, tool_message, response]}


def call_get_schema(state: RecommendState) -> dict[str, list[Any]]:
    llm_with_tools = model.bind_tools([get_schema_tool], tool_choice="any")
    result = llm_with_tools.invoke(state["messages"])
    return {"messages": [result]}


def generate_query(state: RecommendState) -> dict[str, list[Any]]:
    system_prompt = SystemMessage(
        content=(
            "你是一个与 SQL 数据库交互的租房助手。"
            "请根据用户需求生成语法正确的 SQL 查询。"
            "除非用户明确指定数量，否则最多返回 {top_k} 条结果。"
            "不要执行 INSERT、UPDATE、DELETE、DROP 等写操作。"
        ).format(top_k=state.get("room_count", 5))
    )
    llm_with_tools = model.bind_tools([run_query_tool])
    return {"messages": [llm_with_tools.invoke([system_prompt] + state["messages"])]}


def check_query(state: RecommendState) -> dict[str, list[Any]]:
    system_message = SystemMessage(
        content=(
            "你是一个仔细的 SQL 审核助手。"
            "请检查查询中的常见错误，例如 NOT IN 与 NULL、错误的 JOIN 条件、"
            "数据类型不匹配、BETWEEN 使用不当等。"
            "如果查询有问题就改写；如果没有问题，就原样保留并调用查询工具执行。"
        )
    )
    tool_call = state["messages"][-1].tool_calls[0]
    user_message = HumanMessage(content=tool_call["args"]["query"])
    llm_with_tools = model.bind_tools([run_query_tool], tool_choice="any")
    response = llm_with_tools.invoke([system_message, user_message])
    response.id = state["messages"][-1].id
    return {"messages": [response]}
