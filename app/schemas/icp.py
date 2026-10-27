from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.services.icp_config import ICPConfig


class ICPOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    version: int
    is_active: bool
    config: ICPConfig
    created_at: datetime


class ICPUpdate(BaseModel):
    config: ICPConfig
    name: str | None = None


class RecalculateResult(BaseModel):
    icp_version: int
    recalculated: int
