const $ = s => document.querySelector(s), $$ = s => document.querySelectorAll(s);
const api = async (u, o = {}) => {
  const r = await fetch(u, o), d = await r.json();
  if (!r.ok) throw Error(d.detail || 'Something went wrong.');
  return d;
};
const esc = s => String(s).replace(/[&<>'"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c]));
const docLabel = d => d.file_type === 'image' ? 'Image' : `${d.pages} ${d.pages === 1 ? 'page' : 'pages'}`;

function toast(s) {
  const e = $('#toast');
  e.textContent = s;
  e.style.display = 'block';
  setTimeout(() => e.style.display = 'none', 2800);
}

function page(id) {
  $$('.page').forEach(x => x.classList.toggle('active', x.id === id));
  $$('.nav').forEach(x => x.classList.toggle('active', x.dataset.page === id));
  $('#title').textContent = ({ dashboard: 'Good to see you', library: 'My Library', tutor: 'AI Tutor', quiz: 'Quiz Center', flashcards: 'Flashcards', planner: 'Study Planner', settings: 'Settings' })[id];
  if (id === 'library') docs();
  if (id === 'planner') tasks();
}
$$('.nav').forEach(b => b.onclick = () => page(b.dataset.page));
$$('.jump').forEach(b => b.onclick = () => page(b.dataset.target));

async function dashboard() {
  const d = await api('/api/dashboard');
  $('#stats').innerHTML = [['Study documents', d.documents, '▣'], ['Quizzes completed', d.quizzes, '✓'], ['Flashcards', d.flashcards, '▤'], ['Open tasks', d.tasks, '□']]
    .map(x => `<div class="stat"><span>${x[2]} &nbsp;${x[0]}</span><b>${x[1]}</b></div>`).join('');
  $('#recent-docs').innerHTML = d.recent_documents.length
    ? d.recent_documents.map(x => `<div class="list-item"><b>${esc(x.title)}</b><span>${docLabel(x)}</span></div>`).join('')
    : 'Your library is waiting for its first document.';
  $('#next-tasks').innerHTML = d.tasks_list.length
    ? d.tasks_list.map(x => `<div class="list-item"><b>${esc(x.title)}</b><span>${x.due_date || 'No due date'}</span></div>`).join('')
    : 'No upcoming tasks. Add one in Study Planner.';
}

async function docs() {
  const data = await api('/api/documents?q=' + encodeURIComponent($('#search').value)), h = $('#documents');
  h.innerHTML = data.length
    ? data.map(d => {
      const thumb = d.file_type === 'image'
        ? `<img class="doc-thumb" src="/api/documents/${d.id}/file" alt="${esc(d.title)}" loading="lazy">`
        : '<div class="icon">▣</div>';
      return `<article class="doc">${thumb}<h3>${esc(d.title)}</h3><small class="muted">${docLabel(d)} · ${new Date(d.created_at + 'Z').toLocaleDateString()}</small><div class="doc-actions"><button class="link read" data-id="${d.id}">Read</button><button class="link danger del" data-id="${d.id}">Delete</button></div></article>`;
    }).join('')
    : '<div class="empty">Upload a PDF, JPG, or PNG to start building your study library.</div>';
  $$('.read').forEach(b => b.onclick = () => read(b.dataset.id));
  $$('.del').forEach(b => b.onclick = async () => {
    if (confirm('Delete this document and extracted text?')) {
      await api('/api/documents/' + b.dataset.id, { method: 'DELETE' });
      toast('Document deleted');
      refresh();
    }
  });
}

async function read(id) {
  const d = await api('/api/documents/' + id);
  const isImage = d.file_type === 'image';
  const imageMarkup = isImage
    ? `<img class="doc-reader-img" src="/api/documents/${d.id}/file" alt="${esc(d.title)}">`
    : '';
  const bodyText = d.text_content
    ? esc(d.text_content)
    : (isImage
      ? 'Image uploaded. Select this image in AI Tutor or Quiz Center to analyze it with AI.'
      : 'No selectable text was found.');
  $('#documents').innerHTML = `<article class="doc" style="grid-column:1/-1"><button class="link" type="button" id="back-to-library">← Back to library</button><h2 style="margin:16px 0">${esc(d.title)}</h2>${imageMarkup}<p class="muted">${isImage ? 'Image · Extracted text & study notes' : `${docLabel(d)} · Extracted text`}</p><pre style="white-space:pre-wrap;font:14px/1.6 'DM Sans'">${bodyText}</pre></article>`;
  $('#back-to-library').onclick = docs;
}

$('#search').oninput = docs;
$('#pdf-file').onchange = async e => {
  const f = e.target.files[0];
  if (!f) return;
  const ext = (f.name.split('.').pop() || '').toLowerCase();
  if (!['pdf', 'jpg', 'jpeg', 'png'].includes(ext)) {
    toast('Please upload a PDF, JPG, or PNG file.');
    e.target.value = '';
    return;
  }
  $('#upload-status').textContent = ext === 'pdf' ? 'Extracting text…' : 'Analyzing image…';
  try {
    const fd = new FormData();
    fd.append('file', f);
    await api('/api/documents', { method: 'POST', body: fd });
    toast(ext === 'pdf' ? 'Document added' : 'Image added');
    e.target.value = '';
    refresh();
  } catch (x) {
    toast(x.message);
  } finally {
    $('#upload-status').textContent = '';
  }
};

async function context() {
  const d = await api('/api/documents');
  $('#context-doc').innerHTML = '<option value="">General knowledge</option>' + d.map(x => `<option value="${x.id}">${esc(x.title)}</option>`).join('');
}

$('#chat-form').onsubmit = async e => {
  e.preventDefault();
  const i = $('#question'), q = i.value.trim(), c = $('#chat');
  if (!q) return;
  c.insertAdjacentHTML('beforeend', `<div class="message user">${esc(q)}</div><div id="thinking" class="message assistant">Thinking…</div>`);
  i.value = '';
  try {
    const d = await api('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question: q, document_id: $('#context-doc').value || null }) });
    $('#thinking').outerHTML = `<div class="message assistant">${esc(d.answer)}${d.sources.length ? '\n\nSources: ' + d.sources.map(s => esc(s.document) + ' p. ' + s.page).join(', ') : ''}</div>`;
  } catch (x) {
    $('#thinking').textContent = x.message;
  }
  c.scrollTop = c.scrollHeight;
};

async function tasks() {
  const d = await api('/api/tasks'), h = $('#task-list');
  h.innerHTML = d.length
    ? d.map(t => `<article class="task-card ${t.completed ? 'done' : ''}"><input type="checkbox" ${t.completed ? 'checked' : ''} data-task="${t.id}"><div><b>${esc(t.title)}</b><small>${esc(t.subject || 'General')} · ${esc(t.priority)} priority${t.due_date ? ' · due ' + t.due_date : ''}</small></div></article>`).join('')
    : '<div class="empty">Plan your next study session above.</div>';
  $$('[data-task]').forEach(x => x.onchange = async () => {
    await api('/api/tasks/' + x.dataset.task + '/toggle', { method: 'PATCH' });
    tasks();
    dashboard();
  });
}

$('#task-form').onsubmit = async e => {
  e.preventDefault();
  try {
    await api('/api/tasks', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: $('#task-title').value, subject: $('#task-subject').value, due_date: $('#task-date').value, priority: $('#task-priority').value }) });
    e.target.reset();
    toast('Study task added');
    tasks();
    dashboard();
  } catch (x) {
    toast(x.message);
  }
};

