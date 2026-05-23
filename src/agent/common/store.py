from typing import Optional

from pydantic import BaseModel, Field


class ReservedInfo(BaseModel):
    """预约信息。"""

    order_id: str = Field(description="预约工单 ID")
    title: str = Field(description="预约的房源标题")
    phone_number: str = Field(description="预约联系电话")
    price: Optional[float] = Field(
        default=None,
        description="预约房源的价格，单位为元/月",
    )
    intro: Optional[str] = Field(
        default=None,
        description="预约房源的简介",
    )
    city_name: Optional[str] = Field(
        default=None,
        description="预约房源所在城市",
    )
    region_name: Optional[str] = Field(
        default=None,
        description="预约房源所在区域",
    )


class UserPreferences(BaseModel):
    """用户偏好数据。"""

    budget_min: Optional[float] = Field(
        default=None,
        description="用户最低预算，单位为元/月",
    )
    budget_max: Optional[float] = Field(
        default=None,
        description="用户最高预算，单位为元/月",
    )
    reserved_info: Optional[list[ReservedInfo]] = Field(
        default=None,
        description="用户已经预约过的房源列表",
    )
