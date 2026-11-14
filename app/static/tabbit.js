(function () {
  const H = window.AIHarness;
  if (!H) { console.warn('[tabbit] AIHarness 未就绪'); return; }

  H.use({
    id: 'tabbit',
    title: 'Tabbit 浏览器',
    install(api) {
      console.log('[tabbit] 插件已挂载');
      // 只读读取当前标签页
      window.tabbitRead = async () => {
        const r = await api.browser('text', { maxChars: 8000 });
        return r.result || r.error;
      };
      // 打开网页
      window.tabbitOpen = async (url) => {
        const r = await api.browser('open', { url, maxChars: 8000 });
        return r.result || r.error;
      };
      
      api.injectUI('sidebar-bottom', `
        <button class="ghost-btn" style="width:100%;margin-bottom:8px;" onclick="alert('已触发 Tabbit 插件动作（请在控制台查看）')">🌐 Tabbit 插件</button>
      `);
    }
  });
})();