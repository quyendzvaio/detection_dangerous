from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ZoneCreate(BaseModel):
    camera_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=100)
    polygon_json: list[list[float]]
    is_active: bool = True

    @field_validator("polygon_json")
    @classmethod
    def validate_polygon(cls, polygon: list[list[float]]) -> list[list[float]]:
        if len(polygon) < 3:
            raise ValueError("polygon requires at least three points")
        for point in polygon:
            if len(point) != 2 or any(value < 0.0 or value > 1.0 for value in point):
                raise ValueError("polygon points must be normalized [x, y] in [0, 1]")
        return polygon


class ZoneUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    polygon_json: list[list[float]] | None = None
    is_active: bool | None = None

    @field_validator("polygon_json")
    @classmethod
    def validate_polygon(cls, polygon: list[list[float]] | None):
        if polygon is None:
            return None
        return ZoneCreate.validate_polygon(polygon)


class ZoneOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    camera_id: int
    name: str
    polygon_json: list[list[float]]
    is_active: bool
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
