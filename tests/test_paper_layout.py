"""Rendered output regressions: empty residue, alignment and source numbering."""
import re

import fitz

from paper_layout import add_question_pages, question_clips
from paper_numbering import erase_source_numbers


def question(regions):
    return dict(document_id='source', number=5, filename='physics.pdf', year=2025,
                paper='Paper 2', regions=regions)


def test_empty_continuation_residue_is_skipped_and_question_five_becomes_three():
    with fitz.open() as source, fitz.open() as output:
        source.new_page().insert_text((50,100),'(Question 5 continued)')
        page=source.new_page()
        page.insert_text((50,120),'5. Calculate the acceleration. [3]')
        page.insert_text((50,720),'(This question continues on page 7)')
        page=source.new_page()
        page.insert_text((50,70),'(Question 5 continued)')
        page.insert_text((65,180),'(b) Explain the change in acceleration. [2]')
        page.insert_text((50,700),'(This question continues on the following page)')
        q=question([dict(page=i,rect=[30,50,565,790]) for i in range(3)])
        result=erase_source_numbers(source,q,{})
        assert result['erased_administrative']==4
        assert add_question_pages(output,source,q,3)==2
        texts=[p.get_text() for p in output]
        assert 'Question 3\n' in texts[0] and 'continued' not in texts[0]
        assert 'Question 3 (continued)' in texts[1]
        assert not any(re.search(r'Question 5|question continues',t,re.I) for t in texts)
        assert '(b)' in texts[1] and 'acceleration' in texts[0]
        for p in output:
            body=[line for block in p.get_text('dict')['blocks'] for line in block.get('lines',[])
                  if any('acceleration' in span['text'] for span in line['spans'])]
            assert 59 <= body[0]['bbox'][1] < 70


def test_tall_crop_does_not_produce_a_blank_trailing_tile():
    with fitz.open() as source, fitz.open() as output:
        page=source.new_page(width=300,height=1200)
        page.insert_text((30,80),'5. Find the speed. [2]')
        page.insert_text((30,1100),'(Question 5 continued)')
        q=question([dict(page=0,rect=[20,40,280,1180])])
        erase_source_numbers(source,q,{})
        assert add_question_pages(output,source,q,1)==1
        assert 'Question 1 (continued)' not in output[0].get_text()


def test_diagram_only_region_is_preserved_and_blank_region_is_skipped():
    with fitz.open() as source:
        page=source.new_page()
        page.draw_circle((150,160),50,color=(0,0,0))
        regions=[dict(page=0,rect=[30,50,300,250]),dict(page=0,rect=[30,300,300,700])]
        clips=list(question_clips(source,regions))
        assert len(clips)==1 and clips[0][1].y0 < 110 and clips[0][1].y1 > 210


def test_scanned_continuation_label_is_erased_without_erasing_question_content():
    with fitz.open() as native:
        page=native.new_page()
        page.insert_text((50,100),'(Question 5 continued)',fontsize=14)
        page.insert_text((65,180),'(b) Calculate the final velocity.',fontsize=14)
        image=page.get_pixmap(matrix=fitz.Matrix(2,2)).tobytes('png')
    with fitz.open() as source, fitz.open() as output:
        page=source.new_page();page.insert_image(page.rect,stream=image)
        q=question([dict(page=0,rect=[30,70,565,300])])
        result=erase_source_numbers(source,q,{})
        assert result['erased_administrative']==1 and result['warnings']==[]
        assert add_question_pages(output,source,q,3)==1
        rendered=output[0]
        tp=rendered.get_textpage_ocr(language='eng',dpi=200,full=True)
        text=rendered.get_text(textpage=tp)
        assert 'Question 3' in text and 'Question 5' not in text
        assert 'final velocity' in text


def test_reference_to_continued_question_in_task_is_preserved():
    with fitz.open() as source:
        page=source.new_page()
        text='Explain how Question 5 continued the investigation.'
        page.insert_text((50,100),text)
        q=question([dict(page=0,rect=[30,70,565,300])])
        assert erase_source_numbers(source,q,{})['erased_administrative']==0
        assert text in source[0].get_text()


def test_source_header_residue_and_footer_barcode_do_not_make_extra_pages():
    with fitz.open() as source, fitz.open() as output:
        page=source.new_page()
        page.insert_text((280,52),'4')
        page.insert_text((480,52),'8825 - 6721')
        page.insert_text((50,100),'5. State the wavelength.')
        for i in range(20):
            page.draw_rect(fitz.Rect(265+3*i,778,266+3*i,813),color=None,fill=(0,0,0))
        q=question([dict(page=0,rect=[30,70,565,797]),dict(page=0,rect=[30,50,565,62])])
        erase_source_numbers(source,q,{})
        assert add_question_pages(output,source,q,3)==1
        text=output[0].get_text()
        assert '8825' not in text and 'wavelength' in text
        body=[b for b in output[0].get_text('blocks') if 'wavelength' in b[4]][0]
        assert body[1] < 70
