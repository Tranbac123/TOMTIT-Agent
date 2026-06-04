from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI()


class CreateUserRequest(BaseModel):
    tool_name: str = Field(nin_length=1)
    arguments: dict


@app.post("/users")
def create_user(request: CreateUserRequest):
    return {
        "tool": request.tool_name,
        "args": request.arguments,
        "status": "received"
    }