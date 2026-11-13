from datetime import datetime
from typing import Any

from fastapi import APIRouter, Response
from pydantic import BaseModel
from sqlalchemy import delete

from app.dependencies import CurrentUser, DbSession
from app.models import UserMemory

router = APIRouter(prefix="/memory", tags=["memory"])


class MemoryOut(BaseModel):
    profile: dict[str, Any]
    updated_at: datetime | None


@router.get("", response_model=MemoryOut)
async def get_memory(user: CurrentUser, db: DbSession) -> MemoryOut:
    """The caller's long-term profile ({} until they finish an interview as a registered user)."""
    mem = await db.get(UserMemory, user.id)
    return MemoryOut(profile=dict(mem.profile), updated_at=mem.updated_at) if mem else MemoryOut(profile={}, updated_at=None)


@router.delete("", status_code=204)
async def delete_memory(user: CurrentUser, db: DbSession) -> Response:
    await db.execute(delete(UserMemory).where(UserMemory.user_id == user.id))
    await db.commit()
    return Response(status_code=204)
