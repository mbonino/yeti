import datetime
from typing import ClassVar

from pydantic import BaseModel, Field

from core import database_arango
from core.helpers import now

# Database model
class Relationship(BaseModel, database_arango.ArangoYetiConnector):
    _collection_name: ClassVar[str] = "links"
    _type_filter: ClassVar[str | None] = None

    id: str | None = None
    source: str
    target: str
    type: str
    description: str
    created: datetime.datetime
    modified: datetime.datetime

    @classmethod
    def load(cls, object: dict):
        return cls(**object)


class TagRelationship(BaseModel, database_arango.ArangoYetiConnector):
    _type_filter: None = None

    id: str | None = None
    source: str
    target: str
    first_seen: datetime.datetime = Field(default_factory=now)
    last_seen: datetime.datetime
    fresh: bool

    @classmethod
    def load(cls, object: dict):
        return cls(**object)

RelationshipTypes = Relationship | TagRelationship
