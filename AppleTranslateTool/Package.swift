// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "AppleTranslateTool",
    platforms: [.macOS(.v15)],
    products: [
        .executable(name: "AppleTranslateTool-bin", targets: ["AppleTranslateTool"])
    ],
    targets: [
        .executableTarget(
            name: "AppleTranslateTool",
            path: "Sources",
            swiftSettings: [.swiftLanguageMode(.v6)]
        )
    ]
)
