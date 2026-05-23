from typing import Annotated, TypedDict

from langgraph.graph import MessagesState


def merge_value(old, new):
    return new if new is not None else old


class State(MessagesState):
    user_preferences: dict
    user_intent: str
    city: Annotated[str, merge_value]
    budget_min: Annotated[float, merge_value]
    budget_max: Annotated[float, merge_value]
    district: Annotated[str, merge_value]
    room_type: Annotated[str, merge_value]
    orientation: Annotated[str, merge_value]
    room_count: Annotated[int, merge_value]
    others: Annotated[str, merge_value]


class NeedReserveOutput(TypedDict):
    reserve: str
