from typing import Annotated

from langgraph.graph import MessagesState


def merge_value(old, new):
    return new if new is not None else old


class ReserveState(MessagesState):
    title: Annotated[str, merge_value]
    phone: Annotated[str, merge_value]
    id_card: Annotated[str, merge_value]
    reserve_missing_field: Annotated[str, merge_value]
    reserve_missing_question: Annotated[str, merge_value]
