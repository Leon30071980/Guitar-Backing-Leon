"""Configura il client ID OAuth iOS pubblico nel progetto Xcode.
Uso: python3 Tools/configure_google_oauth.py <IOS_CLIENT_ID>
Viene usato il medesimo progetto Google Cloud della PWA. Nessun secret/token.
"""
from pathlib import Path
import re, sys, plistlib

APP_INFO = Path('App/Info.plist')
SUFFIX = '.apps.googleusercontent.com'

def reversed_scheme(client_id):
    if not re.fullmatch(r'[0-9]+-[A-Za-z0-9_-]+' + re.escape(SUFFIX), client_id):
        raise ValueError('Client ID iOS non valido. Usare un client OAuth di tipo iOS, NON il client Web.')
    return 'com.googleusercontent.apps.' + client_id[:-len(SUFFIX)]

def configure(client_id):
    scheme = reversed_scheme(client_id)
    with APP_INFO.open('rb') as f: data=plistlib.load(f)
    data['LeonGoogleClientID']=client_id
    types=data.get('CFBundleURLTypes',[])
    # Conserva lo scheme guitarleoncarplay e ogni altro schema non Google.
    types=[t for t in types if t.get('CFBundleURLName')!='it.leon.guitar.karaoke.google']
    types.append({'CFBundleURLName':'it.leon.guitar.karaoke.google', 'CFBundleURLSchemes':[scheme]})
    data['CFBundleURLTypes']=types
    with APP_INFO.open('wb') as f:plistlib.dump(data,f,sort_keys=False)
    print('OAuth iOS configurato; scheme: '+scheme)

if __name__=='__main__':
    if len(sys.argv)!=2: raise SystemExit('Specificare il Client ID iOS.')
    configure(sys.argv[1])
