"""Validate a registered subject's ports/catalog and optionally analyze a sample PDF."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from subjects import registry, validate_adapter, API_VERSION
from subjects.pipeline import analyze
from source_origin import analyze_origin


def check(subject_id, sample=None, mode='off'):
    subject=registry.get(subject_id)
    catalog=validate_adapter(subject)
    result=dict(schema_version=API_VERSION,subject_id=subject.id,adapter_version=subject.version,
                catalog=catalog,prerequisites=subject.curriculum.prerequisites(),contract_valid=True)
    if sample:
        analysis=analyze(subject,sample,sample.name,ocr_mode=mode)
        analysis['origin_analysis']=analyze_origin(analysis.get('text_pages',[]))
        analysis['origin']=analysis['origin_analysis']['origin']
        result['analysis']=analysis
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--subject',default='ibdp-physics')
    parser.add_argument('--sample',type=Path)
    parser.add_argument('--ocr-mode',choices=['off','auto','verify'],default='off')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    try:
        report=check(args.subject,args.sample,args.ocr_mode)
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,indent=2)+'\n')
        print(f'Validated {args.subject}; report: {args.output}')
    except (ValueError,OSError) as error:
        parser.exit(1,str(error)+'\n')
