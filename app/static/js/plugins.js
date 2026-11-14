export const AIHarness = {
  plugins: {},
  use(plugin) {
    if (!plugin || !plugin.id) return;
    this.plugins[plugin.id] = plugin;
    console.log(`[Plugin] 插件已加载: ${plugin.id}`);
    
    const api = {
      exec: async (cmd, shell = "cmd") => {
        const res = await fetch("/api/plugin/exec", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ command: cmd, shell })
        });
        return await res.json();
      },
      file: async (op, path, content = "") => {
        const res = await fetch("/api/plugin/file", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ op, path, content })
        });
        return await res.json();
      },
      browser: async (action, args) => {
        const res = await fetch("/api/plugin/tabbit", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action, ...args })
        });
        return await res.json();
      },
      injectUI: (target, html) => {
        if (target === 'sidebar-bottom') {
          const div = document.createElement('div');
          div.innerHTML = html;
          document.querySelector('.sb-foot').appendChild(div.firstElementChild);
        }
      },
      registerTool: (def) => console.log("[Plugin] 注册工具:", def.name)
    };

    try { plugin.install(api); } catch (e) { console.error(`[Plugin] 安装失败 ${plugin.id}`, e); }
  }
};
window.AIHarness = AIHarness;

export async function loadExternalPlugin(url) {
  return new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = url;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("脚本加载失败"));
    document.head.appendChild(script);
  });
}