#!/usr/bin/env python3
"""Regenerate the 14-step table first column in SKILL.md / SKILL.en.md from wizard.STEPS.

Only the leading `| N name |` cell of each numbered table row is rewritten;
the hand-written deliverable and gate columns stay untouched.
`--check` (default) fails on drift, `--write` fixes the files in place.
"""
import argparse
import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('wizard', ROOT/'scripts/wizard.py')
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)

ROW = re.compile(r'^\| (\d+) [^|]*\|', re.M)

def render(path, names):
    text = path.read_text(encoding='utf-8')
    def sub(m):
        n = int(m.group(1))
        return f'| {n} {names[n-1]} |' if 1 <= n <= len(names) else m.group(0)
    return ROW.sub(sub, text)

def main():
    p = argparse.ArgumentParser(description=__doc__)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument('--check', action='store_true', help='only verify (default)')
    mode.add_argument('--write', action='store_true', help='rewrite the tables instead of only checking')
    a = p.parse_args()
    stale = []
    for path, names in [(ROOT/'SKILL.md', w.STEPS), (ROOT/'SKILL.en.md', w.STEPS_EN)]:
        new = render(path, names)
        if new != path.read_text(encoding='utf-8'):
            stale.append(path.name)
            if a.write:
                path.write_text(new, encoding='utf-8')
    if stale and not a.write:
        sys.exit('step tables out of date: ' + ', '.join(stale) + ' (run scripts/gendocs.py --write)')
    print(('updated: ' + ', '.join(stale)) if stale else 'step tables up to date')

if __name__ == '__main__':
    main()
