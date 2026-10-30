import AuthenticationServices
import CryptoKit
import Foundation
import Security
import UIKit

// Accesso REST in sola lettura. I dati rimangono nel Google Drive privato.
// OAuth: browser di sistema (mai WKWebView), PKCE, state, token Keychain.
struct LeonDriveSong: Decodable, Identifiable, Hashable {
    let id: String
    let name: String
    let duration: Double?
    let lyricsFileId: String?
    let tracks: [String: String]?
    // "full" e "no_vocals" sono le combinazioni realmente pubblicate dalla PWA.
    var canPlay: Bool { (tracks?["full"]?.isEmpty == false) && (tracks?["no_vocals"]?.isEmpty == false) }
    var hasLyrics: Bool { !(lyricsFileId ?? "").isEmpty }
}

private struct DriveIndex: Decodable { let songs: [LeonDriveSong] }
private struct DriveList: Decodable { let nextPageToken: String?; let files: [DriveItem]? }
private struct DriveItem: Decodable { let id: String; let name: String }
private struct OAuthToken: Decodable {
    let access_token: String
    let refresh_token: String?
    let expires_in: Double?
}

private enum DriveError: LocalizedError {
    case message(String)
    var errorDescription: String? { if case .message(let text) = self { return text }; return nil }
}

private enum DriveKeychain {
    private static let service = "it.leon.guitar.karaoke.google.oauth"
    static func load() -> String? {
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service, kSecAttrAccount as String: "refresh",
            kSecReturnData as String: true, kSecMatchLimit as String: kSecMatchLimitOne]
        var result: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }
    static func save(_ value: String) {
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service, kSecAttrAccount as String: "refresh"]
        SecItemDelete(query as CFDictionary)
        var attributes = query
        attributes[kSecValueData as String] = Data(value.utf8)
        attributes[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        SecItemAdd(attributes as CFDictionary, nil)
    }
    static func clear() {
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service, kSecAttrAccount as String: "refresh"]
        SecItemDelete(query as CFDictionary)
    }
}

private final class LoginPresentation: NSObject, ASWebAuthenticationPresentationContextProviding {
    func presentationAnchor(for session: ASWebAuthenticationSession) -> ASPresentationAnchor {
        UIApplication.shared.connectedScenes
            .compactMap { $0 as? UIWindowScene }
            .flatMap(\.windows)
            .first(where: { $0.isKeyWindow }) ?? UIWindow()
    }
}

@MainActor
final class GoogleDriveLibrary: ObservableObject {
    @Published private(set) var songs: [LeonDriveSong] = []
    @Published private(set) var connected = false
    @Published private(set) var loading = false
    @Published var message = "Collega il tuo Google Drive per leggere la libreria esistente."
    @Published var selected: String? = nil

    private var authSession: ASWebAuthenticationSession?
    private let presentation = LoginPresentation()
    private var accessToken = ""
    private var expiry = Date.distantPast
    private let scope = "https://www.googleapis.com/auth/drive.file"
    private let filesAPI = "https://www.googleapis.com/drive/v3/files"
    private let tokenAPI = URL(string: "https://oauth2.googleapis.com/token")!

    private var clientId: String {
        Bundle.main.object(forInfoDictionaryKey: "LeonGoogleClientID") as? String ?? ""
    }
    private var callbackScheme: String? {
        let suffix = ".apps.googleusercontent.com"
        guard clientId.hasSuffix(suffix), clientId.count > suffix.count + 5 else { return nil }
        return "com.googleusercontent.apps." + clientId.dropLast(suffix.count)
    }
    var configured: Bool { callbackScheme != nil }

    func onLaunch() async {
        guard configured else {
            message = "Configurazione Google mancante: aggiungere il Client ID OAuth iOS allo stesso progetto Google Cloud della PWA, tramite variabile GitHub GUITAR_GOOGLE_IOS_CLIENT_ID."
            return
        }
        guard DriveKeychain.load() != nil else { return }
        await refreshLibrary()
    }

