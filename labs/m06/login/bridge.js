// Explicit classroom adapter, not an injected wallet. No private keys and no chain transport.
const signerOrigin = 'http://localhost:18221';
const failure = (code, message) => Object.assign(new Error(message), {code});

export function openLabSigner() {
  const popup = window.open(signerOrigin + '/', '_blank', 'popup,width=600,height=740');
  if (!popup) throw failure(4900, '未打开签名器；允许本页打开新窗口再试。');
  const pending = new Map(), events = new EventTarget();
  let next = 0, closed = false, ready, failed;
  const opened = new Promise((resolve, reject) => { ready = resolve; failed = reject; });
  function close() {
    if (closed) return;
    closed = true; clearInterval(watch); clearTimeout(deadline);
    window.removeEventListener('message', receive);
    if (!popup.closed) popup.close();
    const err = failure(4900, '教学签名器未启动或已关闭。重新选择来源。');
    failed(err);
    for (const item of pending.values()) item.reject(err);
    pending.clear(); events.dispatchEvent(new CustomEvent('disconnect', {detail: err}));
  }
  function receive(e) {
    if (e.origin !== signerOrigin || e.source !== popup || !e.data) return;
    const {kind, id, result, error, event, value} = e.data;
    if (kind === 'ready') { clearTimeout(deadline); ready(); }
    if (kind === 'event' && ['accountsChanged', 'chainChanged'].includes(event)) {
      events.dispatchEvent(new CustomEvent(event, {detail:value}));
    }
    if (kind === 'reply' && pending.has(id)) {
      const item = pending.get(id); pending.delete(id);
      if (error) item.reject(failure(error.code, error.message)); else item.resolve(result);
    }
  }
  window.addEventListener('message', receive);
  const deadline = setTimeout(close, 15000), watch = setInterval(() => { if (popup.closed) close(); }, 400);
  return {
    on(name, listener) { events.addEventListener(name, e => listener(e.detail)); },
    async request({method, params = []}) {
      await opened;
      if (closed) throw failure(4900, '教学签名器已关闭。');
      const id = ++next;
      if (method === 'eth_requestAccounts' || method === 'personal_sign') popup.focus();
      return new Promise((resolve, reject) => {
        pending.set(id, {resolve, reject}); popup.postMessage({kind:'rpc', id, method, params}, signerOrigin);
      });
    }, close
  };
}
