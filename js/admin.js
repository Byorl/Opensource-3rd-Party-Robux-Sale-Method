// Admin panel logic with modal purchase history (paginated grid)
(function(){
  const loginView = document.getElementById('login-view');
  const panelView = document.getElementById('panel-view');
  const loginBtn = document.getElementById('admin-login-btn');
  const logoutBtn = document.getElementById('admin-logout-btn');
  const refreshBtn = document.getElementById('refresh-btn');
  const usernameInput = document.getElementById('admin-username');
  const passwordInput = document.getElementById('admin-password');
  const accountsTableBody = document.querySelector('#accounts-table tbody');
  const detailContent = document.getElementById('detail-content');
  const detailPlaceholder = document.getElementById('detail-placeholder');
  const openPurchasesBtn = document.getElementById('open-purchases');
  const purchasesModal = document.getElementById('purchases-modal');
  const purchasesGrid = document.getElementById('purchases-grid');
  const purchasesEmpty = document.getElementById('purchases-empty');
  const purchaseCount = document.getElementById('purchase-count');
  const purchasePage = document.getElementById('purchase-page');
  const purchasePrev = document.getElementById('purchase-prev');
  const purchaseNext = document.getElementById('purchase-next');
  const purchaseClose = document.getElementById('purchase-close');

  // state for pagination
  let currentPurchases = [];
  let currentPage = 1;
  const pageSize = 12; // 4x3 grid
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
      }else{
        showToast(data.error||'Login failed','error');
      }
    }catch(e){showToast('Login error','error');}
  }

  async function adminLogout(){
    try{await fetch('/admin/logout',{method:'POST'});}catch(e){}
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
      if(!data.accounts.length){accountsTableBody.innerHTML='<tr><td colspan="6" style="padding:1rem;opacity:.6;">No accounts found</td></tr>';return;}
      accountsTableBody.innerHTML='';
      data.accounts.sort((a,b)=> (b.total_purchases||0)-(a.total_purchases||0));
      for(const acc of data.accounts){
        const tr=document.createElement('tr');
        tr.innerHTML=`<td>${acc.username}</td><td>${acc.roblox_username||'-'}</td><td><span class="badge">${acc.total_purchases||0}</span></td><td>${formatDate(acc.created_at)}</td><td>${formatDate(acc.last_login)}</td><td class="actions"><button class="view">VIEW</button><button class="delete">DEL</button></td>`;
        const viewBtn = tr.querySelector('.view');
        const delBtn = tr.querySelector('.delete');
        viewBtn.addEventListener('click',()=>viewAccount(acc.user_id, acc.username));
        delBtn.addEventListener('click',()=>deleteAccount(acc.user_id, acc.username));
        accountsTableBody.appendChild(tr);
      }
    }catch(e){
      accountsTableBody.innerHTML='<tr><td colspan="6" style="padding:1rem;opacity:.6;">Error loading</td></tr>';
    }
  }

  function copy(text){
    navigator.clipboard.writeText(text).then(()=>showToast('Copied','success')).catch(()=>showToast('Copy failed','error'));
  }

  function renderPurchases(){
    purchasesGrid.innerHTML='';
    if(!currentPurchases.length){
      purchasesEmpty.style.display='block';
      purchasePage.textContent='0/0';
      purchaseCount.textContent='0';
      return;
    }
    purchasesEmpty.style.display='none';
    const totalPages = Math.max(1, Math.ceil(currentPurchases.length / pageSize));
    if(currentPage>totalPages) currentPage=totalPages;
    purchasePage.textContent = currentPage+"/"+totalPages;
    purchaseCount.textContent = currentPurchases.length+" total";
    const start=(currentPage-1)*pageSize;
    const slice=currentPurchases.slice(start,start+pageSize);
    for(const p of slice){
      const card=document.createElement('div');
      card.style.cssText='background:#141823;border:1px solid #262a37;border-radius:10px;padding:.55rem .65rem;display:flex;flex-direction:column;gap:.4rem;font-size:.6rem;position:relative;';
      const keyShort = (p.key||'').length>20 ? p.key.slice(0,10)+'…'+p.key.slice(-6) : (p.key||'-');
      card.innerHTML=`<div style="font-size:.55rem;opacity:.6;">${new Date(p.purchase_date).toLocaleString()}</div>
        <div style="font-weight:600;">${p.product_name||'-'}</div>
        <div style="font-family:monospace;word-break:break-all;">${keyShort}</div>
        <div style="display:flex;gap:.4rem;flex-wrap:wrap;">
          <span style="background:#1e2230;padding:.25rem .4rem;border-radius:4px;">$${p.price||'?'}</span>
          ${(p.purchase_id?`<span style=\"background:#1e2230;padding:.25rem .4rem;border-radius:4px;font-family:monospace;\">${(p.purchase_id+"").slice(0,6)}</span>`:'')}
        </div>
        <button class="copy-btn" data-key="${p.key}" style="position:absolute;top:.45rem;right:.45rem;background:#1e1f29;border:1px solid rgba(255,255,255,.12);color:#9ca3af;font-size:.55rem;padding:.25rem .45rem;border-radius:5px;cursor:pointer;">Copy</button>`;
      purchasesGrid.appendChild(card);
    }
    purchasesGrid.querySelectorAll('.copy-btn').forEach(btn=>{
      btn.addEventListener('click',e=>{
        const k=e.currentTarget.getAttribute('data-key');
        if(k) copy(k);
      });
    });
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
  openPurchasesBtn && openPurchasesBtn.addEventListener('click', openPurchases);

  async function viewAccount(userId, username){
    detailPlaceholder.classList.add('hidden');
    detailContent.classList.remove('hidden');
    detailContent.querySelector('#detail-summary') && (detailContent.querySelector('#detail-summary').innerHTML='<div style="opacity:.5;">Loading...</div>');
    const purchaseTBody = detailContent.querySelector('#detail-purchase-table tbody');
    if(purchaseTBody){ purchaseTBody.innerHTML=''; }
    const emptyState = detailContent.querySelector('#detail-purchase-empty');
    if(emptyState){ emptyState.style.display='none'; }
    try{
      const res = await fetch('/admin/accounts/'+encodeURIComponent(userId));
      const data = await res.json();
      if(!data.success){ detailContent.innerHTML='<div style="color:#ef4444;">'+(data.error||'Failed')+'</div>'; return; }
      const acc=data.account;
      const summary = detailContent.querySelector('#detail-summary');
      if(summary){
        summary.innerHTML = `
          <div style="background:#11141d;border:1px solid rgba(255,255,255,0.06);padding:.55rem .6rem;border-radius:8px;">
            <div style='font-size:.55rem;opacity:.65;letter-spacing:.5px;text-transform:uppercase;'>User</div>
            <div style='font-size:.75rem;font-weight:600;'>${acc.username}</div>
          </div>
          <div style="background:#11141d;border:1px solid rgba(255,255,255,0.06);padding:.55rem .6rem;border-radius:8px;">
            <div style='font-size:.55rem;opacity:.65;letter-spacing:.5px;text-transform:uppercase;'>User ID</div>
            <div style='font-size:.7rem;'>${acc.user_id}</div>
          </div>
          <div style="background:#11141d;border:1px solid rgba(255,255,255,0.06);padding:.55rem .6rem;border-radius:8px;">
            <div style='font-size:.55rem;opacity:.65;letter-spacing:.5px;text-transform:uppercase;'>Roblox</div>
            <div style='font-size:.7rem;'>${acc.roblox_username||'-'}</div>
          </div>
          <div style="background:#11141d;border:1px solid rgba(255,255,255,0.06);padding:.55rem .6rem;border-radius:8px;">
            <div style='font-size:.55rem;opacity:.65;letter-spacing:.5px;text-transform:uppercase;'>Created</div>
            <div style='font-size:.7rem;'>${formatDate(acc.created_at)}</div>
          </div>
          <div style="background:#11141d;border:1px solid rgba(255,255,255,0.06);padding:.55rem .6rem;border-radius:8px;">
            <div style='font-size:.55rem;opacity:.65;letter-spacing:.5px;text-transform:uppercase;'>Last Login</div>
            <div style='font-size:.7rem;'>${formatDate(acc.last_login)}</div>
          </div>
          <div style="background:#11141d;border:1px solid rgba(255,255,255,0.06);padding:.55rem .6rem;border-radius:8px;">
            <div style='font-size:.55rem;opacity:.65;letter-spacing:.5px;text-transform:uppercase;'>Purchases</div>
            <div style='font-size:.85rem;font-weight:600;color:#6366f1;'>${acc.total_purchases||0}</div>
          </div>`;
      }
      // prepare purchase modal data
      currentPurchases = (acc.purchase_history||[]).slice().reverse();
      currentPage = 1;
      renderPurchases();
      openPurchasesBtn && (openPurchasesBtn.disabled = currentPurchases.length===0);
    }catch(e){
      const summary = detailContent.querySelector('#detail-summary');
      if(summary){ summary.innerHTML='<div style="color:#ef4444;">Error loading</div>'; }
    }
  }

  async function deleteAccount(userId, username){
    if(!confirm('Delete account '+username+'?')) return;
    try{
      const res = await fetch('/admin/accounts/'+encodeURIComponent(userId), {method:'DELETE'});
      const data = await res.json();
      if(data.success){
        showToast('Deleted '+username,'success');
        loadAccounts();
        if(detailContent.innerHTML.includes(userId)){
          detailContent.classList.add('hidden');
          detailPlaceholder.classList.remove('hidden');
        }
      } else {
        showToast(data.error||data.message||'Delete failed','error');
      }
    }catch(e){showToast('Delete error','error');}
  }

  loginBtn.addEventListener('click', adminLogin);
  passwordInput.addEventListener('keydown', e=>{ if(e.key==='Enter') adminLogin(); });
  logoutBtn.addEventListener('click', adminLogout);
  refreshBtn.addEventListener('click', loadAccounts);
})();
