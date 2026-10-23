"""Resume optional model reviews from saved text without blocking the UI."""
import hashlib
import json
import sqlite3
import threading
import time
from datetime import datetime, timezone

from language_review import context_hash, PROMPT_VERSION
from subquestions import propose_parts, question_hash, validate_layout


class ModelBackfill:
    def __init__(self, root, availability, review_inputs, review, dependencies):
        self.root, self.availability = root, availability
        self.review_inputs, self.review, self.dependencies = review_inputs, review, dependencies
        self.lock = threading.Lock()
        self.last_check = float('-inf')
        self.state = dict(running=False, checked=0, updated=0, errors=0)

    def kick(self, force=False):
        with self.lock:
            if self.state['running'] or (not force and time.monotonic() - self.last_check < 30):
                return
            self.last_check = time.monotonic()
            if not self.availability()['available']:
                return
            self.state = dict(running=True, checked=0, updated=0, errors=0)
            threading.Thread(target=self._work, daemon=True, name='qwen-backfill').start()

    def status(self):
        with self.lock:
            return dict(self.state)

    def connection(self):
        return sqlite3.connect(self.root / 'bank.sqlite3', timeout=10)

    @staticmethod
    def key(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

    def ocr_review(self, doc, question):
        args = self.review_inputs(doc, question['regions'], question['paper'])
        # Adjudication requires two versions with different topic suggestions.
        if not args[0].strip() or not args[1].strip() or set(args[3]) == set(args[4]):
            return False
        fingerprint = context_hash(*args)
        key = self.key([PROMPT_VERSION, fingerprint])
        previous = question.get('language_review') or {}
        if previous.get('input_hash') == fingerprint and (previous.get('automatic_context') == key or previous.get('model')):
            return False
        for candidate in doc.get('questions', []):
            reusable = candidate.get('language_review') or {}
            if reusable.get('input_hash') == fingerprint and (reusable.get('automatic_context') == key or reusable.get('model')):
                question['language_review'] = dict(reusable)
                return True
        try:
            result = self.review(*args)
        except Exception as error:
            result = dict(status='needs_review', input_hash=fingerprint, topics=[], evidence=[],
                          reason='Optional model review failed: ' + str(error)[:250])
        if result.get('status') == 'unavailable':
            return False
        question['language_review'] = dict(result, automatic_context=key,
                                           attempted_at=datetime.now(timezone.utc).isoformat())
        return True

    def dependency_review(self, doc, question):
        mapping = question.get('subquestions')
        if mapping and mapping.get('source_hash') != question_hash(question):
            mapping = None
        if mapping and mapping.get('status') == 'approved':
            return False
        mapping = mapping or propose_parts(question, doc['text_pages'])
        if not mapping:
            return False
        try:
            validate_layout(question, mapping['parts'])
        except (ValueError, KeyError, TypeError):
            return False  # Unsafe boundaries need manual review before inference.
        context = [{k: p[k] for k in ('id', 'regions', 'text')} for p in mapping['parts']]
        key = self.key(context)
        previous = mapping.get('model_review') or {}
        if mapping.get('analysis_hash') == key and (previous.get('automatic_context') == key or previous.get('model')):
            return False
        try:
            result = self.dependencies(mapping['parts'])
        except Exception as error:
            result = dict(status='needs_review', parts=mapping['parts'],
                          reason='Optional dependency review failed: ' + str(error)[:250])
        question['subquestions'] = dict(mapping, status='draft', source_hash=question_hash(question),
            parts=result['parts'], analysis_hash=key,
            model_review=dict(result, automatic_context=key, attempted_at=datetime.now(timezone.utc).isoformat()))
        return True

    def run_once(self):
        """Persist each unit independently; compare-and-swap protects teacher edits."""
        if not self.availability()['available']:
            return
        with self.connection() as conn:
            documents = conn.execute('SELECT id, data FROM documents').fetchall()
        for doc_id, _ in documents:
            with self.connection() as conn:
                row = conn.execute('SELECT data FROM documents WHERE id=?', (doc_id,)).fetchone()
            if not row:
                continue
            doc = json.loads(row[0])
            if not doc.get('text_pages'):
                continue
            for index in range(len(doc.get('questions', []))):
                # Read again after inference for the prior question, keeping all
                # completed results even if this process stops on the next one.
                with self.connection() as conn:
                    original = conn.execute('SELECT data FROM documents WHERE id=?', (doc_id,)).fetchone()[0]
                current = json.loads(original)
                if index >= len(current.get('questions', [])):
                    continue
                candidate = current['questions'][index]
                try:
                    changed = self.ocr_review(current, candidate)
                    self.state['checked'] += 1
                    if changed:
                        current.setdefault('analysis', {})['language_backfill_at'] = datetime.now(timezone.utc).isoformat()
                        with self.connection() as conn:
                            changed_rows = conn.execute('UPDATE documents SET data=? WHERE id=? AND data=?',
                                (json.dumps(current), doc_id, original)).rowcount
                        self.state['updated'] += changed_rows
                except Exception:
                    self.state['errors'] += 1
            with self.connection() as conn:
                latest = conn.execute('SELECT data FROM documents WHERE id=?', (doc_id,)).fetchone()[0]
                doc = json.loads(latest)
                pending = 0
                for candidate in doc.get('questions', []):
                    args = self.review_inputs(doc, candidate['regions'], candidate['paper'])
                    if args[0].strip() and args[1].strip() and set(args[3]) != set(args[4]):
                        review = candidate.get('language_review') or {}
                        fingerprint = context_hash(*args)
                        if (review.get('input_hash') != fingerprint or
                                not (review.get('model') or review.get('automatic_context') == self.key([PROMPT_VERSION, fingerprint]))):
                            pending += 1
                doc.setdefault('analysis', {})['language_review_status'] = 'pending' if pending else 'complete'
                conn.execute('UPDATE documents SET data=? WHERE id=? AND data=?', (json.dumps(doc), doc_id, latest))
                saved = conn.execute('SELECT id, data FROM questions WHERE document_id=?', (doc_id,)).fetchall()
            for qid, original in saved:
                question = json.loads(original)
                try:
                    changed = self.ocr_review(doc, question)
                    changed = self.dependency_review(doc, question) or changed
                    self.state['checked'] += 1
                    if changed:
                        with self.connection() as conn:
                            changed_rows = conn.execute('UPDATE questions SET data=? WHERE id=? AND data=?',
                                (json.dumps(question), qid, original)).rowcount
                        self.state['updated'] += changed_rows
                except Exception:
                    self.state['errors'] += 1

    def _work(self):
        try:
            self.run_once()
        except Exception:
            self.state['errors'] += 1
        finally:
            with self.lock:
                self.state['running'] = False
