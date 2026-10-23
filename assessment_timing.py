"""Time-per-mark estimates from IB Physics assessment formats, not difficulty."""
import math

VERSION = 'ib-physics-rates-v1'
SOURCE = 'https://www.ibo.org/globalassets/new-structure/recognition/pdfs/dp_sciences_physics_subject-brief_jan_2022_e.pdf'
# duration in minutes, total marks. 2025 Paper 1 timing covers A+B together:
# SL 25+20 marks, HL 40+20 marks. There is no mandated time split between A/B.
PROFILES = {
    ('2025','SL','Paper 1'):(90,45), ('2025','HL','Paper 1'):(120,60),
    ('2025','SL','Paper 2'):(90,50), ('2025','HL','Paper 2'):(150,90),
    ('Legacy','SL','Paper 1'):(45,30), ('Legacy','HL','Paper 1'):(60,40),
    ('Legacy','SL','Paper 2'):(75,50), ('Legacy','HL','Paper 2'):(135,95),
}


def estimate(marks, paper=None, level=None, syllabus='2025'):
    family = 'Paper 1' if paper in ('Paper 1','Paper 1A','Paper 1B') else paper
    profile = PROFILES.get((syllabus,level,family))
    if not marks or not profile:
        return dict(version=VERSION,method='fallback',minutes=5.0 if not marks else round(marks*1.8,1),
                    reason='Marks or a verified paper/level format are unavailable; review this estimate.')
    duration,total = profile
    return dict(version=VERSION,method='ib_mark_rate',minutes=round(marks*duration/total,1),
                minutes_per_mark=duration/total,paper_minutes=duration,paper_marks=total,
                source_level=level,syllabus=syllabus,paper=family,
                note='Paper 1A/1B share the combined Paper 1 average; this is not an official sectional allocation.' if family=='Paper 1' and syllabus=='2025' else 'Average paper pace; question difficulty may vary.')


def refresh(question):
    """Update automatic/old-default estimates, retaining explicit teacher times."""
    previous=question.get('timing') or {}
    old_default=round(question['marks']*1.8,1) if question.get('marks') else 5.0
    if question.get('marks') is None and question.get('paper') in ('Paper 1','Paper 1A'):
        question['marks']=1
    value=estimate(question.get('marks'),question.get('paper'),question.get('source_level',question.get('level')),question.get('syllabus','2025'))
    old=question.get('minutes',5.0)
    automatic=(previous.get('mode')=='automatic' or (not previous and math.isclose(old,old_default,abs_tol=.001)))
    # Approved part-time allocations and dependencies remain teacher-controlled.
    if (question.get('subquestions') or {}).get('status')=='approved':
        automatic=False
    if automatic:
        question['minutes']=value['minutes']
        mapping=question.get('subquestions')
        if mapping and old and question['minutes']!=old:
            for part in mapping.get('parts',[]):
                part['minutes']=part['minutes']*question['minutes']/old
            from subquestions import question_hash
            mapping['source_hash']=question_hash(question)
    question['timing']=dict(value,mode='automatic' if automatic else 'manual')
    return question
