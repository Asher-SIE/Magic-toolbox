// swift-tools-version: 5.3
import PackageDescription

let package = Package(
    name: "AppleTranslateTool",
    platforms: [
        .macOS
    ],
    targets: [
        .executableTarget(
            name: "AppleTranslateTool",
            path: "Sources"
        )
    ]
)