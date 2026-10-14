'use strict';
// Google Drive REST API. I token Google non vengono salvati su disco o nel browser.
const $ = id => document.getElementById(id);
// Sezioni 03 e 04 collegate all'unico player, senza tracce duplicate.
const sectionTransport=window.GuitarTransport.attach({
  audio:$('player'),getDuration:()=>Number(current?.duration)||0,
  onSeek:()=>syncChords()
});
const API = 'https://www.googleapis.com/drive/v3/files';
const UPLOAD = 'https://www.googleapis.com/upload/drive/v3/files';
const APP_FOLDER = 'Guitar Backing Leon';
const MIME_FOLDER = 'application/vnd.google-apps.folder';
const SCOPE = 'https://www.googleapis.com/auth/drive.file';
const capoSelect = $('capo-position');
try { capoSelect.value = String(Math.min(12, Math.max(0, Number(localStorage.getItem('gbl-capo')) || 0))); }
catch { capoSelect.value = '0'; }
const capoValue = () => Number(capoSelect.value) || 0;
const shownChord = chord => window.GuitarChordTools.display(chord, capoValue());
function updateCapo() {
  const chords = current?.chords || [];
  [...$('chords').children].forEach((button, i) => {
    if (!chords[i]) return;
    button.textContent = `${shownChord(chords[i].chord)} · ${fmt(chords[i].start)}`;
    button.title = shownChord(chords[i].chord) === '—' ? 'Accordo non identificato' : 'Vai a ' + shownChord(chords[i].chord);
  });
  $('capo-hint').textContent = capoValue()
    ? `Capotasto al tasto ${capoValue()}: posizioni da suonare. La tonalità della base resta invariata.`
    : 'Accordi originali: la tonalità della base non cambia.';
  karaokeView.render(karaokeWords,current?.chords||[],Number(current?.duration)||0);
  karaokeView.tick($('player').currentTime,false);
  syncChords();
}
capoSelect.addEventListener('change', () => {
  try { localStorage.setItem('gbl-capo', capoSelect.value); } catch {}
  updateCapo();
});
const fmt = v => { const n = Math.max(0,Number(v)||0); return `${Math.floor(n/60)}:${String(Math.floor(n%60)).padStart(2,'0')}`; };
let token = '', tokenClient, tree, songs = [], current = null, sourceUrl = '', loopA = null, loopB = null, refreshing = false;
let forceConsentNext=false;
let guitarEnabled = false, vocalsEnabled = true, mixerSeq = 0;
let karaokeWords=[];
function updateLyricsOffset(value){
  const n=Math.max(-5,Math.min(5,Number(value)||0));
  $('lyrics-offset').value=n;
  $('lyrics-offset-value').textContent=`${n>=0?'+':''}${n.toFixed(1)} s`;
  karaokeView.setOffset(n);
  karaokeView.tick($('player').currentTime,false);
}
$('lyrics-offset').addEventListener('input',()=>{
  const n=Number($('lyrics-offset').value);
  $('lyrics-offset-value').textContent=`${n>=0?'+':''}${n.toFixed(1)} s`;
});
$('lyrics-offset').addEventListener('change',()=>{
  updateLyricsOffset($('lyrics-offset').value);
  if(current){try{localStorage.setItem('gbl-lyrics-offset-'+current.id,$('lyrics-offset').value);}catch{}}
});
$('lyrics-offset-reset').addEventListener('click',()=>{
  updateLyricsOffset(0);
  if(current){try{localStorage.removeItem('gbl-lyrics-offset-'+current.id);}catch{}}
});

