from pydantic import BaseModel, ConfigDict, Field


class TelegramUser(BaseModel):
    id: int
    first_name: str
    last_name: str | None = None
    username: str | None = None


class TelegramChat(BaseModel):
    id: int
    type: str


class TelegramMessage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    message_id: int
    from_: TelegramUser | None = Field(None, alias="from")
    chat: TelegramChat
    text: str | None = None
    date: int


class TelegramUpdate(BaseModel):
    update_id: int
    message: TelegramMessage | None = None
