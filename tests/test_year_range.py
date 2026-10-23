import json

import pytest

from app import create_app
from test_workflow import upload, save


@pytest.fixture
def bank(tmp_path):
    app=create_app(tmp_path);client=app.test_client();doc=upload(client)
    first=save(client,doc,minutes=7)
    second=save(client,doc,1,minutes=6)
    import sqlite3
    with sqlite3.connect(tmp_path/'bank.sqlite3') as conn:
        second['year']=2026
        conn.execute('UPDATE questions SET data=? WHERE id=?',
                     (json.dumps({k:v for k,v in second.items() if k not in ('id','document_id')}),second['id']))
    return client,tmp_path,first,second


@pytest.mark.parametrize('query,which',[
    ('year_min=2025&year_max=2026','both'),('year_min=2026','second'),
    ('year_max=2025','first'),('year_min=2025&year_max=2025','first'),
    ('year=2025','first'),('year_min=2027','none')])
def test_library_inclusive_and_open_year_ranges(bank,query,which):
    client,_,first,second=bank
    result=client.get('/api/questions?'+query)
    assert result.status_code==200
    expected={'both':{first['id'],second['id']},'first':{first['id']},'second':{second['id']},'none':set()}
    assert {q['id'] for q in result.json}==expected[which]


def test_preview_generation_and_fill_share_year_filter(bank):
    client,_,first,second=bank
    options=dict(level='HL',minutes=20,topics=[],year_min=2025,year_max=2025)
    preview=client.post('/api/papers/preview',json=options)
    assert preview.status_code==200 and [q['id'] for q in preview.json['questions']]==[first['id']]
    reasons={r['code']:r['count'] for r in preview.json['diagnostics']['exclusions']}
    assert reasons['year']==1
    generated=client.post('/api/papers',json=dict(options,question_ids=[first['id']],fill_paper=True))
    assert generated.status_code==201 and generated.json['question_ids']==[first['id']]
    assert generated.json['diagnostics']['requested']['year_min']==2025
    invalid=client.post('/api/papers',json=dict(options,question_ids=[second['id']]))
    assert invalid.status_code==400 and 'no longer fit' in invalid.json['error']


@pytest.mark.parametrize('values',[
    dict(year_min=2026,year_max=2025),dict(year_min=1969),dict(year_max=2101),
    dict(year_min='nope'),dict(year_min=2025.5),dict(year=2025,year_max=2026),
])
def test_bad_year_range_is_rejected_consistently(bank,values):
    client,_,_,_=bank
    assert client.get('/api/questions',query_string=values).status_code==400
    for endpoint in ['/api/papers/preview','/api/papers']:
        result=client.post(endpoint,json=dict(level='HL',minutes=20,topics=[],**values))
        assert result.status_code==400 and 'year' in result.json['error'].lower()


def test_unknown_years_are_included_only_without_a_range(bank):
    client,root,first,second=bank
    import sqlite3
    with sqlite3.connect(root/'bank.sqlite3') as conn:
        q=json.loads(conn.execute('SELECT data FROM questions WHERE id=?',(first['id'],)).fetchone()[0])
        q['year']=None
        conn.execute('UPDATE questions SET data=? WHERE id=?',(json.dumps(q),first['id']))
    assert len(client.get('/api/questions').json)==2
    result=client.get('/api/questions?year_min=2025')
    assert [q['id'] for q in result.json]==[second['id']]
