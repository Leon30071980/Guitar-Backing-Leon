# Guitar Leon CarPlay Companion v1.3

Progetto iPhone nativo **incluso nel repository di Guitar Backing Leon**.

Questa versione riceve da `web/carplay_bridge.js` titolo, posizione del lettore, stato Play/Pausa e una **finestra** di versi via URL scheme `guitarleoncarplay://sync?data=...`.
Non preleva dati da Google Drive, non accede al suo account e non contiene brani privati.

## Prova dal sito web

1. Apri la PWA v2.64 dall'icona sulla Home dell'iPhone e accedi come sempre.
2. Carica un brano e attendi che il testo karaoke sia pronto.
3. Nel footer tocca 4 volte **Web 2.64** in 3 secondi: appare il tasto **CarPlay ↗**.
4. Tocca CarPlay ↗ (è un'azione volontaria, necessaria per aprire il Companion iOS).
5. iOS apre Guitar Leon Karaoke con il brano, il tempo e i versi. Il Companion richiede il consenso alle Live Activities.
6. Torna nella PWA e riproduci il brano. Controlla la Dashboard di CarPlay **da fermo**.
7. Se metti in pausa, cerchi un nuovo punto o cambi brano, premi nuovamente CarPlay ↗ per riallineare.

## Installazione senza Mac

Il file `.github/workflows/build-ios-companion.yml`, nella **root dello stesso repository**, prepara una build unsigned su un runner macOS. In GitHub > Actions > CarPlay Companion - compila iOS (unsigned) > Run workflow, scaricare l'artefatto IPA solo se il workflow termina con successo.

L'IPA **non è firmato e non è direttamente installabile**. Occorre firmarlo/installarlo da Windows con un sistema di sideloading compatibile. L'uso di un Apple ID gratuito può richiedere rinnovi periodici e non garantisce il provisioning delle funzioni Live Activities. Nessuna build o installazione iOS reale è stata verificata.

## Limiti tecnici

- Non è un'app CarPlay Audio, ma una **Live Activity** (riquadro Dashboard, non schermo pieno).
- **Nessuna sincronizzazione continua automatica da Safari**: senza un server APNs e provisioning adeguato non c'è un canale attendibile da PWA a Live Activity con Companion sospeso.
- Il widget prova a mostrare i versi tramite `TimelineView`, ma l'OS può ritardare o fermare gli aggiornamenti.
- La dimensione massima disponibile dipende dall'auto e da iOS. L'interfaccia è ottimizzata per `ActivityFamily.small`.
- Non pubblicare i file `lyrics.json` reali né credenziali nel repository.

Versioni: **PWA v2.64**, **Companion v1.3**, motore PC originale **v2.63**.

Fonti:
- https://developer.apple.com/design/human-interface-guidelines/live-activities
- https://developer.apple.com/documentation/activitykit/displaying-live-data-with-live-activities
- https://developer.apple.com/documentation/activitykit/starting-and-updating-live-activities-with-activitykit-push-notifications
