export function copyText(text) {
  return new Promise((res, rej) => {
    if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(text).then(res).catch(() => fallback(text, res, rej));
    else fallback(text, res, rej);
  });
}

function fallback(text, res, rej) {
  try { const ta = document.createElement('textarea'); ta.value = text; ta.style.cssText = 'position:fixed;top:-9999px;'; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); ta.remove(); res(); } catch (e) { rej(e); }
}

export function escapeHtml(s) { return (s || '').replace(/[&<>'"]/g, x => `&#${x.charCodeAt(0)};`); }

export function downloadCode(text, lang, extMap) {
  const ext = extMap[(lang || '').toLowerCase()] || 'txt';
  const url = URL.createObjectURL(new Blob([text], { type: 'text/plain;charset=utf-8' }));
  const a = document.createElement('a'); a.href = url; a.download = `code-${Date.now()}.${ext}`; a.click(); URL.revokeObjectURL(url);
}

const toastTimer = { t: null };
export function toast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(toastTimer.t);
  toastTimer.t = setTimeout(() => el.classList.remove('show'), 2400);
}