"""Single-user local question bank. Run with python app.py."""
import json
import hashlib
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from analysis_storage import rules_hash, source_hash, text_fingerprint, question_fingerprint
from io import BytesIO
from pathlib import Path

import fitz
from flask import Flask, jsonify, render_template, request, send_file

from physics import TOPICS, choose_questions, extract, render_question, validate_regions, suggest, custom_tags, HL_ONLY_TOPICS, validate_level_topics, document_metadata
from ocr import region_text
from paper_types import PAPERS, matches_paper
from language_review import review_disagreement, context_hash, status as model_status
from subquestions import propose_parts, question_hash, validate_layout, validate_graph, approved_map, short_variants, render_variant, choose_short
from dependency_review import analyze_dependencies
from topic_scope import scoped_question, topic_closure, POLICY
from paper_diagnostics import diagnose_selection, finish_diagnostics
from paper_cover import add_practice_cover, finalize_practice_cover
from paper_selection import question_variants, select_required
from paper_numbering import erase_source_numbers
from paper_layout import add_question_pages, PaperLayout, group_questions
from model_backfill import ModelBackfill
from year_filter import year_range, matches_year
from assessment_timing import estimate as time_estimate, refresh as refresh_timing, PROFILES as TIME_PROFILES, SOURCE as TIMING_SOURCE
from level_filter import normalize_mode, sl_mode, exclusion as level_exclusion, suitability, LABELS as LEVEL_LABELS
from watermarks import prepare as prepare_watermarks, filter_analysis as filter_watermarks, rejected as watermark_rejected, page_records as watermark_records
from upload_filter import markscheme_name, markscheme_heading


