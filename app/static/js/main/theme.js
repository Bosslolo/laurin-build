// theme.js - server-driven theme management
(function(){
  const APPLY_ATTR = 'data-theme';
  let currentTheme = null;
  let currentVersion = null;
  const POLL_INTERVAL = 4000; // 4s -- can adjust
  let hardReloadArmed = true; // trigger full reload on version change

  function applyTheme(theme){
    if(!theme) return;
    document.body.setAttribute(APPLY_ATTR, theme);
    document.body.className = document.body.className.replace(/theme-\w+/g,'');
    document.body.classList.add('theme-'+theme);
    if(window.__THEME_DEBUG){ console.log('[theme] applied', theme); }
  }

  function fetchTheme(initial){
    fetch('/api/get-theme', {cache:'no-store'})
      .then(r=>r.json())
      .then(data=>{
        if(!data.success) return;
        if(currentVersion === null){
          currentVersion = data.version;
          currentTheme = data.theme;
          applyTheme(currentTheme);
          return;
        }
        if(data.version !== currentVersion){
          currentVersion = data.version;
          currentTheme = data.theme;
          applyTheme(currentTheme);
          if(hardReloadArmed){
            // Force a full reload so any cached HTML/CSS picks up new theme-specific styling
            location.reload();
          }
        } else if(data.theme !== currentTheme){
          currentTheme = data.theme;
          applyTheme(currentTheme);
        }
      })
      .catch(()=>{});
  }

  // Expose a setter used by admin UI to update instantly without waiting for poll
  window.__setLocalTheme = function(theme, version){
    if(theme){ applyTheme(theme); }
    if(version){ currentVersion = version; }
    else {
      // Force fresh assets when version changes (helps PWA cache busting)
      const newVersion = Date.now().toString();
      currentVersion = newVersion;
      const url = new URL(window.location.href);
      url.searchParams.set('v', newVersion);
      window.location.replace(url.toString());
    }
  }

  function initPolling(){
    fetchTheme(true);
    setInterval(fetchTheme, POLL_INTERVAL);
  }

  function initSSE(){
    try {
      const es = new EventSource('/events');
      let initialized = false;
      es.addEventListener('theme', (evt)=>{
        try {
          const data = JSON.parse(evt.data);
          if(!initialized){
            currentVersion = data.version;
            currentTheme = data.theme;
            applyTheme(currentTheme);
            initialized = true;
            if(window.__THEME_DEBUG){ console.log('[theme] initial SSE payload', data); }
            return;
          }
          if(data.version !== currentVersion){
            currentVersion = data.version;
            currentTheme = data.theme;
            applyTheme(currentTheme);
            // If this window initiated the change (admin click just happened), skip redundant reload within 500ms window
            const justChanged = window.__LAST_THEME_SET && (Date.now() - window.__LAST_THEME_SET < 500);
            if(!justChanged){
              if(window.__THEME_DEBUG){ console.log('[theme] version change reload'); }
              location.reload();
            } else if(window.__THEME_DEBUG){ console.log('[theme] version change but skip reload (originator)'); }
          } else if(data.theme !== currentTheme){
            currentTheme = data.theme;
            applyTheme(currentTheme);
          }
        } catch(e) { console.warn('Bad theme event payload', e); }
      });
      es.onerror = () => {
        // Fallback to polling if SSE connection fails
        es.close();
        initPolling();
      };
    } catch(e){
      initPolling();
    }
  }

  if(document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', initSSE);
  } else {
    initSSE();
  }
})();
