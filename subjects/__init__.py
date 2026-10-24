"""Subject extension API. The interactive bank currently enables IB DP Physics."""
from .ports import SubjectAdapter, AnalysisPort, AssessmentPort, CurriculumPort, RenderingPort
from .registry import registry, SubjectRegistry, validate_adapter

API_VERSION=1
ACTIVE_SUBJECT_ID='ibdp-physics'
