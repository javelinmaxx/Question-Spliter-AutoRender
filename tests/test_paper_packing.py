from io import BytesIO
import re

import fitz
import pytest

from app import create_app
from test_workflow import save


@pytest.fixture
def mixed_bank(tmp_path):
    client=create_app(tmp_path).test_client();saved={}
    for paper in ['Paper 1A','Paper 1B','Paper 2']:
        with fitz.open() as pdf:
            page=pdf.new_page();page.insert_text((50,45),f'IB Physics 2025 Higher level {paper}')
            for n,y in [(1,100),(2,300)]:
                page.insert_text((50,y),f'{n}. Calculate the velocity in {paper} experiment {n}. [2]')
                for k,label in enumerate(['A. 1 m/s','B. 2 m/s','C. 3 m/s','D. 4 m/s']):
                    page.insert_text((65,y+22+k*16),label)
            doc=client.post('/api/documents',data=dict(file=(BytesIO(pdf.tobytes()),f'Physics_HL_{paper}_2025.pdf'),ocr_mode='off')).json
        saved[paper]=[save(client,doc,i,minutes=5,topics=['A.1']) for i in range(2)]
    return client,saved


def assert_grouped_pdf(client,result):
    downloaded=client.get(f"/api/papers/{result['id']}/download")
    with fitz.open(stream=downloaded.data,filetype='pdf') as pdf:
        # Four short Paper 1 questions share a page; the two Paper 2 questions
        # share a separate page, with a dedicated cover preceding both groups.
        assert len(pdf)==3
        text1,text2=pdf[1].get_text(),pdf[2].get_text()
        assert len(re.findall(r'(?m)^Question \d+$',text1))==4
        assert len(re.findall(r'(?m)^Question \d+$',text2))==2
        assert 'Paper 2 experiment' not in text1
        assert 'Paper 1A experiment' not in text2 and 'Paper 1B experiment' not in text2
        assert re.findall(r'(?m)^Question (\d+)$',text1+text2)==['1','2','3','4','5','6']
        assert '(continued)' not in text1+text2
        assert '3 pages' in pdf[0].get_text()


def test_manual_mixed_order_is_grouped_stably_before_numbering(mixed_bank):
    client,qs=mixed_bank
    order=[qs['Paper 2'][1],qs['Paper 1A'][1],qs['Paper 1B'][0],qs['Paper 2'][0],qs['Paper 1A'][0],qs['Paper 1B'][1]]
    result=client.post('/api/papers',json=dict(level='HL',minutes=30,topics=[],question_ids=[q['id'] for q in order]))
    assert result.status_code==201,result.json
    expected=[order[i]['id'] for i in [1,2,4,5,0,3]]
    assert result.json['question_ids']==expected
    assert [s['question_id'] for s in result.json['selections']]==expected
    assert_grouped_pdf(client,result.json)


@pytest.mark.parametrize('fill',[False,True])
def test_automatic_and_fill_are_grouped_and_packed(mixed_bank,fill):
    client,qs=mixed_bank
    options=dict(level='HL',minutes=30,topics=[])
    if fill:options.update(question_ids=[qs['Paper 2'][0]['id']],fill_paper=True)
    result=client.post('/api/papers',json=options)
    assert result.status_code==201,result.json
    if fill:
        assert len(result.json['filled_question_ids'])==5
        teacher=next(s for s in result.json['selections'] if s['question_id']==qs['Paper 2'][0]['id'])
        assert teacher['selection_source']=='teacher' and teacher['number']==5
    assert_grouped_pdf(client,result.json)
