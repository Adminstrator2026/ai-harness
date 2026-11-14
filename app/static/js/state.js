export const state = {
  sessionId: null,
  messages: [],
  sessions: [],
  pendingImgs: [],
  cfg: {
    api_url: '', api_key: '', model: '',
    system: '你是一个 AI 助手，请使用 Markdown 格式回答。',
    tools_enabled: true,
    think_level: 0, permission: 'User',
    enabled_tools: null,
    sandbox_mode: true,     // 🛡️ 沙箱模式：true=受限, false=完整权限
  },
  abortCtrl: null,
  isGen: false,
};

export function loadStorage() {
  try {
    const cfg = JSON.parse(localStorage.getItem('aih_cfg') || '{}');
    Object.assign(state.cfg, cfg);
    state.sessions = JSON.parse(localStorage.getItem('aih_sessions') || '[]');
  } catch (e) {}
  if (state.sessions.length) {
    state.sessionId = state.sessions[0].id;
    state.messages = state.sessions[0].messages || [];
  }
}

export function saveStorage() {
  localStorage.setItem('aih_cfg', JSON.stringify(state.cfg));
  if (state.sessionId) {
    let s = state.sessions.find(x => x.id === state.sessionId);
    if (!s) {
      s = { id: state.sessionId, title: '新对话', messages: [], timestamp: Date.now() };
      state.sessions.unshift(s);
    }
    s.messages = state.messages;
    s.timestamp = Date.now();
    if (state.messages[0] && s.title === '新对话') {
      s.title = (state.messages[0].content || '').slice(0, 20) || '新对话';
    }
    localStorage.setItem('aih_sessions', JSON.stringify(state.sessions.slice(0, 50)));
  }
}