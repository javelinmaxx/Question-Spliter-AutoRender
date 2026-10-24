from io import BytesIO

import fitz
import pytest
from PIL import Image

from app import create_app
from physics import choose_questions


@pytest.fixture
def bank(tmp_path):
    app = create_app(tmp_path)
    app.config.update(TESTING=True)
    return app.test_client(), tmp_path


def sample_pdf():
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((50, 45), 'IB Physics 2025 Higher level Paper 2')
        page.insert_text((50, 90), '1. Calculate the velocity of a projectile. [4]')
        page.insert_text((65, 150), '(a) State the initial acceleration.')
        page = pdf.new_page()
        page.insert_text((65, 90), '(b) Explain the change in momentum. [3]')
        page = pdf.new_page()
        page.insert_text((50, 90), '2. Determine the resistance in this circuit. [5]')
        return pdf.tobytes()


def upload(client, data=None):
    response = client.post('/api/documents', data={'file': (BytesIO(data or sample_pdf()), 'Physics_HL_Paper2_2025.pdf')})
    assert response.status_code == 201, response.json
    return response.json


def save(client, doc, index=0, **overrides):
    q = dict(doc['questions'][index], document_id=doc['id'])
    q.update(overrides)
    response = client.post('/api/questions', json=q)
    assert response.status_code == 201, response.json
    return response.json


def test_existing_paper_one_images_use_tighter_crop_without_changing_saved_geometry(bank):
    from physics import render_question
    client, root = bank
    doc = upload(client)
    regions = [dict(page=0, rect=[30, 70, 565, 200])]
    saved = save(client, doc, paper='Paper 1A', regions=regions)
    # Simulate a PNG saved before the display-crop rule was introduced.
    with fitz.open(root / 'documents' / (doc['id'] + '.pdf')) as source:
        old_png = render_question(source, regions)
        expected = render_question(source, regions, paper='Paper 1A')
    (root / 'images' / (saved['id'] + '.png')).write_bytes(old_png)
    restarted = create_app(root).test_client()
    image = restarted.get(f"/api/questions/{saved['id']}/image")
    assert image.status_code == 200 and image.data == expected and image.data != old_png
    preview = restarted.post(f"/api/documents/{doc['id']}/preview",
                             json=dict(regions=regions, paper='Paper 1A'))
    assert preview.data == expected
    assert restarted.get('/api/questions').json[0]['regions'] == regions


def test_import_group_review_png_search_and_restart(bank):
    client, root = bank
    doc = upload(client)
    assert len(doc['questions']) == 2
    first = doc['questions'][0]
    assert '(a)' in first['text'] and '(b)' in first['text']
    assert 'Determine the resistance' not in first['text']
    assert first['marks'] == 7 and first['minutes'] == 11.7
    assert first['level'] == 'HL' and first['syllabus'] == '2025'
    assert first['topics'] == ['A.1', 'A.2']
    assert client.get('/api/questions').json == []  # Import is not approval.
    preview = client.post(f"/api/documents/{doc['id']}/preview", json={'regions': first['regions']})
    assert preview.status_code == 200 and preview.mimetype == 'image/png'
    saved = save(client, doc, tags=['mechanics'], difficulty='Hard')
    image = Image.open(BytesIO(client.get(f"/api/questions/{saved['id']}/image").data))
    assert image.width == 1400 and image.height > 1000
    # A.2 admits its earlier A.1 foundation; A.1 cannot admit later A.2 content.
    assert len(client.get('/api/questions?q=mechanics&topic=A.2&level=HL').json) == 1
    assert client.get('/api/questions?q=mechanics&topic=A.1&level=HL').json == []
    assert len(client.get('/api/questions?level=SL').json) == 1  # Common SL content from an HL paper.
    reopened = create_app(root).test_client()
    assert reopened.get('/api/questions').json[0]['tags'] == ['mechanics']
    reviewed = reopened.get('/api/documents/' + doc['id']).json
    assert reviewed['questions'][0]['difficulty'] == 'Hard'


