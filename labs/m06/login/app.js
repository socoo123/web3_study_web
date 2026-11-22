import {openLabSigner} from './bridge.js';
const el = id => document.getElementById(id);
const text = (id, s) => { el(id).textContent = s; };
const CHAIN = '31337';
let provider = null, epoch = 0, busy = false, expiryTimer, proof = null, queue = Promise.resolve();
// Serialize writes from this page: an event's reset cannot overtake an already submitted verify.
function api(path, body = {}) {
  const next = queue.then(async () => {
    const r = await fetch('/api/' + path, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
    const data = await r.json(); if (!r.ok) throw new Error(`${r.status} ${data.error}`); return data;
  });
  queue = next.catch(() => {}); return next;
}
const current = n => { if (epoch !== n) throw new Error('请求上下文已改变。'); };
async function snapshot(p) {
  const [accounts, chain] = await Promise.all([p.request({method:'eth_accounts'}), p.request({method:'eth_chainId'})]);
  return {address:accounts[0]?.toLowerCase(), chainId:BigInt(chain).toString()};
}
function renderContext(c) {
  text('context', `钱包地址：${c.address || '未授权'} · 链号 ${c.chainId}${c.chainId === CHAIN ? '' : '（非课程网络，请在签名器切回 31337）'}`);
  el('login').disabled = busy || !c.address || c.chainId !== CHAIN;
}
async function refresh(n) {
  if (!provider) return;
  const c = await snapshot(provider); current(n); renderContext(c);
}
function forget() {
  proof = null; clearTimeout(expiryTimer); el('replay').disabled = true;
  text('identity','未登录'); text('message','尚无待签原文。'); text('result','尚未检查。');
}
function invalidate(reason) {
  const n = ++epoch; busy = false; forget(); el('login').disabled = true;
  text('note', reason);
  return api('reset').then(() => { current(n); return refresh(n); }).catch(e => {
    if (epoch === n) text('note', `${reason} 无法确认当前状态：${e.message}`);
  });
}
async function select(isLab) {
  el('lab').disabled = el('injected').disabled = true;
  let p;
  try {
    p = isLab ? openLabSigner() : window.ethereum;
    if (typeof p?.request !== 'function' || typeof p.on !== 'function') throw new Error('没有 EIP-1193 测试钱包。请使用教学签名器。');
    provider = p;
    for (const event of ['accountsChanged','chainChanged','disconnect']) p.on(event, () => {
      if (provider !== p) return;
      if (event === 'disconnect') {
        provider = null; el('lab').disabled = el('injected').disabled = false; text('context','签名来源已断开。');
      }
      invalidate(`${event}：旧请求已丢弃，必须重新登录。`);
    });
    text('note', '在签名来源中决定是否展示地址。');
    await p.request({method:'eth_requestAccounts'});
    if (provider !== p) return;
    const n = epoch, c = await snapshot(p);
    if (n === epoch && provider === p) { renderContext(c); text('note','仅已连接；点击「请求登录签名」才发起登录。'); }
  } catch (e) {
    if (provider === p || !provider) {
      provider = null; if (isLab) p?.close?.(); el('lab').disabled = el('injected').disabled = false;
      text('context','尚未连接账户。'); await invalidate(`${e.code ?? ''} ${e.message}`);
    }
  }
}
async function assertSame(n, expected) {
  current(n); const c = await snapshot(provider); current(n);
  if (c.address !== expected.address || c.chainId !== expected.chainId) {
    await invalidate('钱包身份或网络不再匹配；重新申请挑战。'); throw new Error('上下文已改变。');
  }
}
function hexUtf8(s) { return '0x' + Array.from(new TextEncoder().encode(s), b => b.toString(16).padStart(2,'0')).join(''); }
el('lab').onclick = () => select(true); el('injected').onclick = () => select(false);
el('reset').onclick = () => invalidate('已清除登录。');
el('login').onclick = async () => {
  const n = ++epoch; busy = true; forget(); el('login').disabled = true; text('note','正在申请一次性挑战。');
  try {
    await api('reset'); current(n); const p = provider, c = await snapshot(p); current(n);
    if (!c.address || c.chainId !== CHAIN) throw new Error('先授权账户并切回 31337。');
    const {message} = await api('challenge', c); current(n); text('message', message);
    await assertSame(n,c); text('note','等待你在签名来源确认或拒绝。');
    const signature = await p.request({method:'personal_sign', params:[hexUtf8(message), c.address]});
    await assertSame(n,c); const signed = {message, signature};
    const session = await api('verify', signed); await assertSame(n,c);
    if (session.address.toLowerCase() !== c.address || session.chainId !== c.chainId) throw new Error('会话绑定不符。');
    proof = signed; el('replay').disabled = false;
    text('identity', `已登录 ${session.address} · 链号 ${session.chainId}`); text('note', `Java 已验签。会话截止 ${session.expires}`);
    expiryTimer = setTimeout(() => { if (epoch === n) invalidate('会话有效期已结束。'); }, Math.max(0, Date.parse(session.expires) - Date.now()));
  } catch (e) { if (epoch === n) await invalidate(`${e.code ?? ''} ${e.message}；未保持登录。`); }
  finally { if (epoch === n) { busy = false; el('login').disabled = false; } }
};
el('status').onclick = async () => {
  const n = epoch;
  try {
    const s = await api('status'); current(n);
    if (s.status === 'AUTHENTICATED') {
      if (!provider) { await invalidate('未连接签名来源；重新登录。'); return; }
      await assertSame(n, {address:s.address.toLowerCase(), chainId:s.chainId});
    } else text('identity','未登录');
    text('result', s.status === 'ANONYMOUS' ? '200 ANONYMOUS' : `200 AUTHENTICATED · ${s.address} · ${s.chainId}`);
  } catch (e) { if (epoch === n) text('result', e.message); }
};
el('replay').onclick = async () => {
  const n = epoch; if (!proof) return;
  try { await api('verify', proof); current(n); await invalidate('异常：同一挑战被接受两次；已清除登录。'); }
  catch (e) { if (epoch === n) text('result', e.message); }
};
window.addEventListener('pageshow', e => { if (e.persisted) location.reload(); });
invalidate('选择一个签名来源；页面不会自动请求钱包授权。');
