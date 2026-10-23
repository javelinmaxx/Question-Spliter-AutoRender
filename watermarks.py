"""Remove identifiable red text overlays, rejecting inseparable raster marks."""
from io import BytesIO
import hashlib
import json
from pathlib import Path
import re
import uuid
import xml.etree.ElementTree as ET

import fitz
from PIL import Image, ImageChops, ImageOps
from ocr import _ocr_lock, read_pages

VERSION='red-watermarks-v3'
LABEL=re.compile(r'watermark|\bib\s*papers\s*\.\s*info\b|ib\s*docs|ibdocuments|papacambridge|exam[ -]mate|thinkib|www\.[a-z]|https?://|t\.me/|not for (?:sale|distribution)|do not copy|confidential|draft|sample copy',re.I)
SVG='{http://www.w3.org/2000/svg}'
ET.register_namespace('',SVG[1:-1])
ET.register_namespace('xlink','http://www.w3.org/1999/xlink')


def red(color):
    if isinstance(color,int):color=((color>>16)&255,(color>>8)&255,color&255)
    elif max(color,default=0)<=1:color=tuple(round(c*255) for c in color[:3])
    return len(color)>=3 and color[0]>110 and color[0]>color[1]*1.4 and color[0]>color[2]*1.4


def is_label(text,hint=''):
    text=re.sub(r'\s+',' ',text)
    hint=re.sub(r'\s+',' ',hint)
    return bool(LABEL.search(text) or hint and hint.casefold() in text.casefold())


def native_targets(page,hint):
    targets=[]
    for block in page.get_text('rawdict',flags=fitz.TEXTFLAGS_RAWDICT & ~fitz.TEXT_PRESERVE_IMAGES)['blocks']:
        for line in block.get('lines',[]):
            spans=[s for s in line['spans'] if red(s['color'])]
            chars=[c for s in spans for c in s['chars']]
            text=''.join(c['c'] for c in chars).strip()
            box=fitz.Rect(line['bbox'])
            if text and is_label(text,hint):
                targets.append(dict(text=text,rect=list(box),chars=chars))
    return targets


def remove_svg_text(page,targets):
    """Remove only the watermark glyph objects, preserving text underneath.

    Glyph outlines avoid font substitution. No rectangle is painted over exam
    content; image pixels are never guessed or inpainted.
    """
    tree=ET.fromstring(page.get_svg_image(text_as_path=True))
    wanted=[c for t in targets for c in t['chars'] if not c['c'].isspace()]
    removed=set()
    for parent in tree.iter():
        for element in list(parent):
            if element.tag!=SVG+'use' or not element.get('data-text'):
                continue
            fill=element.get('fill','')
            if not re.fullmatch(r'#[0-9a-fA-F]{6}',fill) or not red(int(fill[1:],16)):
                continue
            matrix=re.fullmatch(r'matrix\(([^)]+)\)',element.get('transform',''))
            if not matrix:continue
            values=[float(v) for v in re.split(r'[,\s]+',matrix[1].strip())]
            if len(values)!=6:continue
            for index,char in enumerate(wanted):
                x,y=char['origin']
                if index not in removed and char['c']==element.get('data-text') and abs(x-values[4])<.3 and abs(y-values[5])<.3:
                    parent.remove(element);removed.add(index);break
    if len(removed)!=len(wanted):
        raise ValueError('Could not isolate every watermark glyph without touching question content.')
    # Whitespace glyphs have no ink, so leaving them is harmless.
    with fitz.open(stream=ET.tostring(tree),filetype='svg') as vector:
        return vector.convert_to_pdf()


def red_mask(page,area):
    pix=page.get_pixmap(matrix=fitz.Matrix(1,1),clip=area,alpha=False)
    image=Image.open(BytesIO(pix.tobytes('png'))).convert('RGB')
    r,g,b=image.split()
    mask=ImageChops.multiply(ImageChops.subtract(r,g).point(lambda x:255 if x>45 else 0),
                             ImageChops.subtract(r,b).point(lambda x:255 if x>45 else 0))
    mask=ImageChops.multiply(mask,r.point(lambda x:255 if x>110 else 0))
    return mask


def raster_label(mask,hint):
    if mask.histogram()[255]<50:return None
    # OCR sees red ink only. Handwriting/coloured diagrams are left untouched
    # unless an identifiable watermark label is actually recognized.
    for angle in (0,35,-35,45,-45):
        image=ImageOps.invert(mask).rotate(angle,expand=True,fillcolor=255)
        data=BytesIO();image.save(data,format='PNG')
        with fitz.open() as doc:
            page=doc.new_page(width=image.width,height=image.height)
            page.insert_image(page.rect,stream=data.getvalue())
            with _ocr_lock:
                tp=page.get_textpage_ocr(language='eng',dpi=150,full=True)
                text=page.get_text(textpage=tp)
        if is_label(text,hint):return text.strip()[:250]
    return None


