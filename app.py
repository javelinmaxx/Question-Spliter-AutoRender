"""Single-user local question bank. Run with python app.py."""
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from analysis_storage import rules_hash, source_hash, text_fingerprint, question_fingerprint
from io import BytesIO
from pathlib import Path

import fitz
from flask import Flask, jsonify, render_template, request, send_file

from physics import TOPICS, choose_questions, extract, render_question, validate_regions, suggest, custom_tags, HL_ONLY_TOPICS, validate_level_topics, sl_compatible
from ocr import region_text
from language_review import review_disagreement, context_hash, status as model_status
from subquestions import propose_parts, question_hash, validate_layout, validate_graph, approved_map, short_variants, render_variant, choose_short
from dependency_review import analyze_dependencies
from topic_scope import scoped_question, topic_closure, POLICY
from paper_diagnostics import diagnose_selection, finish_diagnostics
from paper_cover import add_practice_cover, finalize_practice_cover
from paper_selection import question_variants, select_required
from paper_numbering import erase_source_numbers
from paper_layout import add_question_pages
from model_backfill import ModelBackfill
from year_filter import year_range, matches_year
from upload_filter import markscheme_name, markscheme_heading


def create_app(data_dir=None):
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = 40 * 1024 * 1024
    root = Path(data_dir or os.environ.get('QUESTION_BANK_DATA', Path(__file__).parent / 'instance')).resolve()
    root.mkdir(parents=True, exist_ok=True)
    for folder in ('documents', 'images', 'papers'):
        (root / folder).mkdir(exist_ok=True)

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
    with db() as conn:
        for row in conn.execute('SELECT id FROM documents WHERE id NOT IN (SELECT document_id FROM source_fingerprints)').fetchall():
            path = root / 'documents' / (row['id'] + '.pdf')
            if path.is_file():
                conn.execute('INSERT OR IGNORE INTO source_fingerprints VALUES (?, ?)', (source_hash(path), row['id']))
        for row in conn.execute('SELECT id, data FROM questions').fetchall():
            value = json.loads(row['data'])
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
        return jsonify(topics=TOPICS, hl_only_topics=sorted(HL_ONLY_TOPICS), prerequisite_policy=POLICY)

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
            result = extract(path, uploaded.filename, ocr_mode=request.form.get('ocr_mode', 'auto'), ocr_cache=root / 'ocr-cache')
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
        path = root / 'documents' / (doc_id + '.pdf')
        mode = old.get('analysis', {}).get('ocr_mode', 'auto')
        result = extract(path, old['filename'], ocr_mode=mode, page_records=old['text_pages'])
        previous = {q['number']: q for q in old['questions']}
        for candidate in result['questions']:
            prior = previous.get(candidate['number'], {}).get('language_review')
            candidate['language_review'] = current_review(result, candidate, prior)
        result['analysis'] = dict(version=1, rules_hash=rules_hash(), source_sha256=source_hash(path), status='complete',
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
        if paper not in ('Paper 1', 'Paper 1A', 'Paper 1B', 'Paper 2'):
            raise ValueError('Choose a paper type before language review.')
        with fitz.open(root / 'documents' / (doc_id + '.pdf')) as pdf:
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
        with fitz.open(root / 'documents' / (doc_id + '.pdf')) as pdf:
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
        if paper not in (('Paper 1', 'Paper 1A', 'Paper 1B', 'Paper 2', 'Unknown') if imported else ('Paper 1', 'Paper 1A', 'Paper 1B', 'Paper 2')):
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
        with fitz.open(root / 'documents' / (doc['id'] + '.pdf')) as pdf:
            regions = validate_regions(pdf, value['regions'])
            png = render_question(pdf, regions)
            text = (region_text(doc['text_pages'], regions) if 'text_pages' in doc
                    else '\n'.join(pdf[r['page']].get_text(clip=fitz.Rect(r['rect'])) for r in regions))
        suggestions = suggest(text, paper, level)
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
        if paper not in ('Unknown', 'Paper 1', 'Paper 1A', 'Paper 1B', 'Paper 2'):
            raise ValueError('Choose a valid paper type.')
        with fitz.open(root / 'documents' / (doc_id + '.pdf')) as pdf:
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
        lower, upper = year_range(request.args)
        items = [q for q in items if matches_year(q.get('year'), lower, upper)]
        for field in ('level', 'syllabus', 'paper', 'difficulty'):
            term = request.args.get(field)
            if term:
                items = [q for q in items if str(q[field]) == term or (field == 'level' and q[field] == 'Both')]
        topics = [t for t in request.args.getlist('topic') if t]
        if request.args.get('level') == 'SL':
            validate_level_topics(topics, 'SL')
            items = [q for q in items if sl_compatible(q)]
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
        with fitz.open(root / 'documents' / (doc_id + '.pdf')) as pdf:
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
            variant = short_variants(q, scoped.get('omitted_parts', []), topics)[0] if mode == 'short' else scoped
            with fitz.open(root / 'documents' / (q['document_id'] + '.pdf')) as pdf:
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
        with fitz.open(root / 'documents' / (q['document_id'] + '.pdf')) as pdf:
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
        level, syllabus = value.get('level'), value.get('syllabus', '2025')
        if level not in ('HL', 'SL') or syllabus not in ('2025', 'Legacy'):
            raise ValueError('Choose HL or SL and a syllabus.')
        selected_topics = value.get('topics', [])
        if not isinstance(selected_topics, list) or any(t not in TOPICS for t in selected_topics):
            raise ValueError('Invalid topics.')
        validate_level_topics(selected_topics, level)
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

    @app.post('/api/papers/preview')
    def preview_paper_selection():
        eligible, diagnostics = paper_pool(request.get_json())
        config = diagnostics['requested']
        candidates = []
        for q in eligible:
            variants = question_variants(q, config['topics'], config['render_mode'])
            candidates.append(dict(id=q['id'], document_id=q['document_id'], number=q['number'],
                                   filename=q['filename'], topics=scoped_question(q, config['topics'])['topics'],
                                   preferred_minutes=variants[0]['minutes'], minimum_minutes=min(v['minutes'] for v in variants),
                                   omitted_parts=variants[0]['omitted_parts']))
        return jsonify(questions=candidates, diagnostics=diagnostics)

    @app.post('/api/papers')
    def generate():
        value = request.get_json()
        eligible, diagnostics = paper_pool(value)
        config = diagnostics['requested']
        target, mode, level, syllabus, selected_topics = (config[key] for key in ('minutes', 'render_mode', 'level', 'syllabus', 'topics'))
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
                return jsonify(error='Some selected questions no longer fit these filters or duration. Refresh the matching questions.', diagnostics=diagnostics), 400
            required = [by_id[i] for i in requested_ids]
            chosen = select_required(required, target, selected_topics, mode)
            if required and not chosen:
                minimum = sum(min(v['minutes'] for v in question_variants(q, selected_topics, mode)) for q in required)
                return jsonify(error=f'The selected {len(required)} questions need at least {minimum:g} estimated minutes; the budget is {target:g}. Increase the budget or deselect questions.', diagnostics=diagnostics), 400
            if fill:
                remaining = round(target - sum(q['minutes'] for q in chosen), 6)
                extras = automatic_choice([q for q in eligible if q['id'] not in set(requested_ids)], remaining, selected_topics, mode)
                filled_ids = [q['id'] for q in extras]
                chosen.extend(extras)
        else:
            chosen = automatic_choice(eligible, target, selected_topics, mode)
        ids = [q['id'] for q in chosen]
        if not chosen:
            return jsonify(error=diagnostics['summary'], diagnostics=diagnostics), 400
        paper_id = uuid.uuid4().hex
        actual = round(sum(q['minutes'] for q in chosen), 1)
        numbering_cache, numbering_results = {}, {}
        original_questions = {q['id']: q for q in questions()}
        with fitz.open() as pdf:
            add_practice_cover(pdf, level=level, syllabus=syllabus, target=target, chosen=chosen, mode=mode)
            for i, q in enumerate(chosen, 1):
                # Keep every crop of the parent together and in source order.
                with fitz.open(root / 'documents' / (q['document_id'] + '.pdf')) as source:
                    numbering_results[q['id']] = erase_source_numbers(source, original_questions[q['id']], numbering_cache)
                    rendered = add_question_pages(pdf, source, q, i)
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
