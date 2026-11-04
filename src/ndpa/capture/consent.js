// Evaluated in the page. arg.fn = 'banner' (find the consent banner) or 'reopen' (find a re-open control).
(arg) => {
  const CONTROL_SEL = 'button, a, [role="button"], input[type="button"], input[type="submit"]';
  const DIALOG_SEL = 'dialog, [role="dialog"], [role="alertdialog"], [aria-modal="true"]';
  const KNOWN = ['#onetrust-banner-sdk', '#onetrust-consent-sdk', '#CybotCookiebotDialog',
    "div[class*='cookiebot']", '#cookieyes', "[data-testid*='cookie-banner']"];
  const MARKER = /cookie|consent|privacy preference/i;
  const STRONG = /\b(accept|agree|allow|reject|decline|deny|refuse|ok|okay|got it|necessary|essential|close|dismiss)\b|[×✕✖]/i;
  const FLOAT_TAGS = new Set(['DIV', 'SECTION', 'ASIDE', 'DIALOG', 'FORM']);

  // All elements under root, including inside open shadow roots.
  const descendants = (root) => {
    const out = [];
    const walk = (r) => {
      for (const el of r.querySelectorAll('*')) {
        out.push(el);
        if (el.shadowRoot) walk(el.shadowRoot);
      }
    };
    walk(root);
    if (root.shadowRoot) walk(root.shadowRoot);
    return out;
  };
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'
      && parseFloat(s.opacity) !== 0;
  };
  const label = (el) => (el.innerText || el.value || '').trim();
  // The banner's message must contain the marker words in text that is NOT inside a button or link,
  // otherwise a button labelled "Accept all cookies" would count as the whole banner.
  const hasMessage = (c) => {
    const walker = document.createTreeWalker(c, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const n = walker.currentNode;
      if (MARKER.test(n.nodeValue) && n.parentElement && !n.parentElement.closest(CONTROL_SEL)) return true;
    }
    return false;
  };
  const rect = (el) => {
    const b = el.getBoundingClientRect();
    return { x: b.x, y: b.y, width: b.width, height: b.height };
  };

  if (arg.fn === 'reopen') {
    const sel = arg.widgets.length ? CONTROL_SEL + ',' + arg.widgets.join(',') : CONTROL_SEL;
    for (const el of descendants(document)) {
      if (!el.matches(sel) || !visible(el)) continue;
      const text = label(el).toLowerCase();
      if (arg.lexicon.some((m) => text.includes(m)) || (arg.widgets.length && el.matches(arg.widgets.join(',')))) {
        return label(el) || el.id || el.className || 'widget';
      }
    }
    return null;
  }

  const all = descendants(document);
  let banner = null;
  let via = null;
  for (const sel of KNOWN) {
    const el = all.find((e) => e.matches(sel) && visible(e));
    if (el) { banner = el; via = 'known'; break; }
  }
  if (!banner) {
    const roots = all.filter((e) => {
      const p = getComputedStyle(e).position;
      return (p === 'fixed' || p === 'sticky' || e.matches(DIALOG_SEL)) && visible(e);
    });
    let best = null;
    for (const root of roots) {
      const pool = [root, ...descendants(root).filter((e) => FLOAT_TAGS.has(e.tagName))];
      for (const c of pool) {
        if (!visible(c) || !hasMessage(c)) continue;
        const controls = descendants(c).filter((e) => e.matches(CONTROL_SEL) && visible(e));
        if (!controls.some((e) => STRONG.test(label(e) + ' ' + (e.getAttribute('aria-label') || '')))) continue;
        const b = c.getBoundingClientRect();
        const area = b.width * b.height;
        if (!best || area < best.area) best = { el: c, area };
      }
    }
    if (best) { banner = best.el; via = 'generic'; }
  }
  if (!banner) return null;

  const controls = descendants(banner).filter((e) => e.matches(CONTROL_SEL) && visible(e)).map((e, i) => {
    const key = arg.mark ? arg.token + '-' + i : null;
    if (key) e.setAttribute('data-ndpa-i', key);
    return {
      key, text: label(e).slice(0, 80),
      aria: (e.getAttribute('aria-label') || e.getAttribute('title') || '').slice(0, 80),
      tag: e.tagName.toLowerCase(), box: rect(e),
    };
  });
  return {
    via, bbox: rect(banner), viewport: { width: innerWidth, height: innerHeight },
    text: (banner.innerText || '').slice(0, 3000), controls,
  };
}
