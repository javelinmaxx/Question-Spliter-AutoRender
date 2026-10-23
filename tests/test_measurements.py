from io import BytesIO

import fitz
import pytest

from app import create_app
from physics import TOPICS, suggest
from topic_scope import scoped_question, topic_closure


@pytest.mark.parametrize('text', [
    'Calculate the percentage uncertainty in the length measurement.',
    'Discuss the accuracy and precision of the measurements.',
    'Identify one systematic error and one random error.',
    'Write the answer to three significant figures.',
    'Draw the line of best fit and error bars.',
    'State the SI unit of force.',
    'A length is (12.0 ± 0.2) cm. Calculate its fractional error.',
    'Convert this measurement from centimetres to metres.',
    'A student measures the diameter using a micrometer.',
    'Determine the resolution of the voltmeter.',
    'Measure the period of the pendulum.'
])
def test_measurement_and_uncertainty_skills_receive_a0(text):
    result=suggest(text,'Paper 2','SL')
    assert 'A.0' in result['topics'] and result['topic_evidence']['A.0']
    assert 'measurements and uncertainties' in result['tags']
    assert 'experimental skills' in result['tags']
    assert 'A.0' not in result['level_conflicts']


@pytest.mark.parametrize('text', [
    'A car travels 25 m in 5 s. Calculate its velocity.',
    'A mass of 5 kg is released from a height of 20 m.',
    'The measured speed is 5 m/s. Calculate the kinetic energy.',
    'Calculate the momentum of a proton moving at 500 m/s.'
])
def test_numbers_or_incidental_measured_values_do_not_imply_a0(text):
    assert 'A.0' not in suggest(text,'Paper 2')['topics']


def test_measurements_remain_a_foundation_without_implying_later_physics():
    assert topic_closure(['A.0']) == {'A.0'}
    assert 'A.0' in topic_closure(['A.1'])
    q=dict(id='q',minutes=5,paper='Paper 2',topics=['A.0','A.1'],regions=[],text='Motion with uncertainties')
    assert scoped_question(q,['A.1']) is not None
    assert scoped_question(q,['A.0']) is None


@pytest.mark.parametrize('level',['SL','HL'])
def test_a0_upload_auto_import_search_generation_and_restart(tmp_path,level):
    client=create_app(tmp_path).test_client()
    with fitz.open() as pdf:
        page=pdf.new_page()
        page.insert_text((50,45),f'IB Physics {level} Paper 1B 2025')
        page.insert_text((50,100),'1. Calculate the percentage uncertainty in the length measurement. [2]')
        data=pdf.tobytes()
    response=client.post('/api/documents',data=dict(file=(BytesIO(data),f'Physics_{level}_Paper1B_2025.pdf'),ocr_mode='off',auto_import='1'))
    assert response.status_code == 201,response.json
    assert response.json['questions'][0]['topics'] == ['A.0']
    result=client.get(f'/api/questions?topic=A.0&level={level}').json
    assert len(result) == 1 and result[0]['topics'] == ['A.0']
    catalog=client.get('/api/catalog').json
    assert catalog['topics']['A.0'] == TOPICS['A.0'] == 'Measurements and uncertainties'
    assert 'A.0' not in catalog['hl_only_topics']
    paper=client.post('/api/papers',json=dict(level=level,minutes=10,topics=['A.0']))
    assert paper.status_code == 201,paper.json
    assert paper.json['question_ids'] == [result[0]['id']]
    restarted=create_app(tmp_path).test_client()
    assert restarted.get('/api/questions?topic=A.0').json[0]['tags'] == result[0]['tags']
