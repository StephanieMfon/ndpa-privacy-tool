/*
scanner/fingerprint_instrumentation.js

Injected via Playwright's context.add_init_script() BEFORE any of the
page's own scripts run, so these wraps are in place from the very first
line of page JS. Every wrap calls through to the ORIGINAL API — the site
must keep working normally during the scan, this is observation only.

Covers the six APIs from Fixed Decisions Register #6 / Rulebook SB-04:
  canvas.toDataURL()/.toBlob(), AudioContext/OfflineAudioContext,
  navigator.plugins, repeated measureText(), WebGLRenderingContext.getParameter(),
  navigator.mediaDevices.enumerateDevices().

Each call is logged to window.__ndpa_fp_log with a performance.now()
timestamp (calibrated against Python's clock by full_scan.py after
navigation) and, where cheaply available, a short excerpt of the returned
value — used for the "strong signal" transmission match in
script_behaviour.check_sb04(). Every wrap is wrapped in its own try/catch
so an instrumentation failure on one API never breaks page functionality
or silently kills the others.
*/
(() => {
    window.__ndpa_fp_log = [];

    function log(api, value_excerpt) {
        try {
            window.__ndpa_fp_log.push({
                api: api,
                perf_now: performance.now(),
                value_excerpt: value_excerpt || null,
            });
        } catch (e) { /* logging must never break the page */ }
    }

    // --- Canvas fingerprinting ---
    try {
        const origToDataURL = HTMLCanvasElement.prototype.toDataURL;
        HTMLCanvasElement.prototype.toDataURL = function (...args) {
            const result = origToDataURL.apply(this, args);
            try { log('canvas.toDataURL', String(result).slice(0, 64)); } catch (e) {}
            return result;
        };
    } catch (e) {}

    try {
        const origToBlob = HTMLCanvasElement.prototype.toBlob;
        HTMLCanvasElement.prototype.toBlob = function (callback, ...args) {
            log('canvas.toBlob', null);
            return origToBlob.call(this, callback, ...args);
        };
    } catch (e) {}

    // --- Audio fingerprinting ---
    // Constructor-level detection only — there's no single "derived value"
    // to capture at construction time (that comes from later calls like
    // getChannelData), so these entries never carry a value_excerpt and
    // rely entirely on the timing-correlation signal in check_sb04.
    try {
        const OrigAudioContext = window.AudioContext || window.webkitAudioContext;
        if (OrigAudioContext) {
            const Wrapped = function (...args) {
                log('AudioContext', null);
                return new OrigAudioContext(...args);
            };
            Wrapped.prototype = OrigAudioContext.prototype;
            window.AudioContext = Wrapped;
        }
    } catch (e) {}

    try {
        const OrigOfflineAudioContext = window.OfflineAudioContext || window.webkitOfflineAudioContext;
        if (OrigOfflineAudioContext) {
            const Wrapped = function (...args) {
                log('OfflineAudioContext', null);
                return new OrigOfflineAudioContext(...args);
            };
            Wrapped.prototype = OrigOfflineAudioContext.prototype;
            window.OfflineAudioContext = Wrapped;
        }
    } catch (e) {}

    // --- Plugin enumeration ---
    try {
        const descriptor = Object.getOwnPropertyDescriptor(Navigator.prototype, 'plugins');
        if (descriptor && descriptor.get) {
            Object.defineProperty(Navigator.prototype, 'plugins', {
                get: function () {
                    log('navigator.plugins', null);
                    return descriptor.get.call(this);
                },
                configurable: true,
            });
        }
    } catch (e) {}

    // --- Font fingerprinting (repeated measureText calls) ---
    // Every call is logged; "repeated" threshold is applied downstream in
    // check_sb04(), not here — this file only observes.
    try {
        const origMeasureText = CanvasRenderingContext2D.prototype.measureText;
        CanvasRenderingContext2D.prototype.measureText = function (...args) {
            log('measureText', String(args[0] || '').slice(0, 32));
            return origMeasureText.apply(this, args);
        };
    } catch (e) {}

    // --- Graphics card fingerprinting ---
    try {
        const origGetParameter = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = function (...args) {
            const result = origGetParameter.apply(this, args);
            try { log('WebGLRenderingContext.getParameter', String(result).slice(0, 64)); } catch (e) {}
            return result;
        };
    } catch (e) {}

    try {
        if (window.WebGL2RenderingContext) {
            const origGetParameter2 = WebGL2RenderingContext.prototype.getParameter;
            WebGL2RenderingContext.prototype.getParameter = function (...args) {
                const result = origGetParameter2.apply(this, args);
                try { log('WebGLRenderingContext.getParameter', String(result).slice(0, 64)); } catch (e) {}
                return result;
            };
        }
    } catch (e) {}

    // --- Device enumeration ---
    try {
        if (navigator.mediaDevices && navigator.mediaDevices.enumerateDevices) {
            const origEnumerate = navigator.mediaDevices.enumerateDevices.bind(navigator.mediaDevices);
            navigator.mediaDevices.enumerateDevices = function (...args) {
                log('navigator.mediaDevices.enumerateDevices', null);
                return origEnumerate(...args);
            };
        }
    } catch (e) {}
})();