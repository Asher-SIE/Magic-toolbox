import Foundation
@preconcurrency import Translation

private struct TranslationRequest: Decodable {
    let action: String
    let sourceLanguage: String
    let targetLanguage: String
    let text: String?
}

private struct TranslationReply: Encodable {
    let ok: Bool
    let translatedText: String?
    let error: String?
    let code: String?
    let status: String?
}

private struct RequestError: Error {
    let code: String
    let message: String
}

private func readRequest() throws -> TranslationRequest {
    let data = FileHandle.standardInput.readDataToEndOfFile()
    guard !data.isEmpty else {
        throw RequestError(code: "invalid_input", message: "Expected one JSON request on standard input")
    }
    do {
        return try JSONDecoder().decode(TranslationRequest.self, from: data)
    } catch {
        throw RequestError(code: "invalid_input", message: "Invalid JSON request: \(error)")
    }
}

private func writeReply(_ reply: TranslationReply) {
    do {
        var data = try JSONEncoder().encode(reply)
        data.append(0x0A)
        FileHandle.standardOutput.write(data)
        FileHandle.standardOutput.synchronizeFile()
    } catch {
        FileHandle.standardError.write(Data("Failed to encode reply: \(error)\n".utf8))
    }
}

// Headless CLI: no window, no focus, no language-download prompts. Language
// packs must be installed via System Settings > General > Language & Region
// > Translation Languages, or translation fails fast with language_not_installed.
@main
struct AppleTranslateTool {
    static func main() async {
        do {
            let request = try readRequest()
            let reply = try await run(request)
            writeReply(reply)
        } catch let error as RequestError {
            writeReply(TranslationReply(ok: false, translatedText: nil, error: error.message, code: error.code, status: nil))
            exit(1)
        } catch {
            writeReply(TranslationReply(ok: false, translatedText: nil, error: error.localizedDescription, code: "unknown", status: nil))
            exit(1)
        }
    }

    private static func run(_ request: TranslationRequest) async throws -> TranslationReply {
        let source = Locale.Language(identifier: request.sourceLanguage)
        let target = Locale.Language(identifier: request.targetLanguage)

        switch request.action {
        case "status":
            let availability = LanguageAvailability()
            let status = await availability.status(from: source, to: target)
            return TranslationReply(ok: true, translatedText: nil, error: nil, code: nil, status: statusName(status))
        case "translate":
            guard let text = request.text, !text.isEmpty else {
                throw RequestError(code: "invalid_input", message: "translate requires non-empty text")
            }
            do {
                let session = TranslationSession(installedSource: source, target: target)
                let response = try await session.translate(text)
                return TranslationReply(ok: true, translatedText: response.targetText, error: nil, code: nil, status: nil)
            } catch TranslationError.notInstalled {
                throw RequestError(code: "language_not_installed", message: "Translation language model is not installed")
            }
        default:
            throw RequestError(code: "invalid_input", message: "Unknown action: \(request.action)")
        }
    }

    private static func statusName(_ status: LanguageAvailability.Status) -> String {
        switch status {
        case .installed: return "installed"
        case .supported: return "supported"
        default: return "unsupported"
        }
    }
}
