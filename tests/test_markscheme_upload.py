from io import BytesIO

import fitz
import pytest

import app as application
from app import create_app
from upload_filter import markscheme_heading, markscheme_name
from test_workflow import sample_pdf


@pytest.mark.parametrize('name', [
    'Physics_paper_2_HL_markscheme.pdf', 'Physics Mark Scheme 2025.PDF',
    'm25_physics_p2_ms.pdf', 'Physics MS TZ2.pdf', 'Marking notes.pdf',
    'Markschemes/generic.pdf', 'papers/mark schemes/session/paper.pdf',
    r'papers\MS\unlabelled.pdf'])
def test_markscheme_filename_or_folder_is_skipped_before_analysis(tmp_path, monkeypatch, name):
    client = create_app(tmp_path).test_client()
    monkeypatch.setattr(application, 'extract', lambda *a, **kw: pytest.fail('Do not analyze named markschemes'))
    filename = name.replace('\\','/').split('/')[-1]
    result = client.post('/api/documents', data=dict(
        file=(BytesIO(b'not even a PDF'),filename),relative_path=name,auto_import='1'))
    assert result.status_code == 200 and result.json['status'] == 'skipped'
    assert result.json['reason'] == 'markscheme'
    assert client.get('/api/documents').json == client.get('/api/questions').json == []
    assert list((tmp_path/'documents').iterdir()) == []


@pytest.mark.parametrize('name', ['Physics_paper_2_HL.pdf','physics_msquared.pdf',
                                  'Momentum measurement.pdf','papers and markschemes/Physics.pdf'])
def test_question_paper_names_are_not_overmatched(name):
    assert not markscheme_name(name)


def test_generic_filename_with_markscheme_cover_is_skipped_without_ocr(tmp_path, monkeypatch):
    with fitz.open() as pdf:
        page=pdf.new_page()
        page.insert_text((50,70),'Physics Higher level Paper 2')
        page.insert_text((50,100),'Markscheme')
        data=pdf.tobytes()
    monkeypatch.setattr(application,'extract',lambda *a,**kw:pytest.fail('Do not OCR readable markscheme covers'))
    client=create_app(tmp_path).test_client()
    response=client.post('/api/documents',data=dict(file=(BytesIO(data),'generic.pdf'),auto_import='1'))
    assert response.status_code == 200 and response.json['reason'] == 'markscheme'
    assert client.get('/api/documents').json == []
    assert list((tmp_path/'documents').iterdir()) == []


def test_markscheme_ocr_heading_is_checked_before_model_review_or_auto_import(tmp_path, monkeypatch):
    original=application.extract
    def scanned_markscheme(*args,**kwargs):
        result=original(*args,**kwargs)
        result['text_pages'][0]['text']='Physics\nMARK SCHEME\n2025\n'
        result['questions'][0]['ocr_comparison']['status']='disagreement'
        return result
    monkeypatch.setattr(application,'extract',scanned_markscheme)
    monkeypatch.setattr(application,'review_disagreement',lambda *a,**kw:pytest.fail('Do not review markscheme questions'))
    client=create_app(tmp_path).test_client()
    result=client.post('/api/documents',data=dict(file=(BytesIO(sample_pdf()),'generic.pdf'),auto_import='1'))
    assert result.status_code == 200 and result.json['status'] == 'skipped'
    assert client.get('/api/documents').json == client.get('/api/questions').json == []


def test_question_mentioning_markscheme_is_not_skipped(tmp_path):
    assert not markscheme_heading('1. Explain how a markscheme can be used in assessment.')
    with fitz.open() as pdf:
        page=pdf.new_page()
        page.insert_text((50,45),'IB Physics Higher level Paper 2 2025')
        page.insert_text((50,100),'1. Explain how a markscheme credits a calculation of projectile velocity. [3]')
        data=pdf.tobytes()
    client=create_app(tmp_path).test_client()
    result=client.post('/api/documents',data=dict(file=(BytesIO(data),'Physics.pdf'),auto_import='1',ocr_mode='off'))
    assert result.status_code == 201 and result.json['import_result']['imported'] == 1
