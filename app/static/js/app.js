import { state, loadStorage, saveStorage } from './state.js';
import { escapeHtml, toast } from './utils.js';
import { mdRender, decorateCodeBlocks, highlightCode, renderMermaid } from './markdown.js';
import { createThinkDOM, createToolCardDOM, createNoticeDOM, createUiEventDOM, renderAskCard } from './ui.js';
import { loadExternalPlugin } from './plugins.js';

const $ = id => document.getElementById(id);

/* ---------- 主题 ---------- */
const THEME_KEY = 'aih_theme';
function applyTheme(t) {
  document.documentElement.dataset.theme = t;
  localStorage.setItem(THEME_KEY, t);
  $('btnTheme').textContent = t === 'dark' ? '☀️' : '🌙';
}

/* ---------- 基础渲染 ---------- */
function renderHistory() {
  const box = $('historyList');
  box.innerHTML = '';
  state.sessions.forEach(s => {
    const el = document.createElement('div');
    el.className = 'history-item' + (s.id === state.sessionId ? ' active' : '');
    el.innerHTML = `<span class="title"></span><button class="del">×</button>`;
    el.querySelector('.title').textContent = s.title || '新对话';
    el.onclick = () => {
      if (state.isGen) return toast('请先停止生成');
      state.sessionId = s.id; state.messages = s.messages || [];
      renderAll(); renderHistory();
    };
    el.querySelector('.del').onclick = (e) => {
      e.stopPropagation();
      state.sessions = state.sessions.filter(x => x.id !== s.id);
      if (state.sessionId === s.id) {
        state.sessionId = state.sessions[0]?.id || null;
        state.messages = state.sessions[0]?.messages || [];
        if (!state.sessionId) newSession();
        renderAll();
      }
      saveStorage();
    };
    box.appendChild(el);
  });
}

function newSession() {
  state.sessionId = null; state.messages = []; state.pendingImgs = [];
  renderImgPreview(); renderAll();
}

function renderAll() {
  const chat = $('chat');
  chat.innerHTML = '';
  if (!state.messages.length) {
    chat.innerHTML = '<div class="msg ai" style="color:var(--muted);text-align:center;margin-top:20vh;">开始你的新对话吧</div>';
    return;
  }
  state.messages.forEach(m => {
    if (m.role === 'user') {
      const el = document.createElement('div');
      el.className = 'msg user';
      let inner = escapeHtml(m.content || '') + (m.images ? `<div class="msg-imgs" style="display:flex;gap:6px;margin-top:8px;">${m.images.map(i => `<img src="${i.dataUrl}" style="max-width:150px;border-radius:6px;">`).join('')}</div>` : '');
      el.innerHTML = `<div class="bubble">${inner}</div>`;
      chat.appendChild(el);
    } else {
      const el = document.createElement('div');
      el.className = 'msg ai';
      const bubble = document.createElement('div');
      bubble.className = 'bubble';
      
      if (m.reasoning) bubble.appendChild(createThinkDOM(m.reasoning, true));
      if (!m.blocks) {
        const md = document.createElement('div'); md.className = 'md'; md.innerHTML = mdRender(m.content);
        bubble.appendChild(md); decorateCodeBlocks(md); highlightCode(md); renderMermaid(md);
      } else {
        m.blocks.forEach(b => {
          if (b.type === 'text') {
            const md = document.createElement('div'); md.className = 'md'; md.innerHTML = mdRender(b.content);
            bubble.appendChild(md); decorateCodeBlocks(md); highlightCode(md); renderMermaid(md);
          } else if (b.type === 'tool') {
            const card = createToolCardDOM(b); bubble.appendChild(card);
            if (b.ui_event && !b.pending) { const extra = createUiEventDOM(b.ui_event); if (extra) bubble.appendChild(extra); }
          } else if (b.type === 'notice') {
            bubble.appendChild(createNoticeDOM(b.text, b.ok));
          }
        });
      }
      el.appendChild(bubble); chat.appendChild(el);
    }
  });
  chat.scrollTop = chat.scrollHeight;
}

