from typing import Annotated

from langgraph.graph import MessagesState


def merge_value(old, new):
    return new if new is not None else old


class RecommendState(MessagesState):
    user_preferences: dict
    city: Annotated[str, merge_value]
    budget_min: Annotated[float, merge_value]
    budget_max: Annotated[float, merge_value]
    district: Annotated[str, merge_value]
    room_type: Annotated[str, merge_value]
    orientation: Annotated[str, merge_value]
    room_count: Annotated[int, merge_value]
    others: Annotated[str, merge_value]


def _format_budget(state: dict) -> str:
    budget_min = state.get("budget_min")
    budget_max = state.get("budget_max")
    if budget_min is not None and budget_max is not None:
        return f"{budget_min} - {budget_max} 元/月"
    if budget_min is not None:
        return f"{budget_min} 元/月以上"
    if budget_max is not None:
        return f"{budget_max} 元/月以下"
    return "未指定"


def get_recommend_info(state: dict) -> str:
    info_prompt = """
提取用户期望推荐的房源信息如下：
- 城市: {city}
- 区域: {district}
- 预算: {budget_text}
- 房屋类型: {room_type}
- 朝向: {orientation}
- 特殊要求: {others}
- 推荐数量: {room_count}
如果某些信息未指定，请使用合适的默认值或适当放宽条件。
"""
    return info_prompt.format(
        city=state.get("city", "未指定"),
        district=state.get("district", "未指定"),
        budget_text=_format_budget(state),
        room_type=state.get("room_type", "未指定"),
        orientation=state.get("orientation", "未指定"),
        others=state.get("others", "无"),
        room_count=state.get("room_count", 5),
    )
