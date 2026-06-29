#!/usr/bin/env python3
from __future__ import annotations
import json, re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
required = [
    'README.md',
    'HANDOFF.md',
    'KNOWN_ISSUES_AND_OPTIMIZATION_REQUESTS.md',
    'GPT_PRO_REVIEW_REQUEST.md',
    'MANIFEST.json',
    'evidence/runtime/OKR_STATE.summary.json',
    'evidence/runtime/KA-001-product-arch-discussion.json',
    'evidence/runtime/KA-001-kanban-workflow.json',
    'evidence/runtime/KA-001-ka-spec.json',
    'evidence/runtime/KA-001-spec-gate-report.json',
    'evidence/runtime/KA-001-reviewer-verdict.json',
    'evidence/runtime/KA-001-pm-final.json',
    'evidence/runtime/KA-001-executor-evidence.md',
    'evidence/runtime/KA-001-validation-output.txt',
]
missing = [p for p in required if not (ROOT/p).exists()]
if missing:
    print('missing required files:', missing)
    sys.exit(1)
for p in ROOT.rglob('*.json'):
    json.loads(p.read_text(encoding='utf-8'))
secret_patterns = [
    re.compile(r'sk-[A-Za-z0-9_-]{8,}'),
    re.compile(r'gho_[A-Za-z0-9_-]{8,}'),
    re.compile(r'xox[baprs]-[A-Za-z0-9_-]{8,}', re.I),
    re.compile(r'\boc_[0-9a-fA-F]{8,}\b'),
    re.compile(r'\bom_[A-Za-z0-9_-]{8,}\b'),
    re.compile(r'\bou_[A-Za-z0-9_-]{8,}\b'),
]
violations=[]
for p in ROOT.rglob('*'):
    if p.is_file():
        text=p.read_text(encoding='utf-8', errors='ignore')
        for pat in secret_patterns:
            if pat.search(text):
                violations.append((str(p.relative_to(ROOT)), pat.pattern))
if violations:
    print('redaction violations:', violations[:20])
    sys.exit(1)
print('bundle validation ok')
