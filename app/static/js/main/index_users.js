// index_users.js - progressive user list load
(function(){
  const grid = document.getElementById('userGrid');
  if(!grid) return;
  const loader = document.getElementById('initialUserLoader');
  const initialSubset = document.getElementById('initialUserSubset');
  
  function render(users){
    // Get existing user IDs to avoid duplicates
    const existingUserIds = new Set();
    if(initialSubset) {
      initialSubset.querySelectorAll('.user-card-container').forEach(container => {
        const link = container.querySelector('a.user-card');
        if(link) {
          const userId = link.href.match(/user_id=(\d+)/);
          if(userId) existingUserIds.add(parseInt(userId[1]));
        }
      });
    }
    
    // Filter out users that are already displayed
    const newUsers = users.filter(u => !existingUserIds.has(u.id));
    
    if(newUsers.length === 0) {
      // No new users to add, just hide the loader
      if(loader) loader.style.display = 'none';
      return;
    }
    
    const frag = document.createDocumentFragment();
    newUsers.forEach(u=>{
      const col = document.createElement('div');
      col.className='col-lg-3 col-md-4 col-sm-6 user-card-container mb-3';
      col.setAttribute('data-user-name', `${u.first_name} ${u.last_name}`);
      col.setAttribute('data-user-first', u.first_name);
      col.setAttribute('data-user-last', u.last_name);
      col.innerHTML = `<a class="user-card" href="/entries?user_id=${u.id}">`+
                      `  <div><h5 class='user-name'>${u.first_name} ${u.last_name}</h5></div>`+
                      `</a>`;
      frag.appendChild(col);
    });
    
    // Hide the loader
    if(loader) loader.style.display = 'none';
    
    // Append new users to the initial subset if it exists, otherwise create a new row
    if(initialSubset) {
      initialSubset.appendChild(frag);
    } else {
      const row = document.createElement('div');
      row.className='row g-4 user-grid';
      row.appendChild(frag);
      grid.appendChild(row);
    }
  }
  setTimeout(()=>{
    fetch('/api/index-data', {cache:'no-store'})
      .then(r=>{ if(!r.ok){ const e=new Error('HTTP '+r.status); e.status=r.status; throw e;} return r.json();})
      .then(d=>{ if(!d.users) throw new Error('Malformed'); render(d.users); })
      .catch(err=>{
        console.error('User list fetch failed:', err);
        const serverCount = grid.getAttribute('data-server-count');
        if(loader){
          loader.innerHTML = `<div class='text-danger'>Could not load users dynamically (${err.status||''}).</div>`+
                              `<div class='small mt-2'>Server saw ${serverCount} users. <a href='/' class='text-decoration-underline'>Reload</a></div>`;
        }
      });
  }, 20);
})();
