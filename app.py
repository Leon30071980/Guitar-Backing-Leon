"""Guitar Backing Leon: elaborazione locale con sincronizzazione Drive opzionale."""
from __future__ import annotations

import json
import logging
import time
import os
import re
import shutil
import subprocess
import sys
import threading
import uuid
import wave
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, jsonify, request, send_file, send_from_directory
from werkzeug.exceptions import RequestEntityTooLarge

# Se avviato con "python app.py", moduli come cloud_library devono condividere
# la STESSA istanza del server e la stessa mappa JOBS, non importare una copia.
if __name__ == "__main__":
    sys.modules["app"] = sys.modules[__name__]

ROOT = Path(__file__).resolve().parent
JOBS_DIR = ROOT / "data" / "jobs"
JOBS_DIR.mkdir(parents=True, exist_ok=True)
MAX_UPLOAD_MB = 150
MAX_DURATION_SEC = 600
PORT = 8765
# Le quattro combinazioni vengono generate UNA volta sul PC.
# Sul telefono si cambia file audio, senza elaborazione AI nel cloud.
TRACK_FILES = {
    "full": "brano_completo.mp3",
    "no_guitar": "base_senza_chitarra.mp3",
    "no_vocals": "base_senza_voce.mp3",
    "no_guitar_no_vocals": "base_senza_voce_e_chitarra.mp3",
}
EXTENSIONS = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac"}
JOBS: dict[str, dict] = {}
LYRIC_TASKS: dict[str, dict] = {}
LOCK = threading.RLock()
POOL = ThreadPoolExecutor(max_workers=1)

app = Flask(__name__, static_folder="static")
from as_import_flask import as_blueprint
app.register_blueprint(as_blueprint)

app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024


def ffmpeg_path() -> str:
    import imageio_ffmpeg
    executable = imageio_ffmpeg.get_ffmpeg_exe()
    os.environ["PATH"] = str(Path(executable).parent) + os.pathsep + os.environ.get("PATH", "")
    return executable


def run_cmd(argv: list[str], timeout: int = 3600) -> None:
    """Esegue senza shell e mostra nel messaggio d'errore l'ultima parte del log."""
    result = subprocess.run(argv, capture_output=True, text=True,
                            errors="replace", timeout=timeout, stdin=subprocess.DEVNULL)
    if result.returncode:
        tail = (result.stderr or "")[-2600:] or (result.stdout or "")[-2600:]
        raise RuntimeError(f"Comando non riuscito (codice {result.returncode}). {tail}")


def run_demucs_with_progress(argv: list[str], on_percent, timeout: int = 7200) -> None:
    """Legge l'avanzamento *riportato da Demucs*, senza stimarlo dal tempo.

    Se il modello non emette una percentuale, la UI rimane sullo stato di fase.
    """
    started = time.monotonic()
    tail = ''
    observed = -1
    process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               stdin=subprocess.DEVNULL, bufsize=0)
    try:
        assert process.stdout is not None
        while True:
            part = process.stdout.read(2048)
            if not part:
                break
            tail = (tail + part.decode('utf-8',errors='replace'))[-4200:]
            # La barra Demucs arriva su stderr usando ritorni-carrello.
            for match in re.finditer(r'(?<!\d)(\d{1,3})(?:\.\d+)?%\s*\|', tail):
                number = int(match.group(1))
                if 0 <= number <= 100 and number > observed:
                    observed = number
                    on_percent(number)
            if time.monotonic() - started > timeout:
                process.kill()
                raise TimeoutError('Separazione Demucs troppo lunga.')
        exit_code = process.wait(timeout=20)
        if exit_code:
            raise RuntimeError(f'Demucs non riuscito (codice {exit_code}). {tail[-2600:]}')
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def public_job(info: dict) -> dict:
    return {k: v for k, v in info.items() if k in
            {"id", "name", "status", "message", "chords", "duration", "error", "tracks", "chord_source", "lyrics_status", "lyrics_count", "lyrics_language", "lyrics_error", "progress_percent", "progress_stage_percent", "user_feedback"}}


def update(job_id: str, **kwargs: object) -> None:
    with LOCK:
        JOBS[job_id].update(kwargs)


