// Injected into every frame before any page script runs.
// Reports who set a cookie or storage item. Values are sent to Python only to be hashed.
(() => {
  const send = (o) => {
    try {
      const r = window.__ndpa_log(JSON.stringify(o));
      if (r && r.catch) r.catch(() => {});
    } catch (e) {}
  };
  // URL of the first http(s) frame in the call stack, skipping our own injected frames.
  const caller = () => {
    const lines = (new Error().stack || '').split('\n').slice(1);
    for (const line of lines) {
      const m = line.match(/(https?:\/\/[^\s)]+?)(?::\d+){1,2}\)?$/);
      if (m) return m[1];
    }
    return null;
  };

  const desc = Object.getOwnPropertyDescriptor(Document.prototype, 'cookie');
  if (desc && desc.configurable) {
    Object.defineProperty(document, 'cookie', {
      configurable: true,
      get() { return desc.get.call(document); },
      set(v) {
        send({ kind: 'cookie_set_js', raw: String(v).slice(0, 4096), script: caller() });
        return desc.set.call(document, v);
      },
    });
  }

  // Note: direct property writes (localStorage.key = 'x') bypass setItem and are not seen.
  const origSetItem = Storage.prototype.setItem;
  Storage.prototype.setItem = function (k, v) {
    let area = 'storage';
    try {
      area = this === window.localStorage ? 'localStorage'
        : this === window.sessionStorage ? 'sessionStorage' : 'storage';
    } catch (e) {}
    send({ kind: 'storage_set', area, key: String(k), value: String(v).slice(0, 4096), script: caller() });
    return origSetItem.apply(this, arguments);
  };
})();