$('#theme').onclick = () => {
  document.body.classList.toggle('dark');
  localStorage.theme = document.body.classList.contains('dark') ? 'dark' : 'light';
};
if (localStorage.theme === 'dark') document.body.classList.add('dark');

async function refresh() {
  await Promise.all([dashboard(), docs(), context(), window.fillQuizDocuments ? window.fillQuizDocuments() : Promise.resolve()]);
}

async function init() {
  try {
    const h = await api('/api/health');
    $('#ai-pill').textContent = h.ai_configured ? 'Gemini connected' : 'AI setup needed';
    $('#ai-status').textContent = h.ai_configured ? 'Gemini is configured and ready.' : 'Gemini is not configured. Add GEMINI_API_KEY to .env to enable it.';
    refresh();
  } catch (e) {
    toast('Cannot reach Smart Study backend.');
  }
}
init();

if ('serviceWorker' in navigator) window.addEventListener('load', () => navigator.serviceWorker.register('/service-worker.js').catch(() => {}));
let installPrompt;
window.addEventListener('beforeinstallprompt', (event) => {
  event.preventDefault();
  installPrompt = event;
  const button = document.querySelector('#install-app');
  if (button) button.hidden = false;
});
document.querySelector('#install-app')?.addEventListener('click', async () => {
  if (!installPrompt) return;
  installPrompt.prompt();
  await installPrompt.userChoice;
  installPrompt = null;
  document.querySelector('#install-app').hidden = true;
});
window.addEventListener('appinstalled', () => {
  installPrompt = null;
  const button = document.querySelector('#install-app');
  if (button) button.hidden = true;
});