def process_audio(job_id: str, extension: str) -> None:
    folder = JOBS_DIR / job_id
    incoming = folder / ("upload" + extension)
    prepared = folder / "input.wav"
    output = folder / "base_senza_chitarra.mp3"
    separated = folder / "separated"
    try:
        ffmpeg = ffmpeg_path()
        update(job_id, status="converting", progress_percent=2, message="Preparazione del file audio...")
        run_cmd([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                 "-i", str(incoming), "-vn", "-ar", "44100", "-ac", "2",
                 "-c:a", "pcm_s16le", str(prepared)], timeout=900)
        with wave.open(str(prepared), "rb") as wf:
            duration = wf.getnframes() / wf.getframerate()
        if duration > MAX_DURATION_SEC:
            raise ValueError("Brano troppo lungo: massimo 10 minuti nella prima versione.")
        if duration < 2:
            raise ValueError("Brano troppo corto: servono almeno 2 secondi di musica.")
        update(job_id, duration=round(duration, 1), status="separating", progress_percent=12,
               message="Separazione AI della chitarra... (il primo utilizzo scarica il modello gratuitamente)")

        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
        from qualita_ai import demucs_args, get_profile
        command = [sys.executable, "-m", "demucs", "-n", "htdemucs_6s",
                   "-d", device, *demucs_args(device),
                   "-o", str(separated), str(prepared)]
        logging.getLogger('ai').info('Separazione Demucs: profilo %s, device %s', get_profile(), device)
        run_demucs_with_progress(command,
            lambda p: update(job_id, progress_percent=round(12 + .43 * p, 1), progress_stage_percent=p),
            timeout=7200)
        wav_folder = separated / "htdemucs_6s" / "input"
        stems = {stem: wav_folder / f"{stem}.wav" for stem in
                 ("guitar", "vocals", "drums", "bass", "piano", "other")}
        missing = [s for s, path in stems.items() if not path.is_file()]
        if missing:
            raise RuntimeError("Tracce Demucs mancanti: " + ", ".join(missing))

        update(job_id, status="analyzing", progress_percent=56, message="Riconoscimento accordi dalla chitarra isolata, con verifica sul mix...")
        # Eventuali errori nell'analisi NON bloccano la consegna della base.
        try:
            from chords import estimate_chords
            from qualita_ai import extended_chords_enabled
            use_extensions = extended_chords_enabled()
            chords = estimate_chords(str(stems["guitar"]), max_seconds=MAX_DURATION_SEC,
                                      reference_path=str(prepared), extended=use_extensions)
            # Stabilizzazione prudente: elimina soltanto spike molto brevi e
            # incerti fra due accordi identici; non forza tempi di battuta.
            from harmonic_engine import stabilize_automatic_chords
            chords, harmonic_smoothing = stabilize_automatic_chords(chords,duration)
            chord_source = "guitar+mix+bassroot+extensions-v2.39" if use_extensions else "guitar+mix+bassroot-v2.39"
            chord_warning = "" if chords else "Accordi non rilevati; la base resta disponibile."
        except Exception as exc:
            chords = []
            chord_source = "error"
            chord_warning = f"Accordi non disponibili ({str(exc)[:180]})."

        # Si trascrive la VOCE ISOLATA, prima che gli stem WAV vengano eliminati.
        # Whisper rimane facoltativo: un suo errore non blocca la base o gli accordi.
        lyrics_status, lyrics_error, lyrics_count, lyrics_language = 'missing', '', 0, ''
        update(job_id, status="transcribing", progress_percent=69, progress_stage_percent=None, message="Karaoke: trascrizione locale della voce con Whisper...")
        try:
            from lyrics import transcribe_audio
            from qualita_ai import default_whisper
            selected_model = default_whisper(device)
            def progress_lyrics(phase, pct=None):
                update(job_id, progress_percent=round(69 + (min(100,max(0,pct))*0.18),1)
                       if phase=='transcribing' and pct is not None else 69,
                       progress_stage_percent=pct if phase=='transcribing' else None)
            try:
                lyric_result = transcribe_audio(str(stems['vocals']), model_name=selected_model,
                                               language=JOBS[job_id].get('requested_language') or None,
                                               progress_callback=progress_lyrics)
            except RuntimeError as ai_exc:
                # Recupero soltanto un reale errore memoria CUDA, senza
                # nascondere problemi di librerie, rete, file o trascrizione.
                if selected_model != 'large-v3' or 'out of memory' not in str(ai_exc).lower():
                    raise
                logging.getLogger('karaoke').warning('Memoria CUDA insufficiente per Large-v3; riprovo con Medium.')
                torch.cuda.empty_cache()
                lyric_result = transcribe_audio(str(stems['vocals']), model_name='medium',
                                                language=JOBS[job_id].get('requested_language') or None,
                                                progress_callback=progress_lyrics)
            (folder / 'lyrics.json').write_text(json.dumps(lyric_result, ensure_ascii=False), encoding='utf-8')
            lyrics_count = len(lyric_result['words'])
            lyrics_language = lyric_result.get('language', '')
            lyrics_status = 'ready' if lyrics_count else 'empty'
        except Exception as exc:
            lyrics_status = 'error'
            lyrics_error = str(exc)[:300]
        update(job_id, lyrics_status=lyrics_status, lyrics_error=lyrics_error,
               lyrics_count=lyrics_count, lyrics_language=lyrics_language)
        update(job_id, status="encoding", progress_percent=88, progress_stage_percent=None,
               message="Creazione delle combinazioni e salvataggio della traccia chitarra...")
        # Conserviamo la sola chitarra anche dopo la pulizia degli STEM WAV:
        # permette confronti e rianalisi future senza ripetere la separazione GPU.
        run_cmd([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                 "-i", str(stems["guitar"]), "-codec:a", "libmp3lame", "-b:a", "192k",
                 str(folder / "chitarra_isolata.mp3")], timeout=900)
        # La voce isolata e' mantenuta LOCALMENTE per future trascrizioni piu' accurate.
        # Non e' una nuova traccia pubblicata su Google Drive.
        run_cmd([ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
                 '-i', str(stems['vocals']), '-codec:a', 'libmp3lame', '-b:a', '192k',
                 str(folder / 'voce_isolata.mp3')], timeout=900)
        # Brano completo dalla registrazione originale (senza sommare stem AI).
        run_cmd([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                 "-i", str(prepared), "-codec:a", "libmp3lame", "-b:a", "192k",
                 str(folder / TRACK_FILES["full"])], timeout=900)

        def encode_mix(stem_names: tuple[str, ...], destination: Path) -> None:
            args = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y"]
            for name in stem_names:
                args.extend(["-i", str(stems[name])])
            concat = "".join(f"[{i}:a]" for i in range(len(stem_names)))
            filt = f"{concat}amix=inputs={len(stem_names)}:duration=longest:normalize=0,alimiter=limit=0.97:level=0[out]"
            args.extend(["-filter_complex", filt, "-map", "[out]", "-codec:a", "libmp3lame",
                         "-b:a", "192k", str(destination)])
            run_cmd(args, timeout=900)

        rest = ("vocals", "drums", "bass", "piano", "other")
        encode_mix(rest, output)
        encode_mix(("guitar", "drums", "bass", "piano", "other"), folder / TRACK_FILES["no_vocals"])
        encode_mix(("drums", "bass", "piano", "other"), folder / TRACK_FILES["no_guitar_no_vocals"])
        with LOCK:
            info = JOBS[job_id]
            info.update(status="done", progress_percent=100, progress_stage_percent=100, chords=chords, chord_source=chord_source, tracks=list(TRACK_FILES),
                        message=chord_warning or "Elaborazione completata. Accordi stimati dalla chitarra; verifica consigliata.")
            result = public_job(info)
        (folder / "result.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        # Report orientativo, mai utilizzato per bloccare il brano.
        try:
            from harmonic_engine import analyze_song_quality
            lyric_words=lyric_result.get('words',[]) if lyrics_status=='ready' else []
            report=analyze_song_quality(chords,lyric_words,duration)
            report['harmonic_smoothing']=locals().get('harmonic_smoothing',{})
            (folder / 'quality_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        except Exception:
            logging.getLogger('ai').exception('Report qualità non disponibile: tracce e karaoke restano validi.')
    except Exception as exc:
        update(job_id, status="error", error=str(exc)[:2800],
               message="Elaborazione non riuscita. Consultare il messaggio di errore.")
    finally:
        # Risparmia spazio su disco. Restano soltanto base MP3 e risultati.
        for path in (incoming, prepared):
            path.unlink(missing_ok=True)
        shutil.rmtree(separated, ignore_errors=True)


def is_valid_id(job_id: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{32}", job_id))


def restore_library() -> None:
    """Riconcilia i brani completati su disco con la libreria in memoria.

    Importazioni Drive e richieste Flask possono correre in thread diversi:
    non sovrascrive lavori ancora in elaborazione né mostra file parziali.
    """
    with LOCK:
        for path in JOBS_DIR.glob("*/result.json"):
            job_id = path.parent.name
            if not is_valid_id(job_id):
                continue
            if job_id in JOBS and JOBS[job_id].get("status") != "done":
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if ((path.parent / "base_senza_chitarra.mp3").is_file()
                        and data.get("status") == "done"):
                    JOBS[job_id] = data
            except (ValueError, OSError, TypeError):
                continue


@app.before_request
def require_local_origin():
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return None
    origin = request.headers.get("Origin")
    if origin:
        p = urlparse(origin)
        if p.scheme != "http" or p.hostname not in {"127.0.0.1", "localhost"} or p.port != PORT:
            return jsonify(error="Origine non autorizzata."), 403
    return None


@app.errorhandler(RequestEntityTooLarge)
def file_too_big(error):
    return jsonify(error=f"File troppo grande. Limite: {MAX_UPLOAD_MB} MB."), 413


@app.get("/")
def index():
    return send_from_directory(ROOT / "static", "index.html")


@app.get("/api/health")
def health():
    try:
        import torch
        gpu = torch.cuda.get_device_name(0) if torch.cuda.is_available() else None
    except Exception:
        gpu = None
    return jsonify(ready=True, gpu=gpu, storage="locale", cloud=False)


@app.get("/api/library")
def library():
    # Include i brani scaricati da Drive durante questa sessione, anche nel
    # caso in cui siano stati creati in un thread diverso dal server web.
    restore_library()
    with LOCK:
        items = [public_job(j) for j in JOBS.values() if j.get("status") == "done"]
    response = jsonify(items=items[::-1])
    response.headers["Cache-Control"] = "no-store"
    return response


FEEDBACK_VALUES = {"good", "average", "bad"}


@app.patch("/api/jobs/<job_id>/feedback")
def update_song_feedback(job_id):
    """Feedback volontario, indipendente dal riconoscimento AI del brano.

    Memorizza solo la scelta esplicita dell'utente, senza cambiare karaoke,
    accordi o tracce. Drive sincronizza il nuovo valore con il ciclo ordinario.
    """
    if not is_valid_id(job_id):
        return jsonify(error="ID brano non valido."), 404
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or "feedback" not in payload:
        return jsonify(error="Scegliere un livello di feedback."), 400
    feedback = payload["feedback"]
    if feedback is not None and (not isinstance(feedback, str) or feedback not in FEEDBACK_VALUES):
        return jsonify(error="Feedback non valido: usare good, average, bad oppure null."), 400

    # v2.65: il feedback e' LOCALE e non aspetta DRIVE_LOCK (puo' restare
    # acquisito durante molte richieste a Google Drive). LOCK impedisce letture
    # parziali ai thread locali e coordina la conclusione di un upload.
    with LOCK:
        info = JOBS.get(job_id)
        folder = JOBS_DIR / job_id
        path = folder / "result.json"
        # Un brano importato da Drive dopo l'ultimo refresh puo' essere solo
        # sul disco. Carichiamo solo quello, senza scandire tutta la libreria.
        if info is None and path.is_file() and (folder / TRACK_FILES["no_guitar"]).is_file():
            try:
                candidate = json.loads(path.read_text(encoding="utf-8"))
                if candidate.get("status") == "done":
                    JOBS[job_id] = candidate
                    info = candidate
            except (ValueError, OSError, TypeError, AttributeError):
                pass
        if not info or info.get("status") != "done" or not path.is_file():
            return jsonify(error="Brano non disponibile nella libreria locale."), 404
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(saved, dict) or saved.get("status") != "done":
                return jsonify(error="Metadati del brano non validi."), 409
            current = saved.get("user_feedback")
            if current == feedback or (current is None and feedback is None):
                return jsonify(feedback=feedback, changed=False, message="Feedback invariato.")
            if feedback is None:
                saved.pop("user_feedback", None)
            else:
                saved["user_feedback"] = feedback
            tmp = folder / ("result.feedback." + uuid.uuid4().hex + ".tmp")
            try:
                tmp.write_text(json.dumps(saved, ensure_ascii=False), encoding="utf-8")
                tmp.replace(path)
            finally:
                tmp.unlink(missing_ok=True)
            JOBS[job_id] = saved
            # Rimane in attesa per Drive. Se un upload e' gia' in corso,
            # publish_job ricontrolla i dati correnti prima di segnare synced.
            (folder / "drive_synced.json").unlink(missing_ok=True)
        except (OSError, ValueError, TypeError) as exc:
            logging.getLogger('feedback').exception('Salvataggio feedback non riuscito: %s', job_id)
            return jsonify(error="Impossibile salvare il giudizio: " + str(exc)[:120]), 500
    return jsonify(feedback=feedback, changed=True, message="Salvato sul PC; Google Drive sara' aggiornato al prossimo ciclo.")


@app.post("/api/jobs")
def submit():
    uploaded = request.files.get("file")
    if not uploaded or not uploaded.filename:
        return jsonify(error="Selezionare un file audio."), 400
    ext = Path(uploaded.filename).suffix.lower()
    if ext not in EXTENSIONS:
        return jsonify(error="Formato non supportato. Scegliere MP3, WAV, FLAC, M4A, OGG o AAC."), 400
    requested_language = request.form.get("language", "en")
    if requested_language not in {"", "en", "it", "es", "fr", "de", "pt"}:
        return jsonify(error="Lingua del canto non supportata."), 400
    # Utilizziamo sempre nomi interni generati, mai i nomi indicati nell'upload.
    job_id = uuid.uuid4().hex
    folder = JOBS_DIR / job_id
    folder.mkdir(parents=True)
    try:
        uploaded.save(folder / ("upload" + ext))
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    with LOCK:
        JOBS[job_id] = {"id": job_id, "name": Path(uploaded.filename).name[:160],
                        "status": "queued", "progress_percent": 0, "message": "In attesa di elaborazione...",
                        "chords": [], "duration": 0, "lyrics_status": "pending",
                        "requested_language": requested_language}
    POOL.submit(process_audio, job_id, ext)
    return jsonify(public_job(JOBS[job_id])), 202


@app.get("/api/jobs/<job_id>")
def job_status(job_id):
    if not is_valid_id(job_id):
        return jsonify(error="ID non valido."), 404
    with LOCK:
        job = JOBS.get(job_id)
        if job:
            return jsonify(public_job(job))
    return jsonify(error="Elaborazione non trovata."), 404


@app.get("/api/jobs/<job_id>/quality")
def job_quality(job_id):
    if not is_valid_id(job_id):
        return jsonify(error='ID brano non valido.'),400
    restore_library()
    with LOCK:
        song=JOBS.get(job_id)
        if not song or song.get('status')!='done':
            return jsonify(error='Brano non disponibile.'),404
        chords=[dict(c) for c in song.get('chords',[])]
        duration=float(song.get('duration') or 0)
    words=[]
    try:
        data=json.loads((JOBS_DIR/job_id/'lyrics.json').read_text(encoding='utf-8'))
        words=data.get('words',[]) if isinstance(data,dict) else []
    except (OSError,ValueError,TypeError):
        pass
    from harmonic_engine import analyze_song_quality
    response=jsonify(analyze_song_quality(chords,words,duration))
    response.headers['Cache-Control']='no-store'
    return response


@app.get("/api/jobs/<job_id>/audio")
@app.get("/api/jobs/<job_id>/download")
def job_audio(job_id):
    if not is_valid_id(job_id):
        return jsonify(error="ID non valido."), 404
    with LOCK:
        data = JOBS.get(job_id)
        if not data or data["status"] != "done":
            return jsonify(error="Base non disponibile."), 404
    audio_path = JOBS_DIR / job_id / "base_senza_chitarra.mp3"
    if not audio_path.is_file():
        return jsonify(error="File audio non trovato."), 404
    download = request.path.endswith("/download")
    return send_file(audio_path, mimetype="audio/mpeg", as_attachment=download,
                     download_name="base_senza_chitarra.mp3", conditional=True)


@app.get("/api/jobs/<job_id>/track/<preset>")
def job_track(job_id, preset):
    if not is_valid_id(job_id) or preset not in TRACK_FILES:
        return jsonify(error="Traccia non valida."), 404
    with LOCK:
        data = JOBS.get(job_id)
        if not data or data.get("status") != "done":
            return jsonify(error="Traccia non disponibile."), 404
    path = JOBS_DIR / job_id / TRACK_FILES[preset]
    if not path.is_file():
        return jsonify(error="Questo brano va rielaborato per usare il mixer."), 404
    return send_file(path, mimetype="audio/mpeg", conditional=True)


@app.patch("/api/jobs/<job_id>/chords")
def edit_job_chords(job_id):
    """Save human corrections, preserving mixer audio and syncing metadata to Drive."""
    if not is_valid_id(job_id):
        return jsonify(error="ID non valido."), 404
    payload = request.get_json(silent=True) or {}
    edits = payload.get("chords")
    if not isinstance(edits, list) or not (1 <= len(edits) <= 2000):
        return jsonify(error="Elenco accordi non valido."), 400
    validated = []
    try:
        for chord in edits:
            label = str(chord["chord"]).strip()
            if len(label) > 25 or not re.fullmatch(r"(?:N|[A-G](?:#|b)?[A-Za-z0-9+#/()]*)", label):
                raise ValueError("Sigla accordo non valida: " + label[:32])
            start, end = float(chord["start"]), float(chord["end"])
            if not (0 <= start < end and end - start >= .09):
                raise ValueError("Tempi accordo non validi.")
            validated.append({"start":round(start,2), "end":round(end,2),
                              "chord":label, "confidence":round(float(chord.get("confidence", 0)),2),
                              "edited":bool(chord.get("edited", False))})
        if validated[0]["start"] != 0:
            raise ValueError("Il primo accordo deve iniziare a 0 secondi.")
        for a,b in zip(validated,validated[1:]):
            if abs(a["end"] - b["start"]) > .015:
                raise ValueError("Gli intervalli devono essere consecutivi, senza buchi o sovrapposizioni.")
    except (TypeError, ValueError, KeyError) as exc:
        return jsonify(error=str(exc)[:250]), 400
    with LOCK:
        data = JOBS.get(job_id)
        if not data or data.get("status") != "done":
            return jsonify(error="Brano non disponibile."), 404
        if abs(validated[-1]["end"] - float(data.get("duration",0))) > 0.2:
            return jsonify(error="L'ultimo accordo deve terminare con il brano."), 400
        file = JOBS_DIR / job_id / "result.json"
        backup = file.with_name("result.prima_correzione.json")
        if not backup.exists() and file.exists():
            shutil.copy2(file, backup)
        # Conserva l'ancora A&S sulla parola se viene cambiata la sigla ma non
        # spostato l'inizio. Se si sposta il tempo, prevale il nuovo timing.
        previous_chords = data.get("chords", [])
        for chord in validated:
            # Gli accordi possono essere inseriti/eliminati dal leggio.
            # Non usare l'indice dell'array (cambia dopo un inserimento),
            # ma l'istante musicale rimasto invariato.
            old = next((old for old in previous_chords if isinstance(old, dict)
                        and abs(float(old.get('start', -10)) - chord['start']) < .015), None)
            anchor = old.get('word_index') if isinstance(old, dict) else None
            if isinstance(anchor, int) and 0 <= anchor < 5000:
                chord['word_index'] = anchor
        data["chords"] = validated
        data["message"] = "Accordi corretti manualmente; sincronizzazione Drive in attesa."
        data["chord_source"] = "corretto-manualmente"
        tmp = file.with_suffix(".tmp")
        tmp.write_text(json.dumps(public_job(data),ensure_ascii=False),encoding="utf-8")
        tmp.replace(file)
        (JOBS_DIR / job_id / "drive_synced.json").unlink(missing_ok=True)
    return jsonify(chords=validated, message="Correzione salvata sul PC; Drive si aggiornerà al prossimo ciclo.")


def save_lyrics(job_id: str, result: dict) -> None:
    # Karaoke AI puro: conserva gli avvisi perché Whisper può essere imperfetto.
    # Correzioni LRCLIB/manuali: impedisce che un salvataggio rovini il brano.
    origin = str(result.get('source', ''))
    if origin.startswith(('lrclib', 'correzione', 'accordiespartiti', 'stable', 'testo-fornito')):
        from karaoke_integrity import require_safe
        with LOCK:
            total_duration = float(JOBS[job_id]['duration'])
        require_safe(result.get('words'), total_duration, context='Salvataggio karaoke')
    folder = JOBS_DIR / job_id
    target = folder / 'lyrics.json'
    if target.exists():
        import datetime
        backups=folder/'backup_testi'
        backups.mkdir(exist_ok=True)
        stamp=datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        shutil.copy2(target,backups/f'lyrics_{stamp}.json')
    tmp = folder / 'lyrics.tmp'
    tmp.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
    tmp.replace(target)
    with LOCK:
        info = JOBS[job_id]
        # Trascrizione AI o LRCLIB cambia le parole: le vecchie ancore A&S
        # non sarebbero piu' valide. Si conserva il tempo di ogni accordo.
        lyric_dependent_keys = {'word_index','display_word_index','display_fraction',
                                'display_anchor_kind','display_anchor_offset'}
        if any(any(k in c for k in lyric_dependent_keys) for c in info.get('chords',[]) if isinstance(c,dict)):
            info['chords'] = [{k:v for k,v in c.items() if k not in lyric_dependent_keys}
                              for c in info['chords']]
            info.pop('chord_word_alignment',None)
        info['lyrics_status'] = 'ready' if result['words'] else 'empty'
        info['lyrics_count'] = len(result['words'])
        info['lyrics_language'] = result.get('language', '')
        info['lyrics_error'] = ''
        meta_tmp = folder / 'result.tmp'
        meta_tmp.write_text(json.dumps(public_job(info), ensure_ascii=False), encoding='utf-8')
        meta_tmp.replace(folder / 'result.json')
        # Su Drive l'aggiornamento verra' applicato nel prossimo ciclo (entro ~60s).
        (folder / 'drive_synced.json').unlink(missing_ok=True)


@app.get('/api/jobs/<job_id>/lyrics')
def get_job_lyrics(job_id):
    if not is_valid_id(job_id):
        return jsonify(error='ID non valido.'), 404
    with LOCK:
        info = JOBS.get(job_id)
        task = LYRIC_TASKS.get(job_id, {})
        if not info or info.get('status') != 'done':
            return jsonify(error='Brano non disponibile.'), 404
        state = dict(status=task.get('status', info.get('lyrics_status', 'missing')),
                     error=task.get('error', info.get('lyrics_error', '')),
                     progress_percent=task.get('progress_percent'),
                     started_at=task.get('started_at'), phase=task.get('phase'))
    path = JOBS_DIR / job_id / 'lyrics.json'
    if path.is_file():
        state.update(json.loads(path.read_text(encoding='utf-8')))
    else:
        state.update(words=[], language='')
    return jsonify(state)


def isolated_vocal_for_existing(job_id: str) -> Path:
    """Rende disponibile la voce isolata per rianalizzare vecchie canzoni.

    Una sola elaborazione Demucs aggiuntiva su brano gia' registrato: nessun costo cloud.
    """
    folder = JOBS_DIR / job_id
    target = folder / 'voce_isolata.mp3'
    if target.is_file():
        return target
    full = folder / TRACK_FILES['full']
    if not full.is_file():
        raise RuntimeError('Audio completo non trovato. Ricaricare la canzone dal PC.')
    temp = folder / '_vocals_temp'
    try:
        import torch
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
        from qualita_ai import demucs_args
        run_cmd([sys.executable, '-m', 'demucs', '-n', 'htdemucs_6s',
                 '-d', device, '--two-stems', 'vocals', *demucs_args(device, vocal_only=True),
                 '-o', str(temp), str(full)], timeout=7200)
        stem = temp / 'htdemucs_6s' / 'brano_completo' / 'vocals.wav'
        if not stem.is_file():
            raise RuntimeError('Demucs non ha prodotto la voce separata.')
        ffmpeg = ffmpeg_path()
        run_cmd([ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
                 '-i', str(stem), '-codec:a', 'libmp3lame', '-b:a', '192k',
                 str(target)], timeout=900)
    finally:
        shutil.rmtree(temp, ignore_errors=True)
    return target


def update_lyric_phase(job_id: str, phase: str, percent: float | None = None) -> None:
    with LOCK:
        current = LYRIC_TASKS.get(job_id)
        if current and current.get('status') == 'running':
            current['phase'] = phase
            current['progress_percent'] = (round(max(0.0,min(100.0,float(percent))),1)
                                           if percent is not None else None)


def transcribe_existing(job_id: str, model: str = 'medium', language: str | None = None) -> None:
    try:
        with LOCK:
            current = LYRIC_TASKS.get(job_id, {})
            LYRIC_TASKS[job_id] = {'status':'running', 'phase':'preparing',
                                   'started_at':current.get('started_at',time.time()),'error':''}
        update_lyric_phase(job_id, 'separating' if not (JOBS_DIR / job_id / 'voce_isolata.mp3').is_file() else 'preparing')
        source = isolated_vocal_for_existing(job_id)
        from lyrics import transcribe_audio
        result = transcribe_audio(str(source), model_name=model, language=language,
                                  progress_callback=lambda phase, percent=None: update_lyric_phase(job_id, phase, percent))
        update_lyric_phase(job_id,'saving')
        save_lyrics(job_id, result)
        with LOCK:
            LYRIC_TASKS[job_id] = {'status':'ready','phase':'complete','progress_percent':100,'error':''}
    except Exception as exc:
        logging.getLogger('karaoke').exception('Trascrizione non riuscita per il brano %s', job_id)
        with LOCK:
            LYRIC_TASKS[job_id] = {'status':'error','phase':'error','error':str(exc)[:500]}


@app.post('/api/jobs/<job_id>/transcribe-lyrics')
def transcribe_job_lyrics(job_id):
    if not is_valid_id(job_id):
        return jsonify(error='ID non valido.'), 404
    with LOCK:
        job = JOBS.get(job_id)
        if not job or job.get('status') != 'done':
            return jsonify(error='Brano non disponibile.'), 404
        if LYRIC_TASKS.get(job_id, {}).get('status') == 'running':
            return jsonify(error='Trascrizione gia in corso.'), 409
    if not ((JOBS_DIR / job_id / TRACK_FILES['full']).is_file() or (JOBS_DIR / job_id / 'voce_isolata.mp3').is_file()):
        return jsonify(error='Audio originale non presente. Ricarichi il brano dal PC.'), 409
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify(error='Formato della richiesta non valido.'), 400
    model = payload.get('model', 'medium')
    language = payload.get('language') or None
    if model not in {'medium','large-v3','small'} or language not in {None,'en','it','es','fr','de','pt'}:
        return jsonify(error='Modello o lingua non validi.'), 400
    with LOCK:
        LYRIC_TASKS[job_id] = {'status': 'running', 'phase': 'queued', 'started_at':time.time(), 'error': ''}
    POOL.submit(transcribe_existing, job_id, model, language)
    return jsonify(status='running', message='Trascrizione locale avviata.'), 202


def align_existing(job_id: str, verified_text: str, language: str, model: str) -> None:
    try:
        with LOCK:
            LYRIC_TASKS[job_id] = {'status':'running', 'error':''}
        source=isolated_vocal_for_existing(job_id)
        from lyrics import align_verified_text
        result=align_verified_text(str(source), verified_text,
                                   language=language, model_name=model)
        save_lyrics(job_id, result)
        with LOCK:
            LYRIC_TASKS[job_id] = {'status':'ready','error':''}
    except Exception as exc:
        with LOCK:
            LYRIC_TASKS[job_id] = {'status':'error','error':str(exc)[:300]}


@app.get('/api/jobs/<job_id>/online-lyrics')
def search_job_online_lyrics(job_id):
    if not is_valid_id(job_id):
        return jsonify(error='ID non valido.'), 404
    with LOCK:
        job=JOBS.get(job_id)
        if not job or job.get('status')!='done':
            return jsonify(error='Selezionare un brano elaborato.'), 404
    from lyrics_online import search, guess_artist_title
    artist_guess,title_guess=guess_artist_title(job.get('name',''))
    title=str(request.args.get('title') or title_guess).strip()
    artist=str(request.args.get('artist') or artist_guess).strip()
    query=str(request.args.get('query') or '').strip()
    if len(query)>200:
        return jsonify(error='Ricerca libera troppo lunga (massimo 200 caratteri).'), 400
    try:
        matches=search(title,artist,query)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except Exception as exc:
        return jsonify(error=str(exc)), 503
    return jsonify(results=matches,artist=artist,title=title,query=query,duration=job.get('duration'))


def align_online_existing(job_id: str, record_id: int, language: str, model: str, allow_estimated: bool = False) -> None:
    try:
        update_lyric_phase(job_id, 'fetching')
        from lyrics_online import by_id, extract_text
        from karaoke_guided import parse_lrc_lines, align_lrc_audio, quality_issues
        entry=by_id(record_id)
        with LOCK:
            duration=float(JOBS[job_id].get('duration') or 0)
        catalog_duration=float(entry.get('duration') or 0)
        anchors=parse_lrc_lines(entry)
        # Tempi LRC validi solo per la stessa registrazione (radio edit/live/remix
        # possono condividere titolo e parole pur avendo strutture diverse).
        if anchors:
            if duration>0 and catalog_duration>0 and abs(duration-catalog_duration)>5:
                raise ValueError('Durata della registrazione diversa dal testo sincronizzato: scegliere la versione esatta (tolleranza 5s).')
        elif duration>0 and catalog_duration>0 and abs(duration-catalog_duration)>12:
            raise ValueError('Durata troppo diversa dalla registrazione: selezionare un altro risultato.')
        text=extract_text(entry)
        update_lyric_phase(job_id, 'separating')
        vocal=isolated_vocal_for_existing(job_id)
        update_lyric_phase(job_id, 'aligning')
        if anchors:
            result=align_lrc_audio(str(vocal), entry, language=language,
                                   model_name=model, allow_estimated=allow_estimated)
        else:
            # Solo testo non sincronizzato: conserva la modalita' classica,
            # ma blocca risultati con timestamp palesemente impossibili.
            from lyrics import align_verified_text, load_mono_16k
            result=align_verified_text(str(vocal),text,language=language,model_name=model)
            vocal_duration=load_mono_16k(str(vocal)).size/16000
            issues=quality_issues(result['words'],vocal_duration)
            if issues:
                raise ValueError('Allineamento sospetto; testo precedente preservato. '+ '; '.join(issues[:3]))
        result.update(source='lrclib+stable-ts-'+model,lyrics_provider='LRCLIB',
                      lyrics_provider_id=record_id,lyrics_provider_url=f'https://lrclib.net/api/get/{record_id}',
                      lyrics_artist=str(entry.get('artistName') or '')[:150],
                      lyrics_title=str(entry.get('trackName') or '')[:150],
                      offset_seconds=0.0)
        update_lyric_phase(job_id, 'saving')
        save_lyrics(job_id,result)
        with LOCK:
            LYRIC_TASKS[job_id]={'status':'ready','phase':'complete','progress_percent':100,'error':''}
    except Exception as exc:
        logging.getLogger('karaoke').exception('Allineamento LRCLIB non riuscito: %s',job_id)
        with LOCK:
            LYRIC_TASKS[job_id]={'status':'error','phase':'error','error':str(exc)[:500]}


@app.post('/api/jobs/<job_id>/online-lyrics-align')
def online_job_lyrics_align(job_id):
    if not is_valid_id(job_id):return jsonify(error='ID non valido.'),404
    with LOCK:
        job=JOBS.get(job_id)
        if not job or job.get('status')!='done':return jsonify(error='Brano non disponibile.'),404
        if LYRIC_TASKS.get(job_id,{}).get('status')=='running':
            return jsonify(error='Elaborazione testo già in corso.'),409
    payload=request.get_json(silent=True) or {}
    try: record_id=int(payload.get('record_id'))
    except (ValueError,TypeError):return jsonify(error='Selezione testo non valida.'),400
    if record_id<=0:return jsonify(error='Selezione testo non valida.'),400
    language=str(payload.get('language') or 'en')
    model=str(payload.get('model') or 'medium')
    if language not in {'en','it','fr','es','de','pt'} or model not in {'medium','large-v3'}:
        return jsonify(error='Modello o lingua non supportati.'),400
    with LOCK:
        LYRIC_TASKS[job_id]={'status':'running','phase':'queued','started_at':time.time(),
                             'progress_percent':None,'error':''}
    allow_estimated = payload.get('allow_estimated') is True
    POOL.submit(align_online_existing,job_id,record_id,language,model,allow_estimated)
    return jsonify(ok=True,status='running'),202


@app.patch('/api/jobs/<job_id>/lyrics-offset')
def save_job_lyrics_offset(job_id):
    if not is_valid_id(job_id):return jsonify(error='ID non valido.'),404
    with LOCK:
        job=JOBS.get(job_id)
        if not job or job.get('status')!='done':return jsonify(error='Brano non disponibile.'),404
        if LYRIC_TASKS.get(job_id,{}).get('status')=='running':
            return jsonify(error='Attendere la fine dell’allineamento.'),409
    import math
    try:
        offset=float((request.get_json(silent=True) or {}).get('offset_seconds'))
        if not math.isfinite(offset) or abs(offset)>5:raise ValueError()
    except (TypeError,ValueError):return jsonify(error='Offset consentito: da -5 a +5 secondi.'),400
    path=JOBS_DIR/job_id/'lyrics.json'
    if not path.is_file():return jsonify(error='Testo non presente.'),404
    result=json.loads(path.read_text(encoding='utf-8'))
    result['offset_seconds']=round(offset,2)
    save_lyrics(job_id,result)
    return jsonify(offset_seconds=result['offset_seconds'],message='Offset salvato; Drive si aggiornerà al prossimo ciclo.')


@app.post('/api/jobs/<job_id>/align-lyrics')
def align_job_lyrics(job_id):
    if not is_valid_id(job_id):
        return jsonify(error='ID non valido.'), 404
    with LOCK:
        job=JOBS.get(job_id)
        if not job or job.get('status')!='done':
            return jsonify(error='Brano non disponibile.'), 404
        if LYRIC_TASKS.get(job_id,{}).get('status')=='running':
            return jsonify(error='Una operazione sul testo e gia in corso.'), 409
    payload=request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error='Dati non validi.'), 400
    verified_text=payload.get('text','')
    language=payload.get('language','en')
    model=payload.get('model','medium')
    if not isinstance(verified_text,str) or not 1<=len(verified_text.strip())<=20000 or \
       language not in {'en','it','es','fr','de','pt'} or model not in {'medium','large-v3'}:
        return jsonify(error='Controllare testo, lingua e modello.'), 400
    if not ((JOBS_DIR/job_id/'voce_isolata.mp3').exists() or
            (JOBS_DIR/job_id/TRACK_FILES['full']).exists()):
        return jsonify(error='Audio non disponibile su questo PC.'), 409
    with LOCK:
        LYRIC_TASKS[job_id]={'status':'running','phase':'queued','started_at':time.time(),'error':''}
    POOL.submit(align_existing,job_id,verified_text,language,model)
    return jsonify(status='running',message='Allineamento testo avviato.'), 202


@app.patch('/api/jobs/<job_id>/lyrics')
def edit_job_lyrics(job_id):
    if not is_valid_id(job_id):
        return jsonify(error='ID non valido.'), 404
    with LOCK:
        info = JOBS.get(job_id)
        if not info or info.get('status') != 'done':
            return jsonify(error='Brano non disponibile.'), 404
        duration = float(info.get('duration', 0))
        if LYRIC_TASKS.get(job_id, {}).get('status') == 'running':
            return jsonify(error='Attendere la fine della trascrizione.'), 409
    path = JOBS_DIR / job_id / 'lyrics.json'
    if not path.exists():
        return jsonify(error='Generare prima il testo automatico.'), 409
    try:
        from lyrics import validate_lyrics
        original = json.loads(path.read_text(encoding='utf-8'))
        incoming = request.get_json(silent=True)
        result = validate_lyrics(incoming, duration)
        result['source'] = original.get('source', result['source'])
        result['language'] = original.get('language', result['language'])
        for key in ('offset_seconds','lyrics_provider','lyrics_provider_id',
                    'lyrics_provider_url','lyrics_artist','lyrics_title'):
            if key in original:result[key]=original[key]
    except (ValueError, OSError, TypeError) as exc:
        return jsonify(error=str(exc)[:200]), 400
    backup = JOBS_DIR / job_id / 'lyrics.prima_correzione.json'
    if not backup.exists():
        shutil.copy2(path, backup)
    save_lyrics(job_id, result)
    return jsonify(status='ready', message='Testo e tempi salvati; sincronizzazione Drive in attesa.', **result)




@app.post('/api/jobs/<job_id>/lyrics-manual')
def edit_full_lyrics_manually(job_id):
    """Anteprima e salvataggio atomico del karaoke corretto senza rielaborare l'audio.

    Correzioni effettuate solo nella libreria locale: Drive riceverà poi
    il testo e gli accordi coerenti. Ogni salvataggio crea backup separati.
    """
    import datetime
    import hashlib
    from manual_lyrics_core import rewrite

    if not is_valid_id(job_id):
        return jsonify(error='ID del brano non valido.'), 404
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or data.get('mode') not in ('preview','apply'):
        return jsonify(error='Richiesta non valida.'), 400
    raw = data.get('text')
    if not isinstance(raw, str) or len(raw) > 20000:
        return jsonify(error='Il testo supera 20.000 caratteri.'), 400
    folder=JOBS_DIR / job_id
    lyrics_file=folder / 'lyrics.json'
    result_file=folder / 'result.json'
    with LOCK:
        info=JOBS.get(job_id)
        if not info or info.get('status')!='done':
            return jsonify(error='Brano non disponibile sul PC.'), 404
        if LYRIC_TASKS.get(job_id,{}).get('status')=='running':
            return jsonify(error='Attendere la fine dell’allineamento karaoke.'), 409
        if not lyrics_file.is_file() or not result_file.is_file():
            return jsonify(error='Nessun karaoke locale da modificare.'), 404
        try:
            old_lyric_bytes=lyrics_file.read_bytes()
            old_result_bytes=result_file.read_bytes()
            original=json.loads(old_lyric_bytes)
            old_words=original.get('words',[])
            old_chords=info.get('chords',[])
            digest=hashlib.sha256(old_lyric_bytes+old_result_bytes).hexdigest()
            result=rewrite(old_words,old_chords,raw,float(info.get('duration',0)))
        except (ValueError,KeyError,TypeError,OSError) as exc:
            return jsonify(error=str(exc)[:300]), 422

        if data['mode']=='preview':
            return jsonify(status='preview',revision=digest,stats=result['stats'],
                           excerpt=' '.join(w['text'] for w in result['words'][:35]))
        if data.get('revision') != digest:
            return jsonify(error='Il karaoke è cambiato dopo l’anteprima. Ripeta la verifica.'),409
        import uuid
        stamp=datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'_'+uuid.uuid4().hex[:6]
        backup=folder/'backup_manual'/stamp
        prev_info=dict(info)
        temp_lyrics=folder/'lyrics.manual.tmp'
        temp_result=folder/'result.manual.tmp'
        try:
            backup.mkdir(parents=True,exist_ok=False)
            (backup/'lyrics.json').write_bytes(old_lyric_bytes)
            (backup/'result.json').write_bytes(old_result_bytes)
            from karaoke_integrity import require_safe
            require_safe(result['words'], float(info.get('duration',0)), result['chords'], context='Editor karaoke')
            new_lyrics={**original,'words':result['words'],'source':'correzione-manuale',
                        'edited':True,'manual_correction_date':stamp}
            info['chords']=result['chords']
            info['lyrics_count']=len(result['words'])
            info['lyrics_status']='ready'
            info['lyrics_error']=''
            temp_lyrics.write_text(json.dumps(new_lyrics,ensure_ascii=False),encoding='utf-8')
            temp_result.write_text(json.dumps(public_job(info),ensure_ascii=False),encoding='utf-8')
            temp_lyrics.replace(lyrics_file)
            temp_result.replace(result_file)
            (folder/'drive_synced.json').unlink(missing_ok=True)
        except (OSError,TypeError,ValueError):
            JOBS[job_id]=prev_info
            try:
                lyrics_file.write_bytes(old_lyric_bytes)
                result_file.write_bytes(old_result_bytes)
            except OSError:
                logging.getLogger('lyrics-manual').exception('Impossibile ripristinare karaoke del brano %s',job_id)
            return jsonify(error='Salvataggio non riuscito; verificare i file del brano e i backup.'),500
        finally:
            temp_lyrics.unlink(missing_ok=True)
            temp_result.unlink(missing_ok=True)
        return jsonify(status='saved',stats=result['stats'],chords=result['chords'],
                       message='Testo modificato sul PC, backup creato; Drive si aggiornerà al prossimo ciclo.')




def realign_as_from_isolated_voice(job_id: str, score_url: str, language: str, model: str) -> None:
    """Ricostruisce da zero il karaoke usando la voce isolata e il testo A&S.

    Non usa i timestamp correnti. Una validazione rigorosa precede ogni scrittura.
    Il salvataggio normale crea un backup e invalida le vecchie ancore accordo-parola.
    """
    try:
        from as_import_core import parse_html, safe_url, _fetch, align_words, ImportErrorAS
        from lyrics import align_verified_text, validate_lyrics
        from karaoke_integrity import require_safe
        update_lyric_phase(job_id, 'lettura A&S')
        url=safe_url(score_url)
        score=parse_html(_fetch(url))
        source=score['words']
        if not 10 <= len(source) <= 2500:
            raise ValueError('Testo A&S troppo breve o troppo lungo per il riallineamento.')
        lines=[]
        last_line=None
        for word in source:
            line_id=word['line']
            if line_id!=last_line:
                lines.append([])
                last_line=line_id
            lines[-1].append(word['text'])
        verified_text='\n'.join(' '.join(line) for line in lines)
        if len(verified_text)>20000:
            raise ValueError('Testo A&S oltre 20.000 caratteri; nessun dato modificato.')
        update_lyric_phase(job_id,'preparazione voce')
        voice=isolated_vocal_for_existing(job_id)
        update_lyric_phase(job_id,'allineamento voce')
        aligned=align_verified_text(str(voice), verified_text,
                                    language=language, model_name=model)
        with LOCK:
            song=JOBS.get(job_id)
            if not song or song.get('status')!='done':
                raise ValueError('Brano non più disponibile.')
            duration=float(song.get('duration',0))
        # Mappa le parole dello spartito sui nuovi tempi Stable-ts, NON sui tempi
        # del karaoke eventualmente corrotto. Gli scostamenti vengono verificati.
        from difflib import SequenceMatcher
        def normalized_token(token):
            import unicodedata
            return ''.join(c for c in unicodedata.normalize('NFKD',str(token).casefold())
                           if c.isalnum() and not unicodedata.combining(c))
        seq_a=[normalized_token(w['text']) for w in source]
        seq_b=[normalized_token(w.get('text','')) for w in aligned.get('words',[])]
        sm=SequenceMatcher(None,seq_a,seq_b,autojunk=False)
        exact=sum(i2-i1 for op,i1,i2,j1,j2 in sm.get_opcodes() if op=='equal')
        if exact/max(len(seq_a),len(seq_b),1)<.68:
            raise ValueError('Stable-ts non ha riconosciuto abbastanza parole A&S. Nessun dato modificato; controllare che la registrazione corrisponda allo spartito.')
        from as_audio_recovery import direct_as_words
        words=direct_as_words(source,aligned['words'])
        if words is not None:
            match=1.0
        else:
            # Solo se Stable-ts ha omesso o modificato parole: la mappatura
            # tradizionale resta soggetta al controllo rigido dei tempi.
            words,match=align_words(source,aligned['words'])
        checked=validate_lyrics({'words':words,'language':language,
                                  'source':'testo-fornito+A&S+stable-ts-'+model},duration)
        # Se la mappatura A&S ha reintrodotto tempi troppo corti, un ultimo
        # recupero strettamente locale ripara la finestra, non l'intero brano.
        # L'operazione viene registrata come stima da verificare all'ascolto.
        from karaoke_integrity import audit_words
        if audit_words(checked['words'],duration):
            from karaoke_resilience import repair_unreliable_word_times
            from lyrics import load_mono_16k
            safer, last_estimates = repair_unreliable_word_times(
                checked['words'],load_mono_16k(str(voice)))
            if len(audit_words(safer,duration)) < len(audit_words(checked['words'],duration)):
                checked=validate_lyrics({'words':safer,'language':language,
                                         'source':'testo-fornito+A&S+stable-ts-'+model},duration)
                recover_info=aligned.setdefault('audio_recovery',{}).setdefault('local_estimates',{})
                earlier_indices=set(recover_info.get('estimated_indices',[]))
                recover_info['estimated_indices']=sorted(earlier_indices | set(last_estimates.get('estimated_indices',[])))
                recover_info['estimated_count']=len(recover_info['estimated_indices'])
        try:
            require_safe(checked['words'], duration, context='Nuovo allineamento A&S')
        except ValueError as exc:
            stats=aligned.get('audio_recovery',{})
            raise ValueError(
                f'{exc} (Rianalisi locale sulla voce: {stats.get("recovered",0)} '
                f'versi recuperati su {stats.get("attempted",0)} tentativi; '
                'nessuna modifica salvata). Se l’errore persiste, serve esaminare '
                'la voce isolata o la versione esatta della registrazione.'
            ) from exc
        # Il resto della libreria continua a usare l'offset precedente.
        previous_path=JOBS_DIR/job_id/'lyrics.json'
        offset=0.0
        if previous_path.is_file():
            try:
                previous=json.loads(previous_path.read_text(encoding='utf-8'))
                offset=float(previous.get('offset_seconds',0))
            except (ValueError,TypeError,KeyError,OSError):pass
        section_info=(aligned.get('audio_recovery') or {}).get('sections') or {}
        estimated=aligned.get('audio_recovery',{}).get('local_estimates',{})
        checked.update(source='testo-fornito+A&S+stable-ts-'+model,
                       language=language,lyrics_provider='A&S',
                       source_url=url,offset_seconds=offset,
                       word_match_score=round(match,3),edited=True,
                       vocal_section_alignment=section_info,
                       timing_method='stable-ts+local-estimates' if estimated.get('estimated_count') else 'stable-ts',
                       timing_estimated_word_count=int(estimated.get('estimated_count') or 0),
                       timing_estimated_word_indices=estimated.get('estimated_indices', []),
                       timing_notice=('Alcune parole sono temporizzate per stima locale. '
                                      'Controllare a orecchio, soprattutto vicino agli assoli.'
                                      if estimated.get('estimated_count') else ''))
        update_lyric_phase(job_id,'salvataggio')
        # La validazione viene ripetuta in save_lyrics; i dati originali vengono
        # copiati nei backup_testi e non si toccano le quattro tracce audio.
        save_lyrics(job_id,checked)
        with LOCK:
            LYRIC_TASKS[job_id]={'status':'ready','phase':'complete',
                'progress_percent':100,'error':'','recovered_from_as':True,
                'timing_estimated_word_count':int(estimated.get('estimated_count') or 0)}
    except Exception as exc:
        logging.getLogger('as-realignment').exception('Riallineamento A&S fallito %s',job_id)
        with LOCK:
            LYRIC_TASKS[job_id]={'status':'error','phase':'error',
                                  'error':str(exc)[:500]}


# 2.48: un solo passaggio per riallineare sia il testo A&S che la sua
# progressione musicale. Non usa l'offset del vecchio karaoke né lo modifica
# in due operazioni separate (che creerebbero disallineamenti temporanei).
def synchronize_as_playback(job_id: str, score_url: str, model: str, language: str) -> None:
    try:
        import datetime
        from as_import_core import parse_html, _fetch, safe_url
        from as_playback_sync import prepare_synced, source_text
        from lyrics import align_verified_text
        folder=JOBS_DIR/job_id
        lyrics_path=folder/'lyrics.json'
        result_path=folder/'result.json'
        with LOCK:
            song=JOBS.get(job_id)
            if not song or song.get('status')!='done':
                raise ValueError('Brano non disponibile.')
            if not lyrics_path.is_file() or not result_path.is_file():
                raise ValueError('Testo o accordi del brano mancanti.')
            lyric_before=lyrics_path.read_bytes()
            result_before=result_path.read_bytes()
            old_lyrics=json.loads(lyric_before)
            old_song=dict(song)
            duration=float(song['duration'])
        update_lyric_phase(job_id,'lettura dello spartito A&S')
        score_url=safe_url(score_url)
        score=parse_html(_fetch(score_url))
        lyrics_text=source_text(score)
        update_lyric_phase(job_id,'preparazione voce isolata')
        voice=isolated_vocal_for_existing(job_id)
        update_lyric_phase(job_id,'sincronizzazione fonetica con la voce')
        aligned=align_verified_text(str(voice),lyrics_text,language=language,model_name=model)
        update_lyric_phase(job_id,'collocazione accordi A&S')
        from chord_timeline import load_acoustic_reference
        ref,_=load_acoustic_reference(folder,old_song)
        # Onset audio storici servono SOLO a suddividere l'intro/assoli; le
        # sigle e le ancore sono sempre le stesse scelte su A&S.
        words,chords,stats=prepare_synced(score,aligned,old_lyrics.get('words',[]),
                                         ref or old_song.get('chords',[]),duration)
        # 2.50: dopo la sincronizzazione VOCALE, analizzare separatamente
        # le progressioni A&S delle pause musicali senza toccare i versi.
        update_lyric_phase(job_id,'allineamento armonico intro / intermezzi / assoli')
        unrefined_chords=[dict(c) for c in chords]
        try:
            from instrumental_timing import refine_from_saved_guitar as refine_instrumental
            suggested, instrumental_timing=refine_instrumental(chords,words,folder,ref)
            from karaoke_integrity import audit_chords
            if audit_chords(suggested,duration,words):
                chords=unrefined_chords
                stats.update(instrumental_audio_warning='Cambi acustici non coerenti: mantenuti i tempi dello spartito.',
                             instrumental_audio_available=True,instrumental_refined=0,
                             instrumental_audio_inserted=0,
                             instrumental_estimated=stats.get('instrumental_events',0))
            else:
                chords=suggested
                stats.update(instrumental_timing)
        except Exception:
            logging.getLogger('instrumental-timing').exception('Audio strumentale non analizzabile: mantengo stime A&S')
            chords=unrefined_chords
            stats.update(instrumental_audio_available=False,instrumental_refined=0,
                         instrumental_estimated=stats.get('instrumental_events',0),
                         instrumental_audio_warning='Audio chitarra non analizzabile: tempi strumentali stimati.')
        from karaoke_integrity import audit_words, audit_chords
        integrity_errors = audit_words(words,duration) + audit_chords(chords,duration,words)
        if integrity_errors:
            raise ValueError('Correzione non salvata: tempi non coerenti dopo il confronto completo. '
                             + ' '.join(integrity_errors[:4])
                             + ' Nessun file modificato; verificare i passaggi segnalati.')
        stats['correction_mode']='unified_2.53'
        if stats['source_unplaced_chords']:
            update_lyric_phase(job_id,'accordi da verificare: salvataggio dei tempi validi')
        # I tempi mostrati nella vecchia interfaccia includevano l'offset.
        # Il confronto visuale deve quindi confrontare orari effettivi,
        # non solo i valori grezzi del file lyrics.json.
        stats['first_display_before'] = (round(stats['first_voice_before'] +
            float(old_lyrics.get('offset_seconds',0) or 0),3)
            if stats['first_voice_before'] is not None else None)
        stats['previous_offset_seconds'] = float(old_lyrics.get('offset_seconds',0) or 0)
        if len(chords)<3:
            raise ValueError('Troppi pochi accordi dopo la sincronizzazione: dati conservati.')
        update_lyric_phase(job_id,'salvataggio sicuro e backup')
        timestamp=datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        new_lyrics={**old_lyrics,'words':words,'source':'accordiespartiti+voce',
                    'source_url':score_url,'lyrics_provider':'A&S',
                    'language':language,'edited':True,'offset_seconds':0.0,
                    'timing_method':'stable-ts-'+model+'+A&S',
                    'timing_estimated_word_count':stats['estimated_word_count'],
                    'playback_sync_date':timestamp,'playback_sync_stats':stats,
                    'as_unplaced_chord_groups':stats['source_unplaced_groups']}
        updated_song={**old_song,'chords':chords,'chord_source':'accordiespartiti',
                      'lyrics_status':'ready','lyrics_error':'',
                      'lyrics_count':len(words),'lyrics_language':language}
        tmp_l=folder/'lyrics.as_sync.tmp';tmp_r=folder/'result.as_sync.tmp'
        with LOCK:
            live=JOBS.get(job_id)
            if not live or live.get('status')!='done' or \
               lyrics_path.read_bytes()!=lyric_before or result_path.read_bytes()!=result_before:
                raise ValueError('Il brano è cambiato durante l’analisi. Nessuna modifica salvata.')
            backup=folder/'backup_as_sync'/timestamp
            backup.mkdir(parents=True,exist_ok=False)
            (backup/'lyrics.json').write_bytes(lyric_before)
            (backup/'result.json').write_bytes(result_before)
            try:
                tmp_l.write_text(json.dumps(new_lyrics,ensure_ascii=False),encoding='utf-8')
                tmp_r.write_text(json.dumps(public_job(updated_song),ensure_ascii=False),encoding='utf-8')
                # I due file vengono creati prima della sostituzione. Se la
                # seconda scrittura fallisce, entrambi tornano dai backup.
                tmp_l.replace(lyrics_path)
                tmp_r.replace(result_path)
            except (OSError,ValueError,TypeError):
                lyrics_path.write_bytes(lyric_before)
                result_path.write_bytes(result_before)
                raise
            finally:
                tmp_l.unlink(missing_ok=True)
                tmp_r.unlink(missing_ok=True)
            JOBS[job_id].update(updated_song)
            (folder/'drive_synced.json').unlink(missing_ok=True)
            LYRIC_TASKS[job_id]={'status':'ready','phase':'complete',
                                  'progress_percent':100,'error':'',
                                  'playback_sync_stats':stats}
    except Exception as exc:
        logging.getLogger('as-playback-sync').exception('Sincronizzazione audio A&S non riuscita: %s',job_id)
        with LOCK:
            LYRIC_TASKS[job_id]={'status':'error','phase':'error','error':str(exc)[:500]}


@app.post('/api/jobs/<job_id>/as-sync-playback')
@app.post('/api/jobs/<job_id>/as-correct-all')
def request_as_sync_playback(job_id):
    """Ricalcola da voce isolata i tempi di testo E accordi A&S con backup."""
    if not is_valid_id(job_id):
        return jsonify(error='ID del brano non valido.'),404
    payload=request.get_json(silent=True)
    if not isinstance(payload,dict):return jsonify(error='Dati non validi.'),400
    model=payload.get('model','small')
    language=payload.get('language','en')
    if model not in {'small','medium'} or language not in {'en','it','es','fr','de','pt'}:
        return jsonify(error='Modello o lingua non validi.'),400
    with LOCK:
        song=JOBS.get(job_id)
        if not song or song.get('status')!='done':return jsonify(error='Brano non disponibile.'),404
        if LYRIC_TASKS.get(job_id,{}).get('status')=='running':
            return jsonify(error='È già in corso un allineamento.'),409
        folder=JOBS_DIR/job_id
        lyric_path=folder/'lyrics.json'
        if not lyric_path.is_file():return jsonify(error='Testo non disponibile.'),409
        old=json.loads(lyric_path.read_text(encoding='utf-8'))
        from as_import_core import safe_url,ImportErrorAS
        try:
            url=safe_url(payload.get('url') or old.get('source_url') or '')
        except ImportErrorAS:
            return jsonify(error='Selezioni prima una scheda A&S oppure importi il testo da A&S.'),400
        if not ((folder/'voce_isolata.mp3').is_file() or (folder/TRACK_FILES['full']).is_file()):
            return jsonify(error='Non c’è la voce isolata né il brano completo su questo PC.'),409
        LYRIC_TASKS[job_id]={'status':'running','phase':'queued',
                              'started_at':time.time(),'error':''}
    POOL.submit(synchronize_as_playback,job_id,url,model,language)
    return jsonify(status='running',message='Sincronizzazione A&S con la voce avviata.'),202


@app.post('/api/jobs/<job_id>/as-realign')
def request_as_realign(job_id):
    """Operazione esplicita: ricrea tempi da voce isolata prima del correttore A&S."""
    if not is_valid_id(job_id):
        return jsonify(error='ID del brano non valido.'),404
    payload=request.get_json(silent=True)
    if not isinstance(payload,dict):
        return jsonify(error='Richiesta non valida.'),400
    from as_import_core import safe_url, ImportErrorAS
    try:
        url=safe_url(payload.get('url',''))
    except ImportErrorAS as exc:
        return jsonify(error=str(exc)),400
    model=payload.get('model','medium')
    language=payload.get('language','en')
    if model not in {'medium','large-v3'} or language not in {'en','it','es','fr','de','pt'}:
        return jsonify(error='Lingua o modello non validi.'),400
    with LOCK:
        info=JOBS.get(job_id)
        if not info or info.get('status')!='done':
            return jsonify(error='Brano non disponibile sul PC.'),404
        if LYRIC_TASKS.get(job_id,{}).get('status')=='running':
            return jsonify(error='Un allineamento è già in corso.'),409
        folder=JOBS_DIR/job_id
        if not ((folder/'voce_isolata.mp3').is_file() or (folder/TRACK_FILES['full']).is_file()):
            return jsonify(error='Audio del brano non disponibile per l’allineamento.'),409
        LYRIC_TASKS[job_id]={'status':'running','phase':'queued',
                              'started_at':time.time(),'error':''}
    POOL.submit(realign_as_from_isolated_voice,job_id,url,language,model)
    return jsonify(status='running',message='Ricostruzione tempi dalla voce isolata avviata.'),202


@app.post('/api/jobs/<job_id>/tabs-preview')
@app.post('/api/jobs/<job_id>/tabs-apply')
@app.post('/api/jobs/<job_id>/as-preview')
@app.post('/api/jobs/<job_id>/as-apply')
def correct_from_as(job_id):
    """Correzione A&S / Tabs & Chords sul PC: backup e sincronizzazione Drive.

    La pagina e' riletta per ogni operazione: il browser non puo' imporre
    timestamp o accordi non verificati dal motore del PC.
    """
    is_tabs = '/tabs-' in request.path
    if not is_valid_id(job_id):
        return jsonify(error='ID del brano non valido.'), 404
    if is_tabs and request.content_length and request.content_length > 220_000:
        return jsonify(error='Spartito troppo grande.'), 413
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or len(str(payload.get('url', ''))) > 1200 or (is_tabs and len(str(payload.get('text',''))) > 100_000):
        return jsonify(error='Richiesta di importazione non valida.'), 400
    applying = request.path.endswith('-apply')
    fix_words = payload.get('lyrics') is True
    fix_chords = payload.get('chords') is True
    if applying and not (fix_words or fix_chords):
        return jsonify(error='Selezionare parole e/o accordi.'), 400
    with LOCK:
        song = JOBS.get(job_id)
        if not song or song.get('status') != 'done':
            return jsonify(error='Brano non disponibile sul PC.'), 404
        if LYRIC_TASKS.get(job_id, {}).get('status') == 'running':
            return jsonify(error='Attendere la fine della trascrizione.'), 409
        folder = JOBS_DIR / job_id
        lyrics_file = folder / 'lyrics.json'
        result_file = folder / 'result.json'
        if not (lyrics_file.is_file() and result_file.is_file()):
            return jsonify(error='Il testo karaoke deve prima essere elaborato sul PC.'), 409
        old_lyrics_bytes = lyrics_file.read_bytes()
        old_result_bytes = result_file.read_bytes()
        import hashlib
        version = hashlib.sha256(old_lyrics_bytes + old_result_bytes).hexdigest()
        if applying and payload.get('base_version') != version:
            return jsonify(error='Il brano è cambiato dall’anteprima. Esegua nuovamente il confronto.'), 409
        try:
            old_lyrics = json.loads(old_lyrics_bytes)
            old_words = old_lyrics.get('words', [])
        except (ValueError, AttributeError):
            return jsonify(error='File karaoke locale non valido.'), 409
        if len(old_words) < 3:
            return jsonify(error='Il brano non dispone di un karaoke AI da correggere.'), 409
        duration = float(song.get('duration', 0))
        old_chords = list(song.get('chords', []))
        # Conserva la timeline AI indipendente dalle parole anche dopo molte
        # importazioni A&S: il primo backup_as contiene di norma l'originale.
        from chord_timeline import load_acoustic_reference
        ai_chords, ai_source = load_acoustic_reference(folder, song)
    try:
        from as_import_core import from_url, ImportErrorAS
        from lyrics import validate_lyrics
        if is_tabs:
            from tabs_chords_import import from_source
            imported = from_source(payload.get('text',''), payload.get('url',''), old_words, old_chords, duration)
        else:
            imported = from_url(payload.get('url'), old_words, old_chords, duration)
        provider = 'C&T · Ultimate Guitar' if is_tabs else 'A&S'
        if (is_tabs and applying and int(imported['stats'].get('estimated_words', 0))
                and not (payload.get('accept_estimated_timing') is True)):
            return jsonify(error='Il testo C&T contiene parole con tempi stimati. Confermare esplicitamente la stima nell’anteprima per salvare con backup.'), 409
        if (not is_tabs and applying and int(imported['stats'].get('source_unplaced_chords',0))
                and not (payload.get('accept_partial_as') is True)):
            return jsonify(error='Importazione A&S non fedele: alcuni accordi strumentali non hanno un intervallo valido. Riveda l’anteprima prima di confermare le omissioni.'),409
        verified = validate_lyrics({'words': imported['words'], 'language': old_lyrics.get('language', ''),
                                    'source': 'ultimate-guitar' if is_tabs else 'accordiespartiti'}, duration)
        chords = imported['chords']
        # A&S fornisce la PAROLA dell'accordo, non un timestamp musicale.
        # Usiamo l'audio della chitarra isolata, senza spostare ancore incerte.
        try:
            from chord_time_refiner import refine_from_saved_guitar
            chords, timing = refine_from_saved_guitar(chords, folder)
            imported['stats'].update(timing)
            if timing.get('audio_available'):
                imported['warning'] = (
                    f"Accordi sopra le parole dello spartito. {timing.get('refined', 0)} cambi "
                    "raffinati sulla chitarra isolata; i rimanenti conservano i tempi "
                    "stimati e vanno verificati all'ascolto."
                )
            else:
                imported['warning'] = (
                    'Chitarra isolata non disponibile per questo brano: '
                    'accordi sulla parola della fonte, tempi stimati dalla trascrizione.'
                )
        except Exception:
            logging.getLogger('chord-refiner').exception('Raffinamento audio non riuscito')
            imported['stats'].update(audio_available=False, refined=0)
            imported['warning'] = (
                'Raffinamento audio non disponibile: conservati i tempi stimati dallo spartito. '
                'Nessuna modifica alla base.'
            )
        # 2.50: ogni sequenza strumentale A&S usa i cambi armonici della
        # chitarra isolata come prova per affinare i tempi; NON sposta i versi.
        if not is_tabs:
            try:
                from instrumental_timing import refine_from_saved_guitar as refine_instrumental
                chords, instrumental_timing=refine_instrumental(chords,verified['words'],folder)
                imported['stats'].update(instrumental_timing)
                imported['warning'] += (
                    f" Strumentali: {instrumental_timing['instrumental_refined']} cambi "
                    "affinati sull'audio; gli altri sono stime da verificare."
                    if instrumental_timing['instrumental_audio_available'] else
                    ' Strumentali: senza chitarra isolata i tempi restano stimati.')
            except Exception:
                logging.getLogger('instrumental-timing').exception('Rifinitura accordi strumentali non disponibile')
                imported['stats'].update(instrumental_audio_available=False,
                                          instrumental_refined=0)
                imported['warning'] += ' Rifinitura strumentale non disponibile; tempi stimati invariati.'
        # 2.28: gli accordi sono una timeline musicale autonoma. Durante i
        # silenzi della VOCE (assoli e interludi) l'AI conserva i cambi rilevati
        # dalla chitarra, senza appoggiarli ai timestamp delle parole.
        from chord_timeline import preserve_instrumental_chords
        chords, instrumental_stats = preserve_instrumental_chords(
            chords, ai_chords, verified['words'], duration)
        imported['stats'].update(instrumental_stats, ai_chord_reference=ai_source)
        if not is_tabs:
            total=int(imported['stats'].get('source_total_chords',0))
            kept=int(imported['stats'].get('source_preserved',0))
            missing=int(imported['stats'].get('source_unplaced_chords',0))
            imported['stats']['source_fidelity']={'read':total,'preserved':kept,'unplaced':missing}
            imported['warning'] += (f' Fedelta A&S: {kept}/{total} eventi conservati dalla fonte, '
                                    f'{missing} non collocabili nel tempo; accordi ripetuti inclusi.')
        if instrumental_stats['instrumental_ai_events']:
            imported['warning'] += (' Cambi strumentali recuperati dalla timeline AI '
                                    'originale: verificare le sigle a orecchio.')
        elif ai_source == 'unavailable':
            imported['warning'] += (' Nessun riferimento AI originale disponibile: '
                                    'i cambi strumentali vanno verificati.')
        # Non nascondere progressioni strumentali presenti nello spartito che
        # non hanno un tempo verificabile: restano da confermare sull'audio.
        missing_rows = int(imported['stats'].get('source_unplaced_chords', 0)) if not is_tabs else int(imported['stats'].get('unplaced_chord_rows', 0))
        if missing_rows:
            imported['warning'] += (f' {missing_rows} accordi strumentali della fonte non collocabili nel tempo: '
                                    'mantenuti gli accordi AI dove disponibili; controllare a orecchio.')
        from karaoke_integrity import require_safe
        require_safe(verified['words'], duration, chords, context='Anteprima fonte esterna')
        if not chords or len(chords) > 2000 or chords[0]['start'] != 0 or \
           abs(chords[-1]['end'] - duration) > .2:
            raise ValueError('Intervalli degli accordi non validi.')
        for a, b in zip(chords, chords[1:]):
            if abs(a['end'] - b['start']) > .015:
                raise ValueError('Accordi con intervalli discontinui.')
    except (ImportErrorAS, ValueError, TypeError, OSError) as exc:
        return jsonify(error=str(exc)[:280]), 422
    except Exception:
        logging.getLogger('as-import').exception('Correzione esterna non riuscita')
        return jsonify(error='Non riesco a elaborare lo spartito: verificare URL, contenuto copiato e formato.'), 502
    if not applying:
        return jsonify(url=imported['url'], base_version=version, origin=imported.get('origin','A&S'), words=verified['words'], chords=chords,
                       stats=imported['stats'], warning=imported['warning'])
    with LOCK:
        if job_id not in JOBS or JOBS[job_id].get('status') != 'done':
            return jsonify(error='Brano cambiato durante l’importazione.'), 409
        if lyrics_file.read_bytes() != old_lyrics_bytes or result_file.read_bytes() != old_result_bytes:
            return jsonify(error='Il brano è stato modificato durante l’anteprima. Riprovare.'), 409
        import datetime
        stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        backups = folder / ('backup_tabs' if is_tabs else 'backup_as') / stamp
        backups.mkdir(parents=True, exist_ok=False)
        (backups / 'lyrics.json').write_bytes(old_lyrics_bytes)
        (backups / 'result.json').write_bytes(old_result_bytes)
        if ai_source == 'current' and not (folder / 'chords_ai_reference.json').exists():
            (folder / 'chords_ai_reference.json').write_bytes(old_result_bytes)
        previous = song.copy()
        lyrics_temp = folder / 'lyrics.as.tmp'
        result_temp = folder / 'result.as.tmp'
        try:
            if fix_words:
                new_lyrics = {**old_lyrics, **verified, 'source': 'ultimate-guitar' if is_tabs else 'accordiespartiti',
                              'source_url': imported['url'], 'lyrics_provider': provider,
                              'import_date': stamp,
                              **({'timing_estimated_word_count':int(imported['stats'].get('estimated_words',0)),
                                  'timing_review_needed':bool(imported['stats'].get('estimated_words',0))}
                                 if is_tabs else {}),
                              **({'tabs_correction_date':stamp} if is_tabs else {'as_correction_date':stamp})}
                lyrics_temp.write_text(json.dumps(new_lyrics, ensure_ascii=False), encoding='utf-8')
            if fix_chords:
                # La posizione esatta sulla parola e' valida soltanto se si
                # adottano insieme le parole A&S (altrimenti gli indici divergono).
                song['chords'] = chords if fix_words else [
                    {k:v for k,v in c.items() if k not in
                     ('word_index','source_word_index','source_fraction')}
                    for c in chords]
                song['chord_source'] = 'ultimate-guitar' if is_tabs else 'accordiespartiti'
            elif fix_words:
                # Testo modificato senza cambiare gli accordi: le ancore
                # precedenti vanno disattivate, restano i loro timestamp.
                song['chords'] = [{k:v for k,v in c.items() if k not in
                                   ('word_index','source_word_index','source_fraction')}
                                  for c in song.get('chords', [])]
                song['message'] = 'Accordi importati; attesa sincronizzazione Drive.'
            if fix_words:
                song['lyrics_status'] = 'ready'
                song['lyrics_count'] = len(verified['words'])
                song['lyrics_error'] = ''
            result_temp.write_text(json.dumps(public_job(song), ensure_ascii=False), encoding='utf-8')
            if fix_words:
                lyrics_temp.replace(lyrics_file)
            result_temp.replace(result_file)
            (folder / 'drive_synced.json').unlink(missing_ok=True)
        except (ValueError, TypeError, OSError):
            JOBS[job_id] = previous
            lyrics_file.write_bytes(old_lyrics_bytes)
            result_file.write_bytes(old_result_bytes)
            return jsonify(error='Errore di salvataggio: gli originali sono stati ripristinati.'), 500
        finally:
            lyrics_temp.unlink(missing_ok=True)
            result_temp.unlink(missing_ok=True)
    return jsonify(status='saved', chords=JOBS[job_id]['chords'],
                   stats=imported['stats'], backup_folder='data/jobs/<id>/' + ('backup_tabs' if is_tabs else 'backup_as'),
                   message='Dati salvati sul PC; sincronizzazione Drive in attesa.')



# 2.66 PC — Wizard di correzione: fonte -> conferma spartito -> un solo comando.
# Le proposte incerte NON vengono sovrascritte: il salvataggio e' transazionale.
SMART_SOURCES: dict[str, dict] = {}
SMART_TASKS: dict[str, dict] = {}


def _smart_phase(job_id: str, message: str):
    with LOCK:
        if job_id in SMART_TASKS and SMART_TASKS[job_id].get('status') == 'running':
            SMART_TASKS[job_id]['phase'] = message
        if LYRIC_TASKS.get(job_id,{}).get('status') == 'running':
            LYRIC_TASKS[job_id]['phase'] = message


@app.post('/api/jobs/<job_id>/smart-source-check')
def smart_source_check(job_id):
    """Verifica realmente URL e contenuto prima di consentire Correggi."""
    if not is_valid_id(job_id):
        return jsonify(error='ID non valido.'),404
    payload=request.get_json(silent=True)
    if not isinstance(payload,dict):return jsonify(error='Richiesta non valida.'),400
    provider=str(payload.get('provider',''))
    url=str(payload.get('url',''))
    if provider not in {'as','ct'} or len(url)>1200:
        return jsonify(error='Selezionare una fonte e uno spartito validi.'),400
    with LOCK:
        job=JOBS.get(job_id)
        if not job or job.get('status')!='done':
            return jsonify(error='Aprire prima il brano sul PC.'),404
        if LYRIC_TASKS.get(job_id,{}).get('status')=='running' or SMART_TASKS.get(job_id,{}).get('status')=='running':
            return jsonify(error='Un altro allineamento e\' in corso.'),409
        folder=JOBS_DIR/job_id
        lp=folder/'lyrics.json';rp=folder/'result.json'
        if not lp.is_file() or not rp.is_file():
            return jsonify(error='Completare prima la prima elaborazione del brano.'),409
        from smart_correction import file_revision
        revision=file_revision(lp.read_bytes(),rp.read_bytes())
    try:
        from smart_correction import source_score,source_summary,PROVIDERS
        safe,score=source_score(provider,url)
        summary=source_summary(score)
    except (ValueError,TypeError,OSError) as exc:
        return jsonify(error=str(exc)[:320]),422
    except Exception as exc:
        from as_import_core import ImportErrorAS
        if isinstance(exc, ImportErrorAS):
            return jsonify(error=str(exc)[:320]),422
        # Le pagine sono esterne: un risultato non leggibile non e' una conferma.
        logging.getLogger('smart-correction').warning('Fonte non disponibile: %s',exc)
        return jsonify(error='Impossibile leggere il contenuto della scheda selezionata: provare un’altra versione.'),422
    with LOCK:
        # La verifica non vincola un contenuto remoto al brano se il PC e' cambiato.
        if (not lp.is_file() or not rp.is_file() or
                file_revision(lp.read_bytes(),rp.read_bytes())!=revision):
            return jsonify(error='Il brano e\' cambiato durante la verifica: ripetere la ricerca.'),409
        now=time.time()
        # Conserva solo le ultime verifiche per evitare crescita incontrollata.
        for k,v in list(SMART_SOURCES.items()):
            if now-v['created']>1200:SMART_SOURCES.pop(k,None)
        token=uuid.uuid4().hex
        SMART_SOURCES[token]={'job_id':job_id,'provider':provider,'url':safe,
                              'revision':revision,'score':score,'created':now}
        if len(SMART_SOURCES)>60:
            oldest=min(SMART_SOURCES,key=lambda key:SMART_SOURCES[key]['created'])
            SMART_SOURCES.pop(oldest,None)
    return jsonify(token=token,url=safe,provider=provider,label=PROVIDERS[provider],
                   **summary)


def _run_smart_correction(job_id: str, verified: dict, language: str):
    """Allineamento vocalico per ENTRAMBE le fonti, con salvataggio protetto.

    Ogni operazione e' eseguita sulla stessa scheda che l'utente ha confermato.
    Fino alla validazione completa non si sovrascrive nessun file del brano.
    """
    try:
        import datetime
        from smart_correction import file_revision, safety_review, make_candidate
        from as_playback_sync import source_text, prepare_synced
        from chord_timeline import load_acoustic_reference,preserve_instrumental_chords
        from karaoke_integrity import require_safe
        from lyrics import align_verified_text
        folder=JOBS_DIR/job_id
        lp=folder/'lyrics.json';rp=folder/'result.json'
        with LOCK:
            info=JOBS.get(job_id)
            if not info or info.get('status')!='done':
                raise ValueError('Il brano non e\' disponibile.')
            raw_l=lp.read_bytes();raw_r=rp.read_bytes()
            if file_revision(raw_l,raw_r)!=verified['revision']:
                raise ValueError('Il brano e\' cambiato dopo la conferma della fonte: ripetere la verifica.')
            original_lyrics=json.loads(raw_l)
            original_song=dict(info)
            duration=float(info['duration'])
        score=verified['score'];provider=verified['provider']
        _smart_phase(job_id,'Preparazione della voce isolata')
        voice=isolated_vocal_for_existing(job_id)
        _smart_phase(job_id,'Allineamento delle parole con la voce')
        aligned=align_verified_text(str(voice),source_text(score),language=language,model_name='small')
        _smart_phase(job_id,'Ricostruzione degli accordi dalla fonte selezionata')
        ai_chords,_=load_acoustic_reference(folder,original_song)
        source_provider='accordiespartiti' if provider=='as' else 'ultimate-guitar'
        words,chords,stats=prepare_synced(score,aligned,original_lyrics.get('words',[]),
            ai_chords or original_song.get('chords',[]),duration,provider=source_provider)
        require_safe(words,duration,chords,context='Correzione automatica')
        _smart_phase(job_id,'Controllo dei cambi musicali e degli intermezzi')
        guitar=folder/'chitarra_isolata.mp3'
        if guitar.is_file():
            try:
                from chord_time_refiner import refine_from_saved_guitar
                chords,refined=refine_from_saved_guitar(chords,folder)
                stats.update(refined)
            except Exception:
                logging.getLogger('smart-correction').exception('Rifinitura accordi non disponibile: tempi sorgente conservati')
            if provider=='as':
                try:
                    from instrumental_timing import refine_from_saved_guitar
                    suggested, harm=refine_from_saved_guitar(chords,words,folder,ai_chords)
                    require_safe(words,duration,suggested,context='Rifinitura strumentale')
                    chords=suggested
                    stats.update(harm)
                except Exception:
                    logging.getLogger('smart-correction').exception('Rifinitura strumentale annullata: stime precedenti conservate')
        chords,ai_stats=preserve_instrumental_chords(chords,ai_chords,words,duration)
        stats.update(ai_stats)
        stamp=datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        candidate_l,candidate_song=make_candidate(original_lyrics,original_song,
            words,chords,stats,provider,verified['url'],stamp)
        candidate_l['language']=language
        candidate_song['lyrics_language']=language
        # Se in uno spartito A&S una progressione risulta senza spazio, tentare
        # il recupero basato su chitarra e la verifica dei motivi, SENZA salvare.
        if provider=='as' and guitar.is_file():
            try:
                from chords import chroma_mix
                from as_gap_recovery import repair_gap
                from as_motif_recovery import recover_repeated_instrumentals
                chroma,dt,_,_=chroma_mix(str(guitar),max_seconds=600)
                if stats.get('source_unplaced_groups'):
                    candidate_l,candidate_song,gap=repair_gap(candidate_l,candidate_song,chroma,dt)
                    stats['source_unplaced_chords']=gap['remaining_unplaced']
                    stats['source_unplaced_groups']=candidate_l.get('as_unplaced_chord_groups',[])
                    stats['gap_recovered_chords']=gap['chords_recovered']
                    stats['repeated_chords_added']=gap.get('repeated_chords_added',0)
                else:
                    candidate_l,candidate_song,reps=recover_repeated_instrumentals(candidate_l,candidate_song,chroma,dt)
                    stats['repeated_chords_added']=reps['repeated_chords_added']
            except Exception:
                logging.getLogger('smart-correction').exception('Recupero motivi non applicabile: controllo prosegue conservativamente')
        words=candidate_l['words']; chords=candidate_song['chords']
        _smart_phase(job_id,'Validazione finale e protezione dei dati')
        issues=safety_review(words,chords,duration,stats,guitar_available=guitar.is_file())
        # Le ripetizioni dedotte dai soli sono ipotesi da approvare all'ascolto.
        if int(stats.get('repeated_chords_added',0) or 0)>0:
            issues.append('Progressioni ripetute dedotte dall’audio: verificare a orecchio prima di salvare.')
        if issues:
            with LOCK:
                SMART_TASKS[job_id].update(status='review',phase='Risultato da verificare',
                    issues=issues, stats=stats,finished_at=time.time())
                LYRIC_TASKS[job_id]={'status':'ready', 'phase':'smart_review','error':''}
            return
        require_safe(words,duration,chords,context='Salvataggio intelligente')
        with LOCK:
            if (not lp.is_file() or not rp.is_file() or
                    file_revision(lp.read_bytes(),rp.read_bytes())!=verified['revision']):
                raise ValueError('Il brano e\' stato modificato nel frattempo: nessun dato sovrascritto.')
            backup=folder/'backup_smart_266'/stamp
            backup.mkdir(parents=True,exist_ok=False)
            (backup/'lyrics.json').write_bytes(raw_l)
            (backup/'result.json').write_bytes(raw_r)
            lt=folder/'lyrics.smart.tmp';rt=folder/'result.smart.tmp'
            try:
                lt.write_text(json.dumps(candidate_l,ensure_ascii=False),encoding='utf-8')
                rt.write_text(json.dumps(public_job(candidate_song),ensure_ascii=False),encoding='utf-8')
                lt.replace(lp);rt.replace(rp)
            except Exception:
                lp.write_bytes(raw_l);rp.write_bytes(raw_r)
                raise
            finally:
                lt.unlink(missing_ok=True);rt.unlink(missing_ok=True)
            JOBS[job_id].update(candidate_song)
            (folder/'drive_synced.json').unlink(missing_ok=True)
            SMART_TASKS[job_id].update(status='saved',phase='Completato',stats=stats,
                issues=[],finished_at=time.time())
            LYRIC_TASKS[job_id]={'status':'ready','phase':'complete','error':'',
                                 'progress_percent':100}
    except Exception as exc:
        logging.getLogger('smart-correction').exception('Correzione automatica %s fallita',job_id)
        with LOCK:
            SMART_TASKS[job_id].update(status='error',phase='Errore',
                error=str(exc)[:420],finished_at=time.time())
            LYRIC_TASKS[job_id]={'status':'ready','phase':'smart_error','error':''}


@app.post('/api/jobs/<job_id>/smart-correct')
def start_smart_correction(job_id):
    if not is_valid_id(job_id):return jsonify(error='ID non valido.'),404
    payload=request.get_json(silent=True)
    if not isinstance(payload,dict):return jsonify(error='Richiesta non valida.'),400
    token=str(payload.get('token',''))
    language=str(payload.get('language','en'))
    if language not in {'en','it','es','fr','de','pt'}:
        return jsonify(error='Lingua non valida.'),400
    with LOCK:
        verified=SMART_SOURCES.get(token)
        if not verified or verified['job_id']!=job_id or time.time()-verified['created']>1200:
            return jsonify(error='La verifica dello spartito e\' scaduta: selezioni nuovamente la fonte.'),409
        if LYRIC_TASKS.get(job_id,{}).get('status')=='running' or SMART_TASKS.get(job_id,{}).get('status')=='running':
            return jsonify(error='Una correzione e\' gia\' in corso.'),409
        lp=JOBS_DIR/job_id/'lyrics.json';rp=JOBS_DIR/job_id/'result.json'
        from smart_correction import file_revision
        if not lp.is_file() or not rp.is_file() or file_revision(lp.read_bytes(),rp.read_bytes())!=verified['revision']:
            return jsonify(error='Il brano e\' cambiato: ripetere la conferma dello spartito.'),409
        SMART_SOURCES.pop(token,None)  # Il token e' monouso.
        SMART_TASKS[job_id]={'status':'running','phase':'In attesa di elaborazione',
            'provider':verified['provider'],'started_at':time.time(),'issues':[],'error':''}
        LYRIC_TASKS[job_id]={'status':'running','phase':'smart_correction',
            'started_at':time.time(),'error':''}
    POOL.submit(_run_smart_correction,job_id,verified,language)
    return jsonify(status='running',message='Correzione avviata.'),202


@app.get('/api/jobs/<job_id>/smart-correct')
def smart_correction_status(job_id):
    if not is_valid_id(job_id):return jsonify(error='ID non valido.'),404
    with LOCK:
        if job_id not in JOBS:return jsonify(error='Brano non disponibile.'),404
        task=SMART_TASKS.get(job_id)
        if not task:return jsonify(status='idle')
        return jsonify({key:value for key,value in task.items()
                        if key in {'status','phase','issues','error','stats','started_at','finished_at','provider'}})


# 2.38 — operazione Demucs indipendente dalla coda di nuove canzoni.
# Una ricostruzione per volta evita due elaborazioni GPU concorrenti.
GUITAR_RECOVERY_POOL = ThreadPoolExecutor(max_workers=1)
GUITAR_RECOVERY_TASKS = {}


def guitar_recovery_payload(job_id):
    from guitar_recovery import has_usable_guitar, has_usable_full
    folder = JOBS_DIR / job_id
    task = dict(GUITAR_RECOVERY_TASKS.get(job_id, {}))
    ready = has_usable_guitar(folder)
    full = has_usable_full(folder)
    state = task.get('state', 'ready' if ready else 'missing')
    if ready and state != 'running':
        state = 'ready'
    return {
        'state': state, 'has_guitar': ready, 'has_full': full,
        'phase': task.get('phase', ''),
        'progress_percent': task.get('progress_percent'),
        'message': task.get('message', ''),
        'error': task.get('error', ''),
    }


def run_guitar_recovery(job_id):
    folder = JOBS_DIR / job_id
    def report(phase, pct=None):
        with LOCK:
            GUITAR_RECOVERY_TASKS[job_id].update(phase=phase,
                progress_percent=((95 if phase.startswith('conversione') else 99 if phase.startswith('salvataggio') else round(min(100, max(0, float(pct))) * .90, 1)) if pct is not None else None),
                message='Ricostruzione chitarra isolata in corso. Non chiudere Guitar Backing Leon.')
    try:
        from guitar_recovery import recover_guitar
        outcome = recover_guitar(folder, demucs_runner=run_demucs_with_progress,
            ffmpeg_runner=run_cmd, ffmpeg_executable=ffmpeg_path(), report=report)
        with LOCK:
            GUITAR_RECOVERY_TASKS[job_id].update(state='done', phase='completata',
                progress_percent=100, message=('Traccia chitarra già disponibile.' if outcome == 'already_present'
                    else 'Chitarra ricostruita da brano_completo.mp3. Ora avvio il confronto degli accordi.'),error='')
    except Exception as exc:
        logging.getLogger('guitar-recovery').exception('Ricostruzione chitarra fallita per %s',job_id)
        with LOCK:
            GUITAR_RECOVERY_TASKS[job_id].update(state='error', phase='errore',
                progress_percent=None, error=str(exc)[:520],
                message='Ricostruzione non riuscita. Il brano, il karaoke e gli accordi non sono stati modificati.')


@app.route('/api/jobs/<job_id>/guitar/rebuild', methods=['GET', 'POST'])
def guitar_rebuild(job_id):
    if not is_valid_id(job_id):
        return jsonify(error='ID brano non valido.'), 404
    restore_library()
    with LOCK:
        song = JOBS.get(job_id)
        if not song or song.get('status') != 'done':
            return jsonify(error='Brano non disponibile nella libreria locale.'), 404
        info = guitar_recovery_payload(job_id)
        if request.method == 'GET':
            response = jsonify(info)
            response.headers['Cache-Control'] = 'no-store'
            return response
        if info['has_guitar']:
            return jsonify(info)
        if info['state'] == 'running':
            return jsonify(info), 202
        if not info['has_full']:
            return jsonify(error='Manca brano_completo.mp3 in questa installazione. Importi il brano completo da Drive oppure carichi l’originale.'), 409
        if any(t.get('state') == 'running' for t in GUITAR_RECOVERY_TASKS.values()):
            return jsonify(error='Un’altra ricostruzione della chitarra è in corso. Riprovare al termine.'), 409
        GUITAR_RECOVERY_TASKS[job_id] = {'state':'running', 'phase':'preparazione',
            'progress_percent':None, 'message':'Avvio Demucs sul file completo già salvato.',
            'error':'', 'started_at':time.time()}
        try:
            GUITAR_RECOVERY_POOL.submit(run_guitar_recovery, job_id)
        except Exception:
            GUITAR_RECOVERY_TASKS.pop(job_id, None)
            return jsonify(error='Impossibile avviare la ricostruzione.'), 500
        return jsonify(guitar_recovery_payload(job_id)), 202


# Le proposte sono temporanee. Ogni cambiamento e' selezionato manualmente.
CHORD_AI_REVIEW_DRAFTS = {}


@app.post('/api/jobs/<job_id>/chords/ai-review')
def preview_chord_ai_review(job_id):
    if not is_valid_id(job_id):
        return jsonify(error='ID brano non valido.'), 404
    restore_library()
    with LOCK:
        info=JOBS.get(job_id)
        if not info or info.get('status')!='done':
            return jsonify(error='Brano non disponibile sul PC.'), 404
        folder=JOBS_DIR/job_id
        saved=folder/'result.json'
        if not saved.is_file():return jsonify(error='Dati del brano mancanti.'),404
        old_bytes=saved.read_bytes()
        import hashlib
        fingerprint=hashlib.sha256(old_bytes).hexdigest()
        song=json.loads(old_bytes)
        chords=song.get('chords',[])
        duration=float(song.get('duration') or 0)
    try:
        from chord_ai_review import analyze_guitar,make_proposals
        estimated=analyze_guitar(folder)
        proposals,stats=make_proposals(chords,estimated,duration)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        return jsonify(error=str(exc)[:440]),409
    except Exception:
        logging.getLogger('chord-ai-review').exception('Nuova analisi chitarra non riuscita')
        return jsonify(error='Analisi della chitarra non riuscita. Nessun dato modificato.'),500
    with LOCK:
        if not saved.is_file() or hashlib.sha256(saved.read_bytes()).hexdigest()!=fingerprint:
            return jsonify(error='Il brano e’ cambiato durante l’analisi. Ripetere.'),409
        now=time.monotonic()
        for key,draft in list(CHORD_AI_REVIEW_DRAFTS.items()):
            if now-draft['time']>1200:CHORD_AI_REVIEW_DRAFTS.pop(key,None)
        preview_id=uuid.uuid4().hex
        CHORD_AI_REVIEW_DRAFTS[preview_id]={
            'job_id':job_id,'hash':fingerprint,'time':now,'proposals':proposals}
    return jsonify(status='preview',preview_id=preview_id,proposals=proposals,
        stats=stats,source='nuova analisi di chitarra_isolata.mp3',
        message=(f"{len(proposals)} correzioni proposte: selezioni soltanto quelle che ritiene corrette."
                 if proposals else 'Analisi della chitarra completata: non emergono differenze abbastanza chiare. Le armonie rilevate non sono necessariamente esatte.'))


@app.post('/api/jobs/<job_id>/chords/ai-apply')
def apply_chord_ai_review(job_id):
    if not is_valid_id(job_id):return jsonify(error='ID brano non valido.'),404
    payload=request.get_json(silent=True) or {}
    preview_id=str(payload.get('preview_id',''))
    selected=payload.get('selected_ids')
    if not re.fullmatch(r'[0-9a-f]{32}',preview_id):
        return jsonify(error='Anteprima non valida. Ripetere l’analisi.'),400
    import hashlib
    import datetime
    with LOCK:
        draft=CHORD_AI_REVIEW_DRAFTS.get(preview_id)
        if not draft or draft['job_id']!=job_id or time.monotonic()-draft['time']>1200:
            return jsonify(error='Anteprima scaduta. Ripetere l’analisi.'),409
        folder=JOBS_DIR/job_id;file=folder/'result.json'
        if not file.is_file():return jsonify(error='Dati del brano mancanti.'),404
        old_bytes=file.read_bytes()
        if hashlib.sha256(old_bytes).hexdigest()!=draft['hash']:
            return jsonify(error='Il brano è cambiato dopo l’anteprima. Nessuna sovrascrittura.'),409
        song=json.loads(old_bytes)
        try:
            from chord_ai_review import apply_selected
            chords=apply_selected(song.get('chords',[]), draft['proposals'],selected,float(song.get('duration',0)))
        except (ValueError,KeyError,TypeError) as exc:
            return jsonify(error=str(exc)[:320]),409
        backup=folder/'backup_auto_chords'/datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        backup.mkdir(parents=True,exist_ok=False)
        (backup/'result.json').write_bytes(old_bytes)
        updated={**song,'chords':chords,'chord_source':str(song.get('chord_source',''))+'+revisione-ia-chitarra',
                 'message':f'{len(selected)} correzioni accordi approvate dopo confronto con la chitarra isolata.'}
        temp=file.with_name('result.chord-ai-review.tmp')
        try:
            temp.write_text(json.dumps(updated,ensure_ascii=False),encoding='utf-8')
            temp.replace(file)
            JOBS[job_id]=updated
            (folder/'drive_synced.json').unlink(missing_ok=True)
            CHORD_AI_REVIEW_DRAFTS.pop(preview_id,None)
        except Exception:
            temp.unlink(missing_ok=True)
            file.write_bytes(old_bytes)
            return jsonify(error='Salvataggio non riuscito: ripristinati i dati precedenti.'),500
    return jsonify(status='saved',chords=chords,changed=len(selected),
         message=f'{len(selected)} correzioni applicate. Backup creato; sincronizzi PC → Drive per lo smartphone.')



# 2.45: true review of musical chord onsets, including imported edited=True
# events. Nothing is written until the user confirms audio proposals.
CHORD_WORD_ALIGN_POOL = ThreadPoolExecutor(max_workers=1)
CHORD_WORD_ALIGN_TASKS = {}


def _chord_word_state_public(state):
    """Never return cached chord/song bytes through the progress endpoint."""
    if not state:
        return {'state': 'idle', 'message': 'Nessuna analisi in corso.'}
    return {k: v for k, v in state.items() if k != '_draft'}


def run_chord_word_alignment(job_id, song_hash, lyric_hash):
    import hashlib
    import uuid
    folder = JOBS_DIR / job_id
    result_file = folder / 'result.json'
    lyric_file = folder / 'lyrics.json'
    def phase(message):
        with LOCK:
            state = CHORD_WORD_ALIGN_TASKS.get(job_id)
            if state is not None and state.get('state') == 'running':
                state['message'] = message
    try:
        original_song = result_file.read_bytes()
        original_lyrics = lyric_file.read_bytes()
        if (hashlib.sha256(original_song).hexdigest() != song_hash or
                hashlib.sha256(original_lyrics).hexdigest() != lyric_hash):
            raise ValueError('I dati del brano sono cambiati: riavviare l’analisi.')
        song = json.loads(original_song)
        lyrics = json.loads(original_lyrics)
        words = lyrics.get('words', [])
        chords = song.get('chords', [])
        if not isinstance(words, list) or len(words) < 2:
            raise ValueError('Servono parole sincronizzate: correggere prima il testo.')
        if not isinstance(chords, list) or not chords:
            raise ValueError('Il brano non contiene accordi da allineare.')
        from chord_ai_review import valid_timeline
        duration = float(song.get('duration') or 0)
        if not valid_timeline(chords, duration):
            raise ValueError('Timeline musicale non valida: correggere prima i cambi.')
        phase('Analisi della traccia audio e confronto dei tempi degli accordi…')
        from chord_word_align import align_with_audio
        proposed, stats = align_with_audio(chords, words,
            float(lyrics.get('offset_seconds') or 0), duration, folder)
        moves = list(stats.pop('proposals', []))
        stale = int(stats.get('stale_word_links', 0))
        proposed_ids = {v['id'] for v in moves}
        if not moves and not stale:
            message = (f'Nessuna modifica attendibile: esaminati '
                f"{stats['acoustic_boundaries_examined']} cambi musicali; "
                'gli accordi risultano già coerenti entro la precisione rilevabile. '
                'Se l’errore rimane visibile, controlli la sincronizzazione delle parole '
                'oppure corregga manualmente il cambio. Nessun file modificato.')
            with LOCK:
                CHORD_WORD_ALIGN_TASKS[job_id] = {
                    'state': 'unchanged', 'message': message, 'stats': stats,
                    'proposals': [], 'draft_id': None}
            return
        draft_id = uuid.uuid4().hex
        phase('Anteprima delle correzioni: nessun dato è stato ancora modificato…')
        with LOCK:
            CHORD_WORD_ALIGN_TASKS[job_id] = {
                'state': 'preview',
                'message': (f'{len(moves)} cambi da valutare; {stale} collegamenti parola da riparare. '
                            'Selezioni gli spostamenti da applicare e confermi.'),
                'stats': stats, 'proposals': moves, 'draft_id': draft_id,
                '_draft': {'created': time.monotonic(),
                           'song_hash': song_hash, 'lyric_hash': lyric_hash,
                           'proposed': proposed, 'allowed': proposed_ids}}
    except Exception as exc:
        logging.getLogger('chord-word-alignment').exception(
            'Verifica audio/accordi non riuscita: %s', job_id)
        with LOCK:
            CHORD_WORD_ALIGN_TASKS[job_id] = {
                'state': 'error', 'message': str(exc)[:440]}


@app.route('/api/jobs/<job_id>/chords/word-align', methods=['GET', 'POST', 'PATCH'])
def chord_word_alignment_job(job_id):
    if not is_valid_id(job_id):
        return jsonify(error='ID brano non valido.'), 404
    restore_library()
    with LOCK:
        song = JOBS.get(job_id)
        if not song or song.get('status') != 'done':
            return jsonify(error='Selezionare un brano pronto nella libreria locale.'), 404
        state = CHORD_WORD_ALIGN_TASKS.get(job_id)
        if request.method == 'GET':
            response = jsonify(_chord_word_state_public(state))
            response.headers['Cache-Control'] = 'no-store'
            return response
        if request.method == 'PATCH':
            import hashlib
            import datetime
            data = request.get_json(silent=True) or {}
            if not isinstance(data, dict):
                return jsonify(error='Richiesta non valida.'), 400
            draft = state.get('_draft') if state else None
            if (not state or state.get('state') != 'preview' or not draft or
                data.get('draft_id') != state.get('draft_id') or
                time.monotonic() - draft['created'] > 1200):
                return jsonify(error='Anteprima non disponibile o scaduta. Ripetere l’analisi.'), 409
            selected = data.get('selected_ids', [])
            if not isinstance(selected, list) or len(selected) > 10000:
                return jsonify(error='Selezione non valida.'), 400
            selected_ids = {str(x) for x in selected}
            if not selected_ids.issubset(draft['allowed']):
                return jsonify(error='Sono stati selezionati cambi non presenti nell’anteprima.'), 400
            folder = JOBS_DIR / job_id
            file = folder / 'result.json'
            lyric_file = folder / 'lyrics.json'
            if (not file.is_file() or not lyric_file.is_file() or
                hashlib.sha256(file.read_bytes()).hexdigest() != draft['song_hash'] or
                hashlib.sha256(lyric_file.read_bytes()).hexdigest() != draft['lyric_hash']):
                return jsonify(error='Testo o accordi modificati dopo l’anteprima: ripetere l’analisi.'), 409
            original = file.read_bytes()
            current = json.loads(original)
            chords = [dict(c) for c in current.get('chords', [])]
            proposals = draft['proposed']
            for action in state['proposals']:
                i = int(action['id'])
                if action['id'] in selected_ids:
                    chords[i]['start'] = round(float(proposals[i]['start']), 3)
                    chords[i]['timing_source'] = 'audio_refined'
                    chords[i]['timing_confidence'] = proposals[i].get('timing_confidence', .5)
                    chords[i]['word_alignment_confirmed'] = True
            for i in range(len(chords)-1):
                chords[i]['end'] = round(float(chords[i+1]['start']), 3)
            # Re-evaluate visual anchors against ACTUAL selected musical onsets.
            from chord_word_align import classify_and_anchor
            lyrics = json.loads(lyric_file.read_bytes())
            chords, link_stats = classify_and_anchor(chords, lyrics.get('words', []),
                           float(lyrics.get('offset_seconds') or 0))
            from chord_ai_review import valid_timeline
            if not valid_timeline(chords, float(current.get('duration') or 0)):
                return jsonify(error='I cambi selezionati creerebbero intervalli non validi. Deselezionare i cambi ravvicinati.'), 409
            stale_count = int(state['stats'].get('stale_word_links', 0))
            # No fake successful save when neither musical timing nor visible links change.
            old_anchors = [(
                c.get('display_word_index'), c.get('display_fraction'), c.get('display_anchor_offset'))
                for c in current.get('chords', [])]
            new_anchors = [(
                c.get('display_word_index'), c.get('display_fraction'), c.get('display_anchor_offset'))
                for c in chords]
            link_changes = sum(a != b for a, b in zip(old_anchors, new_anchors))
            if not selected_ids and not link_changes:
                CHORD_WORD_ALIGN_TASKS[job_id] = {
                    'state': 'unchanged', 'message': 'Nessuna correzione selezionata; nulla è stato modificato.',
                    'stats': state['stats']}
                return jsonify(_chord_word_state_public(CHORD_WORD_ALIGN_TASKS[job_id]))
            backup = folder / 'backup_chord_word_align' / datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
            backup.mkdir(parents=True, exist_ok=False)
            (backup / 'result.json').write_bytes(original)
            new_stats = {**state['stats'], **link_stats,
                         'acoustic_boundaries_refined': len(selected_ids),
                         'display_anchors_changed': link_changes}
            updated = {**current, 'chords': chords, 'chord_word_alignment': new_stats,
                'message': f'Accordi: {len(selected_ids)} tempi corretti; {link_changes} ancoraggi grafici aggiornati.'}
            temporary = file.with_name('result.word-align.tmp')
            try:
                temporary.write_text(json.dumps(updated, ensure_ascii=False), encoding='utf-8')
                temporary.replace(file)
                JOBS[job_id] = updated
                (folder / 'drive_synced.json').unlink(missing_ok=True)
            except Exception:
                temporary.unlink(missing_ok=True)
                file.write_bytes(original)
                return jsonify(error='Salvataggio non riuscito. Dati precedenti ripristinati.'), 500
            CHORD_WORD_ALIGN_TASKS[job_id] = {
                'state': 'done', 'message': updated['message'] + ' Backup creato.',
                'stats': new_stats}
            return jsonify(_chord_word_state_public(CHORD_WORD_ALIGN_TASKS[job_id]))
        # POST: always performs a new analysis, including when last preview is still open.
        if state and state.get('state') == 'running':
            return jsonify(_chord_word_state_public(state)), 202
        if any(row.get('state') == 'running' for row in CHORD_WORD_ALIGN_TASKS.values()):
            return jsonify(error='È già in corso un allineamento. Riprovare al termine.'), 409
        import hashlib
        folder = JOBS_DIR / job_id
        file = folder / 'result.json'
        lyrics = folder / 'lyrics.json'
        if not file.is_file() or not lyrics.is_file():
            return jsonify(error='Mancano i dati degli accordi o del testo.'), 409
        song_hash = hashlib.sha256(file.read_bytes()).hexdigest()
        lyric_hash = hashlib.sha256(lyrics.read_bytes()).hexdigest()
        CHORD_WORD_ALIGN_TASKS[job_id] = {
            'state': 'running', 'message': 'Lettura della traccia audio e del testo…',
            'started_at': time.time()}
        try:
            CHORD_WORD_ALIGN_POOL.submit(run_chord_word_alignment, job_id, song_hash, lyric_hash)
        except Exception:
            CHORD_WORD_ALIGN_TASKS[job_id] = {
                'state': 'error', 'message': 'Avvio analisi non riuscito.'}
            return jsonify(error='Avvio analisi non riuscito.'), 500
        return jsonify(_chord_word_state_public(CHORD_WORD_ALIGN_TASKS[job_id])), 202


@app.post('/api/jobs/<job_id>/chords/refine')
def refine_saved_as_chords(job_id):
    """Re-evaluate timing of an existing A&S score without reprocessing music.

    Safe by default: original lyrics, guitar and four playback tracks untouched.
    Audio evidence is optional and changes are saved only on positive matches.
    """
    if not is_valid_id(job_id):
        return jsonify(error='ID del brano non valido.'), 404
    with LOCK:
        info = JOBS.get(job_id)
        if not info or info.get('status') != 'done':
            return jsonify(error='Brano non disponibile sul PC.'), 404
        chords = [dict(c) for c in info.get('chords', [])]
        if not any(isinstance(c.get('word_index'), int) for c in chords):
            return jsonify(error='Mancano ancoraggi alle parole A&S. Importi prima parole e accordi con Correggi tramite A&S.'), 409
        if not str(info.get('chord_source', '')).startswith('accordiespartiti'):
            return jsonify(error='Il raffinamento richiede una sequenza di accordi A&S.'), 409
        folder = JOBS_DIR / job_id
        result_file = folder / 'result.json'
        if not result_file.is_file():
            return jsonify(error='Dati del brano non disponibili.'), 404
        old_result = result_file.read_bytes()
    try:
        from chord_time_refiner import refine_from_saved_guitar
        adjusted, stats = refine_from_saved_guitar(chords, folder)
    except Exception:
        logging.getLogger('chord-refiner').exception('Raffinamento degli accordi non riuscito')
        return jsonify(error='Non riesco ad analizzare la chitarra isolata di questo brano.'), 422
    if not stats.get('audio_available'):
        return jsonify(error='Manca chitarra_isolata.mp3 nella cartella del brano: i tempi originali sono rimasti invariati.'), 409
    if not stats.get('refined'):
        return jsonify(status='unchanged', stats=stats, chords=chords,
                       message='Nessun cambio modificato: prove acustiche insufficienti. Restano i tempi precedenti.')
    with LOCK:
        if job_id not in JOBS or result_file.read_bytes() != old_result:
            return jsonify(error='Il brano è cambiato durante il calcolo. Riprovi.'), 409
        import datetime
        stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        backup = folder / 'backup_timing' / stamp
        backup.mkdir(parents=True, exist_ok=False)
        (backup / 'result.json').write_bytes(old_result)
        original_job = JOBS[job_id]
        updated_job = {**original_job, 'chords': adjusted,
                       'chord_source': 'accordiespartiti',
                       'message': f"Accordi A&S: {stats['refined']} cambi armonici affinati sull'audio; altri tempi stimati."}
        temp = folder / 'result.refined.tmp'
        try:
            temp.write_text(json.dumps(public_job(updated_job), ensure_ascii=False), encoding='utf-8')
            temp.replace(result_file)
            JOBS[job_id] = updated_job
            (folder / 'drive_synced.json').unlink(missing_ok=True)
        except (OSError, ValueError, TypeError):
            JOBS[job_id] = original_job
            result_file.write_bytes(old_result)
            return jsonify(error='Errore di salvataggio. Ripristinati i dati precedenti.'), 500
        finally:
            temp.unlink(missing_ok=True)
    return jsonify(status='saved', chords=adjusted, stats=stats,
                   message=f"{stats['refined']} cambi affinati sulla chitarra. Backup salvato; Drive si aggiornerà al prossimo ciclo.")


@app.post('/api/jobs/<job_id>/as-gap-repair')
def repair_unplaced_as_gap(job_id):
    """v2.56: corregge soltanto un verso finale trascinato dentro un solo.

    Non richiede accesso al sito A&S ne' rielabora la voce; recupera gli
    accordi A&S gia' salvati come non collocabili. Non cambia gli altri versi.
    Backup prima della sostituzione; concorrenza verificata su entrambi i file.
    """
    if not is_valid_id(job_id):
        return jsonify(error='ID del brano non valido.'),404
    with LOCK:
        song=JOBS.get(job_id)
        if not song or song.get('status')!='done':
            return jsonify(error='Brano non disponibile.'),404
        if song.get('chord_source')!='accordiespartiti':
            return jsonify(error='Riparazione disponibile solo per accordi A&S.'),409
        if LYRIC_TASKS.get(job_id,{}).get('status')=='running':
            return jsonify(error='Un altro riallineamento e\' in corso.'),409
        folder=JOBS_DIR/job_id
        lyric_file=folder/'lyrics.json'; result_file=folder/'result.json'
        if not lyric_file.is_file() or not result_file.is_file():
            return jsonify(error='File del brano non disponibili.'),409
        old_l=lyric_file.read_bytes(); old_r=result_file.read_bytes()
        lyrics=json.loads(old_l); result=json.loads(old_r)
    if not lyrics.get('as_unplaced_chord_groups'):
        return jsonify(status='unchanged',message='Nessuna progressione A&S in attesa di collocazione.'),200
    guitar=folder/'chitarra_isolata.mp3'
    if not guitar.is_file():
        return jsonify(error='Chitarra isolata mancante: il brano non e\' stato modificato.'),409
    try:
        from chords import chroma_mix
        from as_gap_recovery import repair_gap
        chroma, dt, _, _ = chroma_mix(str(guitar),max_seconds=600)
        revised_l,revised_r,stats=repair_gap(lyrics,result,chroma,dt)
        if stats['groups_recovered']<1:
            return jsonify(status='unchanged',stats=stats,
                           message='Il vuoto anomalo non e\' riconoscibile con sicurezza. Nessun file modificato.'),200
    except (ValueError,TypeError) as exc:
        return jsonify(error='Riparazione intermezzo bloccata: '+str(exc)[:400]),422
    except Exception:
        logging.getLogger('as-gap-recovery').exception('Analisi intermezzo %s',job_id)
        return jsonify(error='Analisi intermezzo non completata. Nessun file modificato.'),422
    with LOCK:
        if (JOBS.get(job_id,{}).get('status')!='done' or
            LYRIC_TASKS.get(job_id,{}).get('status')=='running' or
            lyric_file.read_bytes()!=old_l or result_file.read_bytes()!=old_r):
            return jsonify(error='Brano modificato durante la riparazione. Nessun salvataggio.'),409
        import datetime
        stamp=datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        backup=folder/'backup_gap_recovery_256'/stamp
        backup.mkdir(parents=True,exist_ok=False)
        (backup/'lyrics.json').write_bytes(old_l)
        (backup/'result.json').write_bytes(old_r)
        updated_song={**song,'chords':revised_r['chords'],'chord_source':'accordiespartiti'}
        tmp_l=folder/'lyrics.gap.tmp';tmp_r=folder/'result.gap.tmp'
        try:
            tmp_l.write_text(json.dumps(revised_l,ensure_ascii=False),encoding='utf-8')
            tmp_r.write_text(json.dumps(public_job(updated_song),ensure_ascii=False),encoding='utf-8')
            tmp_l.replace(lyric_file)
            tmp_r.replace(result_file)
            JOBS[job_id]=updated_song
            (folder/'drive_synced.json').unlink(missing_ok=True)
        except (OSError,ValueError,TypeError):
            lyric_file.write_bytes(old_l);result_file.write_bytes(old_r)
            return jsonify(error='Salvataggio annullato. Ripristinati i due file precedenti.'),500
        finally:
            tmp_l.unlink(missing_ok=True);tmp_r.unlink(missing_ok=True)
    return jsonify(status='saved',chords=revised_r['chords'],stats=stats,
       message=(f"Intermezzo recuperato: {stats['chords_recovered']} accordi A&S, "
                f"{stats['words_repaired']} parola finale ricollocata, "
                f"{stats['audio_refined']} tempi confrontati con l'audio; "
                f"{stats.get('repeated_chords_added',0)} ripetizioni recuperate. "
                "Gli altri versi non sono stati modificati. Backup creato. "
                "I tempi non confermati restano stime: verificare all'ascolto."))


@app.post('/api/jobs/<job_id>/as-motif-repeat')
def refine_repeated_as_motif(job_id):
    """v2.57: recover a proven repeated guitar motif, never alter sung words.

    Conservatively require a repeated motif elsewhere in the *same* score,
    musical evidence in the saved isolated guitar and a valid result timeline.
    """
    if not is_valid_id(job_id):
        return jsonify(error='ID del brano non valido.'),404
    with LOCK:
        song=JOBS.get(job_id)
        if not song or song.get('status')!='done':
            return jsonify(error='Brano non disponibile.'),404
        if song.get('chord_source')!='accordiespartiti':
            return jsonify(status='unchanged',message='La fonte non e\' A&S: nessuna modifica.'),200
        if LYRIC_TASKS.get(job_id,{}).get('status')=='running':
            return jsonify(error='Un altro allineamento e\' in corso.'),409
        folder=JOBS_DIR/job_id
        lyric_file=folder/'lyrics.json';result_file=folder/'result.json'
        if not lyric_file.is_file() or not result_file.is_file():
            return jsonify(status='unchanged',message='File del brano non disponibili.'),200
        old_l=lyric_file.read_bytes();old_r=result_file.read_bytes()
        lyrics=json.loads(old_l); result=json.loads(old_r)
    if not any(c.get('source_kind')=='instrumental' and c.get('source_provider')=='accordiespartiti'
               for c in result.get('chords',[])):
        return jsonify(status='unchanged',message='Nessuna progressione strumentale A&S disponibile.'),200
    guitar=folder/'chitarra_isolata.mp3'
    if not guitar.is_file():
        return jsonify(status='unchanged',message='Chitarra isolata non disponibile.'),200
    try:
        from chords import chroma_mix
        from as_motif_recovery import recover_repeated_instrumentals
        chroma,dt,_,_=chroma_mix(str(guitar),max_seconds=600)
        revised_l,revised_r,stats=recover_repeated_instrumentals(lyrics,result,chroma,dt)
        if not stats['groups_expanded']:
            return jsonify(status='unchanged',stats=stats,
                message='Nessuna ripetizione armonica sufficientemente confermata: dati invariati.'),200
    except (ValueError,TypeError) as exc:
        return jsonify(error='Riconoscimento ripetizioni bloccato: '+str(exc)[:320]),422
    except Exception:
        logging.getLogger('as-motif-recovery').exception('Motivo armonico %s',job_id)
        return jsonify(error='Analisi delle ripetizioni non completata. Nessun dato salvato.'),422
    with LOCK:
        if (JOBS.get(job_id,{}).get('status')!='done' or
            LYRIC_TASKS.get(job_id,{}).get('status')=='running' or
            lyric_file.read_bytes()!=old_l or result_file.read_bytes()!=old_r):
            return jsonify(error='Brano modificato durante la verifica. Nessun salvataggio.'),409
        import datetime
        stamp=datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        backup=folder/'backup_motif_repeat_257'/stamp
        backup.mkdir(parents=True,exist_ok=False)
        (backup/'lyrics.json').write_bytes(old_l)
        (backup/'result.json').write_bytes(old_r)
        updated_song={**song,'chords':revised_r['chords'],'chord_source':'accordiespartiti'}
        tmp_l=folder/'lyrics.repeat.tmp';tmp_r=folder/'result.repeat.tmp'
        try:
            tmp_l.write_text(json.dumps(revised_l,ensure_ascii=False),encoding='utf-8')
            tmp_r.write_text(json.dumps(public_job(updated_song),ensure_ascii=False),encoding='utf-8')
            tmp_l.replace(lyric_file)
            tmp_r.replace(result_file)
            JOBS[job_id]=updated_song
            (folder/'drive_synced.json').unlink(missing_ok=True)
        except (OSError,ValueError,TypeError):
            lyric_file.write_bytes(old_l);result_file.write_bytes(old_r)
            return jsonify(error='Salvataggio annullato. Ripristinati i file originali.'),500
        finally:
            tmp_l.unlink(missing_ok=True);tmp_r.unlink(missing_ok=True)
    return jsonify(status='saved',chords=revised_r['chords'],stats=stats,
        message=(f"Assolo: {stats['repeated_chords_added']} cambi ripetuti recuperati "
                 f"dall'audio e confrontati con un'altra sezione del brano. "
                 "Parole e accordi dei versi invariati. Backup creato. "
                 "Rimane necessaria la verifica musicale all'ascolto."))


@app.post('/api/jobs/<job_id>/as-instrumental-refine')
def refine_only_instrumental_as(job_id):
    """2.52: recupera e valida i cambi mancanti dei soli, senza toccare i versi.

    Recupera la stessa fonte A&S già associata al brano. Non analizza
    nuovamente la voce e non scrive nulla in caso di dati incoerenti.
    """
    if not is_valid_id(job_id):
        return jsonify(error='ID del brano non valido.'),404
    with LOCK:
        song=JOBS.get(job_id)
        if not song or song.get('status')!='done':
            return jsonify(error='Brano non disponibile.'),404
        if str(song.get('chord_source',''))!='accordiespartiti':
            return jsonify(error='Funzione disponibile per brani con accordi A&S. Importi prima lo spartito.'),409
        if LYRIC_TASKS.get(job_id,{}).get('status')=='running':
            return jsonify(error='Sincronizzazione del testo già in corso.'),409
        folder=JOBS_DIR/job_id
        result_file=folder/'result.json'
        lyrics_file=folder/'lyrics.json'
        if not result_file.is_file() or not lyrics_file.is_file():
            return jsonify(error='File testo/accordi non disponibili sul PC.'),409
        old_result=result_file.read_bytes()
        old_lyrics=lyrics_file.read_bytes()
        info=json.loads(old_lyrics)
        words=info.get('words',[])
        duration=float(song.get('duration') or 0)
        saved_chords=[dict(c) for c in song.get('chords',[])]
        from chord_timeline import load_acoustic_reference
        reference,_=load_acoustic_reference(folder,song)
    from as_import_core import safe_url,parse_html,_fetch,ImportErrorAS
    if not (folder/'chitarra_isolata.mp3').is_file():
        return jsonify(error='Chitarra isolata assente sul PC: nessun cambio applicato.'),409
    try:
        from as_instrumental_repair import repair_instrumental
        from instrumental_timing import refine_from_saved_guitar as refine_instrumental
        reconstruction={'reconstructed_instrumental_events':0,'untimed_source_chords':0,
                        'unchanged_vocal_events':sum(c.get('source_kind')=='lyrics' for c in saved_chords)}
        rebuilt=saved_chords
        # La pagina A&S e' utile per ripristinare la progressione editoriale,
        # ma non deve impedire il recupero dall'audio degli intermezzi mancanti
        # se il sito e' offline o lo spartito non riporta gli accordi del solo.
        try:
            url=safe_url(info.get('source_url',''))
            score=parse_html(_fetch(url))
            rebuilt,reconstruction=repair_instrumental(score,words,saved_chords,reference,duration)
        except (ValueError,TypeError,ImportErrorAS) as error:
            logging.getLogger('instrumental-repair').warning(
                'Fonte A&S non disponibile per %s: proseguo con audio locale: %s',job_id,error)
            reconstruction['instrumental_source_warning']=str(error)[:150]
        adjusted,acoustics=refine_instrumental(rebuilt,words,folder,reference)
        stats={**reconstruction,**acoustics}
        from karaoke_integrity import audit_words, audit_chords
        lyric_errors = audit_words(words, duration)
        if lyric_errors:
            raise ValueError('Il karaoke salvato presenta anomalie preesistenti: ' +
                             ' '.join(lyric_errors[:3]) + ' Nessun file modificato.')
        issues = audit_chords(adjusted, duration, words)
        if issues:
            raise ValueError('La nuova timeline degli accordi non supera il controllo: ' +
                             ' '.join(issues[:4]) +
                             ' Nessun file modificato; il testo non deve essere riallineato.')
    except (ValueError,TypeError,ImportErrorAS) as exc:
        return jsonify(error=str(exc)[:400]),422
    except Exception:
        logging.getLogger('instrumental-repair').exception('Riparazione strumentale fallita %s',job_id)
        return jsonify(error='Impossibile ricostruire e analizzare la progressione strumentale. Dati originali invariati.'),422
    if adjusted==saved_chords:
        return jsonify(status='unchanged',stats=stats,chords=saved_chords,
                       message='Nessun nuovo cambio strumentale sufficientemente attendibile rilevato: nessun file modificato. Controllare la traccia chitarra isolata e, se necessario, correggere gli accordi dal pannello 03.')
    with LOCK:
        if (JOBS.get(job_id,{}).get('status')!='done' or
                LYRIC_TASKS.get(job_id,{}).get('status')=='running' or
                result_file.read_bytes()!=old_result or lyrics_file.read_bytes()!=old_lyrics):
            return jsonify(error='Il brano è cambiato durante il controllo. Riprovare.'),409
        import datetime
        stamp=datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        backup=folder/'backup_instrumental_252'/stamp
        backup.mkdir(parents=True,exist_ok=False)
        (backup/'result.json').write_bytes(old_result)
        (backup/'lyrics.json').write_bytes(old_lyrics)
        updated={**song,'chords':adjusted,'chord_source':'accordiespartiti'}
        tmp=folder/'result.instrumental.tmp'
        try:
            tmp.write_text(json.dumps(public_job(updated),ensure_ascii=False),encoding='utf-8')
            tmp.replace(result_file)
            JOBS[job_id]=updated
            (folder/'drive_synced.json').unlink(missing_ok=True)
        except (OSError,ValueError,TypeError):
            result_file.write_bytes(old_result)
            tmp.unlink(missing_ok=True)
            return jsonify(error='Errore salvataggio. Accordi originali ripristinati.'),500
        finally:
            tmp.unlink(missing_ok=True)
    return jsonify(status='saved',chords=adjusted,stats=stats,
                   message=(f"Strumentali: {stats['reconstructed_instrumental_events']} accordi A&S ricollocati, "
                            f"{stats['instrumental_refined']} cambi affinati dall'audio, "
                            f"{stats['instrumental_audio_inserted']} eventi recuperati dall'audio; "
                            f"{stats['instrumental_estimated']} tempi A&S ancora stimati. "
                            f"{stats.get('instrumental_conflicts_avoided',0)} spostamenti incompatibili annullati. "
                            "Versi e parole invariati. Backup creato; verificare all'ascolto."))


@app.post('/api/jobs/<job_id>/as-restore')
def restore_pre_as(job_id):
    """Recupera la copia precedente al primo import A&S senza perdere dati correnti.

    Restano invariati tutti i file audio. Usa unicamente backup_as locali:
    nessun percorso passato dal browser e nessuna scrittura fuori dal brano.
    """
    if not is_valid_id(job_id):
        return jsonify(error='ID del brano non valido.'), 404
    import datetime
    with LOCK:
        song=JOBS.get(job_id)
        if not song or song.get('status')!='done':
            return jsonify(error='Brano non disponibile.'), 404
        folder=JOBS_DIR/job_id
        base=folder/'backup_as'
        src=None
        # Preferire il backup recente con karaoke AI o LRCLIB pre-A&S.
        for candidate in sorted((p for p in base.iterdir() if p.is_dir()),reverse=True) if base.exists() else []:
            lyric=candidate/'lyrics.json'
            result=candidate/'result.json'
            if not lyric.is_file() or not result.is_file():continue
            try:
                old=json.loads(lyric.read_text(encoding='utf-8'))
                info=json.loads(result.read_text(encoding='utf-8'))
                words=old.get('words',[])
                if not isinstance(words,list) or len(words)<3 or not isinstance(info.get('chords'),list):continue
                if old.get('lyrics_provider')=='A&S' or old.get('source')=='accordiespartiti':continue
                # Non ripristinare backup che contengono gia' i salti e le accelerazioni
                # del karaoke che si sta cercando di riparare.
                from karaoke_integrity import audit_words
                if audit_words(words, float(song.get('duration',0))):continue
                src=(lyric,result,info)
                break
            except (ValueError,TypeError,OSError,AttributeError):continue
        if not src:
            return jsonify(error='Nessun backup pre-A&S con tempi affidabili trovato. Nel pannello 04 apra Testo molto errato e riallinei il testo corretto sulla voce isolata.'),404
        current_lyrics=folder/'lyrics.json'
        current_result=folder/'result.json'
        if not(current_lyrics.is_file() and current_result.is_file()):
            return jsonify(error='File correnti non trovati.'),409
        original_lyrics=current_lyrics.read_bytes()
        original_result=current_result.read_bytes()
        import uuid
        safe_backup=base/('prima_del_ripristino_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8])
        safe_backup.mkdir(parents=True,exist_ok=False)
        (safe_backup/'lyrics.json').write_bytes(original_lyrics)
        (safe_backup/'result.json').write_bytes(original_result)
        try:
            new_lyrics=src[0].read_bytes()
            new_result=src[1].read_bytes()
            restored=src[2]
            # Sicurezza: non recuperare dati che appartengono a un brano diverso.
            if restored.get('id')!=job_id:
                raise ValueError('Backup non appartenente al brano corrente.')
            current_lyrics.write_bytes(new_lyrics)
            current_result.write_bytes(new_result)
            JOBS[job_id].update(restored)
            (folder/'drive_synced.json').unlink(missing_ok=True)
        except (OSError,ValueError,TypeError):
            current_lyrics.write_bytes(original_lyrics)
            current_result.write_bytes(original_result)
            return jsonify(error='Ripristino non riuscito: i dati correnti sono stati conservati.'),500
        return jsonify(status='restored',chords=JOBS[job_id]['chords'],
                       message='Ripristinato il karaoke precedente ad A&S. La versione difettosa resta salvata in backup.')

@app.delete("/api/jobs/<job_id>")
def delete_job(job_id):
    if not is_valid_id(job_id):
        return jsonify(error="ID non valido."), 404
    with LOCK:
        job = JOBS.get(job_id)
        if not job:
            return jsonify(error="Elemento non trovato."), 404
        if job["status"] not in {"done", "error"}:
            return jsonify(error="Attendere che termini l'elaborazione."), 409
        del JOBS[job_id]
    shutil.rmtree(JOBS_DIR / job_id, ignore_errors=True)
    return jsonify(ok=True)


@app.get('/api/drive/library')
def drive_library_list():
    try:
        from cloud_library import cloud_songs
        return jsonify(cloud_songs())
    except Exception as exc:
        return jsonify(error='Archivio Google Drive non disponibile: ' + str(exc)[:260]), 503


@app.post('/api/drive/import')
def drive_library_import():
    payload = request.get_json(silent=True) or {}
    try:
        from cloud_library import start_import
        return jsonify(start_import(payload.get('id'), refresh=payload.get('refresh') is True)), 202
    except ValueError as exc:
        return jsonify(error=str(exc)[:250]), 409


@app.get('/api/drive/import/<job_id>')
def drive_import_status(job_id):
    if not is_valid_id(job_id):
        return jsonify(error='ID brano non valido.'), 404
    from cloud_library import get_import_task
    result = get_import_task(job_id)
    if not result:
        return jsonify(error='Importazione non trovata.'), 404
    return jsonify(result)


@app.post('/api/drive/stems/<job_id>')
def drive_share_stems(job_id):
    try:
        from cloud_library import share_existing_stems
        return jsonify(share_existing_stems(job_id))
    except ValueError as exc:
        return jsonify(error=str(exc)[:260]), 409
    except Exception as exc:
        return jsonify(error='Condivisione tracce non riuscita: '+str(exc)[:250]), 503


@app.post('/api/drive/sync')
def drive_sync_now():
    payload = request.get_json(silent=True) or {}
    try:
        from drive_sync import sync_once
        return jsonify(sync_once(payload.get('ids') if isinstance(payload.get('ids'), list) else None))
    except Exception as exc:
        return jsonify(error='Sincronizzazione fallita: '+str(exc)[:250]), 503


@app.get('/api/drive/cleanup')
def drive_cleanup_list():
    try:
        from drive_sync import cloud_inventory
        return jsonify(cloud_inventory())
    except Exception as exc:
        return jsonify(error='Impossibile leggere l’archivio Drive: ' + str(exc)[:250]), 503


@app.post('/api/drive/cleanup')
def drive_cleanup_trash():
    payload = request.get_json(silent=True) or {}
    if payload.get('confirm') != 'SPOSTA NEL CESTINO':
        return jsonify(error='Confermare lo spostamento nel Cestino.'), 400
    try:
        from drive_sync import cleanup_cloud
        return jsonify(cleanup_cloud(payload.get('items', [])))
    except ValueError as exc:
        return jsonify(error=str(exc)[:250]), 400
    except Exception as exc:
        return jsonify(error='Pulizia Drive incompleta, aggiornare l’elenco: ' + str(exc)[:250]), 503


def start_drive_watcher() -> None:
    """Elabora e sincronizza solo se l'utente ha collegato esplicitamente Drive."""
    def loop():
        from drive_sync import TOKEN_FILE, sync_once
        log = logging.getLogger("drive-watcher")
        while True:
            try:
                if TOKEN_FILE.is_file():
                    sync_once()
            except Exception as exc:
                log.warning("Sincronizzazione Drive non riuscita (ritento al prossimo giro): %s", exc)
            time.sleep(60)
    threading.Thread(target=loop, daemon=True, name="DriveSync").start()


if __name__ == "__main__":
    restore_library()
    ffmpeg_path()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    start_drive_watcher()
    print(f"Guitar Backing Leon: http://127.0.0.1:{PORT}", flush=True)
    threading.Timer(1.2, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}")).start()
    app.run(host="127.0.0.1", port=PORT, threaded=True, debug=False, use_reloader=False)