def test_generator_preserves_parent_and_exports_pdf(bank):
    client, _ = bank
    doc = upload(client)
    saved = save(client, doc)
    save(client, doc, 1)
    response = client.post('/api/papers', json={'level': 'HL', 'minutes': 13, 'topics': ['A.1', 'A.2'], 'paper': 'Paper 2'})
    assert response.status_code == 201, response.json
    result = response.json
    assert result['question_ids'] == [saved['id']]
    assert result['actual_minutes'] == 11.7 and result['shortfall_minutes'] == 1.3
    exported = client.get(f"/api/papers/{result['id']}/download")
    assert exported.status_code == 200
    with fitz.open(stream=exported.data, filetype='pdf') as pdf:
        text = '\n'.join(p.get_text() for p in pdf)
        assert '(a)' in text and '(b)' in text
        assert 'Determine the resistance' not in text
        assert text.index('(a)') < text.index('(b)')


def test_generator_rejects_partial_topic_groups_and_wrong_level(bank):
    client, _ = bank
    doc = upload(client)
    save(client, doc)
    for filters in [dict(level='SL_from_HL', topics=['A.4']), dict(level='HL', topics=['A.1']), dict(level='HL', topics=[], syllabus='Legacy'), dict(level='HL', topics=[], minutes=5)]:
        response = client.post('/api/papers', json={'minutes': 30, **filters})
        assert response.status_code == 400


def test_invalid_crop_and_metadata_never_saved(bank):
    client, _ = bank
    doc = upload(client)
    base = dict(doc['questions'][0], document_id=doc['id'])
    for overrides in [dict(regions=[{'page': 99, 'rect': [0, 0, 50, 50]}]), dict(regions=[{'page': 0, 'rect': [-1, 0, 50, 50]}]), dict(regions=[]), dict(minutes=-5), dict(minutes=float('inf')), dict(level='Unknown'), dict(topics=['made up']), dict(year=0), dict(marks=-2)]:
        response = client.post('/api/questions', json={**base, **overrides})
        assert response.status_code == 400, response.json
    assert client.get('/api/questions').json == []


def test_update_and_manual_question_persist(bank):
    client, _ = bank
    doc = upload(client)
    first = save(client, doc)
    second = save(client, doc, minutes=15, topics=['A.1'])
    assert first['id'] == second['id']
    assert len(client.get('/api/questions').json) == 1
    manual = save(client, doc, number=3, regions=[{'page': 1, 'rect': [40, 60, 550, 200]}])
    result = client.get('/api/documents/' + doc['id']).json
    assert manual['number'] in result['saved_numbers']
    assert len(result['questions']) == 3


def test_scanned_pdf_can_be_manually_reviewed(bank):
    client, _ = bank
    with fitz.open() as pdf:
        pdf.new_page()
        doc = upload(client, pdf.tobytes())
    assert doc['questions'] == []
    assert any('OCR' in warning for warning in doc['warnings'])
    response = client.post('/api/questions', json=dict(document_id=doc['id'], number=1,
        year=2025, level='SL', syllabus='2025', paper='Paper 2', topics=['A.1'],
        minutes=5, regions=[dict(page=0, rect=[30, 40, 550, 700])]))
    assert response.status_code == 201, response.json


def test_invalid_pdf_and_page(bank):
    client, _ = bank
    response = client.post('/api/documents', data={'file': (BytesIO(b'not a PDF'), 'paper.pdf')})
    assert response.status_code == 400
    assert client.get('/api/documents').json == []
    doc = upload(client)
    assert client.get(f"/api/documents/{doc['id']}/pages/0").mimetype == 'image/png'
    assert client.get(f"/api/documents/{doc['id']}/pages/999").status_code == 400


def test_subset_selection_is_not_greedy_or_over_budget():
    items = [dict(id='a', minutes=7), dict(id='b', minutes=6), dict(id='c', minutes=4)]
    assert set(choose_questions(items, 10)) == {'b', 'c'}
    assert choose_questions([dict(id='a', minutes=1.04)], 1) == ()
    assert choose_questions(items, 3) == ()


def test_ui_and_catalog(bank):
    client, _ = bank
    assert client.get('/').status_code == 200
    assert len(client.get('/api/catalog').json['topics']) == 25
    assert client.get('/static/app.js').status_code == 200
