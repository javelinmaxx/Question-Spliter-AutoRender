"""Subject-neutral analysis entry point for adapter development and validation."""
from math import isfinite
from .registry import validate_adapter


def analyze(subject, path, filename, **options):
    catalog=validate_adapter(subject)
    result=subject.analysis.extract(path,filename,**options)
    if not isinstance(result,dict) or not isinstance(result.get('questions'),list) or not isinstance(result.get('metadata'),dict):
        raise ValueError('Analysis must return metadata and a questions list.')
    if result.get('subject_id',subject.id)!=subject.id:
        raise ValueError('Analysis returned another subject identity.')
    seen=set()
    for question in result['questions']:
        number=question.get('number')
        if isinstance(number,bool) or not isinstance(number,int) or number<1 or number in seen:
            raise ValueError('Each parent question needs a unique positive number.')
        seen.add(number)
        if question.get('subject_id',subject.id)!=subject.id:
            raise ValueError('A question returned another subject identity.')
        topics=question.get('topics')
        if not isinstance(topics,list) or any(not isinstance(t,str) or t not in catalog['topics'] for t in topics):
            raise ValueError('Question topics do not belong to this subject.')
        if question.get('paper') not in [*catalog['paper_types'],'Unknown'] or question.get('level') not in [*catalog['levels'],'Unknown']:
            raise ValueError('Question format/level does not belong to this subject.')
        minutes=question.get('minutes')
        if isinstance(minutes,bool) or not isinstance(minutes,(int,float)) or not isfinite(minutes) or minutes<=0:
            raise ValueError('Question time estimates must be positive finite minutes.')
        if not isinstance(question.get('regions'),list) or not question['regions']:
            raise ValueError('Question regions are required.')
        question['subject_id']=subject.id
    result['subject_id']=subject.id
    return result
