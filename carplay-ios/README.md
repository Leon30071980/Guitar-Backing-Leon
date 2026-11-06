# Leon Karaoke Companion — v1.7

**Pacchetto iOS per il repository esistente Guitar-Backing-Leon.** Le app PC v2.63 e web/PWA v2.65 non sono modificate.

## Aggiornamento v1.7 rispetto alla v1.6

1. **Ripresa e sincronizzazione:** quando Leon Karaoke torna in primo piano dopo il blocco schermo, un'altra app o il ritorno dalla Dashboard CarPlay, legge immediatamente il tempo reale di `AVAudioPlayer` e riallinea i versi. Prova inoltre a recuperare una Live Activity già attiva, invece di lasciare la schermata sulla frase iniziale. Le vecchie Live Activities senza lettore (dopo la terminazione del processo) vengono chiuse, anziché restare congelate.
2. **Miglioramento background best-effort:** le richieste di aggiornamento ActivityKit vengono inviate a ogni cambio di frase, pausa/ripresa o salto, più un riancoraggio ogni ~8 secondi mentre il processo rimane eseguibile. La pubblicazione è serializzata per evitare di pubblicare aggiornamenti vecchi dopo quelli nuovi. Il timer MP3 è registrato nei `RunLoop.Mode.common`, riducendo le interruzioni durante gesture e scorrimento.
3. **Libreria compatta:** dopo aver selezionato `▶` e avviato correttamente un brano, la lista Drive si chiude automaticamente. Rimane il pulsante **Apri libreria** per riaprirla; i comandi Play/Pausa, Voce ON/OFF, Precedente/Successivo e coda rimangono disponibili.
4. **Offset facile da regolare:** cursore da 46pt in un'area di trascinamento da 68pt, pulsanti alti almeno 52pt per **−0,5 / −0,1 / Azzera / +0,1 / +0,5 s**. Rimane il range −3...+3 s, con passi 0,1 s, e il valore viene memorizzato. + ritarda le parole, − le anticipa.

## Limite Apple non eliminato

L'audio in background con la categoria `.playback` e `UIBackgroundModes=audio` permette di continuare la riproduzione quando iPhone si blocca. Questo **non garantisce** un aggiornamento per ogni parola o strofa della Live Activity: iOS decide quando eseguire l'app e ridisegnare i widget (incluso CarPlay). Se sospende il processo o il widget, la frase può ancora rimanere ferma nonostante il nuovo sistema di riallineamento. Per aggiornamenti indipendenti dalla vita del processo servirebbe un sistema di notifiche push ActivityKit/APNs con backend e permessi appropriati, ancora non implementato. Non si promette karaoke continuo sul display in ogni auto.

L'offset temporale modifica solo la posizione del testo e non compensa un widget che viene sospeso per decine di secondi.

## Test suggerito in auto, da fermo

1. Avvia 2 brani dalla libreria, controllando che la lista si chiuda al Play e possa essere riaperta.
2. Regola l'offset con i tasti grandi ±0,5 e ±0,1 e verifica che cambi l'anteprima in app senza cambiare l'audio.
3. Lascia suonare e blocca iPhone; annota se, dopo qualche minuto, la Live Activity smette di cambiare strofa mentre l'audio continua.
4. Riapri Leon Karaoke: la frase nell'app deve tornare al punto corretto, **non** all'intro. Ripeti dopo una pausa e una ricerca nella canzone.
5. Verifica su CarPlay. Se resta bloccato anche dopo aver riaperto l'app, annota iOS versione, minuto della canzone, e se l'audio è ancora in riproduzione.

## GitHub Desktop

1. Repository `Guitar-Backing-Leon` → **Fetch origin** / **Pull origin**.
2. Fai una copia di sicurezza o crea un branch (`carplay-v1.7`).
3. Estrai il pacchetto e copia **la cartella `carplay-ios`** nella radice del repository, unendo le cartelle e sostituendo i file omonimi. Il nuovo `App/LeonOffsetControl.swift` deve essere presente.
4. In **Changes**, controlla che ogni modifica appartenga a `carplay-ios/`: NON sostituire il sito web, il PC, `config.js` né `.github/workflows`.
5. Commit `Leon Karaoke Companion v1.7 - ripresa karaoke e interfaccia`, poi **Push origin**; se sul branch, Pull Request e merge su `main`.
6. GitHub → **Actions** → `CarPlay Companion - compila iOS (unsigned)` → **Run workflow** su `main`. Scarica l'artefatto IPA, quindi usa un metodo di firma/installazione affidabile.

Non occorre modificare `GUITAR_GOOGLE_IOS_CLIENT_ID`; la libreria Drive e la coda della v1.6 restano intatte.

## Verifiche locali

- `swiftc -frontend -parse` dei sorgenti Swift (solo sintassi; non sostituisce la compilazione Xcode).
- Test Swift Foundation di coda e offset.
- 27 controlli strutturali v1.7; test offline Drive, lettore e protocollo karaoke.
- Compilazione Xcode, firma e comportamento reale iPhone/CarPlay **da verificare**.
