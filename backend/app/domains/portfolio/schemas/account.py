from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    currency: str = Field(
        default="USD",
        min_length=3,
        max_length=3,
        pattern=r"^[A-Za-z]{3}$",
    )


class AccountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    currency: str
    created_at: datetime
