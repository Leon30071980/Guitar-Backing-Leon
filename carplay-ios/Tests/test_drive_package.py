"""Verifiche offline di struttura, schema e configurazione del progetto v1.6.
Non sostituiscono una build su Xcode né un accesso reale a Google Drive.
"""
import json, plistlib, sys, tempfile
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'Tools'))
from configure_google_oauth import reversed_scheme

assert reversed_scheme('1234567-abc.apps.googleusercontent.com')=='com.googleusercontent.apps.1234567-abc'
for invalid in ('client-web', '123-invalid.apps.example.com', ''):
    try: reversed_scheme(invalid)
    except ValueError: pass
    else: raise AssertionError('client id invalido accettato')

p=plistlib.loads((root/'App/Info.plist').read_bytes())
assert p['CFBundleShortVersionString']=='1.6'
assert any('guitarleoncarplay' in x.get('CFBundleURLSchemes',[]) for x in p['CFBundleURLTypes'])

example={'version': 1, 'songs':[
    {'id':'song123','name':'Canzone esempio', 'duration':175.5,'lyricsFileId':'text123', 'chords':[], 'tracks':{'full':'audio123','no_vocals':'audio124'}},
    {'id':'song456','name':'Senza testo','duration':188.1,'lyricsFileId':None}
]}
items=json.loads(json.dumps(example))['songs']
assert len(items)==2 and items[0]['lyricsFileId']=='text123'
assert items[0]['name']=='Canzone esempio'
assert items[1]['lyricsFileId'] is None

swift=(root/'App/GoogleDriveLibrary.swift').read_text()
assert 'https://www.googleapis.com/auth/drive.file' in swift
assert 'Guitar Backing Leon' in swift and 'libreria.json' in swift
assert 'lyricsFileId' in swift
assert 'ASWebAuthenticationSession' in swift
assert 'SecItemAdd' in swift
assert 'Content-Type", value:' not in swift
print('PASS 12 verifiche offline Drive Connector v1.6')
