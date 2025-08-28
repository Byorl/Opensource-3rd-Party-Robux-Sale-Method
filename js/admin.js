(function(){
  const loginView = document.getElementById('login-view');
  const panelView = document.getElementById('panel-view');
  const loginBtn = document.getElementById('admin-login-btn');
  const logoutBtn = document.getElementById('admin-logout-btn');
  const refreshBtn = document.getElementById('refresh-btn');
  const usernameInput = document.getElementById('admin-username');
  const passwordInput = document.getElementById('admin-password');
  const accountsTableBody = document.querySelector('#accounts-table tbody');

  const accountDrawer = document.getElementById('account-drawer');
  const drawerBackdrop = document.getElementById('drawer-backdrop');
  const drawerTitle = document.getElementById('drawer-title');
  const drawerSummary = document.getElementById('drawer-summary');
  const drawerRecentList = document.getElementById('drawer-recent-list');
  const drawerRecentCount = document.getElementById('drawer-recent-count');
  const drawerViewAllBtn = document.getElementById('drawer-view-all');
  const drawerPurchasesBtn = document.getElementById('drawer-purchases-btn');
  const drawerCloseBtn = document.getElementById('drawer-close');

  const purchasesModal = document.getElementById('purchases-modal');
  const purchasesGrid = document.getElementById('purchases-grid');
  const purchasesEmpty = document.getElementById('purchases-empty');
  const purchaseCount = document.getElementById('purchase-count');
  const purchasePage = document.getElementById('purchase-page');
  const purchasePrev = document.getElementById('purchase-prev');
  const purchaseNext = document.getElementById('purchase-next');
  const purchaseClose = document.getElementById('purchase-close');

  let currentPurchases = [];
  let currentPage = 1;
  const pageSize = 12;
  let currentUserId = null;
  let currentUsername = null;

  const toastContainer = document.getElementById('toast-container');

  function showToast(msg,type){
    if(!toastContainer) return;
    const div=document.createElement('div');
    div.className='toast '+(type||'');
    div.textContent=msg;
    toastContainer.appendChild(div);
    setTimeout(()=>{div.style.opacity='0';div.style.transform='translateY(-5px)';setTimeout(()=>div.remove(),400);},3500);
  }

  async function adminLogin(){
    try{
      const res = await fetch('/admin/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:usernameInput.value.trim(),password:passwordInput.value})});
      const data = await res.json();
      if(data.success){
        showToast('Logged in','success');
        loginView.classList.add('hidden');
        panelView.classList.remove('hidden');
        loadAccounts();
      } else {
        showToast(data.error||'Login failed','error');
      }
    }catch(e){ showToast('Login error','error'); }
  }

  async function adminLogout(){
    try{ await fetch('/admin/logout',{method:'POST'}); }catch(e){}
    panelView.classList.add('hidden');
    loginView.classList.remove('hidden');
    showToast('Logged out');
  }

  function formatDate(s){ if(!s) return '-'; try{ return new Date(s).toLocaleString(); }catch(e){ return s; } }

  async function loadAccounts(){
    accountsTableBody.innerHTML='<tr><td colspan="6" style="padding:1rem;opacity:.6;">Loading...</td></tr>';
    try{
      const res = await fetch('/admin/accounts');
      const data = await res.json();
      if(!data.success){ accountsTableBody.innerHTML='<tr><td colspan="6" style="padding:1rem;opacity:.6;">'+(data.error||'Failed')+'</td></tr>'; return; }
      if(!data.accounts.length){ accountsTableBody.innerHTML='<tr><td colspan="6" style="padding:1rem;opacity:.6;">No accounts found</td></tr>'; return; }
      accountsTableBody.innerHTML='';
      data.accounts.sort((a,b)=>(b.total_purchases||0)-(a.total_purchases||0));
      for(const acc of data.accounts){
        const tr=document.createElement('tr');
        tr.innerHTML=`<td>${acc.username}</td><td>${acc.roblox_username||'-'}</td><td><span class="badge">${acc.total_purchases||0}</span></td><td>${formatDate(acc.created_at)}</td><td>${formatDate(acc.last_login)}</td><td class="actions"><button class="view">VIEW</button><button class="delete">DEL</button></td>`;
        tr.querySelector('.view').addEventListener('click',()=>viewAccount(acc.user_id, acc.username));
        tr.querySelector('.delete').addEventListener('click',()=>deleteAccount(acc.user_id, acc.username));
        accountsTableBody.appendChild(tr);
      }
    }catch(e){
      accountsTableBody.innerHTML='<tr><td colspan="6" style="padding:1rem;opacity:.6;">Error loading</td></tr>';
    }
  }

  function copy(text){ navigator.clipboard.writeText(text).then(()=>showToast('Copied','success')).catch(()=>showToast('Copy failed','error')); }

  function renderPurchases(){
    purchasesGrid.innerHTML='';
    if(!currentPurchases.length){
      purchasesEmpty.style.display='block';
      purchasePage.textContent='0/0';
      purchaseCount.textContent='0';
      return;
    }
    purchasesEmpty.style.display='none';
    const totalPages = Math.max(1, Math.ceil(currentPurchases.length/pageSize));
    if(currentPage>totalPages) currentPage=totalPages;
    purchasePage.textContent = currentPage+"/"+totalPages;
    purchaseCount.textContent = currentPurchases.length+" total";
    const start=(currentPage-1)*pageSize;
    const slice=currentPurchases.slice(start,start+pageSize);
    for(const p of slice){
      const card=document.createElement('div');
      card.style.cssText='background:#141823;border:1px solid #262a37;border-radius:10px;padding:.55rem .65rem;display:flex;flex-direction:column;gap:.4rem;font-size:.6rem;position:relative;';
      const keyShort=(p.key||'').length>20 ? p.key.slice(0,10)+'…'+p.key.slice(-6):(p.key||'-');
      card.innerHTML=`<div style=\"font-size:.55rem;opacity:.6;\">${formatDate(p.purchase_date||p.ts)}</div>
        <div style=\"font-weight:600;\">${p.product_name||'-'}</div>
        <div style=\"font-family:monospace;word-break:break-all;\">${keyShort}</div>
        <div style=\"display:flex;flex-direction:column;gap:.35rem;\">
          <div style=\"display:flex;gap:.4rem;flex-wrap:wrap;align-items:center;\">
            <span style=\"background:#1e2230;padding:.25rem .4rem;border-radius:4px;\">R$${p.price!=null?Number(p.price).toFixed(2):'?'} </span>
            ${(p.purchase_id?`<span style=\\"background:#1e2230;padding:.25rem .4rem;border-radius:4px;font-family:monospace;max-width:100%;overflow-wrap:anywhere;\\">${p.purchase_id}</span>`:'')}
          </div>
          ${(p.transaction_id?`<div style=\\"font-size:.5rem;opacity:.65;word-break:break-all;\\">Txn: <span style=\\"font-family:monospace;\\">${p.transaction_id}</span></div>`:'')}
        </div>
        <button class=\"copy-btn\" data-key=\"${p.key}\" style=\"position:absolute;top:.45rem;right:.45rem;background:#1e1f29;border:1px solid rgba(255,255,255,.12);color:#9ca3af;font-size:.55rem;padding:.25rem .45rem;border-radius:5px;cursor:pointer;\">Copy</button>`;
      purchasesGrid.appendChild(card);
    }
    purchasesGrid.querySelectorAll('.copy-btn').forEach(btn=>btn.addEventListener('click',e=>{const k=e.currentTarget.getAttribute('data-key'); if(k) copy(k);}));
  }

  function openPurchases(){
    if(!currentPurchases.length){ showToast('No purchases',''); }
    purchasesModal.classList.remove('hidden');
    renderPurchases();
  }
  function closePurchases(){ purchasesModal.classList.add('hidden'); }

  purchasePrev && purchasePrev.addEventListener('click',()=>{ if(currentPage>1){ currentPage--; renderPurchases(); }});
  purchaseNext && purchaseNext.addEventListener('click',()=>{ const totalPages=Math.ceil(currentPurchases.length/pageSize)||1; if(currentPage<totalPages){ currentPage++; renderPurchases(); }});
  purchaseClose && purchaseClose.addEventListener('click', closePurchases);
  purchasesModal && purchasesModal.addEventListener('click',e=>{ if(e.target===purchasesModal) closePurchases(); });
  drawerPurchasesBtn && drawerPurchasesBtn.addEventListener('click', openPurchases);
  drawerViewAllBtn && drawerViewAllBtn.addEventListener('click', openPurchases);

  function openDrawer(){ if(!accountDrawer) return; accountDrawer.classList.remove('hidden'); drawerBackdrop.classList.remove('hidden'); document.body.style.overflow='hidden'; }
  function closeDrawer(){ if(!accountDrawer) return; accountDrawer.classList.add('hidden'); drawerBackdrop.classList.add('hidden'); document.body.style.overflow=''; currentUserId=null; currentUsername=null; }
  drawerCloseBtn && drawerCloseBtn.addEventListener('click', closeDrawer);
  drawerBackdrop && drawerBackdrop.addEventListener('click', closeDrawer);
  window.addEventListener('keydown',e=>{ if(e.key==='Escape' && !accountDrawer.classList.contains('hidden')) closeDrawer(); });

  function renderDrawer(account){
    if(!account) return;
    drawerTitle.textContent = account.username || 'Account';
    drawerSummary.innerHTML='';
    const summaryItems=[
      {label:'Username', value:account.username},
      {label:'User ID', value:account.user_id},
      {label:'Roblox', value:account.roblox_username||'-'},
      {label:'Created', value:formatDate(account.created_at)},
      {label:'Last Login', value:formatDate(account.last_login)},
      {label:'Purchases', value:account.total_purchases||0},
      {label:'Total Spent', value:(account.total_spent!=null?('R$'+Number(account.total_spent).toFixed(2)):'R$0.00')}
    ];
    for(const item of summaryItems){
      const box=document.createElement('div');
      box.style.cssText='background:#161a23;border:1px solid rgba(255,255,255,0.07);padding:.55rem .6rem .6rem;border-radius:8px;display:flex;flex-direction:column;gap:.25rem;';
      box.innerHTML=`<div style=\"font-size:.5rem;letter-spacing:.5px;text-transform:uppercase;opacity:.6;\">${item.label}</div><div style=\"font-size:.7rem;font-weight:600;\">${item.value}</div>`;
      drawerSummary.appendChild(box);
    }
    drawerRecentList.innerHTML='';
    const purchases=(account.purchase_history||[]).slice().sort((a,b)=> new Date(b.purchase_date||b.ts||0)-new Date(a.purchase_date||a.ts||0));
    currentPurchases = purchases;
    currentPage=1;
    if(!purchases.length){
      drawerRecentCount.textContent='';
      drawerPurchasesBtn && (drawerPurchasesBtn.disabled=true);
      const empty=document.createElement('div'); empty.style.cssText='font-size:.55rem;opacity:.55;'; empty.textContent='No purchases'; drawerRecentList.appendChild(empty); drawerViewAllBtn.classList.add('hidden');
    } else {
      drawerPurchasesBtn && (drawerPurchasesBtn.disabled=false);
      drawerRecentCount.textContent=purchases.length+' total';
      purchases.slice(0,10).forEach(p=>{
        const row=document.createElement('div');
        row.style.cssText='display:flex;flex-direction:column;background:#12151d;border:1px solid rgba(255,255,255,0.08);border-radius:7px;padding:.5rem .55rem;';
        row.innerHTML=`<div style=\"display:flex;justify-content:space-between;gap:.5rem;align-items:center;\">
            <div style=\"font-size:.6rem;font-weight:600;\">${p.product_name||p.product_id||'-'}</div>
            <div style=\"font-size:.55rem;opacity:.7;\">R$${p.price!=null?Number(p.price).toFixed(2):'0.00'}</div>
          </div>
          <div style=\"display:flex;justify-content:space-between;gap:.5rem;margin-top:.3rem;flex-wrap:wrap;\">
            <div style=\"font-size:.5rem;opacity:.6;\">${formatDate(p.purchase_date||p.ts)}</div>
            <div style=\"font-size:.5rem;font-family:monospace;opacity:.55;\">${(p.purchase_id||'').toString().slice(0,10)}</div>
          </div>`;
        drawerRecentList.appendChild(row);
      });
      if(purchases.length>10){ drawerViewAllBtn.classList.remove('hidden'); } else { drawerViewAllBtn.classList.add('hidden'); }
    }
  }

  async function viewAccount(userId, username){
    currentUserId=userId; currentUsername=username;
    try{
      const res = await fetch('/admin/accounts/'+encodeURIComponent(userId));
      const data = await res.json();
      if(!data.success){ showToast(data.error||'Load failed','error'); return; }
      renderDrawer(data.account);
      openDrawer();
    }catch(e){ showToast('Error loading','error'); }
  }

  async function deleteAccount(userId, username){
    if(!confirm('Delete account '+username+'?')) return;
    try{
      const res = await fetch('/admin/accounts/'+encodeURIComponent(userId), {method:'DELETE'});
      const data = await res.json();
      if(data.success){
        showToast('Deleted '+username,'success');
        loadAccounts();
        if(currentUserId===userId) closeDrawer();
      } else {
        showToast(data.error||data.message||'Delete failed','error');
      }
    }catch(e){ showToast('Delete error','error'); }
  }

  loginBtn.addEventListener('click', adminLogin);
  passwordInput.addEventListener('keydown', e=>{ if(e.key==='Enter') adminLogin(); });
  logoutBtn.addEventListener('click', adminLogout);
  refreshBtn.addEventListener('click', loadAccounts);
})();
