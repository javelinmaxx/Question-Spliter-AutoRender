"""Separate source-paper level from suitability for SL students."""
import json
from pathlib import Path
import re

POLICY=json.loads((Path(__file__).parent/'curriculum_prerequisites.json').read_text())
HL_ONLY=set(POLICY['level_scope']['HL_only'])
MIXED=set(POLICY['level_scope']['SL_and_additional_HL'])
MODES={'SL','HL','SL_from_HL','Any'}
LABELS={'SL':'SL only','HL':'HL only','SL_from_HL':'SL from HL paper','Any':'Any'}


def normalize_mode(mode):
    mode=mode or 'Any'
    if mode not in MODES:
        raise ValueError('Choose SL only, HL only, SL from HL paper, or Any.')
    return mode


def sl_mode(mode):
    return mode in ('SL','SL_from_HL')


def suitability(question):
    topics=set(question.get('topics',[]))|set(question.get('level_conflicts',[]))
    for part in (question.get('subquestions') or {}).get('parts',[]):
        topics.update(part.get('topics',[]))
    blocked=sorted(topics & HL_ONLY)
    # Catch explicit additional-HL knowledge even if its topic tag was missed.
    text=question.get('text','')
    patterns=[r'\b(?:time dilation|length contraction|Lorentz|special relativity|moment of inertia|angular momentum|Carnot|entropy|Faraday|Lenz|photoelectric|de Broglie|Compton)\b',
              r'\b(?:gravitational potential|escape (?:speed|velocity)|relativistic Doppler|Rayleigh criterion|thin.film interference)\b']
    evidence=[m.group(0) for pattern in patterns for m in re.finditer(pattern,text,re.I)]
    decision=question.get('sl_suitability','automatic')
    if blocked or evidence or decision=='hl_only':
        return dict(status='hl_only',topics=blocked,evidence=evidence,reason='HL-only topic or concept detected, or marked HL-only by a teacher.')
    if decision=='needs_review':
        return dict(status='needs_review',reason='Teacher requested a suitability review.')
    source=question.get('source_level',question.get('level'))
    if decision=='sl_suitable' or question.get('level')=='Both' or source=='SL' or (question.get('level')=='SL' and question.get('review_status')=='reviewed'):
        return dict(status='sl_suitable',reason='SL source paper or teacher-confirmed SL content.')
    if not topics or topics & MIXED:
        return dict(status='needs_review',reason='HL question has unknown topics or a topic with additional HL material. Confirm SL suitability after reviewing the question.')
    if source=='HL':
        return dict(status='sl_suitable',reason='Tagged common SL content; no HL-only topic/concept detected.')
    return dict(status='needs_review',reason='Source level is unknown.')


def exclusion(question,mode):
    source=question.get('source_level',question.get('level'))
    if mode=='HL' and source not in ('HL','Both'):
        return 'level'
    if mode=='SL_from_HL' and source!='HL':
        return 'level'
    # SL means suitable content, including compatible questions from HL papers.
    if sl_mode(mode):
        result=suitability(question)
        if result['status']!='sl_suitable':
            return 'sl_content' if result['status']=='hl_only' else 'sl_review'
    return None
