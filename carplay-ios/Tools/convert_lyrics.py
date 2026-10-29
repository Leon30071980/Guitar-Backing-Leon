#!/usr/bin/env python3
"""Validates private lyrics.json exported from Guitar Backing Leon v2.63.
Usage: python Tools/convert_lyrics.py INPUT.json OUTPUT.json
Does not access Google Drive or modify the original file.
"""
import json,sys
from pathlib import Path

def normalize(data):
    words=[]
    for obj in data.get('words',[]):
        try:
            text=str(obj['text']).strip()
            start,end=float(obj['start']),float(obj['end'])
            line=int(obj.get('line',0))
            if text and 0<=start<end:
                words.append(dict(text=text,start=start,end=end,line=line))
        except (ValueError,KeyError,TypeError):pass
    words.sort(key=lambda x:(x['start'],x['end']))
    if not words:raise ValueError('Nessuna parola valida trovata')
    return dict(words=words,offset_seconds=float(data.get('offset_seconds',0) or 0))
if __name__=='__main__':
    if len(sys.argv)!=3:sys.exit('Uso: python Tools/convert_lyrics.py sorgente.json uscita.json')
    result=normalize(json.loads(Path(sys.argv[1]).read_text(encoding='utf-8')))
    Path(sys.argv[2]).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(len(result['words']),'parole, accordi esclusi')
