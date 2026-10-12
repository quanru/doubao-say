// swift-tools-version: 5.9
import PackageDescription
let package = Package(name: "DoubaoSayCore", platforms: [.macOS(.v13)], targets: [
    .target(name: "DoubaoSayCore", path: "Sources", exclude: ["APIASRClient.swift", "ASRParamsStore.swift", "AppState.swift", "AudioCaptureManager.swift", "AudioDevices.swift", "DoubaoASRClient.swift", "DoubaoSayApp.swift", "HotkeyManager.swift", "OverlayPanel.swift", "OverlayView.swift", "ListeningWaveform.swift", "PasteHelper.swift", "SecretStore.swift", "SettingsWindow.swift", "StartupService.swift", "TranscriptionManager.swift", "UpdateChecker.swift", "VibekeyReceiver.swift", "WebViewManager.swift", "WindowCapture.swift"], sources: ["VoiceMotion.swift", "HotkeyGesture.swift", "ASRResponse.swift", "FinalResultGate.swift", "ShortcutGesture.swift", "MacSettings.swift", "Strings.swift", "PolishDefaults.swift", "PolishClient.swift", "PolishCoordinator.swift", "SeedProtocol.swift", "VibekeyProtocol.swift"]),
    .testTarget(name: "DoubaoSayCoreTests", dependencies: ["DoubaoSayCore"], path: "Tests", exclude: ["Transport", "Live", "Network", "Settings"])
])
