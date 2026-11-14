import { copyText, downloadCode, toast } from './utils.js';

const SVG_COPY = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';
const SVG_CHECK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>';
const SVG_DOWN  = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>';
const SVG_WRAP  = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="15" y2="12"/><line x1="3" y1="18" x2="18" y2="18"/></svg>';

export const EXT_MAP = {python:'py',py:'py',javascript:'js',js:'js',typescript:'ts',ts:'ts',html:'html',css:'css',json:'json',yaml:'yml',yml:'yml',bash:'sh',shell:'sh',sh:'sh',sql:'sql',java:'java',c:'c',cpp:'cpp','c++':'cpp',cs:'cs',go:'go',rust:'rs',rs:'rs',php:'php',markdown:'md',md:'md',text:'txt'};

export function decorateCodeBlocks(container) {
  container.querySelectorAll('pre').forEach(pre => {
    const lang = (pre.querySelector('code')?.className || '').match(/(?:language|lang)-([\w+#-]+)/i)?.[1]?.toLowerCase() || '';
    if (lang === 'mermaid') return;
    if (!pre.querySelector('.code-lang')) { const lg = document.createElement('span'); lg.className = 'code-lang'; lg.textContent = lang || 'text'; pre.appendChild(lg); }
    if (pre.querySelector('.code-toolbar')) return;

    const tb = document.createElement('div'); tb.className = 'code-toolbar';
    
    const copyBtn = document.createElement('button'); copyBtn.className = 'code-btn'; copyBtn.innerHTML = `${SVG_COPY} 复制`;
    copyBtn.onclick = (e) => { e.stopPropagation(); copyText(pre.querySelector('code').textContent).then(() => { copyBtn.classList.add('success'); copyBtn.innerHTML = `${SVG_CHECK} 已复制`; setTimeout(() => { copyBtn.classList.remove('success'); copyBtn.innerHTML = `${SVG_COPY} 复制`; }, 1800); }).catch(() => toast('复制失败')); };
    
    const dlBtn = document.createElement('button'); dlBtn.className = 'code-btn'; dlBtn.innerHTML = `${SVG_DOWN} 下载`;
    dlBtn.onclick = (e) => { e.stopPropagation(); downloadCode(pre.querySelector('code').textContent, lang, EXT_MAP); };
    
    const saveBtn = document.createElement('button'); saveBtn.className = 'code-btn'; saveBtn.innerHTML = `💾 保存`;
    saveBtn.onclick = async (e) => { 
      e.stopPropagation(); 
      const filename = prompt("请输入保存的文件名（含后缀）：", `code_${Date.now()}.${EXT_MAP[lang] || 'txt'}`);
      if (!filename) return;
      saveBtn.innerHTML = '⏳...';
      try {
        const resp = await fetch('/api/save_file', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ filename, content: pre.querySelector('code').textContent })
        });
        const data = await resp.json();
        if (data.error) throw new Error(data.error);
        saveBtn.innerHTML = `✅ 已存`;
        toast('已保存至工作区：' + data.path);
        setTimeout(() => saveBtn.innerHTML = '💾 保存', 2000);
      } catch(err) {
        saveBtn.innerHTML = `❌ 失败`;
        toast('保存失败：' + err.message);
        setTimeout(() => saveBtn.innerHTML = '💾 保存', 2000);
      }
    };
    
    const wrapBtn = document.createElement('button'); wrapBtn.className = 'code-btn'; wrapBtn.innerHTML = SVG_WRAP;
    wrapBtn.onclick = (e) => { e.stopPropagation(); pre.classList.toggle('wrap'); wrapBtn.style.color = pre.classList.contains('wrap') ? '#fff' : ''; };

    tb.append(copyBtn, dlBtn, saveBtn, wrapBtn); pre.appendChild(tb);
  });
}

export function highlightCode(container) {
  container.querySelectorAll('pre code').forEach(el => {
    if (el.dataset.hl === 'yes' || el.closest('.mermaid') || /language-mermaid/i.test(el.className)) return;
    try { hljs.highlightElement(el); el.dataset.hl = 'yes'; } catch (e) {}
  });
}

export async function renderMermaid(container) {
  if (!window.mermaid) return;
  container.querySelectorAll('pre code.language-mermaid, pre code.lang-mermaid').forEach(code => {
    const div = document.createElement('div'); div.className = 'mermaid'; div.textContent = code.textContent; code.parentElement.replaceWith(div);
  });
  if (container.querySelectorAll('.mermaid').length) { try { await mermaid.run({ nodes: container.querySelectorAll('.mermaid') }); } catch (e) {} }
}
window.addEventListener('DOMContentLoaded', () => { if (window.mermaid) mermaid.initialize({ startOnLoad: false, theme: 'default', securityLevel: 'loose' }); });

const mathStore = [];
export function closeUnclosedMd(s) {
  let open = false, fence = '';
  for (const line of s.split('\n')) {
    const m = line.match(/^(`{3,}|~{3,})/); if (!m) continue;
    if (!open) { open = true; fence = m[1]; } else if (line.startsWith(fence)) { open = false; fence = ''; }
  }
  if (open) s += '\n```'; return s;
}
export function extractMath(md) {
  mathStore.length = 0; const lines = md.split('\n'); let inFence = false, fenceMark = ''; const out = [];
  for (let line of lines) {
    const fm = line.match(/^(`{3,}|~{3,})/);
    if (fm) { if (!inFence) { inFence = true; fenceMark = fm[1]; } else if (line.startsWith(fenceMark)) { inFence = false; fenceMark = ''; } out.push(line); continue; }
    if (inFence) { out.push(line); continue; }
    const block = line.match(/^\s*\$\$([^$]+?)\$\$\s*$/);
    if (block) { const i = mathStore.length; mathStore.push({ tex: block[1].trim(), display: true }); out.push(`%%MATH${i}%%`); continue; }
    line = line.replace(/(?<!\d)\$([^\$\n]+?)\$(?!\d)/g, (_, tex) => { const i = mathStore.length; mathStore.push({ tex: tex.trim(), display: false }); return `%%MATH${i}%%`; });
    out.push(line);
  }
  return out.join('\n');
}
export function restoreMath(html) {
  if (!window.katex) return html.replace(/%%MATH(\d+)%%/g, (_, n) => { const m = mathStore[+n]; return m ? m.tex : ''; });
  return html.replace(/%%MATH(\d+)%%/g, (_, n) => {
    const m = mathStore[+n]; if (!m || !m.tex) return '';
    try { return katex.renderToString(m.tex, { displayMode: m.display, throwOnError: false, strict: 'ignore' }); } catch (e) { return m.tex; }
  });
}

export function mdRender(text, streaming = false) {
  if (typeof marked === 'undefined') return text.replace(/</g, '&lt;').replace(/\n/g, '<br>');
  let src = streaming ? closeUnclosedMd(text) : text; 
  src = src.replace(/```[a-zA-Z0-9_-]*\s*\n*\s*```/g, '');
  src = extractMath(src);
  let html;
  try { html = marked.parse(src, { breaks: true, gfm: true }); } catch (e) { html = text.replace(/</g, '&lt;'); }
  return restoreMath(window.DOMPurify ? DOMPurify.sanitize(html) : html);
}