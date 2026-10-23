from io import BytesIO
import json
import re
import sqlite3

import fitz
from PIL import Image,ImageChops,ImageStat
import pytest

from app import create_app
from analysis_storage import source_hash
from watermarks import is_label,prepare,red_mask,rejected


def pdf_bytes(watermark=True,raster=False,label='WATERMARK'):
    with fitz.open() as pdf:
        page=pdf.new_page()
        page.insert_text((50,45),'Physics HL Paper 2 2025')
        page.insert_text((50,100),'1. Calculate the velocity of the cart. [3]',fontsize=14)
        page.insert_text((50,160),'A red graph label must remain.',fontsize=14,color=(1,0,0))
        page.draw_line((70,185),(300,185),color=(1,0,0))
        if watermark:page.insert_text((100,105),label,fontsize=32 if label=='WATERMARK' else 18,color=(1,0,0))
        if raster:
            image=page.get_pixmap(matrix=fitz.Matrix(2,2)).tobytes('png')
            with fitz.open() as scan:
                p=scan.new_page();p.insert_image(p.rect,stream=image);return scan.tobytes()
        return pdf.tobytes()


def test_native_red_overlay_removed_without_losing_underlying_text_or_red_diagram(tmp_path):
    path=tmp_path/'source.pdf';path.write_bytes(pdf_bytes());before=source_hash(path)
    cleaned,report=prepare(path,tmp_path/'cache')
    assert report['cleaned_pages']==[0] and report['rejected_regions']==[]
    with fitz.open(cleaned) as got,fitz.open(stream=pdf_bytes(False),filetype='pdf') as expected:
        a=got[0].get_pixmap();b=expected[0].get_pixmap()
        im_a=Image.frombytes('RGB',(a.width,a.height),a.samples)
        im_b=Image.frombytes('RGB',(b.width,b.height),b.samples)
        # Both rasterizers retain black exam glyphs AND unrelated red content.
        for area in [(40,80,500,120),(40,140,400,190)]:
            assert max(ImageStat.Stat(ImageChops.difference(im_a.crop(area),im_b.crop(area))).mean)<2
    assert source_hash(path)==before
    assert prepare(path,tmp_path/'cache')[0]==cleaned


def test_red_handwriting_and_diagram_labels_are_not_watermarks(tmp_path):
    path=tmp_path/'notes.pdf';path.write_bytes(pdf_bytes(False))
    cleaned,report=prepare(path,tmp_path/'cache')
    assert cleaned==path and not report['cleaned_pages'] and not report['rejected_regions']


@pytest.mark.parametrize('label',['DOWNLOADED FROM IBPAPERS.INFO','downloaded from IB PAPERS . INFO'])
def test_ibpapers_overlay_is_recognized_without_hint(tmp_path,label):
    path=tmp_path/'source.pdf';path.write_bytes(pdf_bytes(label=label))
    cleaned,report=prepare(path,tmp_path/'cache')
    assert report['cleaned_pages']==[0] and report['rejected_regions']==[]
    assert label in report['removed_labels']
    with fitz.open(cleaned) as got,fitz.open(stream=pdf_bytes(False),filetype='pdf') as expected:
        a=got[0].get_pixmap();b=expected[0].get_pixmap()
        difference=ImageChops.difference(Image.frombytes('RGB',(a.width,a.height),a.samples),
                                       Image.frombytes('RGB',(b.width,b.height),b.samples))
        assert max(ImageStat.Stat(difference).mean)<2
    assert not is_label('IB papers provide practice for physics.')


def test_flattened_ibpapers_overlay_is_rejected_without_hint(tmp_path):
    path=tmp_path/'scan.pdf';path.write_bytes(pdf_bytes(raster=True,label='DOWNLOADED FROM IBPAPERS.INFO'))
    _,report=prepare(path,tmp_path/'cache')
    assert report['rejected_regions'] and not report['cleaned_pages']


