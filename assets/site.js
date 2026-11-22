const root = document.documentElement;
const button = document.getElementById('theme');
let theme;
try { theme = localStorage.getItem('chainwork-theme'); } catch { /* file:// storage may be disabled */ }
if (theme !== 'dark' && theme !== 'light') theme = matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
function applyTheme() {
  root.dataset.theme = theme;
  button.textContent = theme === 'dark' ? '切换浅色' : '切换深色';
}
applyTheme();
button.hidden = false;
button.addEventListener('click', () => {
  theme = theme === 'dark' ? 'light' : 'dark';
  applyTheme();
  try { localStorage.setItem('chainwork-theme', theme); } catch { /* per-page mode still works */ }
});
const unit = document.getElementById('unit');
if (unit) {
  const fields = document.querySelectorAll('[data-sat]');
  const format = new Intl.NumberFormat('en-US');
  let bitcoin = false;
  unit.hidden = false;
  unit.addEventListener('click', () => {
    bitcoin = !bitcoin;
    for (const field of fields) {
      const sat = BigInt(field.dataset.sat);
      field.textContent = bitcoin ? `${sat / 100000000n}.${String(sat % 100000000n).padStart(8, '0')}` : format.format(sat);
    }
    document.querySelector('[data-unit]').textContent = bitcoin ? 'BTC' : 'sat';
    unit.textContent = bitcoin ? '换算为 sat' : '换算为 BTC';
  });
}

const zoom = document.querySelector('.figure-zoom');
if (zoom && typeof zoom.showModal === 'function') {
  for (const link of document.querySelectorAll('.lesson-figure a')) {
    link.title = '放大看图';
    link.setAttribute('aria-haspopup', 'dialog');
    link.addEventListener('click', event => {
      if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      const image = zoom.querySelector('img');
      image.alt = link.querySelector('img').alt;
      image.src = link.href;
      zoom.querySelector('a').href = link.href;
      link.focus({preventScroll: true});
      zoom.showModal();
      zoom.querySelector('.zoom-scroll').scrollTo(0, 0);
    });
  }
}
