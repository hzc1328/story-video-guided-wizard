#!/usr/bin/env python3
"""Explicit, stage-bound text/TTS calls and local audio/video editing. No image generation.

Thin CLI entry: implementation lives in the mediakit package. Names are
re-exported so existing tests and scripts keep working, and the request /
duration aliases stay patchable.
"""
import argparse
import json
from pathlib import Path
import sys

# Support direct invocation and import-based tests without global installation.
_SCRIPTS=str(Path(__file__).resolve().parent)
if _SCRIPTS not in sys.path: sys.path.insert(0,_SCRIPTS)

from mediakit import audit
from mediakit.audio import mix as _mix
from mediakit.captions import (ass_text, ass_time, build_ass, caption_lines, caption_size,
                               captions, has_filter, layout_captions, validate_cues)
from mediakit.core import (binary, doctor, duration, font_path, hashes, new_output,
                           new_outputs, probe, run, stage, voice_selection, write_new)
from mediakit.providers.base import NoRedirect, request
from mediakit.providers.doubao import DoubaoTTS, decode_tts
from mediakit.providers.doubao import tts as _tts
from mediakit.providers.kimi import KimiClient
from mediakit.providers.kimi import kimi as _kimi
from mediakit.runtime import w
from mediakit.video import assemble as _assemble
from mediakit.video import qc_media, stamp, validate_timeline

__all__=['w','audit','binary','doctor','duration','font_path','hashes','new_output','new_outputs',
 'probe','run','stage','voice_selection','write_new','validate_cues','caption_size','caption_lines',
 'layout_captions','captions','has_filter','ass_time','ass_text','build_ass','validate_timeline',
 'stamp','qc_media','NoRedirect','request','KimiClient','DoubaoTTS','decode_tts',
 'kimi','tts','mix','assemble','main']


def kimi(project,prompt,out,authorized):
    return _kimi(project,prompt,out,authorized,_request=request)

def tts(project,text_path,instructions,voice,rate,out,authorized,selection='VOICE_SELECTION.json'):
    return _tts(project,text_path,instructions,voice,rate,out,authorized,selection,_request=request)

def mix(project,voice,music,out,gain=.16,start=0,length=None):
    return _mix(project,voice,music,out,gain,start,length,_duration=duration)

def assemble(project,plan_path,out):
    return _assemble(project,plan_path,out)

def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='cmd',required=True)
    q=sub.add_parser('doctor');q.add_argument('--require',action='store_true')
    q=sub.add_parser('probe');q.add_argument('file')
    for name in ('kimi','tts','mix','assemble'):
        q=sub.add_parser(name);q.add_argument('project',type=Path);q.add_argument('--out',required=True)
        if name=='kimi':q.add_argument('--prompt',required=True)
        if name=='tts':
            q.add_argument('--text',required=True);q.add_argument('--instructions',required=True);q.add_argument('--voice',required=True);q.add_argument('--rate',type=int,default=0)
            q.add_argument('--selection',default='VOICE_SELECTION.json')
        if name in ('kimi','tts'):q.add_argument('--authorized',action='store_true')
        if name=='mix':
            q.add_argument('--voice',required=True);q.add_argument('--music',required=True);q.add_argument('--gain',type=float,default=.16);q.add_argument('--start',type=float,default=0);q.add_argument('--length',type=float)
        if name=='assemble':q.add_argument('--plan',required=True)
    a=p.parse_args()
    if a.cmd=='doctor':print(json.dumps(doctor(a.require),ensure_ascii=False,indent=2))
    elif a.cmd=='probe':print(json.dumps(probe(a.file),ensure_ascii=False,indent=2))
    elif a.cmd=='kimi':print(kimi(a.project,a.prompt,a.out,a.authorized))
    elif a.cmd=='tts':print(tts(a.project,a.text,a.instructions,a.voice,a.rate,a.out,a.authorized,a.selection))
    elif a.cmd=='mix':print(mix(a.project,a.voice,a.music,a.out,a.gain,a.start,a.length))
    else:print(assemble(a.project,a.plan,a.out))

if __name__=='__main__':
    try:main()
    except (ValueError,OSError,KeyError,TypeError) as e:
        lang=w.cli_language()
        print(('Not finished: ' if lang=='en' else '未完成：')+w.translate(str(e),lang),file=sys.stderr);sys.exit(2)
