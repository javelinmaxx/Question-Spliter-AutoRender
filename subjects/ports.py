"""Version-one extension contracts for future subject adapters."""
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@runtime_checkable
class AnalysisPort(Protocol):
    def extract(self, path, filename, ocr_mode='auto', ocr_cache=None, page_records=None): ...
    def suggest(self, text, paper=None, level=None, syllabus='2025'): ...
    def custom_tags(self, text, topics): ...


@runtime_checkable
class CurriculumPort(Protocol):
    def prerequisites(self): ...
    def context(self, codes): ...
    def model_prompts(self): ...


@runtime_checkable
class AssessmentPort(Protocol):
    def estimate(self, marks, paper=None, level=None, syllabus='2025'): ...
    def level_exclusion(self, question, mode): ...
    def paper_matches(self, actual, requested): ...


@runtime_checkable
class RenderingPort(Protocol):
    def render_question(self, pdf, regions, **kwargs): ...
    def add_cover(self, pdf, **kwargs): ...
    def clean_source(self, source, question, cache, **kwargs): ...


@dataclass(frozen=True)
class SubjectAdapter:
    id: str
    name: str
    version: str
    analysis: AnalysisPort
    curriculum: CurriculumPort
    assessment: AssessmentPort
    rendering: RenderingPort
    # Callable returning a JSON-compatible catalog; no HTTP-loaded code/plugins.
    catalog: object
