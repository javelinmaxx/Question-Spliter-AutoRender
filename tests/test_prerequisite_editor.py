from copy import deepcopy

import pytest

from app import create_app
from topic_scope import topic_closure
from test_workflow import upload, save


def policy(client):
    return client.get('/api/prerequisites').json


def test_saved_map_updates_search_preview_render_and_generation_and_survives_restart(tmp_path):
    client=create_app(tmp_path).test_client();doc=upload(client);question=save(client,doc)
    options=dict(level='HL',minutes=30,topics=['A.2'])
    assert len(client.get('/api/questions?topic=A.2').json)==1
    old=policy(client);requires=deepcopy(old['policy']['requires']);requires['A.2']=[]
    result=client.post('/api/prerequisites',json=dict(requires=requires,revision=old['policy']['revision']))
    assert result.status_code==200,result.json
    assert result.json['policy']['customized']
    assert client.get('/api/questions?topic=A.2').json==[]
    assert client.post('/api/papers/preview',json=options).json['questions']==[]
    assert client.get(f"/api/questions/{question['id']}/image?topic=A.2").status_code==400
    assert client.post('/api/papers',json=dict(options,question_ids=[question['id']])).status_code==400
    assert client.get('/api/questions').json[0]['topics']==question['topics']
    restarted=create_app(tmp_path).test_client()
    assert policy(restarted)['policy']['requires']['A.2']==[]
    assert restarted.get('/api/questions?topic=A.2').json==[]
    current=policy(restarted)
    reset=restarted.post('/api/prerequisites',json=dict(requires=current['defaults'],revision=current['policy']['revision']))
    assert reset.status_code==200 and not reset.json['policy']['customized']
    assert len(restarted.get('/api/questions?topic=A.2').json)==1


def test_maps_are_isolated_per_bank_and_do_not_leak_into_standalone_rules(tmp_path):
    first=create_app(tmp_path/'first').test_client();second=create_app(tmp_path/'second').test_client()
    data=policy(first);requires=deepcopy(data['policy']['requires']);requires['A.2']=[]
    assert first.post('/api/prerequisites',json=dict(requires=requires,revision=data['policy']['revision'])).status_code==200
    assert policy(first)['policy']['requires']['A.2']==[]
    assert policy(second)['policy']['requires']['A.2']==['A.1']
    assert topic_closure(['A.2'])=={'A.0','A.1','A.2'}
    from concurrent.futures import ThreadPoolExecutor
    apps=[first.application,second.application]
    def read(index):
        with apps[index%2].test_client() as client:
            return policy(client)['policy']['requires']['A.2']
    with ThreadPoolExecutor(max_workers=4) as workers:
        assert list(workers.map(read,range(20)))==[[] if i%2==0 else ['A.1'] for i in range(20)]


@pytest.mark.parametrize('invalid',['missing','unknown','self','cycle','duplicate','string','object'])
def test_invalid_graphs_do_not_replace_saved_map(tmp_path,invalid):
    client=create_app(tmp_path).test_client();old=policy(client);requires=deepcopy(old['policy']['requires'])
    if invalid=='missing':del requires['A.0']
    elif invalid=='unknown':requires['A.1']=['Z.9']
    elif invalid=='self':requires['A.1']=['A.1']
    elif invalid=='cycle':requires['A.0']=['A.2']
    elif invalid=='duplicate':requires['A.1']=['A.0','A.0']
    elif invalid=='string':requires['A.1']='A.0'
    elif invalid=='object':requires['A.1']=[{}]
    result=client.post('/api/prerequisites',json=dict(requires=requires,revision=old['policy']['revision']))
    assert result.status_code==400,result.json
    assert policy(client)['policy']==old['policy']


def test_stale_editor_cannot_overwrite_another_saved_revision(tmp_path):
    client=create_app(tmp_path).test_client();original=policy(client)
    requires=deepcopy(original['policy']['requires']);requires['A.2']=[]
    assert client.post('/api/prerequisites',json=dict(requires=requires,revision=original['policy']['revision'])).status_code==200
    stale=client.post('/api/prerequisites',json=dict(requires=original['defaults'],revision=original['policy']['revision']))
    assert stale.status_code==409
    assert policy(client)['policy']['requires']['A.2']==[]
