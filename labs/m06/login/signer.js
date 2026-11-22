const appOrigin = 'http://127.0.0.1:18121', parentTab = window.opener;
const el = id => document.getElementById(id);
let accounts, index = 0, chain = '0x7a69', connected = false, pending = null;
const post = data => parentTab?.postMessage(data, appOrigin);
const reply = (id, result) => post({kind:'reply', id, result});
const reject = (id, code, message) => post({kind:'reply', id, error:{code, message}});
function showContext() {
  el('context').textContent = `账户 ${index === 0 ? 'A' : 'B'}：${accounts[index]} · 链号 ${BigInt(chain)}`;
}
function buttons(on) { el('allow').disabled = el('deny').disabled = !on; }
function cancel(code, text) {
  if (pending) { reject(pending.id, code, text); pending = null; }
  buttons(false); el('note').textContent = text; el('message').textContent = '尚无请求。';
}
async function wallet(path, body = {}) {
  const r = await fetch('/wallet/' + path, {method:'POST', credentials:'omit', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  const data = await r.json(); if (!r.ok) throw new Error(data.error); return data;
}
function change(which) {
  if (which === 'account') index = 1 - index; else chain = chain === '0x7a69' ? '0x7a6a' : '0x7a69';
  if (which === 'chain' || connected) post({kind:'event', event:which === 'account' ? 'accountsChanged' : 'chainChanged', value:which === 'account' ? [accounts[index]] : chain});
  cancel(4100, '账户或网络已改变；旧请求已取消。'); showContext();
}
el('account').onclick = () => change('account'); el('chain').onclick = () => change('chain');
el('deny').onclick = () => cancel(4001, '用户拒绝请求。');
el('allow').onclick = async () => {
  const req = pending; if (!req) return;
  buttons(false);
  try {
    if (req.method === 'eth_requestAccounts') { connected = true; reply(req.id, [accounts[index]]); }
    else {
      const signed = await wallet('confirm', {address:accounts[index], message:req.text});
      if (pending !== req) return; // Selection might have changed while the signer was working.
      reply(req.id, signed.signature);
    }
    pending = null; el('note').textContent = '已确认。返回登录台核对结果。';
  } catch (e) { if (pending === req) cancel(4100, e.message); }
};
window.addEventListener('message', e => {
  if (!parentTab || e.origin !== appOrigin || e.source !== parentTab || e.data?.kind !== 'rpc') return;
  const {id, method, params} = e.data;
  if (method === 'eth_chainId') { reply(id, chain); return; }
  if (method === 'eth_accounts') { reply(id, connected ? [accounts[index]] : []); return; }
  if (!['eth_requestAccounts','personal_sign'].includes(method)) { reject(id, 4200, '不支持此方法。'); return; }
  if (!accounts || pending) { reject(id, -32002, '已有待确认请求或签名器尚未就绪。'); return; }
  let text = '';
  if (method === 'personal_sign') {
    if (!connected || chain !== '0x7a69' || params[1]?.toLowerCase() !== accounts[index].toLowerCase()) { reject(id, 4100, '账户或网络不匹配。'); return; }
    if (typeof params[0] !== 'string' || !/^0x(?:[\da-f]{2}){1,2048}$/i.test(params[0])) { reject(id, -32602, '无效消息字节。'); return; }
    try { text = new TextDecoder('utf-8', {fatal:true}).decode(Uint8Array.from(params[0].slice(2).match(/../g), x => parseInt(x,16))); }
    catch { reject(id, -32602, '不是有效 UTF-8。'); return; }
    if (!text.startsWith(`${e.origin} wants you to sign in with your Ethereum account:\n${accounts[index]}\n\n`)) { reject(id, 4100, '消息签发站点或地址不符。'); return; }
  }
  pending = {id, method, text}; buttons(true);
  el('message').textContent = text || `向 ${e.origin} 展示 ${accounts[index]}。不会签名。`;
  el('note').textContent = method === 'personal_sign' ? '核对完整登录文本。确认将由临时账户签名，不发送交易。' : '是否允许此登录台读取当前测试地址？';
});
try {
  accounts = (await wallet('accounts')).accounts; showContext();
  el('account').disabled = el('chain').disabled = false;
  if (parentTab) post({kind:'ready'}); else el('note').textContent = '请从独立登录台点击「连接教学签名器」打开本窗口。';
} catch { el('note').textContent = '本机签名器不可用。检查 signer 进程。'; }
