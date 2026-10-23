"""Single-user local question bank. Run with python app.py."""
import json
import os
import sqlite3
import uuid
from io import BytesIO
from pathlib import Path

import fitz
from flask import Flask, jsonify, render_template, request, send_file

from physics import TOPICS, choose_questions, extract, render_question, validate_regions, suggest
from ocr import region_text


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
        ''')

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
        return response

    @app.get('/')
    def index():
        return render_template('index.html')

    @app.get('/api/catalog')
    def catalog():
        return jsonify(topics=TOPICS)

    @app.get('/api/documents')
    def documents():
        with db() as conn:
            return jsonify([dict(id=r['id'], filename=r['filename']) for r in conn.execute('SELECT id, filename FROM documents ORDER BY rowid DESC')])

    @app.post('/api/documents')
    def upload():
        uploaded = request.files.get('file')
        if not uploaded or not uploaded.filename.lower().endswith('.pdf'):
            raise ValueError('Choose a PDF file.')
        doc_id = uuid.uuid4().hex
        path = root / 'documents' / (doc_id + '.pdf')
        uploaded.save(path)
        try:
            result = extract(path, uploaded.filename, ocr_mode=request.form.get('ocr_mode', 'auto'), ocr_cache=root / 'ocr-cache')
        except Exception as error:
            path.unlink(missing_ok=True)
            raise ValueError('Could not read PDF: ' + str(error)) from error
        with db() as conn:
            conn.execute('INSERT INTO documents VALUES (?, ?, ?)', (doc_id, Path(uploaded.filename).name, json.dumps(result)))
        return jsonify(document(doc_id)), 201

    @app.get('/api/documents/<doc_id>')
    def get_document(doc_id):
        result = document(doc_id)
        saved = {q['number']: q for q in questions() if q['document_id'] == doc_id}
        suggested = {q['number']: q for q in result['questions']}
        suggested.update(saved)
        result['questions'] = [suggested[n] for n in sorted(suggested)]
        result['saved_numbers'] = list(saved)
        return jsonify(result)

    @app.get('/api/documents/<doc_id>/pages/<int:page>')
    def page_image(doc_id, page):
        document(doc_id)
        with fitz.open(root / 'documents' / (doc_id + '.pdf')) as pdf:
            if page >= len(pdf):
                raise ValueError('Page not found.')
            pix = pdf[page].get_pixmap(matrix=fitz.Matrix(1.4, 1.4), alpha=False)
        return send_file(BytesIO(pix.tobytes('png')), mimetype='image/png')

    @app.post('/api/questions')
    def save_question():
        value = request.get_json()
        doc = document(value['document_id'])
        number = int(value['number'])
        if not 1 <= number <= 999:
            raise ValueError('Question number must be between 1 and 999.')
        level, syllabus = value.get('level'), value.get('syllabus')
        if level not in ('HL', 'SL', 'Both') or syllabus not in ('2025', 'Legacy'):
            raise ValueError('Select the level and syllabus before saving.')
        paper = value.get('paper')
        if paper not in ('Paper 1', 'Paper 1A', 'Paper 1B', 'Paper 2'):
            raise ValueError('Select a valid paper.')
        topics = value.get('topics', [])
        if not isinstance(topics, list) or any(t not in TOPICS for t in topics):
            raise ValueError('Select valid syllabus topics.')
        if not topics:
            raise ValueError('Select at least one topic.')
        minutes = float(value['minutes'])
        if not 0 < minutes <= 300:
            raise ValueError('Estimated time must be between 0 and 300 minutes.')
        difficulty = value.get('difficulty', 'Unrated')
        if difficulty not in ('Unrated', 'Easy', 'Medium', 'Hard'):
            raise ValueError('Invalid difficulty.')
        year = int(value['year'])
        if not 1970 <= year <= 2100:
            raise ValueError('Enter a valid paper year.')
        marks = int(value['marks']) if value.get('marks') not in (None, '') else None
        if marks is not None and not 1 <= marks <= 200:
            raise ValueError('Marks must be between 1 and 200.')
        tags = value.get('tags', [])
        commands = value.get('commands', [])
        if any(not isinstance(items, list) or len(items) > 50 or any(not isinstance(s, str) or len(s) > 100 for s in items) for items in (tags, commands)):
            raise ValueError('Tags and command terms must be lists of short text values.')
        with fitz.open(root / 'documents' / (doc['id'] + '.pdf')) as pdf:
            regions = validate_regions(pdf, value['regions'])
            png = render_question(pdf, regions)
            text = (region_text(doc['text_pages'], regions) if 'text_pages' in doc
                    else '\n'.join(pdf[r['page']].get_text(clip=fitz.Rect(r['rect'])) for r in regions))
        suggestions = suggest(text, paper)
        ocr_text = region_text(doc['text_pages'], regions, 'ocr') if 'text_pages' in doc else ''
        ocr_topics = suggest(ocr_text, paper)['topics'] if ocr_text.strip() else []
        native_present = any(len(doc.get('text_pages', [])[r['page']]['native'].strip()) >= 50 for r in regions) if 'text_pages' in doc else True
        comparison = dict(status=('agreement' if set(suggestions['topics']) == set(ocr_topics) else 'disagreement') if ocr_text.strip() and native_present else 'ocr_only' if ocr_text.strip() else 'not_run', topics=ocr_topics)
        saved = dict(number=number, year=year, level=level, syllabus=syllabus, paper=paper,
                     topics=topics, minutes=minutes, difficulty=difficulty, marks=marks,
                     tags=tags, commands=commands, regions=regions, text=text,
                     filename=doc['filename'], topic_evidence=suggestions['topic_evidence'],
                     ocr_comparison=comparison, review_status='reviewed')
        with db() as conn:
            existing = next((q for q in questions() if q['document_id'] == doc['id'] and q['number'] == number), None)
            qid = existing['id'] if existing else uuid.uuid4().hex
            (root / 'images' / (qid + '.png')).write_bytes(png)
            conn.execute('INSERT OR REPLACE INTO questions VALUES (?, ?, ?)', (qid, doc['id'], json.dumps(saved)))
        return jsonify(id=qid, **saved), 201

    @app.get('/api/questions')
    def search():
        items = questions()
        for field in ('level', 'syllabus', 'paper', 'difficulty', 'year'):
            term = request.args.get(field)
            if term:
                items = [q for q in items if str(q[field]) == term or (field == 'level' and q[field] == 'Both')]
        topic = request.args.get('topic')
        if topic:
            items = [q for q in items if topic in q['topics']]
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
        if not any(q['id'] == qid for q in questions()):
            raise ValueError('Question not found.')
        return send_file(root / 'images' / (qid + '.png'), mimetype='image/png')

    @app.post('/api/papers')
    def generate():
        value = request.get_json()
        target = float(value['minutes'])
        if not 1 <= target <= 300:
            raise ValueError('Choose a duration between 1 and 300 minutes.')
        level, syllabus = value.get('level'), value.get('syllabus', '2025')
        if level not in ('HL', 'SL') or syllabus not in ('2025', 'Legacy'):
            raise ValueError('Choose HL or SL and a syllabus.')
        selected_topics = value.get('topics', [])
        if not isinstance(selected_topics, list) or any(t not in TOPICS for t in selected_topics):
            raise ValueError('Invalid topics.')
        # A mixed-topic parent qualifies only if all its topics were requested.
        eligible = [q for q in questions() if q['level'] in (level, 'Both') and q['syllabus'] == syllabus
                    and (not selected_topics or set(q['topics']).issubset(selected_topics))
                    and (not value.get('paper') or q['paper'] == value['paper'])]
        ids = choose_questions(eligible, target)
        chosen = [q for q in eligible if q['id'] in ids]
        if not chosen:
            raise ValueError('No complete reviewed questions fit these filters and duration. Add questions or increase the time.')
        paper_id = uuid.uuid4().hex
        actual = round(sum(q['minutes'] for q in chosen), 1)
        with fitz.open() as pdf:
            cover = pdf.new_page()
            cover.insert_textbox(fitz.Rect(50, 80, 545, 750), f'IB DP Physics - {level}\nPractice paper\nSyllabus: {syllabus}\nRequested time: {target:g} minutes\nEstimated time: {actual:g} minutes\n{len(chosen)} complete questions\n\nTime estimates are approximate.\nGenerated practice material, not an official IB examination.', fontsize=18)
            for i, q in enumerate(chosen, 1):
                # Keep every crop of the parent together and in source order.
                with fitz.open(root / 'documents' / (q['document_id'] + '.pdf')) as source:
                    for j, region in enumerate(q['regions']):
                        rect = fitz.Rect(region['rect'])
                        # Tile tall crops at a readable scale across consecutive A4 pages.
                        max_height = 710 * rect.width / 495
                        top = rect.y0
                        while top < rect.y1:
                            clip = fitz.Rect(rect.x0, top, rect.x1, min(rect.y1, top + max_height))
                            page = pdf.new_page()
                            label = f'Question {i}' + (' (continued)' if j or top > rect.y0 else '')
                            page.insert_text((50, 35), label, fontsize=12)
                            page.show_pdf_page(fitz.Rect(50, 60, 545, 770), source, region['page'], clip=clip)
                            page.insert_text((50, 805), f"Source: {q['filename'][:55].encode('ascii', 'replace').decode()} | Q{q['number']} | {q['year']} | {q['paper']}", fontsize=8)
                            top += max_height
            pdf.save(root / 'papers' / (paper_id + '.pdf'))
        result = dict(id=paper_id, question_ids=list(ids), target_minutes=target, actual_minutes=actual,
                      shortfall_minutes=round(target - actual, 1), count=len(chosen))
        with db() as conn:
            conn.execute('INSERT INTO papers VALUES (?, ?)', (paper_id, json.dumps(result)))
        return jsonify(result), 201

    @app.get('/api/papers/<paper_id>/download')
    def download(paper_id):
        with db() as conn:
            if not conn.execute('SELECT id FROM papers WHERE id=?', (paper_id,)).fetchone():
                raise ValueError('Paper not found.')
        return send_file(root / 'papers' / (paper_id + '.pdf'), as_attachment=True, download_name='physics-practice-paper.pdf')

    return app


if __name__ == '__main__':
    create_app().run(host='127.0.0.1', port=int(os.environ.get('PORT', '5000')), debug=False)