function checkAudioDuration(){
  const expected=Number(current?.duration)||0;
  const actual=Number($('player').duration)||0;
  const elem=$('sync-audio-check');
  const mismatch=expected>1 && Number.isFinite(actual) && actual>1 && Math.abs(actual-expected)>.75;
  elem.hidden=!mismatch;
  if(mismatch)elem.textContent=`Attenzione: durata dell'audio ${actual.toFixed(1)} s, durata prevista ${expected.toFixed(1)} s (differenza ${(actual-expected).toFixed(1)} s). Potrebbe essere una traccia non perfettamente allineata.`;
}
$('player').addEventListener('loadedmetadata',checkAudioDuration);
$('player').addEventListener('durationchange',checkAudioDuration);
const karaokeView=window.GuitarKaraoke.make({
  root:$('karaoke-lines'),
  formatChord: value=>shownChord(value),
  onSeek: seconds=>{$('player').currentTime=seconds;$('player').play().catch(()=>{});},
});
const cachedAudio = new Map();
const continuousMixer=window.GuitarContinuousMixer.attach($('player'),msg=>notice(msg,true));

function requestedMix(){ return guitarEnabled ? (vocalsEnabled ? 'full' : 'no_vocals') : (vocalsEnabled ? 'no_guitar' : 'no_guitar_no_vocals'); }
function availableMixes(){return current?.tracks || {};}
function updateMixer(){
  const capable=Object.keys(availableMixes()).length>=4;
  const ok=capable && continuousMixer.ready;
  const g=$('toggle-guitar'),v=$('toggle-vocals');
  g.disabled=v.disabled=!ok;
  g.classList.toggle('on',guitarEnabled);v.classList.toggle('on',vocalsEnabled);
  g.setAttribute('aria-pressed',String(guitarEnabled));v.setAttribute('aria-pressed',String(vocalsEnabled));
  g.textContent=`🎸 Chitarre: ${guitarEnabled?'ON':'OFF'}`;
  v.textContent=`🎤 Voce: ${vocalsEnabled?'ON':'OFF'}`;
  $('mixer-note').textContent=ok
    ? 'Mixer continuo pronto: ON/OFF immediati senza fermare il brano.'
    : capable ? 'Preparazione delle combinazioni da Google Drive. Si può ascoltare durante il caricamento.'
    : 'Mixer non disponibile per questo brano: deve essere rielaborato sul PC.';
}
function clearAudioCache(){
  continuousMixer.reset();
  for(const u of cachedAudio.values())URL.revokeObjectURL(u);
  cachedAudio.clear(); sourceUrl='';
}
function updateDownload(mode){
  const id=availableMixes()[mode] || (mode==='no_guitar'?current?.audioFileId:null);
  const url=cachedAudio.get(id);
  $('download').href=url||'#';
  $('download').download=(current?.name||'base').replace(/[\\/:*?"<>|]/g,'-').slice(0,70)+' - '+mode+'.mp3';
}
async function prepareMixer(song,serial){
  const mixes=availableMixes();
  if(Object.keys(mixes).length<4)return;
  const urls={};
  try {
    const downloads=await Promise.all(Object.entries(mixes).map(async ([mode,id])=>{
      let url=cachedAudio.get(id);
      if(!url){
        const blob=await bytes(id);
        if(serial!==mixerSeq || current!==song)return null;
        url=URL.createObjectURL(blob);cachedAudio.set(id,url);
      }
      return [mode,url];
    }));
    if(serial!==mixerSeq || current!==song)return;
    for(const pair of downloads){if(pair)urls[pair[0]]=pair[1];}
    await continuousMixer.prepare(urls);
    if(serial===mixerSeq && current===song){updateMixer();notice('Mixer continuo pronto: nessuna pausa nei cambi di voce e chitarra.');}
  }catch(err){if(serial===mixerSeq)notice('Mixer non pronto: '+err.message,true);}
}
async function switchMix(initial=false){
  if(!current)return;
  if(!initial){
    if(continuousMixer.select(requestedMix())){updateDownload(requestedMix());updateMixer();}
    return;
  }
  const song=current, serial=++mixerSeq;
  const id=availableMixes().no_guitar || song.audioFileId;
  if(!id){notice('La base audio non è disponibile.',true);return;}
  const player=$('player');
  player.pause();
  try {
    let url=cachedAudio.get(id);
    if(!url){const blob=await bytes(id);if(serial!==mixerSeq || current!==song)return;url=URL.createObjectURL(blob);cachedAudio.set(id,url);}
    if(serial!==mixerSeq || current!==song)return;
    sourceUrl=url;
    player.src=url;
    player.load();
    updateDownload('no_guitar');
    notice('Base pronta. Preparazione mixer in corso...');
    prepareMixer(song,serial);
  }catch(err){if(serial===mixerSeq)notice(err.message,true);}
}
$('toggle-guitar').addEventListener('click',()=>{guitarEnabled=!guitarEnabled;switchMix();});
$('toggle-vocals').addEventListener('click',()=>{vocalsEnabled=!vocalsEnabled;switchMix();});


function notice(text, bad=false) { $('notice').textContent=text; $('notice').className=bad?'error':''; }
async function api(url,options={}) {
  if (!token) throw new Error('Sessione Google scaduta. Selezioni "Accedi con Google".');
  const response = await fetch(url,{...options,headers:{Authorization:`Bearer ${token}`,...options.headers}});
  if (!response.ok) {
    let details=''; try {const data=await response.json(); details=data.error?.message||'';}catch{}
    if (response.status===401){token='';$('google-btn').textContent='Ricollega Google';throw new Error('La sessione Google è scaduta. Toccare Ricollega Google per rinnovare l’accesso.');}
    throw new Error(`Google Drive HTTP ${response.status}: ${details||response.statusText}`);
  }
  return response;
}
function queryParts(parts) {return encodeURIComponent(parts.join(' and '));}
function quote(s) {return s.replaceAll('\\','\\\\').replaceAll("'","\\'");}
async function getFiles(parent,name,mime) {
  const q=[`'${parent}' in parents`,'trashed = false'];
  if(name)q.push(`name = '${quote(name)}'`);
  if(mime)q.push(`mimeType = '${quote(mime)}'`);
  const result=[]; let page='';
  do {
    const url=`${API}?q=${queryParts(q)}&fields=nextPageToken%2Cfiles(id%2Cname%2CmimeType%2Csize)&pageSize=1000${page?'&pageToken='+encodeURIComponent(page):''}`;
    const data=await (await api(url)).json();result.push(...(data.files||[]));page=data.nextPageToken||'';
  } while(page);
  return result;
}
async function createFolder(parent,name) {
  const found=await getFiles(parent,name,MIME_FOLDER);
  if(found.length)return found[0].id;
  const res=await api(API+'?fields=id',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,mimeType:MIME_FOLDER,parents:[parent]})});
  return (await res.json()).id;
}
async function createFile(parent,name,blob,contentType) {
  const boundary='guitar_'+Math.random().toString(36).slice(2)+'_'+Date.now();
  const metadata={name,parents:[parent]};
  const body=new Blob([
    `--${boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n${JSON.stringify(metadata)}\r\n`,
    `--${boundary}\r\nContent-Type: ${contentType}\r\n\r\n`,blob,`\r\n--${boundary}--\r\n`
  ],{type:`multipart/related; boundary=${boundary}`});
  const res=await api(`${UPLOAD}?uploadType=multipart&fields=id,name`,{method:'POST',body});
  return res.json();
}
async function bytes(id) {return (await api(`${API}/${encodeURIComponent(id)}?alt=media`)).blob();}
async function jsonFile(id) {return (await api(`${API}/${encodeURIComponent(id)}?alt=media`)).json();}
async function ensureTree() {
  const root=await createFolder('root',APP_FOLDER);
  const pending=await createFolder(root,'Da elaborare');
  const songFolder=await createFolder(root,'Canzoni');
  let index=(await getFiles(root,'libreria.json'))[0]?.id;
  if(!index) index=(await createFile(root,'libreria.json',new Blob([JSON.stringify({version:1,songs:[]})]),'application/json')).id;
  return {root,pending,songFolder,index};
}
async function initGoogle() {
  if(!(window.google?.accounts?.oauth2))throw new Error('Impossibile caricare Google Identity Services. Riprovare da Safari, con connessione Internet.');
  const clientId=window.GUITAR_CONFIG?.clientId||'';
  if(!clientId.endsWith('.apps.googleusercontent.com')||clientId.startsWith('INSERIRE_'))throw new Error('Configurare prima il Client ID web nel file config.js.');
  tokenClient=google.accounts.oauth2.initTokenClient({client_id:clientId,scope:SCOPE,callback:async res=>{
    if(res.error){forceConsentNext=true;notice('Google richiede una nuova autorizzazione. Toccare nuovamente Accedi con Google. ('+res.error+')',true);return;}
    token=res.access_token; $('google-btn').textContent='Google collegato';
    try {tree=await ensureTree();$('dashboard').hidden=false;notice('Collegato al Suo Google Drive privato.');await refreshAll();}
    catch(err){notice(err.message,true);}
  }});
}
$('google-btn').addEventListener('click',async()=>{
  try {if(!tokenClient)await initGoogle();tokenClient.requestAccessToken({prompt:forceConsentNext?'consent':''});forceConsentNext=false;}
  catch(err){notice(err.message,true);}
});

