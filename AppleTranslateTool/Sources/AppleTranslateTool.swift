import Foundation
import Translation

@main
struct TranslateToolMain {
    static func main() {
        let args = CommandLine.arguments
        
        guard args.count >= 4 else {
            print("Usage: AppleTranslateTool <source_lang> <target_lang> <text>")
            print("       AppleTranslateTool --prepare <source_lang> <target_lang>")
            exit(1)
        }
        
        if args[1] == "--prepare" {
            guard args.count >= 4 else {
                print("Error: --prepare requires source and target language")
                exit(1)
            }
            runPrepare(args[2], args[3])
            return
        }
        
        runTranslate(args[1], args[2], args[3...].joined(separator: " "))
    }
    
    static func runPrepare(_ source: String, _ target: String) {
        let sourceLang = Locale.Language(identifier: source)
        let targetLang = Locale.Language(identifier: target)
        
        let semaphore = DispatchSemaphore(value: 0)
        var exitCode = 0
        
        Task {
            do {
                _ = try await TranslationSession.prepareTranslation(
                    from: sourceLang,
                    to: targetLang
                )
                print("Prepared")
            } catch {
                print("Error: \(error)")
                exitCode = 1
            }
            semaphore.signal()
        }
        
        _ = semaphore.wait(timeout: .now() + 10)
        exit(exitCode)
    }
    
    static func runTranslate(_ source: String, _ target: String, _ text: String) {
        let sourceLang = Locale.Language(identifier: source)
        let targetLang = Locale.Language(identifier: target)
        
        let semaphore = DispatchSemaphore(value: 0)
        var exitCode = 0
        var result = ""
        
        Task {
            do {
                let session = try await TranslationSession(
                    from: sourceLang,
                    to: targetLang
                )
                result = try await session.translate(text)
                print(result)
            } catch {
                print("Error: \(error)")
                exitCode = 1
            }
            semaphore.signal()
        }
        
        _ = semaphore.wait(timeout: .now() + 30)
        exit(exitCode)
    }
}