def prepare(path,cache_dir,hint=''):
    """Return a read-only derivative path and cached page-local cleanup report."""
    path=Path(path);cache_dir=Path(cache_dir);cache_dir.mkdir(parents=True,exist_ok=True)
    with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    key=hashlib.sha256((VERSION+digest+hint).encode()).hexdigest()
    manifest=cache_dir/(key+'.json');output=cache_dir/(key+'.pdf')
    if manifest.is_file():
        try:
            result=json.loads(manifest.read_text())
            if not result.get('warnings') and (not result['cleaned_pages'] or output.is_file()):return output if result['cleaned_pages'] else path,result
        except (ValueError,KeyError,OSError):pass
    report=dict(version=VERSION,key=key,source_sha256=digest,hint=hint,cleaned_pages=[],outline_pages=[],removed_labels=[],rejected_regions=[],warnings=[])
    with fitz.open(path) as source,fitz.open() as cleaned:
        for index,page in enumerate(source):
            for annotation in list(page.annots() or []):
                label=annotation.info.get('content','')
                colored = any(red(c) for c in annotation.colors.values() if c)
                if annotation.type[1] in ('FreeText','Stamp','Watermark') and is_label(label,hint):
                    spans=[s for b in annotation.get_text('dict')['blocks'] for l in b.get('lines',[]) for s in l['spans']]
                    colored = colored or any(red(s['color']) for s in spans)
                if colored and annotation.type[1] in ('FreeText','Stamp','Watermark') and is_label(label,hint):
                    page.delete_annot(annotation)
                    if index not in report['cleaned_pages']:report['cleaned_pages'].append(index)
                    report['removed_labels'].append(label)
            targets=native_targets(page,hint)
            replacement=None
            if targets:
                try:
                    replacement=remove_svg_text(page,targets)
                    if index not in report['cleaned_pages']:report['cleaned_pages'].append(index)
                    report['outline_pages'].append(index)
                    report['removed_labels'].extend(t['text'] for t in targets)
                except (ValueError,RuntimeError,ET.ParseError,fitz.mupdf.FzErrorBase) as error:
                    report['rejected_regions'].extend(dict(page=index,rect=t['rect'],reason=str(error)) for t in targets)
            # Native red text has already been dealt with. Inspect embedded
            # images separately, so one raster watermark does not reject an
            # unrelated question elsewhere on the source page.
            areas=[fitz.Rect(i['bbox']) & page.rect for i in page.get_image_info()]
            if not areas and not targets and any(red(d.get('fill') or d.get('color') or ()) for d in page.get_drawings()):
                areas=[page.rect]  # Outlined stamps have no readable text layer.
            raster_source=fitz.open(stream=replacement,filetype='pdf') if replacement else None
            inspect_page=raster_source[0] if raster_source else page
            for area in areas:
                if area.is_empty:continue
                try:
                    text=raster_label(red_mask(inspect_page,area),hint)
                    if text:
                        report['rejected_regions'].append(dict(page=index,rect=list(area),reason='Watermark is flattened into image pixels; original covered content cannot be recovered safely.',label=text))
                except (RuntimeError,fitz.mupdf.FzErrorBase) as error:
                    report['warnings'].append(f'Page {index+1}: red-ink watermark OCR could not run: {str(error)[:100]}')
            if replacement:
                with fitz.open(stream=replacement,filetype='pdf') as fixed:cleaned.insert_pdf(fixed)
            else:cleaned.insert_pdf(source,from_page=index,to_page=index)
            if raster_source:raster_source.close()
        if report['cleaned_pages']:
            temporary=output.with_name(key+'.'+uuid.uuid4().hex+'.tmp.pdf');cleaned.save(temporary);temporary.replace(output)
    temporary=manifest.with_name(key+'.'+uuid.uuid4().hex+'.tmp.json');temporary.write_text(json.dumps(report));temporary.replace(manifest)
    return output if report['cleaned_pages'] else path,report


def rejected(regions,report):
    return any(a['page']==b['page'] and not (fitz.Rect(a['rect']) & fitz.Rect(b['rect'])).is_empty
               for a in regions for b in report.get('rejected_regions',[]))


def page_records(original,cleaned,report,mode,cache_dir):
    # SVG outlines preserve glyph appearance exactly. Restore the original
    # native text as analysis data, omitting only identified watermark glyphs;
    # this also preserves PDF-text-only imports without requiring OCR.
    with fitz.open(cleaned) as pdf:records,warnings=read_pages(pdf,mode,cache_dir)
    with fitz.open(original) as source:
        for index in report['cleaned_pages']:
            page=source[index]
            wanted={(round(c['origin'][0],2),round(c['origin'][1],2),c['c']) for t in native_targets(page,report['hint']) for c in t['chars']}
            lines=[]
            for block in page.get_text('rawdict',flags=fitz.TEXTFLAGS_RAWDICT & ~fitz.TEXT_PRESERVE_IMAGES)['blocks']:
                for line in block.get('lines',[]):
                    chars=[c for s in line['spans'] for c in s['chars'] if not (red(s['color']) and (round(c['origin'][0],2),round(c['origin'][1],2),c['c']) in wanted)]
                    if not chars:continue
                    box=fitz.Rect(chars[0]['bbox'])
                    for char in chars[1:]:box|=fitz.Rect(char['bbox'])
                    lines.append(dict(text=''.join(c['c'] for c in chars),bbox=list(box)))
            records[index]['native_lines']=lines
            records[index]['native']='\n'.join(l['text'] for l in lines)
    return records,warnings


def filter_analysis(result,report):
    removed=[q for q in result['questions'] if rejected(q['regions'],report)]
    result['questions']=[q for q in result['questions'] if not rejected(q['regions'],report)]
    result['watermark']=dict(report,rejected_questions=[q['number'] for q in removed])
    if report['cleaned_pages']:result['warnings'].append(f"Removed red text watermarks from {len(report['cleaned_pages'])} pages in a rendering copy.")
    if removed:result['warnings'].append(f"Excluded {len(removed)} question groups with watermarks that could not be removed safely.")
    result['warnings'].extend(report['warnings'])
    return result