async function refreshAll(){if(refreshing)return;refreshing=true;try{
  const [index,pending]=await Promise.all([jsonFile(tree.index),getFiles(tree.pending)]);
  songs=Array.isArray(index.songs)?index.songs:[];
  drawLibrary();
  const valid=pending.filter(x=>x.mimeType!==MIME_FOLDER);
  $('queue').textContent=valid.length?`${valid.length} brano/i in attesa o in elaborazione sul PC: ${valid.map(x=>x.name).join(' · ')}`:'Nessun brano in attesa.';
} catch(err){notice(err.message,true);} finally{refreshing=false;}}
$('refresh').addEventListener('click',refreshAll);
function drawLibrary(){
  $('library').replaceChildren();
  if(!songs.length){$('library').textContent='Nessuna base ancora disponibile. Avvii l’elaborazione dal PC oppure carichi un brano in coda.';return;}
  for(const s of songs){
    const btn=document.createElement('button');btn.className='song-row';btn.type='button';
    const a=document.createElement('strong');a.textContent=s.name||'Brano';
    const b=document.createElement('small');b.textContent=`${fmt(s.duration)} · MP3`;btn.append(a,b);
    btn.addEventListener('click',()=>openSong(s));$('library').append(btn);
  }
}
function renderChords(chords){
  $('chords').replaceChildren();
  for(const c of chords){const button=document.createElement('button');button.type='button';button.className='chord';button.textContent=`${shownChord(c.chord)} · ${fmt(c.start)}`;button.addEventListener('click',()=>{$('player').currentTime=Number(c.start)||0;$('player').play().catch(()=>{});});$('chords').append(button);}
  if(!chords.length)$('chords').textContent='Accordi non rilevati.';
  updateCapo();
}
async function openSong(song){
  $('player-panel').hidden=false;
  $('chords-panel').hidden=false;
  $('track-name').textContent=song.name||'Brano';
  notice('Preparazione della base musicale privata...');
  ++mixerSeq;
  $('player').pause();
  clearAudioCache();
  current=song;guitarEnabled=false;vocalsEnabled=true;
  $('chord-engine-source').textContent = (song.chord_source||'').startsWith('guitar+mix')
    ? 'Analisi dalla chitarra isolata; accordi indicativi.'
    : song.chord_source === 'corretto-manualmente' ? 'Accordi con correzioni manuali.'
    : 'Accordi da un’analisi precedente: per migliorarli utilizzi la rianalisi sul PC.';
  loopA=loopB=null;loopMessage();renderChords(song.chords||[]);
  $('karaoke-panel').hidden=false;
  karaokeWords=[];
  updateLyricsOffset(0);
  $('sync-audio-check').hidden=true;
  karaokeView.render([], song.chords||[],Number(song.duration)||0);
  loadKaraoke(song);
  $('player').playbackRate=Number($('speed').value);
  updateMixer();
  await switchMix(true);
  $('karaoke-panel').scrollIntoView({behavior:'smooth',block:'start'});
}
async function loadKaraoke(song){
  if(!song?.lyricsFileId){
    $('karaoke-status').textContent='Testo non ancora disponibile. Generarlo dal PC, quindi aggiornare la libreria.';
    return;
  }
  $('karaoke-status').textContent='Caricamento testo privato da Google Drive...';
  try{
    const result=await jsonFile(song.lyricsFileId);
    if(current!==song)return;
    karaokeWords=Array.isArray(result.words)?result.words:[];
    let offset=Number(result.offset_seconds)||0;
    try{const local=localStorage.getItem('gbl-lyrics-offset-'+song.id);if(local!==null)offset=Number(local)||0;}catch{}
    updateLyricsOffset(offset);
    karaokeView.render(karaokeWords,song.chords||[],Number(song.duration)||0);
    karaokeView.tick($('player').currentTime,false);
    $('karaoke-status').textContent=karaokeWords.length
      ? `${karaokeWords.length} parole · Lingua: ${result.language||'automatica'} · Clicchi una parola per ascoltare da quel punto.`
      : 'Nessun testo riconosciuto per questo brano.';
  }catch(err){if(current===song)$('karaoke-status').textContent='Impossibile caricare testo: '+err.message;}
}
function syncChords(){
  if(!current)return;
  const p=$('player'),t=p.currentTime||0;
  karaokeView.tick(t);
  if(loopA!==null&&loopB!==null&&loopB>loopA&&t>=loopB){p.currentTime=loopA;return;}
  const chords=current.chords||[];
  const idx=chords.findIndex(c=>t>=c.start&&t<c.end);
  $('chord-now').textContent=idx<0?'—':shownChord(chords[idx].chord);
  $('chord-next').textContent=shownChord(chords.slice(idx+1).find(c=>c.chord!=='N')?.chord);
  [...$('chords').children].forEach((e,i)=>e.classList.toggle('selected',i===idx));
}
function loopMessage(){$('loop-info').textContent=loopA===null?'Selezioni A e B per ripetere una sezione.':`A: ${fmt(loopA)} · B: ${loopB===null?'da impostare':fmt(loopB)}`;}
$('player').addEventListener('timeupdate',syncChords);$('player').addEventListener('seeked',syncChords);
// Aggiornamento temporale piu' preciso dei soli eventi HTML5 timeupdate.
let chordFrame=0,lastChordFrame=0;
function followAudioClock(now){
  const player=$('player');
  if(player.paused||player.ended){chordFrame=0;return;}
  if(now-lastChordFrame>=65){lastChordFrame=now;syncChords();}
  chordFrame=requestAnimationFrame(followAudioClock);
}
$('player').addEventListener('play',()=>{if(!chordFrame)chordFrame=requestAnimationFrame(followAudioClock);});
$('player').addEventListener('pause',()=>{if(chordFrame)cancelAnimationFrame(chordFrame);chordFrame=0;syncChords();});
$('speed').addEventListener('change',()=>{$('player').playbackRate=Number($('speed').value);});
$('set-a').addEventListener('click',()=>{loopA=$('player').currentTime||0;loopB=null;loopMessage();});
$('set-b').addEventListener('click',()=>{if(loopA===null||$('player').currentTime<=loopA){notice('Imposti prima A, poi B in un punto successivo.',true);return;}loopB=$('player').currentTime;loopMessage();});
$('clear-loop').addEventListener('click',()=>{loopA=loopB=null;loopMessage();});
$('upload-form').addEventListener('submit',async ev=>{ev.preventDefault();
  const f=$('upload-file').files[0];if(!f)return;
  if(f.size>40*1024*1024){notice('Da smartphone il limite prudenziale è 40 MB. Carichi i file più grandi dal PC.',true);return;}
  const ext=f.name.split('.').pop().toLowerCase();
  if(!['mp3','wav','flac','m4a','ogg','aac'].includes(ext)){notice('Formato non supportato.',true);return;}
  $('upload-btn').disabled=true;notice('Caricamento sul Suo Google Drive privato in corso...');
  try{await createFile(tree.pending,f.name,f,f.type||'application/octet-stream');$('upload-file').value='';notice('Caricamento riuscito. Il PC elaborerà automaticamente al prossimo avvio.');await refreshAll();}
  catch(err){notice(err.message,true);}finally{$('upload-btn').disabled=false;}
});

