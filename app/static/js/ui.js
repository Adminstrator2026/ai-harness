import { mdRender, decorateCodeBlocks, highlightCode } from './markdown.js';
import { state } from './state.js';

export function createThinkDOM(text, done) {
  const el = document.createElement('div');
  el.className = 'think';
  el.innerHTML = `
    <div class="think-head">
      <img class="think-icon" src="/resources/png/thinking_icon.svg" onerror="this.style.display='none'">
      <span class="think-text ${done ? '' : 'loading'}">${done ? '已深度思考' : '正在深度思考...'}</span>
      <svg class="think-arrow" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 12L10 8L6 4"/></svg>
    </div>
    <div class="think-body"></div>
  `;
  el.querySelector('.think-body').textContent = text || '';
  el.querySelector('.think-head').onclick = () => el.classList.toggle('open');
  return el;
}

export function createToolCardDOM(b) {
  const card = document.createElement('div');
  card.className = 'tool ' + (b.pending ? 'pending' : (b.ok ? 'ok' : 'err'));
  card.dataset.id = b.id;
  card.style.margin = '12px 0';
  card.innerHTML = `
    <div class="tool-head">
      <span class="title"></span><span class="name"></span><span class="status"></span>
    </div>
    <div class="tool-body"></div>`;
  card.querySelector('.title').textContent = b.title || b.name;
  card.querySelector('.name').textContent = b.name;
  const st = card.querySelector('.status');
  if (b.pending) { st.textContent = '运行中…'; }
  else { st.textContent = b.ok ? '✓ 完成' : '✗ 失败'; st.style.color = b.ok ? 'var(--ok)' : 'var(--err)'; }
  const body = card.querySelector('.tool-body');
  body.textContent = '参数：' + JSON.stringify(b.args, null, 2);
  if (!b.pending && b.result) body.textContent += '\n---\n结果：\n' + b.result;
  card.querySelector('.tool-head').onclick = () => card.classList.toggle('open');
  return card;
}

export function createNoticeDOM(text, ok) {
  const el = document.createElement('div');
  el.className = 'notice' + (ok ? ' ok' : '');
  el.style.margin = '10px 0';
  el.textContent = text;
  return el;
}

export function createUiEventDOM(ev) {
  if (ev.event === 'note') {
    const el = document.createElement('div');
    el.className = 'card';
    el.style.margin = '12px 0';
    el.innerHTML = `<div class="card-title"></div><div class="md"></div>`;
    el.querySelector('.card-title').textContent = ev.data.title || '提示';
    el.querySelector('.md').innerHTML = mdRender(ev.data.text || '');
    decorateCodeBlocks(el.querySelector('.md'));
    highlightCode(el.querySelector('.md'));
    return el;
  } else if (ev.event === 'steps') {
    const el = document.createElement('div');
    el.className = 'card';
    el.style.margin = '12px 0';
    el.innerHTML = `<div class="card-title"></div>`;
    el.querySelector('.card-title').textContent = ev.data.title || '进度';
    (ev.data.steps || []).forEach(s => {
      const row = document.createElement('div');
      row.className = 'step ' + (s.state || 'todo');
      row.innerHTML = `<span class="dot"></span><span class="txt"></span>`;
      row.querySelector('.txt').textContent = s.text || '';
      el.appendChild(row);
    });
    return el;
  }
  return null;
}

export function renderAskCard(ev, bubble) {
  const card = document.createElement('div');
  card.className = 'ask-card';
  card.style.margin = '12px 0';
  card.innerHTML = `<h4>AI 需要你的回答</h4>`;
  (ev.questions || []).forEach((q, qi) => {
    const block = document.createElement('div');
    block.className = 'ask-q';
    block.innerHTML = `<div class="q"></div><div class="opts"></div>`;
    block.querySelector('.q').textContent = (qi + 1) + '. ' + (q.text || '');
    const opts = block.querySelector('.opts');
    const picked = [];
    (q.options || []).forEach(opt => {
      const b = document.createElement('div');
      b.className = 'opt'; b.textContent = opt.label || opt;
      b.onclick = () => {
        if (q.multi) {
          const i = picked.indexOf(opt.label || opt);
          if (i >= 0) { picked.splice(i, 1); b.classList.remove('on'); }
          else { picked.push(opt.label || opt); b.classList.add('on'); }
        } else {
          opts.querySelectorAll('.opt').forEach(x => x.classList.remove('on'));
          b.classList.add('on'); picked.length = 0; picked.push(opt.label || opt);
        }
      };
      opts.appendChild(b);
    });
    block.appendChild(document.createElement('input')).placeholder = '自定义回答…';
    card.appendChild(block);
    block.dataset.qi = qi; block._picked = picked;
  });
  const actions = document.createElement('div');
  actions.className = 'ask-actions';
  actions.innerHTML = `<button class="primary-btn">提交回答</button>`;
  actions.querySelector('button').onclick = async () => {
    const arr = (ev.questions || []).map((q, qi) => {
      const block = card.querySelector(`.ask-q[data-qi="${qi}"]`);
      const picked = block?._picked || [];
      const inp = block?.querySelector('input');
      const custom = inp && inp.value.trim();
      if (picked.length) return picked.join('、');
      if (custom) return custom;
      return '未回答';
    });
    card.remove();
    try { await fetch('/api/ask/' + encodeURIComponent(ev.id), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ session_id: state.sessionId, answers: arr }) }); } catch (e) {}
  };
  card.appendChild(actions);
  bubble.appendChild(card);
  bubble.scrollTop = bubble.scrollHeight;
}