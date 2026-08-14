from pydantic import BaseModel


class HomeVisitResponse(BaseModel):
    visitor_count: int
