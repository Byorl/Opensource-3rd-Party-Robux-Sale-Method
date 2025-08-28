(function() {
  let API_BASE = '';
  fetch('/config.json').then(r=>r.ok?r.json():null).then(cfg=>{ if(cfg && cfg.baseUrl){ API_BASE = cfg.baseUrl.replace(/\/$/,''); } }).catch(()=>{});
  const PAGE_SIZE = 12;
  let state = {
    user: null,
    purchases: [],
    filtered: [],
    page: 1,
    view: 'grid',
    sort: 'newest',
    search: ''
  };

  function $(id){ return document.getElementById(id); }
  function qs(sel, root=document){ return root.querySelector(sel); }
  function qsa(sel, root=document){ return Array.from(root.querySelectorAll(sel)); }

  function makeAuthRequest(path, options = {}) {
    const opts = { credentials: 'include', ...options };
  return fetch(API_BASE + path, opts);
  }

  function formatDate(dateString) {
    if(!dateString) return '';
    const d = new Date(dateString);
    return d.toLocaleDateString('en-US', {year:'numeric', month:'short', day:'numeric'}) + ' ' + d.toLocaleTimeString('en-US',{hour:'2-digit', minute:'2-digit'});
  }

  function shortKey(key) {
    if(!key) return '';
    if(key.length <= 18) return key;
    return key.slice(0,8) + '…' + key.slice(-6);
  }

  function robuxIcon(size=14) {
    return `<img src="icon/robux.svg" alt="R$" style="width:${size}px;height:${size}px;vertical-align:middle;opacity:.85">`;
  }

  async function checkAuth() {
    try {
      const res = await makeAuthRequest('/me');
      if(!res.ok) return null;
      const data = await res.json();
      if(data.authenticated) {
        localStorage.setItem('user_data', JSON.stringify(data.user));
        return data.user;
      }
    } catch(e) { console.warn('auth error', e); }
    localStorage.removeItem('user_data');
    return null;
  }

  async function loadPurchases() {
    try {
      const res = await makeAuthRequest('/purchase-history');
      if(!res.ok) return [];
      const data = await res.json();
      return data.purchases || [];
    } catch(e){ console.error('load purchases', e); return []; }
  }

  function applyFilters() {
    const term = state.search.trim().toLowerCase();
    let list = [...state.purchases];

    if(term) {
      list = list.filter(p => [p.product_name, p.key, p.roblox_username, p.purchase_id]
        .filter(Boolean)
        .some(v => v.toLowerCase().includes(term)));
    }

    switch(state.sort) {
      case 'oldest':
        list.sort((a,b)=> new Date(a.purchase_date) - new Date(b.purchase_date));
        break;
      case 'product':
        list.sort((a,b)=> (a.product_name||'').localeCompare(b.product_name||''));
        break;
      case 'price':
        list.sort((a,b)=> (b.price||0) - (a.price||0));
        break;
      case 'newest':
      default:
        list.sort((a,b)=> new Date(b.purchase_date) - new Date(a.purchase_date));
    }

    state.filtered = list;
    const totalPages = Math.max(1, Math.ceil(list.length / PAGE_SIZE));
    if(state.page > totalPages) state.page = totalPages;
  }

  function renderPagination() {
    const pagEl = $('pagination');
    if(!pagEl) return;
    const total = state.filtered.length;
    const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

    if(total === 0) {
      pagEl.style.display = 'none';
      return;
    }

    pagEl.style.display = totalPages > 1 ? 'flex' : 'none';
    $('pageInfo').textContent = `Page ${state.page} / ${totalPages}`;
    const prevBtn = $('prevPage');
    const nextBtn = $('nextPage');
    prevBtn.disabled = state.page <= 1;
    nextBtn.disabled = state.page >= totalPages;
  }

  function buildCard(p) {
    return `<div class="purchase-card" data-key="${p.key}">
      <div class="card-head">
        <div class="product">${p.product_name || 'Unknown Product'}</div>
        <div class="price" title="Price">${robuxIcon()} <span>${p.price||0}</span></div>
      </div>
      <div class="meta">
        <div class="meta-row" title="Purchase Date">${formatDate(p.purchase_date)}</div>
        <div class="meta-row smaller" title="Username">@${p.roblox_username || 'N/A'}</div>
        <div class="meta-row smaller mono" title="Purchase ID">${p.purchase_id}</div>
      </div>
      <div class="key-line" title="License Key">
        <span class="full-key">${p.key}</span>
        <span class="short-key">${shortKey(p.key)}</span>
        <button class="copy-btn" data-copy="${p.key}" aria-label="Copy license key">Copy</button>
      </div>
    </div>`;
  }

  function buildListRow(p) {
    return `<div class="purchase-row" data-key="${p.key}">
      <div class="col product" title="Product">${p.product_name || 'Unknown'}</div>
      <div class="col date" title="Date">${formatDate(p.purchase_date)}</div>
      <div class="col user" title="User">@${p.roblox_username || 'N/A'}</div>
      <div class="col price" title="Price">${robuxIcon(12)} ${p.price||0}</div>
      <div class="col key mono" title="Key">${shortKey(p.key)}</div>
      <div class="col actions"><button class="copy-btn small" data-copy="${p.key}" aria-label="Copy license key">Copy</button></div>
    </div>`;
  }

  function renderPurchases() {
    const container = $('purchases-container');
    if(!container) return;

    applyFilters();
    const start = (state.page - 1) * PAGE_SIZE;
    const slice = state.filtered.slice(start, start + PAGE_SIZE);

    if(state.filtered.length === 0) {
      container.innerHTML = '';
      $('emptyState').style.display = 'block';
    } else {
      $('emptyState').style.display = 'none';
      container.className = state.view === 'grid' ? 'purchases-grid' : 'purchases-list';
      container.innerHTML = slice.map(p => state.view === 'grid' ? buildCard(p) : buildListRow(p)).join('');
    }

    renderPagination();
  }

  function updateSummary() {
    if(!state.user) return;
    $('username').textContent = state.user.username;
    $('member-since').textContent = 'Member since ' + formatDate(state.user.created_at);
    $('total-purchases').textContent = state.purchases.length;
    const totalSpent = state.purchases.reduce((s,p)=> s + (p.price||0),0);
    $('total-spent').textContent = totalSpent;
  }

  function attachEvents() {
    $('searchBox').addEventListener('input', e => { state.search = e.target.value; state.page = 1; renderPurchases(); });
    $('sortSelect').addEventListener('change', e => { state.sort = e.target.value; renderPurchases(); });
    $('viewMode').addEventListener('change', e => { state.view = e.target.value; renderPurchases(); });
    $('prevPage').addEventListener('click', () => { if(state.page>1){ state.page--; renderPurchases(); }});
    $('nextPage').addEventListener('click', () => { state.page++; renderPurchases(); });

    $('logout-btn').addEventListener('click', logout);

    $('purchases-container').addEventListener('click', e => {
      const btn = e.target.closest('button.copy-btn');
      if(!btn) return;
      const key = btn.getAttribute('data-copy');
      navigator.clipboard.writeText(key).then(()=> {
        const original = btn.textContent;
        btn.textContent = 'Copied!';
        btn.classList.add('copied');
        setTimeout(()=> { btn.textContent = original; btn.classList.remove('copied'); }, 1800);
      }).catch(()=> {
        btn.textContent = 'Failed';
        setTimeout(()=> { btn.textContent = 'Copy'; }, 1500);
      });
    });
  }

  async function logout() {
    try { await makeAuthRequest('/logout', {method:'POST'});} catch(e){/* ignore */}
    localStorage.removeItem('user_data');
    window.location.href = 'index.html';
  }

  function show(el){ el && (el.style.display='block'); }
  function hide(el){ el && (el.style.display='none'); }

  function injectStyles() {
    if(document.getElementById('history-inline-styles')) return;
    const css = `
    #history-app { max-width:1200px; margin:0 auto; }
    .user-info.compact { background: var(--bg-alt,#121212); border:1px solid var(--border,#222); border-radius:14px; padding:1.1rem 1.25rem 1rem; margin-bottom:1.25rem; box-shadow:0 2px 4px rgba(0,0,0,.4); }
    .summary-main { display:flex; flex-wrap:wrap; align-items:center; gap:1rem; }
    .summary-user h2 { margin:0 0 2px; font-size:1.35rem; }
    .summary-user p { margin:0; font-size:.75rem; opacity:.7; letter-spacing:.5px; text-transform:uppercase; }
    .summary-stats { display:flex; gap:.75rem; }
    .stat-block { background:#1d1d1d; padding:.55rem .9rem; border-radius:10px; min-width:90px; text-align:center; position:relative; }
    .stat-value { font-size:1.1rem; font-weight:600; line-height:1.1; }
    .stat-label { font-size:.6rem; opacity:.65; text-transform:uppercase; letter-spacing:.7px; margin-top:2px; }
    .logout-btn { background:linear-gradient(135deg,#292929,#1c1c1c); color:#eee; border:1px solid #333; padding:.55rem .95rem; border-radius:9px; cursor:pointer; font-size:.75rem; letter-spacing:.5px; transition:.2s; }
    .logout-btn:hover { background:#363636; }
    .summary-actions { margin-left:auto; display:flex; align-items:center; gap:.6rem; }
    .summary-filters { display:flex; flex-wrap:wrap; gap:.6rem; margin-top:.9rem; }
    .summary-filters input, .summary-filters select { background:#1b1b1b; border:1px solid #2a2a2a; color:#ddd; padding:.55rem .7rem; border-radius:8px; font-size:.75rem; flex:1; min-width:160px; }
    .summary-filters select { flex:0 0 auto; }
    .summary-filters input:focus, .summary-filters select:focus { outline:1px solid #444; }

    .purchases-grid { display:grid; gap:.9rem; grid-template-columns:repeat(auto-fill,minmax(220px,1fr)); }
    .purchase-card { background:#141414; border:1px solid #222; border-radius:14px; padding:.85rem .85rem .75rem; display:flex; flex-direction:column; gap:.55rem; position:relative; overflow:hidden; transition:border-color .2s, transform .2s; }
    .purchase-card:hover { border-color:#333; transform:translateY(-2px); }
    .card-head { display:flex; align-items:center; justify-content:space-between; gap:.4rem; }
    .product { font-weight:600; font-size:.82rem; letter-spacing:.3px; }
    .price { font-size:.7rem; opacity:.85; display:flex; align-items:center; gap:3px; background:#1f1f1f; padding:.25rem .45rem; border-radius:6px; }
    .meta { font-size:.63rem; line-height:1.25; opacity:.78; display:flex; flex-direction:column; gap:2px; }
    .meta-row.mono { font-family: "SFMono-Regular","Consolas","Roboto Mono",monospace; font-size:.54rem; opacity:.55; }
    .key-line { background:#1b1b1b; padding:.45rem .55rem; border:1px solid #242424; border-radius:9px; display:flex; align-items:center; gap:.55rem; font-size:.6rem; font-family:"SFMono-Regular","Consolas","Roboto Mono",monospace; }
    .key-line .short-key { display:none; }
    .copy-btn { margin-left:auto; background:#222; border:1px solid #333; color:#ddd; font-size:.6rem; padding:.35rem .55rem; border-radius:7px; cursor:pointer; letter-spacing:.5px; transition:.2s; }
    .copy-btn:hover { background:#2d2d2d; }
    .copy-btn.copied { background:#1f4d1f; border-color:#2d6b2d; color:#c8f7c8; }

    @media (max-width:600px) {
      .key-line .full-key { display:none; }
      .key-line .short-key { display:inline; }
    }

    /* List view */
    .purchases-list { display:flex; flex-direction:column; gap:4px; }
    .purchase-row { display:grid; grid-template-columns: 1.2fr .9fr .9fr .5fr 1fr auto; gap:.4rem; align-items:center; background:#151515; border:1px solid #222; padding:.55rem .75rem; border-radius:11px; font-size:.6rem; }
    .purchase-row .product { font-weight:600; font-size:.7rem; }
    .purchase-row .actions { text-align:right; }
    .purchase-row .copy-btn.small { font-size:.55rem; padding:.3rem .5rem; }
    .purchase-row:hover { border-color:#333; }
    @media (max-width:850px) { .purchase-row { grid-template-columns: 1.2fr .9fr .6fr .5fr auto; } .purchase-row .user { display:none; } }
    @media (max-width:640px) { .purchase-row { grid-template-columns: 1fr .8fr .5fr auto; } .purchase-row .date { display:none; } }

    .pagination { margin-top:1.1rem; display:flex; align-items:center; justify-content:center; gap:.75rem; }
    .page-btn { background:#1a1a1a; border:1px solid #2a2a2a; color:#ccc; padding:.45rem .9rem; font-size:.65rem; border-radius:8px; cursor:pointer; letter-spacing:.5px; }
    .page-btn:disabled { opacity:.35; cursor:default; }
    .page-btn:not(:disabled):hover { background:#252525; }
    .page-info { font-size:.6rem; letter-spacing:.5px; opacity:.65; }

    .empty-state { background:#151515; border:1px dashed #2a2a2a; padding:2.2rem 1.5rem; border-radius:16px; text-align:center; margin-top:1rem; }
    .empty-state h3 { margin:0 0 .75rem; font-size:1.05rem; }
    .empty-state p { margin:0 0 .6rem; font-size:.75rem; opacity:.7; }

    .loading-container { display:flex; flex-direction:column; align-items:center; gap:.85rem; padding:3rem 1rem; }
    .loading-spinner { width:38px; height:38px; border:4px solid #222; border-top-color:#3b82f6; border-radius:50%; animation:spin 1s linear infinite; }
    @keyframes spin { to { transform:rotate(360deg);} }
    `;
    const style = document.createElement('style');
    style.id = 'history-inline-styles';
    style.textContent = css;
    document.head.appendChild(style);
  }

  async function init() {
    injectStyles();
    const user = await checkAuth();
    if(!user) {
      hide($('history-app'));
      hide($('loading'));
      show($('not-logged-in'));
      return;
    }
    state.user = user;
    show($('history-app'));
    show($('loading'));

    try {
      state.purchases = await loadPurchases();
    } finally {
      hide($('loading'));
      show($('purchasesSection'));
    }

    updateSummary();
    renderPurchases();
  }

  document.addEventListener('DOMContentLoaded', () => {
    attachEvents();
    (function setupBackLink(){
      const link = document.getElementById('back-link');
      if(!link) return;
      const ref = document.referrer || '';
      if(ref.includes('license.html')) {
        link.href = ref;
        link.textContent = '← Back to Purchase';
      } else if(ref.includes('product.html')) {
        link.href = ref;
        link.textContent = '← Back to Product';
      } else if(ref.includes('index.html')) {
        link.href = 'index.html';
        link.textContent = '← Back to Store';
      } else {
        link.href = 'index.html';
        link.textContent = '← Back to Store';
      }
    })();
    init();
  });
})();