/* ---------- 图片/视频处理 ---------- */
const fileToDataUrl = f => new Promise(r => { const fr = new FileReader(); fr.onload = () => r(fr.result); fr.readAsDataURL(f); });

function renderImgPreview() {
  const box = $('imgPreview');
  box.innerHTML = '';
  state.pendingImgs.forEach((img, i) => {
    const el = document.createElement('div');
    el.className = 'thumb-img';
    el.innerHTML = `<img src="${img.dataUrl}" title="${img.from === 'video' ? '视频帧' : ''}">` +
      (img.from === 'video' ? '<span class="vf-badge">帧</span>' : '');
    const rm = document.createElement('button');
    rm.className = 'rm';
    rm.textContent = '×';
    rm.onclick = () => { state.pendingImgs.splice(i, 1); renderImgPreview(); };
    el.appendChild(rm);
    box.appendChild(el);
  });
}

function extractVideoFrames(file, count = 6, maxW = 800) {
  return new Promise((resolve, reject) => {
    const video = document.createElement('video');
    const url = URL.createObjectURL(file);
    video.preload = 'auto'; video.muted = true; video.playsInline = true;
    let settled = false;
    const done = (fn, arg) => { if (settled) return; settled = true; try { URL.revokeObjectURL(url); } catch (e) {} fn(arg); };
    video.onerror = () => done(reject, new Error('视频无法解码'));
    video.onloadedmetadata = async () => {
      try {
        const dur = video.duration;
        if (!isFinite(dur) || dur <= 0) throw new Error('无法读取视频时长');
        const scale = Math.min(1, maxW / (video.videoWidth || maxW));
        const canvas = document.createElement('canvas');
        canvas.width = Math.max(1, Math.round((video.videoWidth || maxW) * scale));
        canvas.height = Math.max(1, Math.round((video.videoHeight || maxW) * scale));
        const ctx = canvas.getContext('2d');
        const frames = [];
        const seek = t => new Promise(res => {
          const onSeek = () => { video.removeEventListener('seeked', onSeek); res(); };
          video.addEventListener('seeked', onSeek);
          video.currentTime = Math.min(Math.max(t, 0), Math.max(0, dur - 0.05));
        });
        for (let i = 0; i < count; i++) {
          const t = dur <= 0.2 ? 0 : (dur * (i + 0.5)) / count;
          await seek(t);
          ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
          frames.push(canvas.toDataURL('image/jpeg', 0.82));
        }
        done(resolve, frames);
      } catch (e) { done(reject, e); }
    };
    video.src = url;
    setTimeout(() => { if (!settled) done(reject, new Error('视频解析超时')); }, 20000);
  });
}

/* ---------- 发送与流处理 ---------- */
async function send() {
  if (state.isGen) return;
  const text = $('input').value.trim();
  if (!text && !state.pendingImgs.length) return;
  if (!state.cfg.model) return toast('请先选择模型');

  const imgs = state.pendingImgs.slice();
  state.messages.push({ role: 'user', content: text, images: imgs });
  $('input').value = ''; $('input').style.height = 'auto';
  state.pendingImgs = []; renderImgPreview();
  saveStorage(); renderAll();

  await runAgent();
}

