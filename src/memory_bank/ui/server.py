from __future__ import annotations

from pathlib import Path

import rich_click as click

from memory_bank.cli import CONTEXT_SETTINGS, console, cli


HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Memory Bank</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🧠</text></svg>">
<style>
  :root{--bg:#0f1117;--surface:#1a1d27;--border:#2a2d3a;--accent:#7c6af7;--accent2:#a78bfa;--text:#e2e8f0;--muted:#64748b;--user:#3b82f6;--assistant:#10b981;--gap:1rem}
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:var(--bg);color:var(--text);font:14px/1.6 system-ui,sans-serif;min-height:100vh;display:flex;flex-direction:column}
  header{background:var(--surface);border-bottom:1px solid var(--border);padding:.75rem var(--gap);display:flex;align-items:center;gap:.75rem}
  header h1{font-size:1.1rem;font-weight:700;color:var(--accent2)}
  header span{color:var(--muted);font-size:.8rem}
  #stats-bar{display:flex;gap:1.5rem;margin-left:auto;font-size:.8rem;color:var(--muted)}
  #stats-bar b{color:var(--text)}
  main{display:flex;flex:1;gap:0;overflow:hidden}
  aside{width:220px;flex-shrink:0;background:var(--surface);border-right:1px solid var(--border);padding:var(--gap);display:flex;flex-direction:column;gap:.5rem}
  aside h2{font-size:.7rem;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin-bottom:.25rem}
  .filter-group{display:flex;flex-direction:column;gap:.35rem}
  select,input[type="text"],#q{background:#0f1117;border:1px solid var(--border);color:var(--text);border-radius:6px;padding:.4rem .6rem;font-size:.82rem;width:100%}
  select:focus,input:focus{outline:none;border-color:var(--accent)}
  #content{flex:1;display:flex;flex-direction:column;overflow:hidden}
  .tab-bar{display:flex;gap:0;border-bottom:1px solid var(--border);background:var(--surface)}
  .tab-btn{background:none;border:none;border-bottom:2px solid transparent;color:var(--muted);padding:.6rem 1.2rem;font-size:.85rem;cursor:pointer;font-weight:600}
  .tab-btn.active{color:var(--accent2);border-bottom-color:var(--accent)}
  .tab-btn:hover:not(.active){color:var(--text)}
  #search-bar{padding:var(--gap);display:flex;gap:.5rem;border-bottom:1px solid var(--border);display:none}
  #search-bar #q{flex:1;font-size:.95rem;padding:.5rem .75rem}
  button{background:var(--accent);color:#fff;border:none;border-radius:6px;padding:.5rem 1.1rem;font-size:.85rem;cursor:pointer;white-space:nowrap}
  button:hover{background:var(--accent2)}
  button:disabled{opacity:.4;cursor:default}
  #view-area{flex:1;overflow-y:auto;padding:var(--gap);display:flex;flex-direction:column;gap:.75rem}
  #empty{text-align:center;color:var(--muted);padding:3rem;display:none}
  #loading{text-align:center;color:var(--muted);padding:3rem;display:none}
  .err{color:#f87171;font-size:.82rem;padding:.5rem var(--gap)}
  /* Session list table */
  .session-table{width:100%;border-collapse:collapse}
  .session-table th{text-align:left;font-size:.7rem;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);padding:.5rem .75rem;border-bottom:1px solid var(--border);position:sticky;top:0;background:var(--bg);z-index:1;cursor:pointer;user-select:none}
  .session-table th:hover{color:var(--text)}
  .session-table th .sort-arrow{margin-left:.3em;font-size:.6rem;color:var(--accent)}
  .session-table td{padding:.6rem .75rem;border-bottom:1px solid var(--border);font-size:.82rem;vertical-align:top}
  .session-table tr{cursor:pointer}
  .session-table tbody tr:hover{background:var(--surface)}
  .session-table .title-cell{color:#cbd5e1;max-width:400px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .session-table .muted-cell{color:var(--muted);font-size:.75rem;white-space:nowrap}
  /* Detail view */
  .detail-header{padding:var(--gap);border-bottom:1px solid var(--border);display:flex;align-items:center;gap:1rem;flex-wrap:wrap}
  .detail-header .back-btn{background:none;border:1px solid var(--border);color:var(--muted);padding:.3rem .7rem;font-size:.8rem;border-radius:6px}
  .detail-header .back-btn:hover{color:var(--text);border-color:var(--accent)}
  .detail-meta{display:flex;gap:1rem;flex-wrap:wrap;font-size:.78rem;color:var(--muted)}
  .detail-meta b{color:var(--text)}
  .thread{max-width:800px;margin:0 auto;width:100%;display:flex;flex-direction:column;gap:.75rem;padding:var(--gap) 0}
  .msg{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:.75rem 1rem;border-left:3px solid var(--muted);content-visibility:auto}
  .msg.msg-user{border-left-color:var(--user)}
  .msg.msg-assistant{border-left-color:var(--assistant)}
  .msg-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:.4rem}
  .msg-role{font-size:.72rem;font-weight:600;text-transform:uppercase;letter-spacing:.05em}
  .msg-user .msg-role{color:var(--user)}
  .msg-assistant .msg-role{color:var(--assistant)}
  .msg-ts{font-size:.7rem;color:var(--muted)}
  .msg-body{white-space:pre-wrap;word-break:break-word;font-size:.85rem;line-height:1.65;color:#cbd5e1;max-height:400px;overflow:hidden}
  .msg-body.expanded{max-height:none}
  .msg-body pre{background:#0d0f15;border-radius:6px;padding:.6rem;overflow-x:auto;margin:.4rem 0}
  .msg-body code{font-family:ui-monospace,monospace;font-size:.82rem}
  .msg-expand{background:none;border:none;color:var(--accent);font-size:.75rem;padding:.2rem 0;cursor:pointer;margin-top:.3rem}
  /* Search result cards */
  .card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:1rem;transition:border-color .15s}
  .card:hover{border-color:var(--accent)}
  .card-meta{display:flex;gap:.75rem;align-items:center;margin-bottom:.5rem;flex-wrap:wrap}
  .badge{font-size:.7rem;padding:.15rem .5rem;border-radius:999px;font-weight:600}
  .role-user{background:#1e3a5f;color:var(--user)}
  .role-assistant{background:#064e3b;color:var(--assistant)}
  .source-badge{background:#1e1b4b;color:var(--accent2)}
  .score{margin-left:auto;font-size:.75rem;color:var(--muted)}
  .card-content{white-space:pre-wrap;word-break:break-word;font-size:.85rem;line-height:1.65;max-height:300px;overflow-y:auto;color:#cbd5e1}
  .card-content.expanded{max-height:none}
  .expand-btn{background:none;border:none;color:var(--accent);font-size:.75rem;padding:.2rem 0;cursor:pointer;margin-top:.4rem}
  .session-link{background:none;border:none;color:var(--accent);font-size:.72rem;cursor:pointer;padding:0;text-decoration:underline}
</style>
</head>
<body>
<header>
  <h1>&#x1F9E0; Memory Bank</h1>
  <span id="db-path"></span>
  <div id="stats-bar">
    <span>Messages: <b id="stat-total">...</b></span>
    <span>Sessions: <b id="stat-sessions">...</b></span>
    <span id="stat-sources"></span>
  </div>
</header>
<main>
  <aside>
    <h2>Filters</h2>
    <div class="filter-group">
      <label style="font-size:.75rem;color:var(--muted)">Source</label>
      <select id="f-source"><option value="">All sources</option></select>
    </div>
    <div class="filter-group" id="role-filter" style="display:none">
      <label style="font-size:.75rem;color:var(--muted)">Role</label>
      <select id="f-role">
        <option value="">Both</option>
        <option value="user">User</option>
        <option value="assistant">Assistant</option>
      </select>
    </div>
    <div class="filter-group">
      <label style="font-size:.75rem;color:var(--muted)">Project</label>
      <input type="text" id="f-project" placeholder="any project...">
    </div>
    <div class="filter-group">
      <label style="font-size:.75rem;color:var(--muted)">From</label>
      <input type="date" id="f-date-from" style="width:100%">
    </div>
    <div class="filter-group">
      <label style="font-size:.75rem;color:var(--muted)">To</label>
      <input type="date" id="f-date-to" style="width:100%">
    </div>
    <div class="filter-group">
      <label style="font-size:.75rem;color:var(--muted)">Limit</label>
      <select id="f-limit">
        <option value="10" selected>10</option>
        <option value="25">25</option>
        <option value="50">50</option>
        <option value="100">100</option>
      </select>
    </div>
    <div class="filter-group">
      <button onclick="resetFilters()" style="width:100%;margin-top:.25rem">Reset filters</button>
    </div>
  </aside>
  <div id="content">
    <div class="tab-bar">
      <button class="tab-btn active" id="tab-sessions" onclick="switchTab('sessions')">Sessions</button>
      <button class="tab-btn" id="tab-search" onclick="switchTab('search')">Search</button>
    </div>
    <div id="search-bar">
      <input type="text" id="q" placeholder="Search your chat history..." autofocus>
      <button id="search-btn" onclick="doSearch()">Search</button>
    </div>
    <div class="err" id="err-msg"></div>
    <div id="loading">Loading...</div>
    <div id="empty"></div>
    <div id="view-area"></div>
  </div>
</main>
<script>
let currentTab='sessions';
let currentDetail=null;
let sessionData=[];
let sortCol='date';
let sortAsc=false;

function escHtml(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function fmtDate(iso){if(!iso)return '';try{return new Date(iso).toLocaleDateString()}catch(e){return iso;}}
function fmtDateTime(iso){if(!iso)return '';try{return new Date(iso).toLocaleString()}catch(e){return iso;}}

async function loadStats(){
  try{
    const d=await fetch('/api/stats').then(r=>r.json());
    document.getElementById('stat-total').textContent=d.total_messages.toLocaleString();
    document.getElementById('stat-sessions').textContent=(d.total_sessions||0).toLocaleString();
    document.getElementById('db-path').textContent=d.db_path;
    const sources=Object.keys(d.by_source||{});
    const sel=document.getElementById('f-source');
    sources.forEach(s=>{const o=document.createElement('option');o.value=s;o.textContent=s+' ('+d.by_source[s]+')';sel.appendChild(o);});
    const bar=sources.map(s=>'<span>'+s+': <b>'+d.by_source[s]+'</b></span>').join(' &middot; ');
    document.getElementById('stat-sources').innerHTML=bar;
  }catch(e){console.error(e)}
}

function switchTab(tab){
  currentTab=tab;
  currentDetail=null;
  document.getElementById('tab-sessions').classList.toggle('active',tab==='sessions');
  document.getElementById('tab-search').classList.toggle('active',tab==='search');
  document.getElementById('search-bar').style.display=tab==='search'?'flex':'none';
  document.getElementById('role-filter').style.display=tab==='search'?'flex':'none';
  document.getElementById('err-msg').textContent='';
  if(tab==='sessions') loadSessions();
  else{ document.getElementById('view-area').innerHTML=''; document.getElementById('empty').style.display='none'; }
}

// --- Sessions list ---
const SORT_KEYS={
  project:s=>(s.project||'').toLowerCase(),
  title:s=>(s.title||'').toLowerCase(),
  date:s=>s.last_ts||'',
  messages:s=>s.message_count||0,
  model:s=>(s.model||'').toLowerCase(),
};

function toggleSort(col){
  if(sortCol===col) sortAsc=!sortAsc;
  else{ sortCol=col; sortAsc=col==='project'||col==='title'||col==='model'; }
  renderSessions();
}

async function loadSessions(){
  const area=document.getElementById('view-area');
  area.innerHTML='';
  document.getElementById('loading').style.display='block';
  document.getElementById('empty').style.display='none';
  const params=new URLSearchParams({
    limit:document.getElementById('f-limit').value,
    source:document.getElementById('f-source').value,
    project:document.getElementById('f-project').value,
    date_from:document.getElementById('f-date-from').value,
    date_to:document.getElementById('f-date-to').value,
  });
  try{
    sessionData=await fetch('/api/sessions?'+params).then(r=>r.json());
    document.getElementById('loading').style.display='none';
    if(!sessionData.length){
      document.getElementById('empty').style.display='block';
      document.getElementById('empty').innerHTML='No sessions found.<br><span style="font-size:.82rem">Run <code>memory-bank ingest claude-code</code> to get started.</span>';
      return;
    }
    renderSessions();
  }catch(e){
    document.getElementById('loading').style.display='none';
    document.getElementById('err-msg').textContent='Error: '+e.message;
  }
}

function renderSessions(){
  const area=document.getElementById('view-area');
  area.innerHTML='';
  const keyFn=SORT_KEYS[sortCol]||SORT_KEYS.date;
  const sorted=[...sessionData].sort((a,b)=>{
    const va=keyFn(a),vb=keyFn(b);
    let cmp=va<vb?-1:va>vb?1:0;
    return sortAsc?cmp:-cmp;
  });
  const cols=[
    {key:'project',label:'Project'},
    {key:'title',label:'Title'},
    {key:'date',label:'Date'},
    {key:'messages',label:'Messages'},
    {key:'model',label:'Model'},
  ];
  const table=document.createElement('table');table.className='session-table';
  const hrow=cols.map(c=>{
    const arrow=sortCol===c.key?(sortAsc?'&#9650;':'&#9660;'):'';
    return '<th onclick="toggleSort(\''+c.key+'\')">'+c.label+(arrow?'<span class="sort-arrow">'+arrow+'</span>':'')+'</th>';
  }).join('');
  table.innerHTML='<thead><tr>'+hrow+'</tr></thead>';
  const tbody=document.createElement('tbody');
  sorted.forEach(s=>{
    const tr=document.createElement('tr');
    const dateRange=fmtDate(s.first_ts)+(s.first_ts!==s.last_ts?' - '+fmtDate(s.last_ts):'');
    const model=(s.model||'').replace('claude-','').replace('-20250514','');
    tr.innerHTML='<td class="muted-cell">'+escHtml(s.project||'')+'</td>'
      +'<td class="title-cell">'+escHtml(s.title||'(untitled)')+'</td>'
      +'<td class="muted-cell">'+dateRange+'</td>'
      +'<td style="text-align:center">'+s.message_count+'</td>'
      +'<td class="muted-cell">'+escHtml(model)+'</td>';
    tr.onclick=()=>loadDetail(s.session_id,s);
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  area.appendChild(table);
}

// --- Session detail ---
async function loadDetail(sessionId,sessionMeta){
  history.pushState({view:'detail',sessionId},'','#session/'+sessionId);
  currentDetail=sessionId;
  const area=document.getElementById('view-area');
  area.innerHTML='';
  document.getElementById('loading').style.display='block';
  try{
    const data=await fetch('/api/sessions/'+encodeURIComponent(sessionId)).then(r=>r.json());
    document.getElementById('loading').style.display='none';
    if(data.error){document.getElementById('err-msg').textContent=data.error;return;}
    const messages=data.messages;
    const meta=data.meta;
    // Header
    const hdr=document.createElement('div');hdr.className='detail-header';
    const model=(meta.model||'').replace('claude-','').replace('-20250514','');
    hdr.innerHTML='<button class="back-btn" onclick="goBackToSessions()">&larr; Back</button>'
      +'<div class="detail-meta">'
      +'<span>Project: <b>'+escHtml(meta.project||'')+'</b></span>'
      +'<span>'+fmtDateTime(meta.first_ts)+' &mdash; '+fmtDateTime(meta.last_ts)+'</span>'
      +'<span>'+messages.length+' messages</span>'
      +(model?'<span>Model: <b>'+escHtml(model)+'</b></span>':'')
      +(meta.git_branch?'<span>Branch: <b>'+escHtml(meta.git_branch)+'</b></span>':'')
      +'</div>';
    area.appendChild(hdr);
    // Thread
    const thread=document.createElement('div');thread.className='thread';
    messages.forEach(m=>{
      const msg=document.createElement('div');
      msg.className='msg msg-'+m.role;
      const ts=fmtDateTime(m.timestamp);
      msg.innerHTML='<div class="msg-header"><span class="msg-role">'+m.role+'</span><span class="msg-ts">'+ts+'</span></div>'
        +'<div class="msg-body">'+escHtml(m.content||'')+'</div>';
      const body=msg.querySelector('.msg-body');
      // defer height check
      setTimeout(()=>{
        if(body.scrollHeight>410){
          const btn=document.createElement('button');btn.className='msg-expand';btn.textContent='Show more';
          btn.onclick=()=>{body.classList.toggle('expanded');btn.textContent=body.classList.contains('expanded')?'Show less':'Show more';};
          msg.appendChild(btn);
        }
      },0);
      thread.appendChild(msg);
    });
    area.appendChild(thread);
  }catch(e){
    document.getElementById('loading').style.display='none';
    document.getElementById('err-msg').textContent='Error: '+e.message;
  }
}

function goBackToSessions(){
  history.pushState({view:'sessions'},'','#');
  currentDetail=null;
  loadSessions();
}

window.addEventListener('popstate',()=>{
  if(currentDetail){currentDetail=null;loadSessions();}
});

// --- Search ---
async function doSearch(){
  const q=document.getElementById('q').value.trim();
  if(!q)return;
  const btn=document.getElementById('search-btn');
  btn.disabled=true;
  document.getElementById('loading').style.display='block';
  document.getElementById('view-area').innerHTML='';
  document.getElementById('empty').style.display='none';
  document.getElementById('err-msg').textContent='';
  const params=new URLSearchParams({q,
    limit:document.getElementById('f-limit').value,
    source:document.getElementById('f-source').value,
    role:document.getElementById('f-role').value,
    project:document.getElementById('f-project').value,
    date_from:document.getElementById('f-date-from').value,
    date_to:document.getElementById('f-date-to').value,
  });
  try{
    const data=await fetch('/api/search?'+params).then(r=>r.json());
    document.getElementById('loading').style.display='none';
    btn.disabled=false;
    if(!data.length){document.getElementById('empty').style.display='block';document.getElementById('empty').textContent='No results. Try a different query.';return;}
    const area=document.getElementById('view-area');
    data.forEach(r=>{
      const ts=fmtDateTime(r.timestamp);
      const score=r.score!=null?'<span class="score">score '+r.score.toFixed(3)+'</span>':'';
      const proj=r.project?'<span style="color:var(--muted);font-size:.75rem">'+escHtml(r.project)+'</span>':'';
      const sessionLink=r.session_id?'<button class="session-link" onclick="event.stopPropagation();loadDetailFromSearch(\''+escHtml(r.session_id)+'\')">View session</button>':'';
      const card=document.createElement('div');card.className='card';
      card.innerHTML='<div class="card-meta">'
        +'<span class="badge role-'+r.role+'">'+r.role+'</span>'
        +'<span class="badge source-badge">'+(r.source||'')+'</span>'
        +proj
        +'<span style="color:var(--muted);font-size:.72rem">'+ts+'</span>'
        +score
        +sessionLink
        +'</div>'
        +'<div class="card-content">'+escHtml(r.content||'')+'</div>';
      const cc=card.querySelector('.card-content');
      if(cc.scrollHeight>310){
        const btn2=document.createElement('button');btn2.className='expand-btn';btn2.textContent='Show more';
        btn2.onclick=()=>{cc.classList.toggle('expanded');btn2.textContent=cc.classList.contains('expanded')?'Show less':'Show more';};
        card.appendChild(btn2);
      }
      area.appendChild(card);
    });
  }catch(e){
    document.getElementById('loading').style.display='none';
    btn.disabled=false;
    document.getElementById('err-msg').textContent='Error: '+e.message;
  }
}

function loadDetailFromSearch(sessionId){
  switchTab('sessions');
  loadDetail(sessionId,{});
}

document.getElementById('q').addEventListener('keydown',e=>{if(e.key==='Enter')doSearch();});

// Re-fetch when any filter changes
function onFilterChange(){
  if(currentTab==='sessions'&&!currentDetail) loadSessions();
  else if(currentTab==='search'&&document.getElementById('q').value.trim()) doSearch();
}
['f-source','f-limit','f-role'].forEach(id=>document.getElementById(id).addEventListener('change',onFilterChange));
['f-date-from','f-date-to'].forEach(id=>document.getElementById(id).addEventListener('change',onFilterChange));
// Debounce project input to avoid excessive API calls while the user types
let projectDebounce;
document.getElementById('f-project').addEventListener('input',()=>{clearTimeout(projectDebounce);projectDebounce=setTimeout(onFilterChange,400);});

// Reset all filter fields to defaults and reload the current tab
function resetFilters(){
  document.getElementById('f-source').value='';
  document.getElementById('f-role').value='';
  document.getElementById('f-project').value='';
  document.getElementById('f-date-from').value='';
  document.getElementById('f-date-to').value='';
  document.getElementById('f-limit').value='10';
  onFilterChange();
}

loadStats().then(()=>loadSessions());
</script>
</body>
</html>"""


@cli.group(context_settings=CONTEXT_SETTINGS, invoke_without_command=True)
@click.option(
    "--port", "-p",
    default=8765,
    show_default=True,
    metavar="PORT",
    help="Local port for the web UI. Defaults to 8765 to avoid conflicting with Qdrant (6333).",
)
@click.option(
    "--no-browser", "-B",
    is_flag=True,
    help="Start the server but don't open a browser tab.",
)
@click.option(
    "--db",
    type=click.Path(),
    default=None,
    envvar="MEMORY_BANK_DB",
    metavar="DIR",
    help="Override the Qdrant DB storage path. Env: [dim]MEMORY_BANK_DB[/dim].",
)
@click.pass_context
def ui(ctx, port, no_browser, db):
    """Launch a web UI to browse and search your memory bank.

    Run with no subcommand for a foreground server, or use start / stop / status
    to manage a background server.

    \b
    Examples:
      memory-bank ui                    # foreground
      memory-bank ui start              # background daemon
      memory-bank ui stop               # stop background server
      memory-bank ui status             # check if running
      memory-bank ui --port 8765        # foreground on custom port
      memory-bank ui start -p 8765      # background on custom port
    """
    ctx.ensure_object(dict)
    ctx.obj["port"] = port
    ctx.obj["no_browser"] = no_browser
    ctx.obj["db"] = db

    if ctx.invoked_subcommand is not None:
        return
    import json
    import threading
    import time
    import webbrowser
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from urllib.parse import parse_qs, urlparse

    from memory_bank.db import DatabaseLockedError, MemoryDB, get_db_path
    from memory_bank.ui.daemon import _ui_url

    db_path = Path(db).expanduser() if db else get_db_path()
    memory_db = MemoryDB(path=db_path)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # silence default access log
            pass

        def send_json(self, data, status=200):
            body = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            try:
                self._handle_get()
            except DatabaseLockedError:
                self.send_json(
                    {"error": "Database is temporarily locked by another process, try again"},
                    503,
                )

        def _handle_get(self):
            parsed = urlparse(self.path)
            path = parsed.path

            if path in ("/", "/ui"):
                body = HTML.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            elif path == "/api/stats":
                self.send_json(memory_db.stats())

            elif path == "/api/sessions":
                qs = parse_qs(parsed.query)
                limit = int(qs.get("limit", ["10"])[0])
                source = qs.get("source", [""])[0] or None
                project = qs.get("project", [""])[0] or None
                date_from = qs.get("date_from", [""])[0] or None
                date_to = qs.get("date_to", [""])[0] or None
                results = memory_db.list_sessions(
                    limit=limit, source=source, project=project,
                    since=date_from, before=date_to,
                )
                self.send_json(results)

            elif path.startswith("/api/sessions/"):
                session_id = path.split("/")[-1]
                if not session_id:
                    self.send_json({"error": "missing session id"}, 400)
                    return
                messages = memory_db.get_session(session_id)
                if not messages:
                    self.send_json({"error": "session not found"}, 404)
                    return
                # Build meta from messages
                meta = {
                    "session_id": session_id,
                    "project": messages[0].get("project", ""),
                    "source": messages[0].get("source", ""),
                    "first_ts": messages[0].get("timestamp", ""),
                    "last_ts": messages[-1].get("timestamp", ""),
                    "model": messages[0].get("model", ""),
                    "git_branch": messages[0].get("git_branch", ""),
                }
                self.send_json({"meta": meta, "messages": messages})

            elif path == "/api/search":
                qs = parse_qs(parsed.query)
                q = qs.get("q", [""])[0].strip()
                if not q:
                    self.send_json({"error": "missing query"}, 400)
                    return
                limit = int(qs.get("limit", ["10"])[0])
                source = qs.get("source", [""])[0] or None
                role = qs.get("role", [""])[0] or None
                project = qs.get("project", [""])[0] or None
                date_from = qs.get("date_from", [""])[0] or None
                date_to = qs.get("date_to", [""])[0] or None
                results = memory_db.search(
                    q, limit=limit, source=source, role=role,
                    project=project, since=date_from, before=date_to,
                )
                self.send_json(results)

            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self):
            try:
                self._handle_post()
            except DatabaseLockedError:
                self.send_json(
                    {"error": "Database is temporarily locked by another process, try again"},
                    503,
                )

        def _handle_post(self):
            parsed = urlparse(self.path)
            path = parsed.path

            if path == "/api/ingest":
                content_length = int(self.headers.get("Content-Length", 0))
                if content_length == 0:
                    self.send_json({"error": "empty request body"}, 400)
                    return

                try:
                    body = json.loads(self.rfile.read(content_length))
                except (json.JSONDecodeError, ValueError) as exc:
                    self.send_json({"error": f"invalid JSON: {exc}"}, 400)
                    return

                raw_messages = body.get("messages")
                if not raw_messages or not isinstance(raw_messages, list):
                    self.send_json({"error": "messages must be a non-empty list"}, 422)
                    return

                try:
                    from memory_bank.schema import ChatMessage

                    messages = [ChatMessage.from_payload(m) for m in raw_messages]
                    inserted, skipped = memory_db.upsert(messages)
                    self.send_json({
                        "inserted": inserted,
                        "skipped": skipped,
                        "batch_size": len(messages),
                    })
                except (KeyError, TypeError) as exc:
                    self.send_json({"error": f"invalid message format: {exc}"}, 422)
                except Exception as exc:
                    self.send_json({"error": f"ingest failed: {exc}"}, 500)
            else:
                self.send_response(404)
                self.end_headers()

    try:
        server = HTTPServer(("127.0.0.1", port), Handler)
    except OSError as exc:
        if exc.errno == 48:  # Address already in use
            console.print(
                f"[bold red]Error:[/bold red] Port {port} is already in use.\n"
                f"[dim]Try [cyan]memory-bank ui stop[/cyan] to stop a background server, "
                f"or use [cyan]--port[/cyan] to pick a different port.[/dim]"
            )
            return
        raise
    url = _ui_url(port)
    console.print(
        f"[bold magenta]Memory Bank UI[/bold magenta]  [cyan]{url}[/cyan]"
    )
    console.print(f"[dim]DB: {db_path}[/dim]")
    console.print("[dim]Press Ctrl+C to stop.[/dim]\n")

    if not no_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        console.print("\n[dim]Stopped.[/dim]")
        server.shutdown()


from memory_bank.ui.daemon import _register_daemon_commands  # noqa: E402
_register_daemon_commands(ui)