def test_flattened_recognized_watermark_rejects_affected_image(tmp_path):
    path=tmp_path/'scan.pdf';path.write_bytes(pdf_bytes(True,True))
    _,report=prepare(path,tmp_path/'cache')
    assert report['rejected_regions']
    assert rejected([dict(page=0,rect=[30,70,560,250])],report)
    assert not rejected([dict(page=1,rect=[30,70,560,250])],report)


def test_upload_saves_clean_images_and_generated_pdf_without_requiring_ocr(tmp_path):
    client=create_app(tmp_path).test_client()
    raw=pdf_bytes()
    result=client.post('/api/documents',data=dict(file=(BytesIO(raw),'Physics_HL_2025_Paper2.pdf'),ocr_mode='off',auto_import='1'))
    assert result.status_code==201,result.json
    assert result.json['watermark']['cleaned_pages']==[0]
    assert result.json['import_result']['imported']==1
    question=client.get('/api/questions').json[0]
    assert 'WATERMARK' not in question['text'] and 'Calculate the velocity' in question['text']
    assert 'A red graph label' in question['text']
    paper=client.post('/api/papers',json=dict(level='HL',minutes=10,topics=[]))
    assert paper.status_code==201,paper.json
    pdf=client.get(f"/api/papers/{paper.json['id']}/download")
    with fitz.open(stream=pdf.data,filetype='pdf') as rendered:
        page=rendered[1];tp=page.get_textpage_ocr(language='eng',dpi=200,full=True);text=page.get_text(textpage=tp)
        assert 'WATERMARK' not in text and 'velocity' in text
        assert not re.search(r'(?m)^1[.)]',text)
    original=tmp_path/'documents'/(result.json['id']+'.pdf')
    assert original.read_bytes()==raw


def test_unremovable_import_is_excluded_and_cannot_be_manually_saved(tmp_path):
    client=create_app(tmp_path).test_client()
    result=client.post('/api/documents',data=dict(file=(BytesIO(pdf_bytes(True,True)),'Physics_HL_2025_Paper2.pdf'),ocr_mode='auto',auto_import='1'))
    assert result.status_code==201,result.json
    assert result.json['watermark']['rejected_questions']==[1]
    assert result.json['questions']==[] and result.json['import_result']['imported']==0
    value=dict(document_id=result.json['id'],number=1,level='HL',syllabus='2025',year=2025,paper='Paper 2',topics=['A.1'],minutes=5,marks=3,difficulty='Unrated',regions=[dict(page=0,rect=[30,70,560,250])])
    saved=client.post('/api/questions',json=value)
    assert saved.status_code==400 and 'watermark' in saved.json['error']
    assert client.get('/api/questions').json==[]


def legacy_import(tmp_path,monkeypatch,raster=False):
    import app as application
    actual=application.prepare_watermarks
    report=dict(version='before-watermark-cleanup',key='0'*64,cleaned_pages=[],removed_labels=[],rejected_regions=[],warnings=[],hint='')
    monkeypatch.setattr(application,'prepare_watermarks',lambda path,*args:(path,dict(report)))
    client=create_app(tmp_path).test_client();raw=pdf_bytes(True,raster)
    result=client.post('/api/documents',data=dict(file=(BytesIO(raw),'Physics_HL_2025_Paper2.pdf'),ocr_mode='auto' if raster else 'off',auto_import='1'))
    assert result.status_code==201,result.json
    assert result.json['import_result']['imported']==1,result.json
    q=client.get('/api/questions').json[0]
    monkeypatch.setattr(application,'prepare_watermarks',actual)
    return result.json,q,raw


def test_startup_retrofits_existing_png_and_preserves_question_identity(tmp_path,monkeypatch):
    doc,q,raw=legacy_import(tmp_path,monkeypatch)
    image=tmp_path/'images'/(q['id']+'.png');before=image.read_bytes()
    client=create_app(tmp_path).test_client();bank=client.get('/api/questions').json
    assert len(bank)==1 and bank[0]['id']==q['id']
    assert bank[0]['topics']==q['topics']
    assert image.read_bytes()!=before
    assert (tmp_path/'documents'/(doc['id']+'.pdf')).read_bytes()==raw
    # A restart reuses the cleanup/PDF cache and does not rewrite the clean PNG.
    after=image.read_bytes();create_app(tmp_path)
    assert image.read_bytes()==after


