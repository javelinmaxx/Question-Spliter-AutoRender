"""The existing Physics implementation exposed through subject extension ports."""
from copy import deepcopy
from pathlib import Path

from .ports import SubjectAdapter


class PhysicsPorts:
    def catalog(self):
        from physics import TOPICS, HL_ONLY_TOPICS
        from paper_types import PAPERS
        return dict(schema_version=1, id='ibdp-physics', name='IB DP Physics',
                    qualification='IB Diploma Programme', topics=dict(TOPICS),
                    levels=['HL','SL','Both'], syllabuses=['2025','Legacy'],
                    paper_types=list(PAPERS), hl_only_topics=sorted(HL_ONLY_TOPICS))

    def extract(self, path, filename, ocr_mode='auto', ocr_cache=None, page_records=None):
        from physics import extract
        result=extract(path,filename,ocr_mode=ocr_mode,ocr_cache=ocr_cache,page_records=page_records)
        result['subject_id']='ibdp-physics'
        for question in result['questions']:
            question['subject_id']='ibdp-physics'
        return result

    def suggest(self, *args, **kwargs):
        from physics import suggest
        return suggest(*args, **kwargs)

    def custom_tags(self, *args, **kwargs):
        from physics import custom_tags
        return custom_tags(*args, **kwargs)

    def prerequisites(self):
        from prerequisite_policy import DEFAULT_POLICY
        return deepcopy(DEFAULT_POLICY['requires'])

    def context(self, codes):
        from curriculum_context import curriculum_context
        return curriculum_context(codes)

    def model_prompts(self):
        root=Path(__file__).resolve().parents[1]/'prompts'
        from curriculum_context import OCR_PROMPT_VERSION, DEPENDENCY_PROMPT_VERSION
        return dict(ocr=dict(version=OCR_PROMPT_VERSION,system=(root/'physics_ocr.md').read_text()),
                    dependencies=dict(version=DEPENDENCY_PROMPT_VERSION,system=(root/'physics_dependencies.md').read_text()))

    def estimate(self, *args, **kwargs):
        from assessment_timing import estimate
        return estimate(*args, **kwargs)

    def level_exclusion(self, *args, **kwargs):
        from level_filter import exclusion
        return exclusion(*args, **kwargs)

    def paper_matches(self, *args, **kwargs):
        from paper_types import matches_paper
        return matches_paper(*args, **kwargs)

    def render_question(self, *args, **kwargs):
        from physics import render_question
        return render_question(*args, **kwargs)

    def add_cover(self, *args, **kwargs):
        from paper_cover import add_practice_cover
        return add_practice_cover(*args, **kwargs)

    def clean_source(self, *args, **kwargs):
        from paper_numbering import erase_source_numbers
        return erase_source_numbers(*args, **kwargs)


def adapter():
    ports=PhysicsPorts()
    return SubjectAdapter('ibdp-physics','IB DP Physics','1',ports,ports,ports,ports,ports.catalog)