// Pulizia Google Drive anche da iPhone, senza PC acceso: scope drive.file, nessun server.
const cloudList=$('drive-cleanup-list'), cloudStatus=$('drive-cleanup-status'), cloudTrash=$('drive-cleanup-trash');
function selectedCloudItems(){return [...cloudList.querySelectorAll('input[data-cloud-kind]:checked')].map(el=>({kind:el.dataset.cloudKind,id:el.dataset.cloudId}));}
function cloudSection(title,entries){
  const section=document.createElement('div');section.className='cleanup-group';
  const h=document.createElement('h3');h.textContent=`${title} (${entries.length})`;section.append(h);
  if(!entries.length){const p=document.createElement('p');p.className='hint';p.textContent='Nessun elemento.';section.append(p);}
  for(const item of entries){
    const row=document.createElement('label');row.className='cleanup-item';
    const check=document.createElement('input');check.type='checkbox';check.dataset.cloudKind=item.kind;check.dataset.cloudId=item.id;
    check.addEventListener('change',()=>{cloudTrash.disabled=!selectedCloudItems().length;});
    const info=document.createElement('span');info.textContent=item.name;
    const sub=document.createElement('small');sub.textContent=item.kind==='orphan'?'Cartella non presente nell’indice':item.kind==='index'?'Riferimento nell’indice senza cartella':item.kind==='pending'?'Da elaborare':'Brano pubblicato';
    const labels=document.createElement('span');labels.append(info,sub);row.append(check,labels);section.append(row);
  }
  cloudList.append(section);
}
async function cloudInventory(){
  if(!tree){cloudStatus.textContent='Acceda prima con Google.';return;}
  cloudStatus.textContent='Lettura delle cartelle...';cloudTrash.disabled=true;cloudList.replaceChildren();
  try{
    const [index,folders,pending]=await Promise.all([
      jsonFile(tree.index),getFiles(tree.songFolder),getFiles(tree.pending)
    ]);
    const published=Array.isArray(index.songs)?index.songs:[];
    const refs=new Map(published.filter(x=>x?.id).map(x=>[String(x.id),x]));
    const songDirs=folders.filter(x=>x.mimeType===MIME_FOLDER);
    const byName=new Map(songDirs.map(x=>[x.name,x]));
    const all=published.map(x=>{
      const folder=byName.get(String(x.id));return {kind:folder?'song':'index',id:folder?.id||String(x.id),name:x.name||String(x.id),jobId:String(x.id)};
    });
    const oldFolders=songDirs.filter(f=>!refs.has(f.name)).map(f=>({kind:'orphan',id:f.id,name:f.name,jobId:f.name}));
    const pendingItems=pending.map(x=>({kind:'pending',id:x.id,name:x.name}));
    cloudSection('Canzoni pubblicate',all);
    cloudSection('Cartelle precedenti o non indicizzate',oldFolders);
    cloudSection('Da elaborare',pendingItems);
    cloudStatus.textContent=`${published.length} brani in libreria · ${songDirs.length} cartelle · ${pending.length} elementi in coda.`;
  }catch(err){cloudStatus.textContent=err.message;}
}
$('drive-cleanup-load').addEventListener('click',cloudInventory);
async function cloudFileTrash(fileId){
  await api(`${API}/${encodeURIComponent(fileId)}?fields=id,trashed`,{
    method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({trashed:true})
  });
}
async function cloudSaveIndex(index){
  // Il file JSON resta presente. Non si elimina mai il manifest di libreria.
  const blob=new Blob([JSON.stringify(index,null,2)],{type:'application/json'});
  const res=await api(`${UPLOAD}/${encodeURIComponent(tree.index)}?uploadType=media&fields=id`,{
    method:'PATCH',headers:{'Content-Type':'application/json'},body:blob
  });
  return res.json();
}
cloudTrash.addEventListener('click',async()=>{
  const selected=selectedCloudItems();if(!selected.length)return;
  if(!confirm(`Spostare nel Cestino ${selected.length} elemento/i? Sul PC i file resteranno salvati.`))return;
  const phrase=prompt('Scriva CESTINO per confermare');if(phrase!=='CESTINO')return;
  cloudTrash.disabled=true;cloudStatus.textContent='Spostamento nel Cestino...';
  try{
    // Rileggiamo l'indice prima di modificare la libreria. Evitare la pulizia mentre il PC sincronizza.
    const index=await jsonFile(tree.index);
    const dirs=await getFiles(tree.songFolder), queue=await getFiles(tree.pending);
    const indexed=Array.isArray(index.songs)?index.songs:[];
    const folderMap=new Map(dirs.filter(x=>x.mimeType===MIME_FOLDER).map(x=>[x.id,x]));
    const queueIds=new Set(queue.map(x=>x.id));
    const byFolderName=new Set(dirs.filter(x=>x.mimeType===MIME_FOLDER).map(x=>x.name));
    const indexedIds=new Set(indexed.map(x=>String(x.id)));
    const songIdsToRemove=new Set();
    for(const item of selected){
      if(item.kind==='pending'){
        if(!queueIds.has(item.id))throw new Error('Un file della coda non esiste più: aggiornare l’elenco.');
        await cloudFileTrash(item.id);
      }else if(item.kind==='song'){
        const folder=folderMap.get(item.id);
        if(!folder||!indexedIds.has(folder.name))throw new Error('La libreria è cambiata: aggiornare l’elenco.');
        await cloudFileTrash(folder.id);songIdsToRemove.add(folder.name);
      }else if(item.kind==='orphan'){
        const folder=folderMap.get(item.id);
        if(!folder||indexedIds.has(folder.name))throw new Error('Cartella aggiornata, ricaricare la libreria.');
        await cloudFileTrash(folder.id);
        if(/^[a-f0-9]{32}$/.test(folder.name))songIdsToRemove.add(folder.name);
      }else if(item.kind==='index'){
        if(!indexedIds.has(item.id)||byFolderName.has(item.id))throw new Error('Indice modificato, aggiornare l’elenco.');
        songIdsToRemove.add(item.id);
      }else throw new Error('Elemento non valido.');
    }
    if(songIdsToRemove.size){
      // Rileggere ancora dopo i PATCH. Gli ID eliminati restano come tombstones per evitare re-upload.
      const latest=await jsonFile(tree.index);
      latest.songs=(Array.isArray(latest.songs)?latest.songs:[]).filter(x=>!songIdsToRemove.has(String(x.id)));
      latest.deletedSongIds=[...new Set([...(latest.deletedSongIds||[]),...songIdsToRemove])].slice(-3000);
      await cloudSaveIndex(latest);
    }
    if(current && songIdsToRemove.has(String(current.id))){$('player').pause();current=null;$('player-panel').hidden=true;$('chords-panel').hidden=true;$('karaoke-panel').hidden=true;clearAudioCache();}
    cloudStatus.textContent='Spostamento riuscito. L’audio locale sul PC resta disponibile.';
    await refreshAll();await cloudInventory();
  }catch(err){cloudStatus.textContent='Pulizia parziale o non riuscita: '+err.message+' Aggiorni l’elenco prima di riprovare.';}
});
