from pydantic import BaseModel, ConfigDict, Field


class Provenance(BaseModel):
    """
    Source-reference model representing the exact numeric location of parsed data in the source document.
    All location identifiers are strictly numeric.
    """

    model_config = ConfigDict(frozen=True)

    page: int | None = None  # 1-based page number if known
    element: int | None = None  # 1-based element index
    order: int  # 1-based sequential document reading order


class DateInfo(BaseModel):
    """
    Standardized date representation.
    Always preserves the original date text exactly.
    Normalizes unambiguous dates to standard format (e.g. MM/YYYY or MM/YYYY – MM/YYYY).
    """

    model_config = ConfigDict(frozen=True)

    original: str  # Mandatory original date string from document
    normalized: str | None = (
        None  # Normalized standard representation (e.g. "01/2024 – 03/2025")
    )
    start_date: str | None = None  # Normalized start (e.g. "01/2024" or "2024")
    end_date: str | None = (
        None  # Normalized end (e.g. "03/2025" or "Present" or "2025")
    )
    is_present: bool = False  # True if ongoing / current / present


class LinkItem(BaseModel):
    """Represents a hyperlink or profile URL found in the resume."""

    model_config = ConfigDict(frozen=True)

    url: str
    label: str | None = (
        None  # e.g. "linkedin", "github", "portfolio", "project", "custom"
    )
    provenance: Provenance | None = None


class CandidateIdentity(BaseModel):
    """Explicitly stated contact and identity information of the candidate."""

    name: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    links: list[LinkItem] = Field(default_factory=list)
    provenance: Provenance | None = None


class SummarySection(BaseModel):
    """Candidate summary, objective, or profile statement."""

    text: str
    original_title: str | None = None
    provenance: Provenance | None = None


class ExperienceItem(BaseModel):
    """Represents a work experience, internship, or professional employment entry."""

    organization: str | None = None
    role: str | None = None
    location: str | None = None
    dates: DateInfo | None = None
    description: list[str] = Field(default_factory=list)
    provenance: Provenance | None = None


class EducationItem(BaseModel):
    """Represents an academic credential or educational history entry."""

    institution: str | None = None
    degree: str | None = None
    field_of_study: str | None = None
    location: str | None = None
    dates: DateInfo | None = None
    description: list[str] = Field(default_factory=list)
    provenance: Provenance | None = None


class ProjectItem(BaseModel):
    """Represents a project entry with explicitly associated details."""

    name: str | None = None
    description: list[str] = Field(default_factory=list)
    dates: DateInfo | None = None
    technologies: list[str] = Field(default_factory=list)
    links: list[LinkItem] = Field(default_factory=list)
    provenance: Provenance | None = None


class SkillCategory(BaseModel):
    """Represents a group or category of explicitly stated candidate skills."""

    category: str | None = (
        None  # e.g. "Languages", "Frameworks", "Tools", or None for general
    )
    skills: list[str] = Field(default_factory=list)
    provenance: Provenance | None = None


class CertificationItem(BaseModel):
    """Represents an explicitly identifiable professional certification or license."""

    name: str
    issuer: str | None = None
    dates: DateInfo | None = None
    credential_id: str | None = None
    links: list[LinkItem] = Field(default_factory=list)
    provenance: Provenance | None = None


class AwardItem(BaseModel):
    """Represents an award, achievement, scholarship, or honor."""

    title: str
    issuer: str | None = None
    dates: DateInfo | None = None
    description: str | None = None
    provenance: Provenance | None = None


class PublicationItem(BaseModel):
    """Represents a scholarly publication, paper, patent, or article."""

    title: str
    authors: list[str] = Field(default_factory=list)
    venue: str | None = None
    dates: DateInfo | None = None
    links: list[LinkItem] = Field(default_factory=list)
    description: str | None = None
    provenance: Provenance | None = None


class LanguageItem(BaseModel):
    """Represents a language and explicitly stated proficiency."""

    language: str
    proficiency: str | None = None  # e.g. "Native", "Fluent", "Conversational"
    provenance: Provenance | None = None


class VolunteeringItem(BaseModel):
    """Represents a volunteer or community service experience."""

    organization: str | None = None
    role: str | None = None
    dates: DateInfo | None = None
    description: list[str] = Field(default_factory=list)
    provenance: Provenance | None = None


class OrganizationItem(BaseModel):
    """Represents membership, leadership, or club affiliation."""

    organization: str | None = None
    role: str | None = None
    dates: DateInfo | None = None
    description: list[str] = Field(default_factory=list)
    provenance: Provenance | None = None


class AdditionalSection(BaseModel):
    """Preserves unclassified, custom, or ambiguous sections with original title and content."""

    original_title: str
    content: list[str] = Field(default_factory=list)
    provenance: Provenance | None = None


class CanonicalResume(BaseModel):
    """
    Canonical semantic representation of a parsed resume.
    Standardizes meaning while preserving evidence, original titles, dates, and numeric provenance.
    """

    identity: CandidateIdentity = Field(default_factory=CandidateIdentity)
    summary: SummarySection | None = None
    experience: list[ExperienceItem] = Field(default_factory=list)
    education: list[EducationItem] = Field(default_factory=list)
    projects: list[ProjectItem] = Field(default_factory=list)
    skills: list[SkillCategory] = Field(default_factory=list)
    certifications: list[CertificationItem] = Field(default_factory=list)
    awards: list[AwardItem] = Field(default_factory=list)
    publications: list[PublicationItem] = Field(default_factory=list)
    languages: list[LanguageItem] = Field(default_factory=list)
    volunteering: list[VolunteeringItem] = Field(default_factory=list)
    organizations: list[OrganizationItem] = Field(default_factory=list)
    links: list[LinkItem] = Field(default_factory=list)
    additional_sections: list[AdditionalSection] = Field(default_factory=list)
