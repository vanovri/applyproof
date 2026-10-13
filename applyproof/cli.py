import argparse
import json
from pathlib import Path
from .models import Case, Draft
from .engine import assess, build_draft, ai_select, markdown

def main():
    parser = argparse.ArgumentParser(description='Prepare traceable evidence for an application. Never submits.')
    parser.add_argument('case', type=Path, help='JSON with profile and job')
    parser.add_argument('--ollama', metavar='MODEL', help='Opt in to evidence-ID selection using local Ollama')
    parser.add_argument('--select', nargs='*', help='Verified fact IDs for a manual draft')
    parser.add_argument('--output', type=Path, default=Path('application-review.json'))
    args = parser.parse_args()
    case = Case.model_validate_json(args.case.read_text(encoding='utf-8'))
    if args.ollama:
        result = ai_select(case, args.ollama)
        result['markdown'] = markdown(result)
    elif args.select:
        result = build_draft(Draft(**case.model_dump(), selected_ids=args.select))
        result['markdown'] = markdown(result)
    else:
        result = assess(case)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f'Review saved: {args.output}')

if __name__ == '__main__':
    main()