    func connect() async {
        guard let scheme = callbackScheme else {
            message = "Google non configurato. Vedi GUIDA_DRIVE_CARPLAY.md."
            return
        }
        if loading { return }
        loading = true
        defer { loading = false }
        do {
            let verifier = Self.randomToken(byteCount: 48)
            let challenge = Data(SHA256.hash(data: Data(verifier.utf8)))
                .base64EncodedString().replacingOccurrences(of: "+", with: "-")
                .replacingOccurrences(of: "/", with: "_")
                .replacingOccurrences(of: "=", with: "")
            let state = Self.randomToken(byteCount: 24)
            let redirect = scheme + ":/oauth2redirect"
            var c = URLComponents(string: "https://accounts.google.com/o/oauth2/v2/auth")!
            c.queryItems = [
                URLQueryItem(name: "client_id", value: clientId),
                URLQueryItem(name: "redirect_uri", value: redirect),
                URLQueryItem(name: "response_type", value: "code"),
                URLQueryItem(name: "scope", value: scope),
                URLQueryItem(name: "access_type", value: "offline"),
                URLQueryItem(name: "prompt", value: "consent"),
                URLQueryItem(name: "state", value: state),
                URLQueryItem(name: "code_challenge", value: challenge),
                URLQueryItem(name: "code_challenge_method", value: "S256")
            ]
            guard let authURL = c.url else { throw DriveError.message("URL di accesso non valido.") }
            let callback = try await authorize(url: authURL, scheme: scheme)
            guard callback.scheme == scheme,
                  let params = URLComponents(url: callback, resolvingAgainstBaseURL: false)?.queryItems,
                  params.first(where: { $0.name == "state" })?.value == state else {
                throw DriveError.message("Risposta OAuth non valida: controllo state fallito.")
            }
            if let error = params.first(where: { $0.name == "error" })?.value {
                throw DriveError.message("Google: " + error)
            }
            guard let code = params.first(where: { $0.name == "code" })?.value, !code.isEmpty else {
                throw DriveError.message("Google non ha restituito un codice OAuth.")
            }
            let token = try await exchange([
                "client_id": clientId, "redirect_uri": redirect,
                "grant_type": "authorization_code", "code": code,
                "code_verifier": verifier
            ])
            adopt(token)
            connected = true
            message = "Google collegato. Carico la libreria..."
            try await readLibrary()
        } catch {
            message = error.localizedDescription
        }
    }

    func disconnect() {
        DriveKeychain.clear()
        accessToken = ""
        expiry = .distantPast
        connected = false
        songs = []
        selected = nil
        message = "Collegamento Google scollegato da Leon Karaoke (i file Drive sono invariati)."
    }

    func refreshLibrary() async {
        if loading { return }
        loading = true
        defer { loading = false }
        do { try await readLibrary() }
        catch { message = error.localizedDescription }
    }

    func fetchLyrics(for song: LeonDriveSong) async throws -> Data {
        guard let lyricsId = song.lyricsFileId, !lyricsId.isEmpty else {
            throw DriveError.message("Questo brano non ha ancora un testo sincronizzato su Drive.")
        }
        return try await fetchFile(lyricsId)
    }

    // Scarica i due MP3 nell'area cache PRIVATA di iOS, senza link pubblici
    // né token nella URL. Può riutilizzare il file tra un avvio e l'altro.
    func downloadTrack(for song: LeonDriveSong, mix: String) async throws -> URL {
        guard mix == "full" || mix == "no_vocals",
              let fileId = song.tracks?[mix], Self.validFileId(fileId) else {
            throw DriveError.message("Traccia \(mix) non presente su Drive: rielabora il brano sul PC.")
        }
        let cache = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("GuitarLeonAudio", isDirectory: true)
        try FileManager.default.createDirectory(at: cache, withIntermediateDirectories: true)
        let target = cache.appendingPathComponent(fileId).appendingPathExtension("mp3")
        if FileManager.default.fileExists(atPath: target.path) {
            if let size = (try? target.resourceValues(forKeys: [.fileSizeKey]).fileSize), size > 1024 {
                return target
            }
            try? FileManager.default.removeItem(at: target)
        }
        let bearer = try await authorizedToken()
        var c = URLComponents(string: filesAPI + "/" + fileId)!
        c.queryItems = [URLQueryItem(name: "alt", value: "media")]
        var req = URLRequest(url: c.url!)
        req.setValue("Bearer " + bearer, forHTTPHeaderField: "Authorization")
        req.timeoutInterval = 180
        let (downloaded, response) = try await URLSession.shared.download(for: req)
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard status == 200 else {
            throw DriveError.message("Download audio Drive non riuscito (HTTP \(status)).")
        }
        let size = (try downloaded.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0
        guard size > 1024 && size <= 250_000_000 else {
            throw DriveError.message("Dimensione audio non valida o superiore a 250 MB.")
        }
        // Il download non deve mai modificare i file Google Drive.
        if FileManager.default.fileExists(atPath: target.path) { try FileManager.default.removeItem(at: target) }
        try FileManager.default.moveItem(at: downloaded, to: target)
        return target
    }

    private static func validFileId(_ id: String) -> Bool {
        !id.isEmpty && id.count < 200 && id.allSatisfy {
            $0.isASCII && ($0.isLetter || $0.isNumber || $0 == "_" || $0 == "-")
        }
    }

    private func readLibrary() async throws {
        // Stesso schema della PWA: root/Guitar Backing Leon/libreria.json
        let roots = try await list(parent: "root", name: "Guitar Backing Leon", mime: "application/vnd.google-apps.folder")
        guard let folder = roots.first else {
            throw DriveError.message("Cartella Guitar Backing Leon non visibile. Accedi con l'account giusto e configura l'OAuth iOS nello stesso progetto Google Cloud della PWA (scope drive.file).")
        }
        let indexes = try await list(parent: folder.id, name: "libreria.json", mime: nil)
        guard let index = indexes.first else {
            throw DriveError.message("libreria.json non visibile su Drive: verificare permessi e account Google.")
        }
        let data = try await fetchFile(index.id)
        let library = try JSONDecoder().decode(DriveIndex.self, from: data)
        songs = library.songs.sorted { $0.name.localizedStandardCompare($1.name) == .orderedAscending }
        connected = true
        message = "Libreria sincronizzata: \(songs.count) brani (sola lettura)."
    }

    private func list(parent: String, name: String, mime: String?) async throws -> [DriveItem] {
        let safe = name.replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "'", with: "\\'")
        var query = "'\(parent)' in parents and trashed = false and name = '\(safe)'"
        if let mime { query += " and mimeType = '\(mime)'" }
        var items: [DriveItem] = []
        var page: String? = nil
        repeat {
            var c = URLComponents(string: filesAPI)!
            c.queryItems = [URLQueryItem(name: "q", value: query),
                            URLQueryItem(name: "fields", value: "nextPageToken,files(id,name)"),
                            URLQueryItem(name: "pageSize", value: "1000")]
            if let page { c.queryItems?.append(URLQueryItem(name: "pageToken", value: page)) }
            let data = try await request(url: c.url!)
            let response = try JSONDecoder().decode(DriveList.self, from: data)
            items.append(contentsOf: response.files ?? [])
            page = response.nextPageToken
        } while page != nil
        return items
    }

