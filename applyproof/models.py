from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

class Source(StrictModel):
    label: str = Field(min_length=1, max_length=200)
    locator: str = Field(min_length=1, max_length=500)
    excerpt: str = Field(min_length=1, max_length=2000)
    verified: bool = False

class Fact(StrictModel):
    id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,40}$')
    text: str = Field(min_length=1, max_length=1000)
    skills: list[str] = Field(default_factory=list, max_length=30)
    level: Literal['exposure', 'hands-on', 'credential'] = 'exposure'
    source: Source

class Profile(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    facts: list[Fact] = Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def unique_ids(self):
        ids = [fact.id for fact in self.facts]
        if len(ids) != len(set(ids)):
            raise ValueError('Fact IDs must be unique.')
        return self

class Requirement(StrictModel):
    id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,40}$')
    label: str = Field(min_length=1, max_length=200)
    skill: str = Field(min_length=1, max_length=100)
    minimum_level: Literal['exposure', 'hands-on', 'credential'] = 'hands-on'
    mandatory: bool = True

class Location(StrictModel):
    city: str = Field(min_length=1, max_length=200)
    scope: Literal['office', 'role']
    source: Source

class Job(StrictModel):
    company: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=200)
    source: Source
    requirements: list[Requirement] = Field(min_length=1, max_length=50)
    locations: list[Location] = Field(default_factory=list, max_length=20)
    preferred_city: str = Field(default='', max_length=200)

    @model_validator(mode='after')
    def unique_ids(self):
        ids = [r.id for r in self.requirements]
        if len(ids) != len(set(ids)):
            raise ValueError('Requirement IDs must be unique.')
        return self

class Case(StrictModel):
    profile: Profile
    job: Job

class Draft(Case):
    selected_ids: list[str] = Field(default_factory=list, max_length=100)

class Audit(Draft):
    bullets: list[str] = Field(default_factory=list, max_length=100)
