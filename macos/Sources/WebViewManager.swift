import AppKit
import WebKit

@MainActor
final class WebViewManager: NSObject, WKScriptMessageHandler, WKNavigationDelegate, WKUIDelegate, NSWindowDelegate {
    private let appState: AppState
    private var webView: WKWebView?
    private var window: NSWindow?
    var onLoginStatusChange: ((String, String?) -> Void)?
    init(appState: AppState) { self.appState = appState }

    func showLoginWindow() {
        if webView == nil {
            let config = WKWebViewConfiguration()
            // Cookie persistence is explicitly managed through Keychain.
            config.websiteDataStore = .nonPersistent()
            for (name, time) in [("inject-websocket", WKUserScriptInjectionTime.atDocumentStart),
                                 ("inject-dom", .atDocumentEnd)] {
                guard let url = Bundle.main.url(forResource: name, withExtension: "js"),
                      let source = try? String(contentsOf: url, encoding: .utf8) else {
                    appState.errorMessage = L("Login resources are missing. Rebuild the app.", "缺少登录资源，请重新构建应用。")
                    return
                }
                let guarded = "if (location.hostname === 'www.doubao.com') {\n" + source + "\n}"
                config.userContentController.addUserScript(WKUserScript(source: guarded, injectionTime: time, forMainFrameOnly: true))
            }
            config.userContentController.add(self, name: "asrHandler")
            let view = WKWebView(frame: .zero, configuration: config)
            view.navigationDelegate = self; view.uiDelegate = self
            view.customUserAgent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
            let panel = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1000, height: 720),
                styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
            panel.title = L("Doubao Say — Sign in", "豆包说 — 登录")
            panel.isReleasedWhenClosed = false; panel.contentView = view; panel.delegate = self
            window = panel; webView = view
            view.load(URLRequest(url: URL(string: "https://www.doubao.com/chat")!))
        }
        if let window { ApplicationPresence.willShow(window) }
        window?.center(); window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }
    func windowWillClose(_ notification: Notification) {
        if let window { ApplicationPresence.didHide(window) }
    }
    func hideLoginWindow() {
        window?.orderOut(nil)
        if let window { ApplicationPresence.didHide(window) }
    }
    func destroyWebView() {
        webView?.stopLoading()
        webView?.configuration.userContentController.removeScriptMessageHandler(forName: "asrHandler")
        webView?.navigationDelegate = nil; webView?.uiDelegate = nil
        hideLoginWindow(); window?.contentView = nil
        window = nil; webView = nil
    }
    func extractASRParams() async -> DoubaoASRParams? {
        guard let view = webView, view.url?.host == "www.doubao.com" else { return nil }
        let cookies: [HTTPCookie] = await withCheckedContinuation { continuation in
            view.configuration.websiteDataStore.httpCookieStore.getAllCookies { continuation.resume(returning: $0) }
        }
        let scoped = cookies.filter { $0.domain == "doubao.com" || $0.domain.hasSuffix(".doubao.com") }
        func webID(_ key: String) async -> String? {
            guard let raw = try? await view.evaluateJavaScript("localStorage.getItem('\(key)')") as? String,
                  let data = raw.data(using: .utf8),
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
            if let value = json["web_id"] as? String { return value }
            if let value = json["web_id"] as? NSNumber { return value.stringValue }
            return nil
        }
        guard !scoped.isEmpty, let deviceID = await webID("samantha_web_web_id"), !deviceID.isEmpty,
              let identifier = await webID("__tea_cache_tokens_497858"), !identifier.isEmpty else { return nil }
        return DoubaoASRParams(httpCookies: scoped, deviceId: deviceID, webId: identifier)
    }
    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.webView === webView, message.frameInfo.isMainFrame,
              message.frameInfo.securityOrigin.host == "www.doubao.com", message.name == "asrHandler",
              let body = message.body as? [String: Any], body["type"] as? String == "login",
              let status = body["status"] as? String else { return }
        onLoginStatusChange?(status, nil)
    }
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        webView.evaluateJavaScript("window.__doubaoMurmur?.isLoginButtonPresent()") { [weak self] result, _ in
            if result as? Bool == true { self?.appState.loginStatus = .notLoggedIn }
        }
    }
    func webView(_ webView: WKWebView, requestMediaCapturePermissionFor origin: WKSecurityOrigin,
        initiatedByFrame frame: WKFrameInfo, type: WKMediaCaptureType,
        decisionHandler: @escaping (WKPermissionDecision) -> Void) { decisionHandler(.deny) }
    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
        for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if navigationAction.targetFrame == nil { webView.load(navigationAction.request) }
        return nil
    }
}
