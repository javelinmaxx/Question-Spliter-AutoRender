import fitz

from app import create_app
from test_workflow import upload, save
from test_subquestions import saved_parent, approve
from paper_cover import add_practice_cover
from physics import TOPICS


def generated(client, **changes):
    payload=dict(level='HL',minutes=90,topics=[])
    payload.update(changes)
    result=client.post('/api/papers',json=payload)
    assert result.status_code == 201,result.json
    response=client.get(f"/api/papers/{result.json['id']}/download")
    return fitz.open(stream=response.data,filetype='pdf')


def test_practice_cover_has_correct_exam_details_and_actual_page_count(tmp_path):
    client=create_app(tmp_path).test_client()
    doc=upload(client);save(client,doc);save(client,doc,1)
    with generated(client) as pdf:
        text=pdf[0].get_text()
        for expected in ['Physics','Higher level','Paper 2','PRACTICE ASSESSMENT','Candidate number',
                         'Time allowed: 1 hour 30 minutes','Instructions to candidates','[12 marks]',
                         'Not an official IB examination',f'{len(pdf)} pages']:
            assert expected in text,expected
        assert 'Topics' in text and 'All topics' in text
        assert 'Practice assessment' in pdf.metadata['title']
        assert pdf[0].rect.width == 595 and pdf[0].rect.height == 842
        assert all(0 <= b[0] < b[2] <= 595 and 0 <= b[1] < b[3] <= 842 for b in pdf[0].get_text('blocks'))


def test_short_cover_does_not_claim_original_marks_for_omitted_parts(tmp_path):
    client=create_app(tmp_path).test_client()
    q=saved_parent(client);approve(client,q)
    with generated(client,render_mode='short',minutes=5) as pdf:
        text=pdf[0].get_text()
        assert 'Total marks are not confirmed' in text
        assert 'maximum mark' not in text
        assert 'Rendering: Short' in text and 'Time allowed: 5 minutes' in text


def test_sl_mixed_paper_legacy_cover_uses_correct_level_and_paper_label(tmp_path):
    client=create_app(tmp_path).test_client()
    doc=upload(client)
    save(client,doc,level='SL',syllabus='Legacy')
    save(client,doc,1,level='SL',syllabus='Legacy',paper='Paper 1A')
    with generated(client,level='SL',syllabus='Legacy') as pdf:
        text=pdf[0].get_text()
        assert 'Standard level' in text and 'Mixed-paper practice' in text
        assert 'Legacy syllabus' in text and 'Higher level' not in text


def test_selected_topic_codes_and_titles_appear_on_generated_cover(tmp_path):
    client=create_app(tmp_path).test_client()
    doc=upload(client);save(client,doc)
    with generated(client,topics=['A.1','A.2']) as pdf:
        text=pdf[0].get_text()
        assert 'A.1 Kinematics' in text and 'A.2 Forces and momentum' in text
        assert 'All topics' not in text


def test_all_topic_titles_fit_without_overlapping_cover_footer():
    with fitz.open() as pdf:
        add_practice_cover(pdf,level='HL',syllabus='2025',target=45,mode='full',
                           chosen=[dict(paper='Paper 2',minutes=30,marks=10)],topics=list(TOPICS))
        text=pdf[0].get_text()
        for code,title in TOPICS.items():
            assert f'{code} {title}' in text.replace('\n',' ')
        blocks=pdf[0].get_text('blocks')
        topic_blocks=[b for b in blocks if 'A.0 Measurements' in b[4]]
        assert topic_blocks and max(b[3] for b in topic_blocks)<734

def test_automatic_selection_seed_is_reused_and_printed_with_topics(tmp_path):
    client=create_app(tmp_path).test_client()
    doc=upload(client)
    save(client,doc,minutes=7,topics=['A.1'])
    save(client,doc,1,minutes=6,topics=['A.1'])
    options=dict(level='HL',minutes=13,topics=['A.1'])
    preview=client.post('/api/papers/preview',json=dict(options,auto_select=True,selection_seed=314159))
    assert preview.status_code==200,preview.json
    assert preview.json['selection_seed']==314159
    generated=client.post('/api/papers',json=dict(options,selection_seed=preview.json['selection_seed']))
    assert generated.status_code==201,generated.json
    assert generated.json['question_ids']==preview.json['selected_question_ids']
    assert generated.json['selection_seed']==314159
    downloaded=client.get(f"/api/papers/{generated.json['id']}/download")
    with fitz.open(stream=downloaded.data,filetype='pdf') as pdf:
        text=pdf[0].get_text()
        assert 'A.1 Kinematics' in text
        assert 'Random seed: 314159' in text
        assert 'Seed 314159' in pdf.metadata['title']
