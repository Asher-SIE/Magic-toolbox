import AppKit
import Foundation
import SwiftUI
import Translation

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
}

private enum RequestError: LocalizedError {
    case invalidInput(String)

    var errorDescription: String? {
        switch self {
        case .invalidInput(let message): return message
        }
    }
}

private func readRequest() throws -> TranslationRequest {
    let data = FileHandle.standardInput.readDataToEndOfFile()
    guard !data.isEmpty else {
        throw RequestError.invalidInput("Expected one JSON request on standard input")
    }
    return try JSONDecoder().decode(TranslationRequest.self, from: data)
}

@MainActor
private func writeReply(_ reply: TranslationReply) {
    do {
        var data = try JSONEncoder().encode(reply)
        data.append(0x0A)
        FileHandle.standardOutput.write(data)
    } catch {
        FileHandle.standardError.write(Data("Failed to encode reply: \(error)\n".utf8))
    }
    FileHandle.standardOutput.synchronizeFile()
    NSApplication.shared.terminate(nil)
}

@available(macOS 15.0, *)
private struct TranslationRunnerView: View {
    let request: TranslationRequest
    @State private var configuration: TranslationSession.Configuration
    @State private var started = false

    init(request: TranslationRequest) {
        self.request = request
        _configuration = State(initialValue: .init(
            source: Locale.Language(identifier: request.sourceLanguage),
            target: Locale.Language(identifier: request.targetLanguage)
        ))
    }

    var body: some View {
        VStack(spacing: 12) {
            ProgressView()
            Text("Preparing Apple Translation…")
        }
        .padding(24)
        .frame(minWidth: 320, minHeight: 120)
        .translationTask(configuration) { session in
            guard !started else { return }
            started = true
            do {
                // This is also the supported way for macOS to ask permission to
                // download a missing on-device language model.
                try await session.prepareTranslation()
                if request.action == "prepare" {
                    writeReply(.init(ok: true, translatedText: nil, error: nil))
                    return
                }
                guard request.action == "translate" else {
                    throw RequestError.invalidInput("Unknown action: \(request.action)")
                }
                let sourceText = request.text ?? ""
                let response = try await session.translate(sourceText)
                writeReply(.init(ok: true, translatedText: response.targetText, error: nil))
            } catch {
                writeReply(.init(ok: false, translatedText: nil, error: error.localizedDescription))
            }
        }
    }
}

@main
private struct AppleTranslateToolApp: App {
    private let request: Result<TranslationRequest, Error>

    init() {
        request = Result { try readRequest() }
        NSApplication.shared.setActivationPolicy(.accessory)
        NSApplication.shared.activate(ignoringOtherApps: true)
    }

    var body: some Scene {
        WindowGroup("Apple Translation") {
            Group {
                if #available(macOS 15.0, *) {
                    switch request {
                    case .success(let request):
                        TranslationRunnerView(request: request)
                    case .failure(let error):
                        Color.clear.task {
                            writeReply(.init(ok: false, translatedText: nil, error: error.localizedDescription))
                        }
                    }
                } else {
                    Color.clear.task {
                        writeReply(.init(ok: false, translatedText: nil, error: "Apple Translation requires macOS 15 or later"))
                    }
                }
            }
        }
        .windowResizability(.contentSize)
    }
}