    private func fetchFile(_ id: String) async throws -> Data {
        guard Self.validFileId(id) else {
            throw DriveError.message("ID file Drive non valido.")
        }
        var c = URLComponents(string: filesAPI + "/" + id)!
        c.queryItems = [URLQueryItem(name: "alt", value: "media")]
        let data = try await request(url: c.url!)
        guard data.count < 2_000_000 else { throw DriveError.message("File testo troppo grande.") }
        return data
    }

    private func request(url: URL) async throws -> Data {
        let bearer = try await authorizedToken()
        var req = URLRequest(url: url)
        req.setValue("Bearer " + bearer, forHTTPHeaderField: "Authorization")
        req.setValue("application/json", forHTTPHeaderField: "Accept")
        req.timeoutInterval = 25
        let (data, response) = try await URLSession.shared.data(for: req)
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard status == 200 else {
            if status == 401 { throw DriveError.message("Sessione Google scaduta: riconnetti Google Drive.") }
            if status == 403 { throw DriveError.message("Drive HTTP 403: file non accessibili con i permessi OAuth attuali.") }
            throw DriveError.message("Google Drive HTTP \(status).")
        }
        return data
    }

    private func authorizedToken() async throws -> String {
        if !accessToken.isEmpty && Date() < expiry { return accessToken }
        guard let refresh = DriveKeychain.load() else {
            throw DriveError.message("Premi Collega Google Drive per autorizzare la libreria.")
        }
        let token = try await exchange([
            "client_id": clientId, "grant_type": "refresh_token", "refresh_token": refresh
        ])
        adopt(token)
        connected = true
        return token.access_token
    }

    private func adopt(_ token: OAuthToken) {
        accessToken = token.access_token
        expiry = Date().addingTimeInterval(max(30, (token.expires_in ?? 3600) - 90))
        if let refresh = token.refresh_token, !refresh.isEmpty { DriveKeychain.save(refresh) }
    }

    private func exchange(_ params: [String: String]) async throws -> OAuthToken {
        var c = URLComponents()
        c.queryItems = params.sorted { $0.key < $1.key }.map { URLQueryItem(name: $0.key, value: $0.value) }
        var req = URLRequest(url: tokenAPI)
        req.httpMethod = "POST"
        req.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type")
        req.httpBody = Data((c.percentEncodedQuery ?? "").utf8)
        req.timeoutInterval = 25
        let (data, response) = try await URLSession.shared.data(for: req)
        guard (response as? HTTPURLResponse)?.statusCode == 200 else {
            throw DriveError.message("Autorizzazione Google non riuscita. Verifica Client ID e consenso OAuth.")
        }
        return try JSONDecoder().decode(OAuthToken.self, from: data)
    }

    private func authorize(url: URL, scheme: String) async throws -> URL {
        try await withCheckedThrowingContinuation { continuation in
            let session = ASWebAuthenticationSession(url: url, callbackURLScheme: scheme) { [weak self] callback, error in
                self?.authSession = nil
                if let callback { continuation.resume(returning: callback) }
                else { continuation.resume(throwing: error ?? DriveError.message("Accesso Google annullato.")) }
            }
            session.presentationContextProvider = presentation
            session.prefersEphemeralWebBrowserSession = false
            authSession = session
            if !session.start() {
                authSession = nil
                continuation.resume(throwing: DriveError.message("Impossibile aprire l'autenticazione Google."))
            }
        }
    }

    private static func randomToken(byteCount: Int) -> String {
        var bytes = [UInt8](repeating: 0, count: byteCount)
        let status = SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes)
        precondition(status == errSecSuccess, "Sorgente casuale sicura non disponibile")
        return Data(bytes).base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }
}