def create_app(data_dir=None):
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = 40 * 1024 * 1024
    root = Path(data_dir or os.environ.get('QUESTION_BANK_DATA', Path(__file__).parent / 'instance')).resolve()
    root.mkdir(parents=True, exist_ok=True)
    for folder in ('documents', 'images', 'papers'):
        (root / folder).mkdir(exist_ok=True)

    @app.get('/api/health')
    def health():
        return jsonify(service='ibdp-physics-question-bank', data_id=hashlib.sha256(str(root).encode()).hexdigest())

    def db():
        connection = sqlite3.connect(root / 'bank.sqlite3')
        connection.row_factory = sqlite3.Row
        return connection

    with db() as conn:
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS documents (id TEXT PRIMARY KEY, filename TEXT NOT NULL, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS questions (id TEXT PRIMARY KEY, document_id TEXT NOT NULL, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS papers (id TEXT PRIMARY KEY, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS source_fingerprints (sha256 TEXT PRIMARY KEY, document_id TEXT NOT NULL);
        ''')

    # Upgrade earlier local banks once; preserve all saved annotations.
    def upgrade_unknown_paper(question, source_paper):
        if question.get('paper', 'Unknown') == 'Unknown' and source_paper == 'Paper 3':
            mapping = question.get('subquestions')
            current_map = mapping and mapping.get('source_hash') == question_hash(question)
            question['paper'] = 'Paper 3'
            if current_map:
                mapping['source_hash'] = question_hash(question)

    with db() as conn:
        source_levels, source_papers = {}, {}
        for row in conn.execute('SELECT id,filename,data FROM documents').fetchall():
            value = json.loads(row['data'])
            metadata = value.setdefault('metadata', {})
            if metadata.get('paper', 'Unknown') == 'Unknown':
                text = '\n'.join(p.get('native') or p.get('text', '') for p in value.get('text_pages', [])[:4])
                if document_metadata(text, row['filename'])['paper'] == 'Paper 3':
                    metadata['paper'] = 'Paper 3'
            source_papers[row['id']] = metadata.get('paper', 'Unknown')
            source_levels[row['id']] = value.get('metadata', {}).get('level', 'Unknown')
            for candidate in value.get('questions', []):
                upgrade_unknown_paper(candidate, source_papers[row['id']])
                candidate['source_level'] = source_levels[row['id']]
                refresh_timing(candidate)
            conn.execute('UPDATE documents SET data=? WHERE id=?', (json.dumps(value), row['id']))
        for row in conn.execute('SELECT id FROM documents WHERE id NOT IN (SELECT document_id FROM source_fingerprints)').fetchall():
            path = root / 'documents' / (row['id'] + '.pdf')
            if path.is_file():
                conn.execute('INSERT OR IGNORE INTO source_fingerprints VALUES (?, ?)', (source_hash(path), row['id']))
        for row in conn.execute('SELECT id, document_id, data FROM questions').fetchall():
            value = json.loads(row['data'])
            upgrade_unknown_paper(value, source_papers.get(row['document_id']))
            original_level = source_levels.get(row['document_id'])
            value.setdefault('source_level', original_level if original_level in ('HL','SL') else value.get('level'))
            refresh_timing(value)
            image = root / 'images' / (row['id'] + '.png')
            if not value.get('content_hash') and image.is_file():
                value['content_hash'] = question_fingerprint(value['text'], image.read_bytes())
                value['text_hash'] = text_fingerprint(value['text'])
            conn.execute('UPDATE questions SET data=? WHERE id=?', (json.dumps(value), row['id']))

    def document(doc_id):
        with db() as conn:
            row = conn.execute('SELECT * FROM documents WHERE id=?', (doc_id,)).fetchone()
        if row is None:
            raise ValueError('Document not found.')
        return dict(id=row['id'], filename=row['filename'], **json.loads(row['data']))

    def source_path(doc_id):
        report = document(doc_id).get('watermark', {})
        if report.get('cleaned_pages'):
            path = root / 'watermarks' / (report['key'] + '.pdf')
            if not path.is_file():
                raise ValueError('Cleaned source is missing. Run Clean watermarks or restart to rebuild it from the original PDF.')
            return path
        return root / 'documents' / (doc_id + '.pdf')

    def analyze_pdf(path, filename, mode='auto', hint=''):
        if len(hint) > 150:
            raise ValueError('Watermark text must be at most 150 characters.')
        cleaned, report = prepare_watermarks(path, root / 'watermarks', hint)
        if report['cleaned_pages']:
            records, warnings = watermark_records(path, cleaned, report, mode, root / 'ocr-cache')
            result = extract(cleaned, filename, ocr_mode=mode, page_records=records)
            result['warnings'].extend(warnings)
        else:
            result = extract(cleaned, filename, ocr_mode=mode, ocr_cache=root / 'ocr-cache')
        return filter_watermarks(result, report)

    def questions():
        with db() as conn:
            return [dict(id=r['id'], document_id=r['document_id'], **json.loads(r['data']))
                    for r in conn.execute('SELECT * FROM questions ORDER BY rowid DESC')]

    def question_by_id(qid):
        q = next((q for q in questions() if q['id'] == qid), None)
        if q is None:
            raise ValueError('Question not found.')
        return q

    def save_question_data(q):
        with db() as conn:
            conn.execute('UPDATE questions SET data=? WHERE id=?',
                         (json.dumps({k: v for k, v in q.items() if k not in ('id', 'document_id')}), q['id']))

    def part_layout(q, supplied=None):
        doc = document(q['document_id'])
        if 'text_pages' not in doc:
            raise ValueError('Re-import this PDF with OCR before creating a subquestion layout.')
        mapping = q.get('subquestions')
        if not mapping or mapping.get('source_hash') != question_hash(q):
            mapping = propose_parts(q, doc['text_pages'])
        if not mapping:
            if supplied is None:
                raise ValueError('Could not safely identify at least two lettered subquestion groups. This question will remain whole.')
            mapping = dict(version=1, status='draft', source_hash=question_hash(q), parts=[], model_review=None)
        if supplied is not None:
            validate_layout(q, supplied)
            validate_graph(supplied)
            mapping = dict(mapping, parts=[dict(id=p['id'], label=p['label'], regions=p['regions'],
                                               requires=p['requires'], minutes=float(p['minutes']),
                                               topics=p.get('topics', []),
                                               text=region_text(doc['text_pages'], p['regions'])) for p in supplied])
        return doc, mapping

    def layout_hash(parts):
        import hashlib
        return hashlib.sha256(json.dumps([{k: p[k] for k in ('id', 'regions', 'text')} for p in parts], sort_keys=True).encode()).hexdigest()

    @app.get('/api/questions/<qid>/subquestions')
    def get_subquestions(qid):
        q = question_by_id(qid)
        doc, mapping = part_layout(q)
        return jsonify(mapping=mapping, question=q, pages=doc['pages'])

    @app.post('/api/questions/<qid>/subquestions/analyze')
    def analyze_subquestions(qid):
        q = question_by_id(qid)
        _, mapping = part_layout(q, (request.get_json() or {}).get('parts'))
        validate_layout(q, mapping['parts'])
        result = analyze_dependencies(mapping['parts'])
        q['subquestions'] = dict(mapping, status='draft', source_hash=question_hash(q), parts=result['parts'],
                                 model_review=result, analysis_hash=layout_hash(result['parts']))
        save_question_data(q)
        return jsonify(q['subquestions'])

    @app.post('/api/questions/<qid>/subquestions/approve')
    def approve_subquestions(qid):
        value = request.get_json() or {}
        if value.get('confirmed') is not True:
            raise ValueError('Confirm that shared context, boundaries, timing and dependencies have been reviewed.')
        q = question_by_id(qid)
        _, mapping = part_layout(q, value['parts'])
        validate_layout(q, mapping['parts'])
        validate_graph(mapping['parts'])
        for part in mapping['parts']:
            validate_level_topics(part.get('topics', []), q['level'])
        if mapping.get('analysis_hash') != layout_hash(mapping['parts']):
            mapping['model_review'] = None
        q['subquestions'] = dict(mapping, status='approved', approval_source='manual_review', source_hash=question_hash(q))
        save_question_data(q)
        return jsonify(q['subquestions'])

    def review_inputs(doc, regions, paper):
        if 'text_pages' in doc:
            native = region_text(doc['text_pages'], regions, 'native')
            ocr = region_text(doc['text_pages'], regions, 'ocr')
        else:
            native, ocr = '', ''
        pdf_topics, ocr_topics = suggest(native, paper)['topics'], suggest(ocr, paper)['topics']
        return native, ocr, paper, pdf_topics, ocr_topics

    def current_review(doc, q, review):
        if not review:
            return None
        args = review_inputs(doc, q['regions'], q['paper'])
        return review if review.get('input_hash') == context_hash(*args) else None

    @app.get('/api/model/status')
    def language_model_status():
        return jsonify(**model_status(), backfill=backfill.status())

    @app.before_request
    def resume_optional_model_checks():
        backfill.kick()

    @app.errorhandler(ValueError)
    @app.errorhandler(KeyError)
    @app.errorhandler(TypeError)
    def invalid(error):
        return jsonify(error=str(error)), 400

    @app.errorhandler(413)
    def too_large(error):
        return jsonify(error='PDF uploads must be smaller than 40 MB.'), 413

    @app.after_request
    def secure(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; object-src 'none'; frame-ancestors 'none'"
        if request.method == 'POST' and response.status_code < 400:
            backfill.kick(force=True)
        return response

    @app.get('/')
    def index():
        return render_template('index.html')

    @app.get('/api/catalog')
    def catalog():
        return jsonify(topics=TOPICS, hl_only_topics=sorted(HL_ONLY_TOPICS), prerequisite_policy=POLICY,
                       level_modes=LEVEL_LABELS, timing_source=TIMING_SOURCE,
                       timing_profiles=[dict(syllabus=s,level=l,paper=p,minutes=m,marks=k,minutes_per_mark=m/k) for (s,l,p),(m,k) in TIME_PROFILES.items()])

    @app.get('/api/documents')
    def documents():
        with db() as conn:
            return jsonify([dict(id=r['id'], filename=r['filename']) for r in conn.execute('SELECT id, filename FROM documents ORDER BY rowid DESC')])

    @app.post('/api/documents')
    def upload():
        uploaded = request.files.get('file')
        if not uploaded or not uploaded.filename.lower().endswith('.pdf'):
            raise ValueError('Choose a PDF file.')
        def skipped_markscheme():
            return jsonify(status='skipped', reason='markscheme', filename=Path(uploaded.filename).name,
                           message='Ignored markscheme; no questions were imported.'), 200
        if markscheme_name(uploaded.filename) or markscheme_name(request.form.get('relative_path', '')):
            return skipped_markscheme()
        doc_id = uuid.uuid4().hex
        path = root / 'documents' / (doc_id + '.pdf')
        uploaded.save(path)
        try:
            with fitz.open(path) as pdf:
                is_markscheme = any(markscheme_heading(pdf[i].get_text()) for i in range(min(4, len(pdf))))
            if is_markscheme:
                path.unlink(missing_ok=True)
                return skipped_markscheme()
            digest = source_hash(path)
            with db() as conn:
                prior = conn.execute('SELECT d.id FROM source_fingerprints f JOIN documents d ON d.id=f.document_id WHERE f.sha256=?', (digest,)).fetchone()
            if prior and not document(prior['id']).get('text_pages'):
                prior = None  # Upgrade legacy imports that never stored page data.
            if prior:
                existing_path = root / 'documents' / (prior['id'] + '.pdf')
                if existing_path.is_file():
                    path.unlink()
                else:
                    path.replace(existing_path)
                response = document(prior['id'])
                if request.form.get('watermark_text', '').strip():
                    clean_document_watermarks(prior['id'], request.form['watermark_text'].strip())
                    response = document(prior['id'])
                if any(markscheme_heading(r.get('text', '')) or markscheme_heading(r.get('native', '')) for r in response.get('text_pages', [])[:4]):
                    return skipped_markscheme()
                response['duplicate_document'] = True
                response['message'] = 'This PDF was already analyzed. Reused the saved page data and analysis.'
                if request.form.get('auto_import') == '1':
                    response.setdefault('analysis', {})['auto_import'] = True
                    with db() as conn:
                        conn.execute('UPDATE documents SET data=? WHERE id=?',
                                     (json.dumps({k: v for k, v in response.items() if k not in ('id', 'filename', 'duplicate_document', 'message')}), prior['id']))
                    response['import_result'] = import_document_questions(prior['id'])
                return jsonify(response), 200
            result = analyze_pdf(path, uploaded.filename, request.form.get('ocr_mode', 'auto'), request.form.get('watermark_text', '').strip())
        except Exception as error:
            path.unlink(missing_ok=True)
            raise ValueError('Could not read PDF: ' + str(error)) from error
        if any(markscheme_heading(page.get('text', '')) or markscheme_heading(page.get('native', ''))
               for page in result.get('text_pages', [])[:4]):
            path.unlink(missing_ok=True)
            return skipped_markscheme()
        pending = [q for q in result['questions'] if q.get('ocr_comparison', {}).get('status') == 'disagreement']
        result['analysis'] = dict(version=1, rules_hash=rules_hash(), source_sha256=digest, status='complete', completed_at=datetime.now(timezone.utc).isoformat(),
                                  ocr_mode=request.form.get('ocr_mode', 'auto'), auto_import=request.form.get('auto_import') == '1',
                                  language_review_status='pending' if pending else 'complete')
        # Commit extracted text, boundaries and tags before potentially slow model calls.
        with db() as conn:
            conn.execute('INSERT INTO documents VALUES (?, ?, ?)', (doc_id, Path(uploaded.filename).name, json.dumps(result)))
            conn.execute('INSERT INTO source_fingerprints VALUES (?, ?) ON CONFLICT(sha256) DO UPDATE SET document_id=excluded.document_id', (digest, doc_id))
        for index, q in enumerate(pending):
            args = review_inputs(result, q['regions'], q['paper'])
            try:
                q['language_review'] = review_disagreement(*args, TOPICS, cache_dir=root / 'language-reviews')
            except Exception as error:
                q['language_review'] = dict(status='needs_review', input_hash=context_hash(*args),
                                            reason='Optional model review failed: ' + str(error)[:250],
                                            topics=[], evidence=[])
            if index == len(pending) - 1:
                result['analysis']['language_review_status'] = 'complete'
            with db() as conn:
                conn.execute('UPDATE documents SET data=? WHERE id=?', (json.dumps(result), doc_id))
        response = document(doc_id)
        if request.form.get('auto_import') == '1':
            response['import_result'] = import_document_questions(doc_id)
        return jsonify(response), 201

    @app.get('/api/documents/<doc_id>')
    def get_document(doc_id):
        result = document(doc_id)
        saved = {q['number']: q for q in questions() if q['document_id'] == doc_id}
        suggested = {q['number']: q for q in result['questions']}
        reviews = {q['number']: q.get('language_review') for q in result['questions']}
        suggested.update(saved)
        for number, q in suggested.items():
            if 'commands' not in q or 'tags' not in q:
                defaults = suggest(q.get('text', ''), q.get('paper'))
                q.setdefault('commands', defaults['commands'])
                q.setdefault('tags', defaults['tags'])
            q['language_review'] = (current_review(result, q, q.get('language_review'))
                                    or current_review(result, q, reviews.get(number)))
        result['questions'] = [suggested[n] for n in sorted(suggested)]
        result['saved_numbers'] = list(saved)
        result['rules_changed'] = result.get('analysis', {}).get('rules_hash') != rules_hash()
        return jsonify(result)

    @app.post('/api/documents/<doc_id>/reanalyse')
    def reanalyse_document(doc_id):
        old = document(doc_id)
        if not old.get('text_pages'):
            raise ValueError('This import has no saved OCR/page data. Upload it once to store page data before reanalysis.')
        path = source_path(doc_id)
        mode = old.get('analysis', {}).get('ocr_mode', 'auto')
        result = extract(path, old['filename'], ocr_mode=mode, page_records=old['text_pages'])
        if old.get('watermark'):
            filter_watermarks(result, old['watermark'])
        previous = {q['number']: q for q in old['questions']}
        for candidate in result['questions']:
            prior = previous.get(candidate['number'], {}).get('language_review')
            candidate['language_review'] = current_review(result, candidate, prior)
        result['analysis'] = dict(version=1, rules_hash=rules_hash(), source_sha256=source_hash(root / 'documents' / (doc_id + '.pdf')), status='complete',
                                  completed_at=datetime.now(timezone.utc).isoformat(), ocr_mode=mode,
                                  language_review_status='not_rerun', reused_page_data=True, auto_import=old.get('analysis', {}).get('auto_import', False))
        with db() as conn:
            conn.execute('UPDATE documents SET data=? WHERE id=?', (json.dumps(result), doc_id))
        existing = {q['number']: q for q in questions() if q['document_id'] == doc_id}
        updated, added, preserved, failed, duplicates = [], [], [], [], []
        for candidate in result['questions']:
            saved = existing.get(candidate['number'])
            if not saved and not result['analysis']['auto_import']:
                continue
            if saved and saved.get('review_status') != 'imported':
                preserved.append(saved['id'])
                continue
            try:
                outcome = persist_question(dict(candidate, document_id=doc_id), imported=True)
                if outcome.get('duplicate'):
                    duplicates.append(candidate['number'])
                else:
                    (updated if saved else added).append(outcome['id'])
            except (ValueError, KeyError, TypeError) as error:
                failed.append(dict(number=candidate['number'], error=str(error)))
        detected_numbers = {q['number'] for q in result['questions']}
        outdated = []
        for number, saved in existing.items():
            if number not in detected_numbers and saved.get('review_status') == 'imported':
                saved['analysis_outdated'] = True
                save_question_data(saved)
                outdated.append(number)
        return jsonify(document_id=doc_id, questions=len(result['questions']), updated_question_ids=updated, new_question_ids=added,
                       duplicate_numbers=duplicates, outdated_numbers=outdated,
                       preserved_reviewed_ids=preserved, failed=failed, reused_page_data=True)

    @app.post('/api/documents/<doc_id>/questions/<int:number>/language-review')
    def resolve_language_disagreement(doc_id, number):
        doc = document(doc_id)
        candidate = next((q for q in doc['questions'] if q['number'] == number), None)
        if candidate is None:
            candidate = next((q for q in questions() if q['document_id'] == doc_id and q['number'] == number), None)
            if candidate is None:
                raise ValueError('Save the question before requesting language review.')
            doc['questions'].append(candidate)
        value = request.get_json() or {}
        paper = value.get('paper', candidate['paper'])
        if paper not in PAPERS:
            raise ValueError('Choose a paper type before language review.')
        with fitz.open(source_path(doc_id)) as pdf:
            regions = validate_regions(pdf, value.get('regions', candidate['regions']))
        result = review_disagreement(*review_inputs(doc, regions, paper), TOPICS,
                                     cache_dir=root / 'language-reviews')
        candidate['language_review'] = result
        with db() as conn:
            conn.execute('UPDATE documents SET data=? WHERE id=?',
                         (json.dumps({k: v for k, v in doc.items() if k not in ('id', 'filename')}), doc_id))
        # Proposals do not change saved tags. Explicit review/save keeps the user in control.
        return jsonify(result)

    @app.get('/api/documents/<doc_id>/pages/<int:page>')
    def page_image(doc_id, page):
        document(doc_id)
        with fitz.open(source_path(doc_id)) as pdf:
            if page >= len(pdf):
                raise ValueError('Page not found.')
            pix = pdf[page].get_pixmap(matrix=fitz.Matrix(1.4, 1.4), alpha=False)
        return send_file(BytesIO(pix.tobytes('png')), mimetype='image/png')

    def persist_question(value, imported=False):
        doc = document(value['document_id'])
        number = int(value['number'])
        if not 1 <= number <= 999:
            raise ValueError('Question number must be between 1 and 999.')
        level, syllabus = value.get('level'), value.get('syllabus')
        if level not in (('HL', 'SL', 'Both', 'Unknown') if imported else ('HL', 'SL', 'Both')) or syllabus not in (('2025', 'Legacy', 'Unknown') if imported else ('2025', 'Legacy')):
            raise ValueError('Select the level and syllabus before saving.')
        paper = value.get('paper')
        if paper not in ((*PAPERS, 'Unknown') if imported else PAPERS):
            raise ValueError('Select a valid paper.')
        topics = value.get('topics', [])
        if not isinstance(topics, list) or any(t not in TOPICS for t in topics):
            raise ValueError('Select valid syllabus topics.')
        validate_level_topics(topics, level)
        if not topics and not imported:
            raise ValueError('Select at least one topic.')
        minutes = float(value['minutes'])
        if not 0 < minutes <= 300:
            raise ValueError('Estimated time must be between 0 and 300 minutes.')
        difficulty = value.get('difficulty', 'Unrated')
        if difficulty not in ('Unrated', 'Easy', 'Medium', 'Hard'):
            raise ValueError('Invalid difficulty.')
        year = None if imported and value.get('year') is None else int(value['year'])
        if year is not None and not 1970 <= year <= 2100:
            raise ValueError('Enter a valid paper year.')
        marks = int(value['marks']) if value.get('marks') not in (None, '') else None
        if marks is not None and not 1 <= marks <= 200:
            raise ValueError('Marks must be between 1 and 200.')
        with fitz.open(source_path(doc['id'])) as pdf:
            regions = validate_regions(pdf, value['regions'])
            if watermark_rejected(regions, doc.get('watermark', {})):
                raise ValueError('This question contains a watermark that cannot be removed safely and cannot be added to the bank.')
            png = render_question(pdf, regions)
            text = (region_text(doc['text_pages'], regions) if 'text_pages' in doc
                    else '\n'.join(pdf[r['page']].get_text(clip=fitz.Rect(r['rect'])) for r in regions))
        suggestions = suggest(text, paper, level,syllabus)
        tags = value.get('tags', custom_tags(text, topics))
        commands = value.get('commands', suggestions['commands'])
        if any(not isinstance(items, list) or len(items) > 50 or any(not isinstance(s, str) or len(s) > 100 for s in items) for items in (tags, commands)):
            raise ValueError('Tags and command terms must be lists of short text values.')
        ocr_text = region_text(doc['text_pages'], regions, 'ocr') if 'text_pages' in doc else ''
        ocr_topics = suggest(ocr_text, paper)['topics'] if ocr_text.strip() else []
        native_present = any(len(doc.get('text_pages', [])[r['page']]['native'].strip()) >= 50 for r in regions) if 'text_pages' in doc else True
        comparison = dict(status=('agreement' if set(suggestions['topics']) == set(ocr_topics) else 'disagreement') if ocr_text.strip() and native_present else 'ocr_only' if ocr_text.strip() else 'not_run', topics=ocr_topics)
        prior = next((q.get('language_review') for q in doc['questions'] if q['number'] == number), None)
        language_result = current_review(doc, dict(regions=regions, paper=paper), prior)
        saved = dict(number=number, year=year, level=level, syllabus=syllabus, paper=paper,
                     topics=topics, minutes=minutes, difficulty=difficulty, marks=marks,
                     tags=tags, commands=commands, regions=regions, text=text,
                     filename=doc['filename'], topic_evidence=suggestions['topic_evidence'],
                     ocr_comparison=comparison, level_conflicts=suggestions['level_conflicts'], review_status='imported' if imported else 'reviewed', language_review=language_result)
        original_level = doc.get('metadata', {}).get('level')
        saved['source_level'] = original_level if original_level in ('HL','SL') else level
        saved['watermark_key'] = doc.get('watermark', {}).get('key')
        sl_suitability = value.get('sl_suitability', 'automatic')
        if sl_suitability not in ('automatic','sl_suitable','hl_only','needs_review'):
            raise ValueError('Choose a valid SL suitability decision.')
        saved['sl_suitability'] = sl_suitability
        if sl_suitability == 'sl_suitable' and suitability(saved)['status']=='hl_only':
            raise ValueError('HL-only content was detected. Review the crops and tags before confirming SL suitability.')
        baseline = time_estimate(marks,paper,saved['source_level'],syllabus)
        saved['timing'] = dict(baseline,mode='automatic' if abs(minutes-baseline['minutes'])<.001 else 'manual')
        content_hash = question_fingerprint(text, png)
        saved['content_hash'], saved['text_hash'] = content_hash, text_fingerprint(text)
        duplicate = next((q for q in questions() if q.get('content_hash') == content_hash
                          and (q['document_id'], q['number']) != (doc['id'], number)), None)
        if duplicate:
            if imported:
                return dict(duplicate, duplicate=True)
            raise ValueError(f"This question already exists in the bank: {duplicate['filename']} Q{duplicate['number']}.")
        saved['possible_duplicate_ids'] = [q['id'] for q in questions()
                                           if (q['document_id'], q['number']) != (doc['id'], number) and q.get('text_hash') == saved['text_hash'] and q.get('content_hash') != content_hash
                                           and len(text.strip()) >= 80]
        with db() as conn:
            existing = next((q for q in questions() if q['document_id'] == doc['id'] and q['number'] == number), None)
            prior_map = existing.get('subquestions') if existing else None
            saved['subquestions'] = prior_map if prior_map and prior_map.get('source_hash') == question_hash(saved) else None
            qid = existing['id'] if existing else uuid.uuid4().hex
            (root / 'images' / (qid + '.png')).write_bytes(png)
            conn.execute('INSERT OR REPLACE INTO questions VALUES (?, ?, ?)', (qid, doc['id'], json.dumps(saved)))
        return dict(id=qid, **saved)

    @app.post('/api/documents/<doc_id>/suggest-tags')
    def suggest_question_tags(doc_id):
        doc = document(doc_id)
        value = request.get_json() or {}
        paper = value.get('paper', 'Unknown')
        if paper not in ('Unknown', *PAPERS):
            raise ValueError('Choose a valid paper type.')
        with fitz.open(source_path(doc_id)) as pdf:
            regions = validate_regions(pdf, value['regions'])
            text = (region_text(doc['text_pages'], regions) if 'text_pages' in doc else
                    '\n'.join(pdf[r['page']].get_text(clip=fitz.Rect(r['rect'])) for r in regions))
        suggestions = suggest(text, paper)
        topics = value.get('topics', suggestions['topics'])
        if not isinstance(topics, list) or any(code not in TOPICS for code in topics):
            raise ValueError('Select valid syllabus topics.')
        validate_level_topics(topics, value.get('level', doc['metadata'].get('level')))
        return jsonify(commands=suggestions['commands'], tags=custom_tags(text, topics))

    @app.post('/api/questions')
    def save_question():
        return jsonify(persist_question(request.get_json())), 201

    def import_document_questions(doc_id):
        doc = document(doc_id)
        existing = {q['number'] for q in questions() if q['document_id'] == doc_id}
        added, skipped, failed, duplicates = [], [], [], []
        for candidate in doc['questions']:
            number = candidate['number']
            if number in existing:
                skipped.append(number)
                continue
            try:
                saved = persist_question(dict(candidate, document_id=doc_id), imported=True)
            except (ValueError, KeyError, TypeError) as error:
                failed.append(dict(number=number, error=str(error)))
                continue
            existing.add(number)
            if saved.get('duplicate'):
                skipped.append(number)
                duplicates.append(dict(number=number, existing_question_id=saved['id'], filename=saved['filename']))
            else:
                added.append(saved['id'])
        return dict(document_id=doc_id, imported=len(added), question_ids=added,
                    skipped_numbers=skipped, failed=failed, duplicate_questions=duplicates)

    @app.post('/api/documents/<doc_id>/confirm-import')
    def confirm_import(doc_id):
        return jsonify(import_document_questions(doc_id))

    @app.get('/api/questions')
    def search():
        items = questions()
        mode = normalize_mode(request.args.get('level'))
        lower, upper = year_range(request.args)
        items = [q for q in items if matches_year(q.get('year'), lower, upper)]
        for field in ('syllabus', 'difficulty'):
            term = request.args.get(field)
            if term:
                items = [q for q in items if str(q[field]) == term or (field == 'level' and q[field] == 'Both')]
        items = [q for q in items if matches_paper(q['paper'], request.args.get('paper'))]
        topics = [t for t in request.args.getlist('topic') if t]
        if sl_mode(mode):
            validate_level_topics(topics, 'SL')
        items = [q for q in items if level_exclusion(q,mode) is None]
        for q in items:
            q['sl_content'] = suitability(q)
        if topics:
            topic_closure(topics)
            items = [variant for q in items if (variant := scoped_question(q, topics)) is not None]
        query = request.args.get('q', '').strip().lower()
        if query:
            items = [q for q in items if query in ' '.join([q['text'], *q['tags'], *q['commands'], *q['topics'], q['filename']]).lower()]
        return jsonify(items)

    @app.post('/api/documents/<doc_id>/preview')
    def preview(doc_id):
        document(doc_id)
        with fitz.open(source_path(doc_id)) as pdf:
            regions = validate_regions(pdf, request.get_json()['regions'])
            png = render_question(pdf, regions)
        return send_file(BytesIO(png), mimetype='image/png')

    @app.get('/api/questions/<qid>/image')
    def image(qid):
        q = question_by_id(qid)
        mode = request.args.get('mode', 'full')
        if mode not in ('full', 'short'):
            raise ValueError('Render mode must be full or short.')
        topics = [t for t in request.args.getlist('topic') if t]
        scoped = scoped_question(q, topics)
        if scoped is None:
            raise ValueError('This question requires content outside the requested topic scope.')
        if mode == 'short' or scoped.get('omitted_parts'):
            if mode == 'short' and 'omit' in request.args:
                variant = render_variant(q, set(request.args.getlist('omit')) | set(scoped.get('omitted_parts', [])))
                if topics and approved_map(q) and not any(p['id'] in variant['kept_parts'] and set(p.get('topics', [])) & set(topics)
                                                         for p in q['subquestions']['parts']):
                    raise ValueError('Keep at least one part that assesses a selected target topic.')
            else:
                variant = short_variants(q, scoped.get('omitted_parts', []), topics)[0] if mode == 'short' else scoped
            with fitz.open(source_path(q['document_id'])) as pdf:
                png = render_question(pdf, variant['regions'])
            return send_file(BytesIO(png), mimetype='image/png')
        return send_file(root / 'images' / (qid + '.png'), mimetype='image/png')

    @app.post('/api/questions/<qid>/render')
    def render_subquestions(qid):
        q = question_by_id(qid)
        value = request.get_json() or {}
        mode = value.get('mode', 'full')
        if mode not in ('full', 'short'):
            raise ValueError('Render mode must be full or short.')
        if mode == 'full' and value.get('omitted_parts'):
            raise ValueError('Full mode preserves every part. Choose Short to omit parts.')
        omitted = value.get('omitted_parts')
        if omitted is not None and (not isinstance(omitted, list) or any(not isinstance(p, str) for p in omitted)):
            raise ValueError('Omitted parts must be a list of part IDs.')
        topics = value.get('topics', [])
        topic_closure(topics)
        scoped = scoped_question(q, topics)
        if scoped is None:
            raise ValueError('This question needs content outside the selected topic scope.')
        forced = scoped.get('omitted_parts', [])
        variant = (render_variant(q, set(omitted) | set(forced)) if omitted is not None else short_variants(q, forced, topics)[0]) if mode == 'short' else scoped
        if topics and approved_map(q):
            parts = q['subquestions']['parts']
            if not any(p['id'] in variant['kept_parts'] and set(p.get('topics', [])) & set(topics) for p in parts):
                raise ValueError('Keep at least one part that assesses a selected target topic.')
        with fitz.open(source_path(q['document_id'])) as pdf:
            png = render_question(pdf, variant['regions'])
        return send_file(BytesIO(png), mimetype='image/png')

    def paper_pool(value):
        lower, upper = year_range(value)
        target = float(value['minutes'])
        mode = value.get('render_mode', 'full')
        if mode not in ('full', 'short'):
            raise ValueError('Render mode must be full or short.')
        if not 1 <= target <= 300:
            raise ValueError('Choose a duration between 1 and 300 minutes.')
        level, syllabus = normalize_mode(value.get('level')), value.get('syllabus', '2025')
        if syllabus not in ('2025', 'Legacy'):
            raise ValueError('Choose a syllabus.')
        selected_topics = value.get('topics', [])
        if not isinstance(selected_topics, list) or any(t not in TOPICS for t in selected_topics):
            raise ValueError('Invalid topics.')
        validate_level_topics(selected_topics, 'SL' if sl_mode(level) else 'HL')
        topic_closure(selected_topics)
        with db() as conn:
            analyzed = [dict(id=r['id'], questions=json.loads(r['questions'] or '[]')) for r in
                        conn.execute("SELECT id, json_extract(data, '$.questions') AS questions FROM documents")]
        source_ids = {d['id'] for d in analyzed if (root / 'documents' / (d['id'] + '.pdf')).is_file()}
        document_ids = value.get('document_ids', [])
        if not isinstance(document_ids, list) or any(not isinstance(i, str) for i in document_ids):
            raise ValueError('Source papers must be a list of document IDs.')
        if set(document_ids) - {d['id'] for d in analyzed}:
            raise ValueError('Some selected source papers no longer exist. Refresh the question list.')
        eligible, diagnostics = diagnose_selection(questions(), analyzed, level=level, syllabus=syllabus,
                                                   paper=value.get('paper'), topics=selected_topics, mode=mode,
                                                   target=target, source_ids=source_ids, document_ids=document_ids,
                                                   year_min=lower, year_max=upper)
        return eligible, diagnostics

    def automatic_choice(eligible, target, topics, mode):
        if mode == 'short':
            return choose_short(eligible, target, topics)
        scoped = [variant for q in eligible if (variant := scoped_question(q, topics)) is not None]
        ids = choose_questions(scoped, target)
        return [q for q in scoped if q['id'] in ids]

    def planned_questions(eligible, config, value):
        """One selection algorithm shared by editable plans and PDF output."""
        target, selected_topics, mode = (config[key] for key in ('minutes', 'topics', 'render_mode'))
        requested_ids = value.get('question_ids')
        fill = value.get('fill_paper', False)
        if not isinstance(fill, bool):
            raise ValueError('Fill paper must be true or false.')
        filled_ids = []
        if requested_ids is not None:
            if not isinstance(requested_ids, list) or (not requested_ids and not fill) or any(not isinstance(i, str) for i in requested_ids) or len(set(requested_ids)) != len(requested_ids):
                raise ValueError('Select at least one unique question, or use automatic selection.')
            by_id = {q['id']: q for q in eligible}
            if set(requested_ids) - set(by_id):
                return [], [], 'Some selected questions no longer fit these filters or duration. Refresh the matching questions.'
            required = [by_id[i] for i in requested_ids]
            chosen = select_required(required, target, selected_topics, mode)
            if required and not chosen:
                minimum = sum(min(v['minutes'] for v in question_variants(q, selected_topics, mode)) for q in required)
                return [], [], f'The selected {len(required)} questions need at least {minimum:g} estimated minutes; the budget is {target:g}. Increase the budget or deselect questions.'
            if fill:
                remaining = round(target - sum(q['minutes'] for q in chosen), 6)
                extras = automatic_choice([q for q in eligible if q['id'] not in set(requested_ids)], remaining, selected_topics, mode)
                filled_ids = [q['id'] for q in extras]
                chosen.extend(extras)
        else:
            chosen = automatic_choice(eligible, target, selected_topics, mode)
        chosen = group_questions(chosen)
        return chosen, filled_ids, None

    @app.post('/api/papers/preview')
    def preview_paper_selection():
        value = request.get_json()
        eligible, diagnostics = paper_pool(value)
        config = diagnostics['requested']
        auto_select = value.get('auto_select', False)
        if not isinstance(auto_select, bool):
            raise ValueError('Auto-select must be true or false.')
        chosen, filled_ids = [], []
        if auto_select:
            chosen, filled_ids, error = planned_questions(eligible, config, value)
            if error or not chosen:
                return jsonify(error=error or diagnostics['summary'], diagnostics=diagnostics), 400
        selected = {q['id']: q for q in chosen}
        candidates = []
        page_data = {}
        for q in eligible:
            variants = question_variants(q, config['topics'], config['render_mode'])
            if q['document_id'] not in page_data:
                page_data[q['document_id']] = document(q['document_id']).get('text_pages', [])
            records = page_data[q['document_id']]
            preferred = selected.get(q['id'], variants[0])
            # Prefer saved OCR for each crop, falling back to extracted PDF text
            # on pages where OCR was unnecessary. Match the preview's variant.
            text = '\n'.join(region_text(records, [r], 'ocr' if records[r['page']].get('lines') else 'selected')
                             for r in preferred['regions']) if records else q.get('text', '')
            candidates.append(dict(id=q['id'], document_id=q['document_id'], number=q['number'],
                                   filename=q['filename'], topics=scoped_question(q, config['topics'])['topics'],
                                   text=text,
                                   preferred_minutes=preferred['minutes'], minimum_minutes=min(v['minutes'] for v in variants),
                                   omitted_parts=preferred['omitted_parts']))
        return jsonify(questions=candidates, diagnostics=diagnostics,
                       selected_question_ids=[q['id'] for q in chosen], filled_question_ids=filled_ids,
                       estimated_minutes=round(sum(q['minutes'] for q in chosen), 1))

    @app.post('/api/papers')
    def generate():
        value = request.get_json()
        eligible, diagnostics = paper_pool(value)
        config = diagnostics['requested']
        target, mode, level, syllabus, selected_topics = (config[key] for key in ('minutes', 'render_mode', 'level', 'syllabus', 'topics'))
        requested_ids, fill = value.get('question_ids'), value.get('fill_paper', False)
        chosen, filled_ids, error = planned_questions(eligible, config, value)
        if error:
            return jsonify(error=error, diagnostics=diagnostics), 400
        ids = [q['id'] for q in chosen]
        if not chosen:
            return jsonify(error=diagnostics['summary'], diagnostics=diagnostics), 400
        paper_id = uuid.uuid4().hex
        actual = round(sum(q['minutes'] for q in chosen), 1)
        numbering_cache, numbering_results = {}, {}
        original_questions = {q['id']: q for q in questions()}
        with fitz.open() as pdf:
            add_practice_cover(pdf, level=level, syllabus=syllabus, target=target, chosen=chosen, mode=mode, topics=selected_topics)
            layout = PaperLayout(pdf)
            for i, q in enumerate(chosen, 1):
                # Keep every crop of the parent together and in source order.
                with fitz.open(source_path(q['document_id'])) as source:
                    outline_pages = document(q['document_id']).get('watermark', {}).get('outline_pages', [])
                    numbering_results[q['id']] = erase_source_numbers(source, original_questions[q['id']], numbering_cache, outline_pages=outline_pages)
                    rendered = add_question_pages(pdf, source, q, i, layout=layout)
                    numbering_results[q['id']]['rendered_pages'] = rendered
                    if not rendered:
                        raise ValueError(f"Question {q['number']} in {q['filename']} has no visible content after cleanup. Review its crop before generating a paper.")
            finalize_practice_cover(pdf)
            pdf.save(root / 'papers' / (paper_id + '.pdf'))
        completed_diagnostics = finish_diagnostics(diagnostics, chosen, target)
        if requested_ids is not None and not fill and actual < target:
            completed_diagnostics['summary'] = f'Your selected questions provide {actual:g} estimated minutes, leaving {target - actual:g} minutes. Enable Fill paper to add other matching questions.'
        result = dict(id=paper_id, question_ids=list(ids), target_minutes=target, actual_minutes=actual,
                      shortfall_minutes=round(target - actual, 1), count=len(chosen), render_mode=mode,
                      diagnostics=completed_diagnostics,
                      selection_mode='manual' if requested_ids is not None else 'automatic',
                      requested_question_ids=requested_ids or [], filled_question_ids=filled_ids,
                      numbering=numbering_results,
                      selections=[dict(question_id=q['id'], number=i, source_number=q['number'], selection_source='filled' if q['id'] in filled_ids else 'teacher' if requested_ids is not None else 'automatic', kept_parts=q['kept_parts'], omitted_parts=q['omitted_parts'],
                                       topic_omitted_parts=q.get('topic_omitted_parts', []),
                                       topics=q['topics'],
                                       estimated_minutes=round(q['minutes'], 2), render_mode=q['render_mode']) for i, q in enumerate(chosen, 1)],
                      topic_scope=dict(requested=selected_topics, allowed=sorted(topic_closure(selected_topics)), policy_version=POLICY['version']),
                      short_fallbacks=[q['id'] for q in chosen if mode == 'short' and not q['dependency_approved']])
        with db() as conn:
            conn.execute('INSERT INTO papers VALUES (?, ?)', (paper_id, json.dumps(result)))
        return jsonify(result), 201

    @app.get('/api/papers/<paper_id>/download')
    def download(paper_id):
        with db() as conn:
            if not conn.execute('SELECT id FROM papers WHERE id=?', (paper_id,)).fetchone():
                raise ValueError('Paper not found.')
        return send_file(root / 'papers' / (paper_id + '.pdf'), as_attachment=True, download_name='physics-practice-paper.pdf')

    def clean_document_watermarks(doc_id, hint=None):
        doc = document(doc_id)
        original = root / 'documents' / (doc_id + '.pdf')
        if not original.is_file():
            return dict(document_id=doc_id, deleted_question_ids=[], updated_question_ids=[], skipped=True)
        hint = doc.get('watermark', {}).get('hint', '') if hint is None else hint
        if not isinstance(hint, str) or len(hint) > 150:
            raise ValueError('Watermark text must be at most 150 characters.')
        cleaned, report = prepare_watermarks(original, root / 'watermarks', hint)
        previous = doc.get('watermark', {})
        report_changed = any(previous.get(field) != report.get(field) for field in
                             ('key', 'cleaned_pages', 'outline_pages', 'removed_labels', 'rejected_regions', 'warnings'))
        if report_changed:
            if report['cleaned_pages']:
                result = analyze_pdf(original, doc['filename'], doc.get('analysis', {}).get('ocr_mode', 'auto'), hint)
                result['analysis'] = doc.get('analysis', {})
            else:
                result = {k: v for k, v in doc.items() if k not in ('id', 'filename')}
                filter_watermarks(result, report)
            if previous.get('deleted_question_ids'):
                result['watermark']['deleted_question_ids'] = previous['deleted_question_ids']
            with db() as conn:
                conn.execute('UPDATE documents SET data=? WHERE id=?', (json.dumps(result), doc_id))
        deleted, updated = [], []
        with db() as conn:
            rows = conn.execute('SELECT id,data FROM questions WHERE document_id=?', (doc_id,)).fetchall()
        for row in rows:
            q = json.loads(row['data'])
            if watermark_rejected(q['regions'], report):
                with db() as conn:
                    count = conn.execute('DELETE FROM questions WHERE id=? AND data=?', (row['id'], row['data'])).rowcount
                if count:
                    (root / 'images' / (row['id'] + '.png')).unlink(missing_ok=True)
                    deleted.append(row['id'])
            elif q.get('watermark_key') != report['key'] or report_changed:
                if report['cleaned_pages']:
                    old_hash = question_hash(q)
                    labels = {text.strip().casefold() for text in report['removed_labels']}
                    q['text'] = '\n'.join(line for line in q['text'].splitlines() if line.strip().casefold() not in labels)
                    q['text_hash'] = text_fingerprint(q['text'])
                    mapping = q.get('subquestions')
                    if mapping and mapping.get('source_hash') == old_hash:
                        mapping['source_hash'] = question_hash(q)
                    with fitz.open(cleaned) as pdf:
                        png = render_question(pdf, q['regions'])
                    q['content_hash'] = question_fingerprint(q['text'], png)
                else:
                    png = None
                q['watermark_key'] = report['key']
                with db() as conn:
                    count = conn.execute('UPDATE questions SET data=? WHERE id=? AND data=?', (json.dumps(q), row['id'], row['data'])).rowcount
                if count:
                    if png is not None:
                        (root / 'images' / (row['id'] + '.png')).write_bytes(png)
                    updated.append(row['id'])
        if deleted:
            with db() as conn:
                raw = conn.execute('SELECT data FROM documents WHERE id=?', (doc_id,)).fetchone()['data']
                data = json.loads(raw)
                audit = data.setdefault('watermark', {}).setdefault('deleted_question_ids', [])
                audit.extend(i for i in deleted if i not in audit)
                data.setdefault('warnings', []).append(f'Watermark cleanup deleted {len(deleted)} saved question groups that could not be cleaned safely.')
                conn.execute('UPDATE documents SET data=? WHERE id=? AND data=?', (json.dumps(data), doc_id, raw))
        return dict(document_id=doc_id, deleted_question_ids=deleted, updated_question_ids=updated,
                    cleaned_pages=report['cleaned_pages'], rejected_regions=report['rejected_regions'], warnings=report['warnings'])

    @app.post('/api/documents/<doc_id>/clean-watermarks')
    def clean_watermarks(doc_id):
        hint = (request.get_json() or {}).get('watermark_text', '')
        if not isinstance(hint, str) or len(hint) > 150:
            raise ValueError('Watermark text must be at most 150 characters.')
        return jsonify(clean_document_watermarks(doc_id, hint.strip()))

    # Retrofit existing banks once per source/hint version. Originals stay intact.
    with db() as conn:
        watermark_docs = [row['id'] for row in conn.execute('SELECT id FROM documents')]
    for doc_id in watermark_docs:
        try:
            clean_document_watermarks(doc_id)
        except (ValueError, RuntimeError, OSError, fitz.mupdf.FzErrorBase) as error:
            with db() as conn:
                row = conn.execute('SELECT data FROM documents WHERE id=?', (doc_id,)).fetchone()
                data = json.loads(row['data'])
                warning = 'Watermark cleanup could not finish; inspect this source or use Clean watermarks: ' + str(error)[:200]
                if warning not in data.setdefault('warnings', []):data['warnings'].append(warning)
                conn.execute('UPDATE documents SET data=? WHERE id=?', (json.dumps(data), doc_id))

    backfill = ModelBackfill(root, lambda: model_status(), review_inputs,
        lambda *args: review_disagreement(*args, TOPICS, cache_dir=root / 'language-reviews'),
        lambda parts: analyze_dependencies(parts))
    app.extensions['model_backfill'] = backfill
    backfill.kick()
    return app


def run_local():
    """Bind before opening a browser, so a port conflict never opens another app."""
    import sys
    import threading
    import webbrowser
    from werkzeug.serving import make_server

    port = int(os.environ.get('PORT', '5001'))
    server = make_server('127.0.0.1', port, create_app(), threaded=True)
    url = f'http://127.0.0.1:{server.server_port}'
    print(f'Question bank: {url}\nPress Ctrl+C to stop.', flush=True)
    desktop = sys.platform in ('darwin', 'win32') or bool(os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY'))
    preference = os.environ.get('QUESTION_BANK_OPEN_BROWSER', 'auto').lower()

    def open_browser():
        try:
            opened = webbrowser.open(url, new=2)
        except (webbrowser.Error, OSError):
            opened = False
        if not opened:
            print(f'Open {url} in your browser.', flush=True)

    try:
        if preference == '1' or (preference == 'auto' and desktop):
            threading.Thread(target=open_browser, daemon=True).start()
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == '__main__':
    run_local()
