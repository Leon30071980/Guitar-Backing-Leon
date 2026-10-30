# Leon Karaoke CarPlay Companion — v1.6

**Solo progetto iOS:** il programma PC v2.63 e la PWA web v2.65 restano invariati.

## Novità v1.6

- **Coda musicale da Drive:** cerca nella libreria, usa `+` per accodare più canzoni o `▶` per iniziare immediatamente. Non duplica i brani in Google Drive.
- **Precedente / Successivo:** comandi nell'interfaccia e in `MPRemoteCommandCenter`, disponibili anche tramite i controlli multimediali standard di iOS/CarPlay se il sistema li espone. Premendo Precedente dopo 3 secondi dall'inizio, riparte il brano attuale; prima di 3 secondi passa a quello precedente.
- **Fine brano:** passa automaticamente al successivo. La coda si ferma alla fine, senza riproduzione ciclica. I due MP3 restano sincronizzati, chitarra sempre ON, Voce ON/OFF invariato.
- **Riordina / rimuovi:** frecce ↑/↓ per modificare l'ordine; `×` per togliere un brano non attivo. `Svuota prossimi` mantiene soltanto il brano attivo. La coda degli ID viene conservata su iPhone fra le aperture.
- **Preparazione prossimo brano:** avvia il download del testo e dei due MP3 successivi mentre suona il brano attuale (al massimo un brano di anticipo). Può esserci attesa con rete lenta o iOS in background; non è garantito playback gapless.
- **Offset parole:** slider −3...+3 s, passi 0,1 s, pulsanti ±0,1 s e Azzera. **+ ritarda le parole**, **− le anticipa**. La correzione agisce sulle parole sia in app sia nei dati della Live Activity, senza cambiare `currentTime` dell'audio; si salva su iPhone in UserDefaults.
- **Stima latenza audio iOS:** route e `AVAudioSession.outputLatency` solo a titolo indicativo. Non rappresenta il ritardo reale completo di CarPlay; usare l'offset per la calibrazione percepita.
- **Robustezza:** delegate AVAudioPlayer per passaggio automatico quando il timer UI viene rallentato; richieste MP3 duplicate deduplicate in memoria.

## Test pratico consigliato

1. Collega Google Drive (OAuth iOS esistente). Aggiungi 3 canzoni in coda usando `+`.
2. Avvia la coda, verifica ▶/⏸/■, chitarra sempre ON, Voce ON/OFF e Next/Prev.
3. Verifica il passaggio automatico alla seconda alla fine della prima e i tasti Media Control da iPhone.
4. Collega CarPlay **da fermo** e verifica riquadro Live Activity e controlli standard. Usa +0,5 s se le parole appaiono mezzo secondo prima dell'audio, o −0,5 s nel caso opposto.
5. Blocca iPhone: gli aggiornamenti di Live Activity possono ancora essere diradati/sospesi da iOS. Non è garantito il cambio di ogni strofa su CarPlay.

## Distribuzione nello stesso GitHub

1. In GitHub Desktop: seleziona il repository esistente e fai **Fetch origin / Pull origin**.
2. Crea facoltativamente un branch `carplay-v1.6`.
3. Estrai lo ZIP e copia **l'intera cartella `carplay-ios`** nella radice del repository locale, accettando la sostituzione dei file omonimi.
4. Controlla che nelle modifiche compaiano **solo file in `carplay-ios/`**; non toccare `index.html`, `config.js`, `app.js`, `.github/workflows/`.
5. Commit `Leon Karaoke Companion v1.6 - coda e offset`, poi Push/Publish; apri una Pull Request verso `main` se lavori su branch separato.
6. GitHub > Actions > `CarPlay Companion - compila iOS (unsigned)` > Run workflow su `main` > scarica IPA unsigned. La firma/installazione resta esterna a GitHub.
7. Usa lo stesso Apple ID e bundle ID per aggiornare l'app via una procedura di firma attendibile. Non disabilitare Defender né autorizzare programmi che ha segnalato senza ulteriori verifiche.

**Non cambiare la variabile GitHub Actions `GUITAR_GOOGLE_IOS_CLIENT_ID`.** Il Client ID viene inserito in `Info.plist` dal workflow esistente. Nessuna password o token deve essere pubblicata nel repository.

## Limiti dichiarati

- I test nella cartella `Tests` sono verifiche Linux/offline: la compilazione iOS richiede GitHub Actions/Xcode e la funzionalità va verificata su iPhone reale.
- La Live Activity CarPlay non ha una dimensione liberamente espandibile e non garantisce aggiornamenti continui delle strofe a iPhone bloccato.
- La latenza totale CarPlay non è misurabile automaticamente con certezza da `outputLatency`; l'offset manuale non corregge eventuali ritardi variabili o ridisegni sospesi.
- I comandi Precedente/Successivo di iOS/CarPlay sono **comandi multimediali standard**; non sono pulsanti personalizzati dentro la Live Activity.

Versione: **v1.6** (da v1.5). PC v2.63 invariata, web v2.65 invariata.
