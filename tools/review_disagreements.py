"""Run the configured local model on the real-paper validation disagreements."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from language_review import review_disagreement, status
from ocr import region_text
from physics import TOPICS, suggest


def run(validation, output):
    records = []
    for path in sorted(validation.glob('*/extraction.json')):
        document = json.loads(path.read_text())
        for q in document['questions']:
            if q['ocr_comparison']['status'] != 'disagreement':
                continue
            native = region_text(document['text_pages'], q['regions'], 'native')
            ocr = region_text(document['text_pages'], q['regions'], 'ocr')
            result = review_disagreement(native, ocr, q['paper'], suggest(native, q['paper'])['topics'],
                                         suggest(ocr, q['paper'])['topics'], TOPICS,
                                         cache_dir=output.parent / 'language-reviews')
            records.append(dict(source_case=path.parent.name, question=q['number'], review=result))
    if not records:
        raise ValueError('No disagreements found; this is not a model validation run.')
    output.parent.mkdir(parents=True, exist_ok=True)
    report = dict(model=status(), cases=records, resolved=sum(r['review']['status'] == 'resolved' for r in records),
                  remaining=sum(r['review']['status'] != 'resolved' for r in records))
    output.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--validation', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run(args.validation, args.output)
    except (ValueError, OSError) as error:
        parser.exit(1, str(error) + '\n')
    sys.exit(bool(result['remaining']))
