from __future__ import annotations

from typing import Annotated, Literal, NotRequired, Self, TypedDict

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

SkillLevel = Literal["exposure", "hands-on", "credential"]
LocationScope = Literal["office", "role"]
LocationStatus = Literal["conflicting", "unverified", "verified", "matches", "differs"]
RequirementStatus = Literal[
    "job_unverified",
    "supported",
    "partial",
    "evidence_unverified",
    "gap",
]
ReviewStatus = Literal["needs_review", "ready_for_human_review"]
AuditStatus = Literal["traceable", "needs_evidence"]
PdfTextStatus = Literal["text_layer_found", "needs_text_layer_review"]

Identifier = Annotated[str, Field(pattern=r"^[a-zA-Z0-9_-]{1,40}$")]
SkillTag = Annotated[str, Field(min_length=1, max_length=100)]


class LocationAssessment(TypedDict):
    status: LocationStatus
    office_cities: list[str]
    role_cities: list[str]
    question: str


class RequirementRow(TypedDict):
    id: str
    label: str
    skill: str
    mandatory: bool
    status: RequirementStatus
    fact_ids: list[str]


class AssessmentResult(TypedDict):
    requirements: list[RequirementRow]
    location: LocationAssessment
    unresolved_requirements: list[str]
    evidence_digest: str
    review_status: ReviewStatus


class DraftBullet(TypedDict):
    fact_id: str
    text: str
    source: dict[str, str | bool]


class DraftResult(TypedDict):
    name: str
    company: str
    role: str
    bullets: list[DraftBullet]
    assessment: AssessmentResult
    draft_mode: str
    human_review_required: bool
    markdown: NotRequired[str]
    selection_provider: NotRequired[str]


class AuditRow(TypedDict):
    text: str
    status: AuditStatus
    fact_id: str | None


class PdfInspectionResult(TypedDict):
    pages: int
    characters_by_page: list[int]
    status: PdfTextStatus
    stored: bool
    note: str


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Source(StrictModel):
    label: str = Field(min_length=1, max_length=200)
    locator: str = Field(min_length=1, max_length=500)
    excerpt: str = Field(min_length=1, max_length=2000)
    verified: StrictBool = False


class Fact(StrictModel):
    id: Identifier
    text: str = Field(min_length=1, max_length=1000)
    skills: list[SkillTag] = Field(default_factory=list, max_length=30)
    level: SkillLevel = "exposure"
    source: Source


class Profile(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    facts: list[Fact] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_ids(self) -> Self:
        ids = [fact.id for fact in self.facts]
        if len(ids) != len(set(ids)):
            raise ValueError("Fact IDs must be unique.")
        return self


class Requirement(StrictModel):
    id: Identifier
    label: str = Field(min_length=1, max_length=200)
    skill: str = Field(min_length=1, max_length=100)
    minimum_level: SkillLevel = "hands-on"
    mandatory: StrictBool = True


class Location(StrictModel):
    city: str = Field(min_length=1, max_length=200)
    scope: LocationScope
    source: Source


class Job(StrictModel):
    company: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=200)
    source: Source
    requirements: list[Requirement] = Field(min_length=1, max_length=50)
    locations: list[Location] = Field(default_factory=list, max_length=20)
    preferred_city: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def unique_ids(self) -> Self:
        ids = [r.id for r in self.requirements]
        if len(ids) != len(set(ids)):
            raise ValueError("Requirement IDs must be unique.")
        return self


class Case(StrictModel):
    profile: Profile
    job: Job


class Draft(Case):
    selected_ids: list[str] = Field(default_factory=list, max_length=100)


class Audit(Draft):
    bullets: list[str] = Field(default_factory=list, max_length=100)
