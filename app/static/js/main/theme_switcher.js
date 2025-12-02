// theme_switcher.js - Admin theme selection UI
(function(){
  const btn = document.getElementById('themeSwitcherBtn');
  const modalEl = document.getElementById('themeSwitcherModal');
  if(!btn || !modalEl) return;

  function selectTheme(theme){
    fetch('/api/set-theme', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({theme})
    })
      .then(r=>{
        if(r.redirected && r.url.includes('/admin/login')){
          // User is not authenticated as admin
          alert('⚠️ Admin Authentication Required\n\nYou need to log in as an admin to change themes.\n\nPlease go to: http://localhost:5001/admin/login');
          return;
        }
        return r.json();
      })
      .then(data=>{
        if(!data || !data.success){ 
          console.warn('Theme update failed', data?.error || 'Unknown error'); 
          return; 
        }
        if(window.__setLocalTheme){ window.__setLocalTheme(data.theme, data.version); }
        window.__LAST_THEME_SET = Date.now();
        if(window.__THEME_DEBUG){ console.log('[theme] admin set', data.theme, 'v', data.version); }
        // Close modal
        const inst = bootstrap.Modal.getInstance(modalEl) || new bootstrap.Modal(modalEl);
        inst.hide();
      })
      .catch(err=>console.error('Theme update error', err));
  }

  // Button opens modal
  btn.addEventListener('click', ()=>{
    (new bootstrap.Modal(modalEl)).show();
  });

  // Click any theme option
  modalEl.querySelectorAll('.theme-option').forEach(opt=>{
    opt.addEventListener('click', ()=> selectTheme(opt.dataset.theme));
  });
})();
