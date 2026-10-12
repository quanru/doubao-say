// inject-websocket.js
// Injected at document start for login detection and page visibility override.
// ASR is now handled natively via URLSessionWebSocketTask — no WebSocket interception needed.
(function() {
    'use strict';

    // --- Page Visibility API override ---
    // Prevent the page from knowing it's hidden so that JS timers and
    // session keep-alive requests continue running in the background.
    Object.defineProperty(document, 'visibilityState', {
        get: function() { return 'visible'; },
        configurable: true
    });
    Object.defineProperty(document, 'hidden', {
        get: function() { return false; },
        configurable: true
    });
    // Suppress visibilitychange events so page logic never enters a "hidden" branch
    document.addEventListener('visibilitychange', function(e) {
        e.stopImmediatePropagation();
    }, true);

    // --- Fetch interception: detect profile API for login status ---
    var OriginalFetch = window.fetch;
    window.fetch = function() {
        var url = arguments[0];
        var urlStr = (typeof url === 'string') ? url : (url && url.url) || '';

        var promise = OriginalFetch.apply(this, arguments);

        if (urlStr.includes('/alice/profile/self')) {
            promise.then(function(response) {
                var cloned = response.clone();
                cloned.json().then(function(data) {
                    if (data && data.code === 0 && data.data && data.data.profile_brief) {
                        window.webkit.messageHandlers.asrHandler.postMessage({
                            type: 'login',
                            status: 'loggedIn',
                            nickname: data.data.profile_brief.nickname || ''
                        });
                    } else {
                        window.webkit.messageHandlers.asrHandler.postMessage({
                            type: 'login',
                            status: 'notLoggedIn'
                        });
                    }
                }).catch(function() {
                    window.webkit.messageHandlers.asrHandler.postMessage({
                        type: 'login',
                        status: 'notLoggedIn'
                    });
                });
            }).catch(function() {
                // Network error — can't determine login
            });
        }

        return promise;
    };

    // --- XHR interception: fallback for profile API ---
    var OriginalXHROpen = XMLHttpRequest.prototype.open;
    var OriginalXHRSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function(method, url) {
        this.__doubaoMurmurUrl = url;
        return OriginalXHROpen.apply(this, arguments);
    };
    XMLHttpRequest.prototype.send = function() {
        if (this.__doubaoMurmurUrl && this.__doubaoMurmurUrl.includes('/alice/profile/self')) {
            this.addEventListener('load', function() {
                try {
                    var data = JSON.parse(this.responseText);
                    if (data && data.code === 0 && data.data && data.data.profile_brief) {
                        window.webkit.messageHandlers.asrHandler.postMessage({
                            type: 'login',
                            status: 'loggedIn',
                            nickname: data.data.profile_brief.nickname || ''
                        });
                    }
                } catch(e) {}
            });
        }
        return OriginalXHRSend.apply(this, arguments);
    };
})();