def test_startup_deletes_uncleanable_bank_question_and_image_but_keeps_original(tmp_path,monkeypatch):
    doc,q,raw=legacy_import(tmp_path,monkeypatch,raster=True)
    client=create_app(tmp_path).test_client()
    assert client.get('/api/questions').json==[]
    assert not (tmp_path/'images'/(q['id']+'.png')).exists()
    assert (tmp_path/'documents'/(doc['id']+'.pdf')).read_bytes()==raw
    analysis=client.get('/api/documents/'+doc['id']).json
    assert q['id'] in analysis['watermark']['deleted_question_ids']
    assert analysis['questions']==[]
    duplicate=client.post('/api/documents',data=dict(file=(BytesIO(raw),'Physics_HL_2025_Paper2.pdf'),auto_import='1'))
    assert duplicate.json['duplicate_document'] and duplicate.json['import_result']['imported']==0
    assert create_app(tmp_path).test_client().get('/api/questions').json==[]


def test_removal_failure_excludes_only_affected_question_region(tmp_path,monkeypatch):
    import watermarks
    path=tmp_path/'source.pdf';path.write_bytes(pdf_bytes())
    monkeypatch.setattr(watermarks,'remove_svg_text',lambda *args:(_ for _ in ()).throw(ValueError('Cannot isolate glyphs')))
    _,report=prepare(path,tmp_path/'cache')
    assert rejected([dict(page=0,rect=[30,70,560,140])],report)
    assert not rejected([dict(page=0,rect=[30,300,560,500])],report)


def test_only_red_watermark_annotations_are_removed(tmp_path):
    path=tmp_path/'annotations.pdf'
    with fitz.open() as pdf:
        page=pdf.new_page();page.insert_text((50,100),'1. Calculate the velocity. [3]')
        page.add_freetext_annot(fitz.Rect(100,80,400,140),'WATERMARK',text_color=(1,0,0))
        page.add_freetext_annot(fitz.Rect(100,180,400,240),'WATERMARK',text_color=(0,0,1))
        pdf.save(path)
    cleaned,report=prepare(path,tmp_path/'cache')
    assert report['cleaned_pages']==[0] and report['outline_pages']==[]
    with fitz.open(cleaned) as pdf:
        assert len(list(pdf[0].annots()))==1
        assert 'Calculate the velocity' in pdf[0].get_text()


def test_custom_watermark_text_cleans_a_new_brand(tmp_path):
    path=tmp_path/'brand.pdf'
    with fitz.open() as pdf:
        page=pdf.new_page();page.insert_text((50,100),'1. Calculate the velocity. [3]')
        page.insert_text((150,100),'ACME ARCHIVE',fontsize=22,color=(1,0,0));pdf.save(path)
    cleaned,report=prepare(path,tmp_path/'cache',hint='ACME ARCHIVE')
    assert report['cleaned_pages']==[0] and report['removed_labels']==['ACME ARCHIVE']
    assert not report['rejected_regions']


def test_changed_inspection_with_same_cache_key_cannot_reimport_deleted_question(tmp_path,monkeypatch):
    import app as application
    doc,q,raw=legacy_import(tmp_path,monkeypatch)
    report=dict(version='updated',key='0'*64,cleaned_pages=[],outline_pages=[],removed_labels=[],
                rejected_regions=[dict(page=0,rect=[30,70,560,200],reason='Watermark cannot be isolated')],warnings=[],hint='')
    monkeypatch.setattr(application,'prepare_watermarks',lambda path,*args:(path,dict(report)))
    client=create_app(tmp_path).test_client()
    assert client.get('/api/questions').json==[]
    restored=client.get('/api/documents/'+doc['id']).json
    assert restored['questions']==[] and restored['watermark']['rejected_regions']
    assert client.post('/api/documents/'+doc['id']+'/confirm-import',json={}).json['imported']==0