async function runAgent() {
  state.isGen = true;
  $('btnSend').style.display = 'none'; $('btnStop').style.display = 'inline-block';
  state.abortCtrl = new AbortController();

  const cur = { reasoning: '', blocks: [{ type: 'text', content: '' }], thinkEl: null, thinkBody: null, tools: {} };
  const chat = $('chat');
  const wrap = document.createElement('div');
  wrap.className = 'msg ai'; wrap.innerHTML = `<div class="bubble"></div>`;
  const bubble = wrap.querySelector('.bubble');
  chat.appendChild(wrap);

  let currentMdEl = document.createElement('div'); currentMdEl.className = 'md'; bubble.appendChild(currentMdEl);

  const apiMsgs = state.messages.map(m => {
    if (m.role !== 'user' || !m.images || !m.images.length) return { role: m.role, content: m.content };
    const content = [];
    if (m.content) content.push({ type: 'text', text: m.content });
    m.images.forEach(i => content.push({ type: 'image_url', image_url: { url: i.dataUrl } }));
    return { role: 'user', content };
  });

  const payload = {
    session_id: state.sessionId, messages: apiMsgs.slice(-20),
    api_url: state.cfg.api_url, api_key: state.cfg.api_key, model: state.cfg.model,
    system: state.cfg.system, tools_enabled: state.cfg.tools_enabled,
    think_level: Number(state.cfg.think_level), permission: state.cfg.permission,
    enabled_tools: state.cfg.enabled_tools,
    sandbox_mode: state.cfg.sandbox_mode !== false,  // 默认 true
  };

  let buf = '';
  try {
    const resp = await fetch('/api/chat', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload), signal: state.abortCtrl.signal,
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${(await resp.text()).slice(0, 300)}`);
    
    const reader = resp.body.getReader(); const dec = new TextDecoder();
    while (true) {
      const { done, value } = await reader.read(); if (done) break;
      buf += dec.decode(value, { stream: true });
      const lines = buf.split('\n'); buf = lines.pop();
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        try { handleEvent(JSON.parse(line.slice(6)), cur, bubble, () => currentMdEl, (el) => currentMdEl = el); } catch (e) {}
      }
    }
  } catch (e) {
    if (e.name === 'AbortError') bubble.innerHTML += `<div class="notice">已停止</div>`;
    else bubble.appendChild(createNoticeDOM('请求失败：' + (e.message || e), false));
  } finally {
    state.isGen = false;
    $('btnSend').style.display = 'inline-block'; $('btnStop').style.display = 'none';
    if (cur.thinkEl) cur.thinkEl.querySelector('.think-text').textContent = '已深度思考';

    if (cur.blocks.some(b => b.type !== 'text' || b.content.trim()) || cur.reasoning) {
      if (cur.blocks[cur.blocks.length-1]?.type === 'text' && !cur.blocks[cur.blocks.length-1].content.trim()) cur.blocks.pop();
      state.messages.push({ role: 'assistant', reasoning: cur.reasoning, blocks: cur.blocks, content: cur.blocks.filter(b=>b.type==='text').map(b=>b.content).join('\n\n') });
      saveStorage();
    }
    bubble.querySelectorAll('.md').forEach(md => { decorateCodeBlocks(md); highlightCode(md); renderMermaid(md); });
  }
}

function handleEvent(ev, cur, bubble, getMd, setMd) {
  const autoScroll = () => { if ($('chat').scrollHeight - $('chat').scrollTop - $('chat').clientHeight < 160) $('chat').scrollTop = $('chat').scrollHeight; };
  switch (ev.type) {
    case 'session': if (!state.sessionId) { state.sessionId = ev.id; saveStorage(); } break;
    case 'reasoning':
      cur.reasoning += ev.text || '';
      if (!cur.thinkEl) { cur.thinkEl = createThinkDOM('', false); cur.thinkBody = cur.thinkEl.querySelector('.think-body'); bubble.insertBefore(cur.thinkEl, bubble.firstChild); }
      cur.thinkBody.textContent = cur.reasoning; break;
    case 'token':
      let mdEl = getMd();
      if (!mdEl) { cur.blocks.push({ type: 'text', content: '' }); mdEl = document.createElement('div'); mdEl.className = 'md'; bubble.appendChild(mdEl); setMd(mdEl); }
      cur.blocks[cur.blocks.length - 1].content += ev.text || '';
      mdEl.innerHTML = mdRender(cur.blocks[cur.blocks.length - 1].content, true);
      decorateCodeBlocks(mdEl); highlightCode(mdEl); autoScroll(); break;
    case 'tool_start':
      setMd(null);
      const toolBlock = { type: 'tool', id: ev.id, name: ev.name, title: ev.title, args: ev.args, pending: true, ok: false, result: '' };
      cur.blocks.push(toolBlock); cur.tools[ev.id] = toolBlock;
      bubble.appendChild(createToolCardDOM(toolBlock)); autoScroll(); break;
    case 'tool_end':
      const t = cur.tools[ev.id];
      if (t) {
        t.pending = false; t.ok = ev.ok; t.result = ev.result; t.ui_event = ev.ui_event;
        const old = bubble.querySelector(`.tool[data-id="${ev.id}"]`);
        if (old) old.replaceWith(createToolCardDOM(t));
        if (ev.ui_event) { const extra = createUiEventDOM(ev.ui_event); if (extra) bubble.appendChild(extra); }
      }
      autoScroll(); break;
    case 'ask': renderAskCard(ev, bubble); break;
    case 'notice': cur.blocks.push({ type: 'notice', text: ev.text, ok: ev.ok }); bubble.appendChild(createNoticeDOM(ev.text, ev.ok)); autoScroll(); break;
    case 'task_complete': cur.blocks.push({ type: 'notice', text: '✓ 任务完成：' + (ev.summary || ''), ok: true }); bubble.appendChild(createNoticeDOM('✓ 任务完成：' + (ev.summary || ''), true)); break;
    case 'round_limit': cur.blocks.push({ type: 'notice', text: `已达上限（${ev.max} 轮）`, ok: false }); bubble.appendChild(createNoticeDOM(`已达上限（${ev.max} 轮）`, false)); break;
    case 'error': cur.blocks.push({ type: 'notice', text: '错误：' + ev.message, ok: false }); bubble.appendChild(createNoticeDOM('错误：' + ev.message, false)); break;
    case 'done': if (cur.thinkEl) cur.thinkEl.querySelector('.think-text').textContent = '已深度思考'; break;
  }
}

/* ---------- 配置与工具 ---------- */
async function fetchModels() {
  const box = $('modelList'); box.innerHTML = '<div style="padding:10px;text-align:center;color:var(--muted);">加载中…</div>';
  try {
    const resp = await fetch('/api/models', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ api_url: state.cfg.api_url, api_key: state.cfg.api_key }) });
    const data = await resp.json();
    if (data.error) throw new Error(data.error);
    box.innerHTML = '';
    data.models.forEach(m => {
      const el = document.createElement('div'); el.className = 'model-item' + (m === state.cfg.model ? ' active' : ''); el.textContent = m;
      el.onclick = () => { state.cfg.model = m; updateModelLabel(); saveStorage(); $('modelPopover').style.display = 'none'; toast('已选择：' + m); };
      box.appendChild(el);
    });
  } catch (e) { box.innerHTML = `<div style="color:var(--err);text-align:center;">${e.message}</div>`; }
}

function updateModelLabel() {
  const m = state.cfg.model || '未选模型';
  const t = ['Off', '中', '高'][Number(state.cfg.think_level || 0)];
  $('modelLabel').textContent = `${m} · ${t}`;
}

let allToolsCache = [];
async function loadPlugins() {
  const container = $('pluginListContainer'); container.innerHTML = '<div style="text-align:center;padding:10px;">加载中…</div>';
  try {
    if (!allToolsCache.length) allToolsCache = await (await fetch('/api/tools')).json();
    container.innerHTML = '';
    let enabled = state.cfg.enabled_tools || allToolsCache.map(t => t.name);
    allToolsCache.forEach(t => {
      const el = document.createElement('label'); el.className = 'plugin-item';
      el.innerHTML = `<input type="checkbox" value="${t.name}" ${enabled.includes(t.name) ? 'checked' : ''}><div class="plugin-info"><div class="plugin-name">${t.title} <span style="font-size:11px;color:var(--muted);">(${t.name})</span></div><div class="plugin-desc">${t.desc || ''}</div></div>`;
      el.querySelector('input').onchange = () => { state.cfg.enabled_tools = [...container.querySelectorAll('input:checked')].map(i => i.value); saveStorage(); };
      container.appendChild(el);
    });
  } catch (e) { container.innerHTML = '加载失败'; }
}

/* ---------- 启动与绑定 ---------- */
function bind() {
  $('btnNew').onclick = () => { if (state.isGen) return toast('请先停止'); newSession(); renderHistory(); };
  $('btnSend').onclick = send;
  $('btnStop').onclick = () => { try { state.abortCtrl?.abort(); } catch (e) {} };
  $('btnTheme').onclick = () => applyTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
  $('btnImg').onclick = () => $('imgInput').click();
  $('input').addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); } });
  $('input').addEventListener('input', function () {
    this.style.height = 'auto';
    this.style.height = Math.min(this.scrollHeight, 200) + 'px';
  });
  
  // 图片/视频上传绑定
  $('imgInput').addEventListener('change', async e => {
    const files = [...e.target.files];
    e.target.value = '';
    for (const f of files) {
      try {
        if (f.type.startsWith('image/')) {
          if (f.size >= 5242880) { toast('图片超 5MB，已跳过'); continue; }
          state.pendingImgs.push({ dataUrl: await fileToDataUrl(f), from: 'image' });
        } else if (f.type.startsWith('video/')) {
          if (f.size > 200 * 1024 * 1024) { toast('视频超 200MB，已跳过'); continue; }
          toast('正在抽取视频关键帧…');
          const frames = await extractVideoFrames(f, 6);
          frames.forEach(d => state.pendingImgs.push({ dataUrl: d, from: 'video' }));
          toast(`已抽取 ${frames.length} 帧`);
        } else {
          toast('不支持的文件类型');
        }
      } catch (err) {
        toast('处理失败：' + (err.message || err));
      }
      renderImgPreview();
    }
  });
  
  $('modelLabel').onclick = () => { const p = $('modelPopover'); if (p.style.display === 'none') { p.style.display = 'flex'; fetchModels(); } else { p.style.display = 'none'; } };
  $('btnRefreshModels').onclick = (e) => { e.stopPropagation(); fetchModels(); };
  document.addEventListener('click', (e) => { const p = $('modelPopover'); if (p.style.display !== 'none' && !p.contains(e.target) && e.target.id !== 'modelLabel') p.style.display = 'none'; });

  $('btnPlugins').onclick = async () => { $('pluginsModal').classList.add('show'); await loadPlugins(); };
  $('btnClosePlugins').onclick = () => $('pluginsModal').classList.remove('show');

  // ── 设置弹窗（之前未实现，现在补上） ──
  $('btnSettings').onclick = () => {
    // 打开时把当前 cfg 灌进表单
    $('apiUrl').value = state.cfg.api_url || '';
    $('apiKey').value = state.cfg.api_key || '';
    $('model').value = state.cfg.model || '';
    $('system').value = state.cfg.system || '';
    $('toolsEnabled').checked = !!state.cfg.tools_enabled;
    $('thinkLevel').value = state.cfg.think_level ?? 0;
    $('permission').value = state.cfg.permission || 'workspace';
    $('sandboxMode').checked = state.cfg.sandbox_mode !== false;
    $('settingsModal').classList.add('show');
  };
  $('btnCloseSettings').onclick = () => $('settingsModal').classList.remove('show');
  $('btnSaveSettings').onclick = () => {
    state.cfg.api_url = $('apiUrl').value.trim();
    state.cfg.api_key = $('apiKey').value.trim();
    state.cfg.model = $('model').value.trim();
    state.cfg.system = $('system').value.trim() || state.cfg.system;
    state.cfg.tools_enabled = $('toolsEnabled').checked;
    state.cfg.think_level = Number($('thinkLevel').value) || 0;
    state.cfg.permission = $('permission').value;
    state.cfg.sandbox_mode = $('sandboxMode').checked;
    saveStorage();
    updateModelLabel();
    $('settingsModal').classList.remove('show');
    toast('✅ 设置已保存');
  };

  setTimeout(async () => { try { await loadExternalPlugin('/static/tabbit.js'); } catch (e) {} }, 1000);
}

/* ---------- 初始化 ---------- */
applyTheme(localStorage.getItem(THEME_KEY) || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'));
loadStorage(); bind(); updateModelLabel(); renderHistory(); renderAll();