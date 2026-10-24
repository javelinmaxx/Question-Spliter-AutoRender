"""Explicit subject registration and validation. No dynamic code in API input."""
import re
from .ports import AnalysisPort, AssessmentPort, CurriculumPort, RenderingPort


def validate_adapter(subject):
    if not re.fullmatch(r'[a-z][a-z0-9]*(?:-[a-z0-9]+)*',subject.id) or not subject.name or not subject.version:
        raise ValueError('Subject adapters need a stable slug, name and version.')
    for port, contract in [(subject.analysis,AnalysisPort),(subject.assessment,AssessmentPort),
                           (subject.curriculum,CurriculumPort),(subject.rendering,RenderingPort)]:
        if not isinstance(port,contract):
            raise ValueError(f'{subject.id}: incomplete {contract.__name__}.')
    catalog=subject.catalog()
    if catalog.get('schema_version')!=1 or catalog.get('id')!=subject.id:
        raise ValueError('Catalog schema_version/id does not match its adapter.')
    topics=catalog.get('topics')
    if not isinstance(topics,dict) or not topics or any(not isinstance(k,str) or not k or not isinstance(v,str) or not v for k,v in topics.items()):
        raise ValueError('Provide a non-empty topic code/title catalog.')
    for field in ('levels','syllabuses','paper_types'):
        values=catalog.get(field)
        if not isinstance(values,list) or not values or any(not isinstance(v,str) or not v for v in values) or len(values)!=len(set(values)):
            raise ValueError(f'Provide unique {field} values.')
    if not set(catalog.get('hl_only_topics',[])).issubset(topics):
        raise ValueError('HL-only topics must belong to the subject catalog.')
    graph=subject.curriculum.prerequisites()
    if not isinstance(graph,dict) or set(graph)!=set(topics):
        raise ValueError('Provide a prerequisite list for every topic.')
    visited,path=set(),set()
    def visit(code):
        if code in path:raise ValueError('Circular subject prerequisites.')
        if code in visited:return
        edges=graph[code]
        if not isinstance(edges,list) or any(not isinstance(e,str) or e not in topics for e in edges) or len(edges)!=len(set(edges)):
            raise ValueError('Prerequisites must be unique catalog topic codes.')
        path.add(code)
        for earlier in edges:visit(earlier)
        path.remove(code);visited.add(code)
    for code in topics:visit(code)
    return catalog


class SubjectRegistry:
    def __init__(self):self._subjects={}

    def register(self, subject):
        validate_adapter(subject)
        if subject.id in self._subjects:raise ValueError('Subject is already registered: '+subject.id)
        self._subjects[subject.id]=subject
        return subject

    def get(self, subject_id):
        if subject_id not in self._subjects:raise ValueError('Unknown subject: '+str(subject_id))
        return self._subjects[subject_id]

    def list(self):return list(self._subjects.values())


registry=SubjectRegistry()
from .physics import adapter
registry.register(adapter())
# Additional reviewed adapters are registered explicitly here, not from HTTP input.
