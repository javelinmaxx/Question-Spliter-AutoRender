from dataclasses import replace
from copy import deepcopy
import pytest

from app import create_app
from subjects import registry, SubjectAdapter, SubjectRegistry
from subjects.physics import PhysicsPorts
from subjects.pipeline import analyze


class FixturePorts(PhysicsPorts):
    def catalog(self):
        return dict(schema_version=1,id='fixture-subject',name='Fixture subject',topics={'X.1':'Fixture topic'},
                    levels=['HL','SL','Both'],syllabuses=['Fixture'],paper_types=['Fixture paper'],hl_only_topics=[])
    def prerequisites(self):return {'X.1':[]}
    def extract(self,*args,**kwargs):
        return dict(metadata=dict(paper='Fixture paper'),questions=[dict(number=1,topics=['X.1'],paper='Fixture paper',
            level='HL',minutes=2,regions=[dict(page=0,rect=[0,0,100,100])])])


def fixture_adapter():
    ports=FixturePorts()
    return SubjectAdapter('fixture-subject','Fixture subject','1',ports,ports,ports,ports,ports.catalog)


def test_subject_discovery_and_existing_physics_catalog_are_versioned(tmp_path):
    client=create_app(tmp_path).test_client()
    response=client.get('/api/subjects').json
    assert response['schema_version']==1 and response['active_subject']=='ibdp-physics'
    assert response['subjects'][0]['bank_enabled']
    assert client.get('/api/subjects/ibdp-physics/catalog').json['topics']['A.1']=='Kinematics'
    assert client.get('/api/subjects/missing/catalog').status_code==404
    assert client.get('/api/catalog').json['subject']['id']=='ibdp-physics'


def test_an_independent_subject_can_register_and_analyze_without_physics_topics():
    local=SubjectRegistry();subject=local.register(fixture_adapter())
    result=analyze(local.get('fixture-subject'),None,'fixture.pdf')
    assert result['subject_id']=='fixture-subject'
    assert result['questions'][0]['topics']==['X.1']
    assert result['questions'][0]['subject_id']=='fixture-subject'
    with pytest.raises(ValueError,match='already registered'):local.register(subject)
    assert 'fixture-subject' not in [s.id for s in registry.list()]


def test_invalid_adapter_catalog_and_cross_subject_outputs_are_rejected():
    subject=fixture_adapter();bad=deepcopy(subject.catalog());bad['hl_only_topics']=['A.1']
    with pytest.raises(ValueError,match='HL-only'):SubjectRegistry().register(replace(subject,catalog=lambda:bad))
    ports=FixturePorts()
    ports.prerequisites=lambda:{'X.1':['X.1']}
    with pytest.raises(ValueError,match='Circular'):SubjectRegistry().register(replace(subject,curriculum=ports))
    ports=FixturePorts();original=ports.extract
    ports.extract=lambda *a,**kw:dict(original(),subject_id='another-subject')
    with pytest.raises(ValueError,match='identity'):analyze(replace(subject,analysis=ports),None,'fixture.pdf')


def test_foreign_question_cannot_be_saved_in_physics_bank(tmp_path):
    from test_workflow import upload
    client=create_app(tmp_path).test_client();doc=upload(client)
    q=dict(doc['questions'][0],document_id=doc['id'],subject_id='fixture-subject')
    response=client.post('/api/questions',json=q)
    assert response.status_code==400 and 'subject' in response.json['error']
    assert client.get('/api/questions').json==[]
    assert client.get('/api/questions?subject_id=fixture-subject').status_code==400


def test_shared_extractor_accepts_non_physics_rules(tmp_path):
    from pdf_extraction import extract_pdf
    import fitz
    path=tmp_path/'fixture.pdf'
    with fitz.open() as pdf:
        for number in (1,2):
            page=pdf.new_page();page.insert_text((50,45),'Fixture subject examination 2025')
            page.insert_text((50,100),f'{number}. Give a response for this fixture topic. [1]')
        pdf.save(path)
    def metadata(*args):return dict(year=2025,level='HL',syllabus='Fixture',paper='Fixture paper')
    def suggest(*args):return dict(topics=['X.1'],commands=[],tags=['fixture'],marks=1,minutes=2,difficulty='Unrated')
    result=extract_pdf(path,path.name,metadata_fn=metadata,suggest_fn=suggest,ocr_mode='off')
    assert len(result['questions'])==2
    assert all(q['topics']==['X.1'] and q['paper']=='Fixture paper' for q in result['questions'])
