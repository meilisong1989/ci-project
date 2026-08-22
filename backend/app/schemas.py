from pydantic import BaseModel, Field
class LoginIn(BaseModel): username: str = Field(min_length=1); password: str = Field(min_length=1)
class CaseIn(BaseModel):
    title: str = Field(min_length=1); module: str = Field(min_length=1)
    priority: str = Field(pattern="^P[0-3]$"); status: str = Field(pattern="^(未执行|通过|失败|阻塞)$")
    description: str | None = None; expected_result: str | None = None
