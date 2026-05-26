'use strict';

const app = document.getElementById('app');

async function api(path, opts = {}) {
  const res = await fetch(path, { credentials: 'same-origin', ...opts });
  return res;
}

async function apiJSON(path, opts = {}) {
  const res = await api(path, opts);
  let body = null;
  try { body = await res.json(); } catch (_) {}
  return { res, body };
}

// --- modal -----------------------------------------------------------------

function confirmDialog(message, opts = {}) {
  const { confirmText = 'Confirm', cancelText = 'Cancel', danger = true } = opts;
  return new Promise((resolve) => {
    const dialog = document.getElementById('modal');
    dialog.querySelector('[data-role=message]').textContent = message;
    const confirmBtn = dialog.querySelector('[data-role=confirm]');
    const cancelBtn = dialog.querySelector('[data-role=cancel]');
    confirmBtn.textContent = confirmText;
    cancelBtn.textContent = cancelText;
    confirmBtn.classList.toggle('danger', danger);

    const onConfirm = () => { dialog.returnValue = 'confirm'; dialog.close(); };
    const onCancel = () => { dialog.returnValue = 'cancel'; dialog.close(); };
    const onBackdrop = (e) => {
      const r = dialog.getBoundingClientRect();
      const inside = e.clientX >= r.left && e.clientX <= r.right
                  && e.clientY >= r.top && e.clientY <= r.bottom;
      if (!inside) { dialog.returnValue = 'cancel'; dialog.close(); }
    };
    const onClose = () => {
      confirmBtn.removeEventListener('click', onConfirm);
      cancelBtn.removeEventListener('click', onCancel);
      dialog.removeEventListener('click', onBackdrop);
      dialog.removeEventListener('close', onClose);
      resolve(dialog.returnValue === 'confirm');
    };

    confirmBtn.addEventListener('click', onConfirm);
    cancelBtn.addEventListener('click', onCancel);
    dialog.addEventListener('click', onBackdrop);
    dialog.addEventListener('close', onClose);
    dialog.returnValue = 'cancel';   // default on ESC / backdrop
    dialog.showModal();
    cancelBtn.focus();               // safer default than auto-focusing the destructive action
  });
}

// --- theme -----------------------------------------------------------------

(function initTheme() {
  const saved = localStorage.getItem('theme');
  if (saved) document.documentElement.setAttribute('data-theme', saved);
})();

// --- routing ---------------------------------------------------------------

let sse = null;

async function route() {
  const { res, body } = await apiJSON('/api/auth/me');
  if (res.status === 401) {
    if (sse) { sse.close(); sse = null; }
    renderLogin();
    return;
  }
  renderShell();
  const hash = location.hash || '#/clips';
  if (hash === '#/settings') renderSettings();
  else renderClips();
  ensureSSE();
}

window.addEventListener('hashchange', route);

// --- login ----------------------------------------------------------------

function renderLogin() {
  app.replaceChildren(document.getElementById('tpl-login').content.cloneNode(true));
  const form = document.getElementById('login-form');
  const err = form.querySelector('[data-role=error]');
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    err.hidden = true;
    const data = Object.fromEntries(new FormData(form).entries());
    const { res, body } = await apiJSON('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        username: data.username,
        password: data.password,
        remember: !!data.remember,
      }),
    });
    if (!res.ok) {
      err.textContent = (body && body.error) || 'login failed';
      err.hidden = false;
      return;
    }
    location.hash = '#/clips';
    route();
  });
}

// --- shell ----------------------------------------------------------------

function renderShell() {
  if (document.querySelector('header')) {
    highlightNav();
    return;
  }
  app.replaceChildren(document.getElementById('tpl-shell').content.cloneNode(true));
  document.getElementById('logout').addEventListener('click', async () => {
    await api('/api/auth/logout', { method: 'POST' });
    location.hash = '';
    route();
  });
  document.getElementById('theme-toggle').addEventListener('click', () => {
    const cur = document.documentElement.getAttribute('data-theme') || 'dark';
    const next = cur === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('theme', next);
  });
  highlightNav();
}

function highlightNav() {
  const tab = (location.hash || '#/clips').replace('#/', '');
  document.querySelectorAll('header nav a').forEach(a => {
    a.classList.toggle('active', a.dataset.tab === tab);
  });
}

// --- clips view -----------------------------------------------------------

let clipsCache = [];

// Attached once at module load — re-running renderClips() must not stack
// duplicate paste handlers (caused double-upload).
document.addEventListener('paste', async (e) => {
  if (location.hash && location.hash !== '#/clips') return;
  const status = document.getElementById('push-status');
  if (!status) return;
  const items = e.clipboardData.items;
  for (const item of items) {
    if (item.kind === 'file') {
      await uploadFile(item.getAsFile(), status);
      return;
    }
  }
  const text = e.clipboardData.getData('text/plain');
  if (text) await pushTextValue(text, status);
});

function renderClips() {
  const view = document.getElementById('view');
  view.replaceChildren(document.getElementById('tpl-clips').content.cloneNode(true));

  const zone = document.getElementById('paste-zone');
  const textInput = document.getElementById('text-input');
  const fileInput = document.getElementById('file-input');
  const pushText = document.getElementById('push-text');
  const status = document.getElementById('push-status');
  const clearAll = document.getElementById('clear-all');

  zone.addEventListener('dragover', (e) => { e.preventDefault(); zone.classList.add('drag'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('drag'));
  zone.addEventListener('drop', async (e) => {
    e.preventDefault();
    zone.classList.remove('drag');
    if (e.dataTransfer.files.length) await uploadFile(e.dataTransfer.files[0], status);
  });
  fileInput.addEventListener('change', async () => {
    if (fileInput.files.length) await uploadFile(fileInput.files[0], status);
    fileInput.value = '';
  });
  pushText.addEventListener('click', async () => {
    const v = textInput.value;
    if (!v) return;
    await pushTextValue(v, status);
    textInput.value = '';
  });
  clearAll.addEventListener('click', async () => {
    if (!await confirmDialog('Delete every clip? This cannot be undone.', { confirmText: 'Delete all' })) return;
    await api('/api/clips', { method: 'DELETE' });
  });

  const hint = document.getElementById('http-image-hint');
  if (hint && !window.isSecureContext) hint.hidden = false;

  loadClips();
}

async function uploadFile(file, status) {
  status.textContent = `uploading ${file.name || 'paste'}…`;
  const fd = new FormData();
  fd.append('file', file, file.name || 'paste');
  const res = await api('/api/clip', {
    method: 'POST',
    headers: { 'X-Device-Label': deviceLabel() },
    body: fd,
  });
  status.textContent = res.ok ? 'pushed.' : `failed: ${res.status}`;
  setTimeout(() => { status.textContent = ''; }, 2500);
}

async function pushTextValue(text, status) {
  status.textContent = 'uploading text…';
  const res = await api('/api/clip', {
    method: 'POST',
    headers: {
      'Content-Type': 'text/plain; charset=utf-8',
      'X-Device-Label': deviceLabel(),
    },
    body: text,
  });
  status.textContent = res.ok ? 'pushed.' : `failed: ${res.status}`;
  setTimeout(() => { status.textContent = ''; }, 2500);
}

function deviceLabel() {
  let label = localStorage.getItem('device_label');
  if (!label) {
    label = 'web-' + Math.random().toString(36).slice(2, 8);
    localStorage.setItem('device_label', label);
  }
  return label;
}

async function loadClips() {
  const { body } = await apiJSON('/api/clips?limit=200');
  clipsCache = Array.isArray(body) ? body : [];
  renderClipList();
}

function renderClipList() {
  const list = document.getElementById('clips');
  const empty = document.getElementById('empty');
  if (!list) return;
  list.replaceChildren();
  if (!clipsCache.length) { empty.hidden = false; return; }
  empty.hidden = true;
  for (const clip of clipsCache) list.appendChild(buildRow(clip));
}

function buildRow(clip) {
  const frag = document.getElementById('tpl-clip-row').content.cloneNode(true);
  const li = frag.querySelector('li');
  li.dataset.id = clip.id;
  const icon = li.querySelector('[data-role=icon]');
  if (clip.type === 'image') {
    const img = document.createElement('img');
    img.src = `/api/clip/${clip.id}`;
    img.alt = '';
    icon.replaceChildren(img);
  } else if (clip.type === 'text') {
    icon.textContent = '¶';
  } else {
    icon.textContent = '📄';
  }
  const preview = li.querySelector('[data-role=preview]');
  if (clip.type === 'text') {
    preview.textContent = clip.preview || '';
  } else if (clip.type === 'image') {
    preview.textContent = `${clip.mime} · ${(clip.filename || 'image')}`;
  } else {
    preview.textContent = clip.filename || `${clip.mime} (${formatBytes(clip.size)})`;
  }
  li.querySelector('[data-role=device]').textContent = `from ${clip.device_label}`;
  li.querySelector('[data-role=ago]').textContent = ago(clip.created_at);
  li.querySelector('[data-role=size]').textContent = formatBytes(clip.size);

  li.querySelector('[data-action=copy]').addEventListener('click', () => copyToClipboard(clip));
  li.querySelector('[data-action=download]').addEventListener('click', () => downloadClip(clip));
  li.querySelector('[data-action=delete]').addEventListener('click', async () => {
    if (!await confirmDialog('Delete this clip?', { confirmText: 'Delete' })) return;
    await api(`/api/clip/${clip.id}`, { method: 'DELETE' });
  });
  return li;
}

async function copyToClipboard(clip) {
  if (clip.type === 'text') {
    try {
      const res = await api(`/api/clip/${clip.id}`);
      const text = await res.text();
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
      } else if (!legacyCopyText(text)) {
        throw new Error('legacy copy refused');
      }
      toast('copied text');
      return;
    } catch (e) {
      toast('copy failed — downloading instead');
      downloadClip(clip);
      return;
    }
  }
  if (clip.type === 'image') {
    const canImage = window.ClipboardItem
      && navigator.clipboard
      && navigator.clipboard.write
      && window.isSecureContext;
    if (canImage) {
      try {
        const res = await api(`/api/clip/${clip.id}`);
        const blob = await res.blob();
        const item = new ClipboardItem({ [blob.type || 'image/png']: blob });
        await navigator.clipboard.write([item]);
        toast('copied image');
        return;
      } catch (e) {
        // fall through to download
      }
    } else {
      toast('image copy needs HTTPS — downloading instead');
    }
  }
  downloadClip(clip);
}

function legacyCopyText(text) {
  // Works on plain HTTP where navigator.clipboard is unavailable.
  // iOS Safari refuses opacity:0 / hidden textareas; we render a tiny but
  // technically-visible element and select via setSelectionRange.
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.readOnly = false;
  ta.contentEditable = 'true';
  ta.style.position = 'fixed';
  ta.style.top = '0';
  ta.style.left = '0';
  ta.style.width = '1px';
  ta.style.height = '1px';
  ta.style.padding = '0';
  ta.style.border = '0';
  ta.style.outline = 'none';
  ta.style.boxShadow = 'none';
  ta.style.background = 'transparent';
  ta.style.fontSize = '16px';   // avoid iOS zoom on focus
  document.body.appendChild(ta);

  const prevRange = document.getSelection().rangeCount > 0
    ? document.getSelection().getRangeAt(0) : null;

  ta.focus();
  ta.setSelectionRange(0, text.length);
  // Belt-and-suspenders for iOS: also create a Range over the element.
  const range = document.createRange();
  range.selectNodeContents(ta);
  const sel = window.getSelection();
  sel.removeAllRanges();
  sel.addRange(range);
  ta.setSelectionRange(0, text.length);

  let ok = false;
  try { ok = document.execCommand('copy'); } catch (_) {}

  ta.remove();
  if (prevRange) {
    const s = window.getSelection();
    s.removeAllRanges();
    s.addRange(prevRange);
  }
  return ok;
}

function downloadClip(clip) {
  const a = document.createElement('a');
  a.href = `/api/clip/${clip.id}`;
  a.download = clip.filename || clip.id;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

function toast(msg) {
  const status = document.getElementById('push-status');
  if (!status) return;
  status.textContent = msg;
  setTimeout(() => { status.textContent = ''; }, 1500);
}

function formatBytes(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

function ago(epoch) {
  const sec = Math.max(1, Math.floor(Date.now() / 1000 - epoch));
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
  return `${Math.floor(sec / 86400)}d ago`;
}

// --- SSE ------------------------------------------------------------------

function ensureSSE() {
  if (sse) return;
  sse = new EventSource('/api/events');
  sse.addEventListener('clip.new', (e) => {
    const clip = JSON.parse(e.data);
    clipsCache = [clip, ...clipsCache.filter(c => c.id !== clip.id)];
    renderClipList();
  });
  sse.addEventListener('clip.deleted', (e) => {
    const { id } = JSON.parse(e.data);
    clipsCache = clipsCache.filter(c => c.id !== id);
    renderClipList();
  });
  sse.addEventListener('clips.cleared', () => {
    clipsCache = [];
    renderClipList();
  });
  sse.onerror = () => {
    // EventSource auto-reconnects; if we got logged out the next reconnect 401s.
  };
}

// --- settings view --------------------------------------------------------

async function renderSettings() {
  const view = document.getElementById('view');
  view.replaceChildren(document.getElementById('tpl-settings').content.cloneNode(true));
  const { body: settings } = await apiJSON('/api/settings');
  const form = document.getElementById('settings-form');
  for (const k of ['history_size', 'item_ttl_hours', 'max_item_size_mb']) {
    form.elements[k].value = settings[k];
  }
  const status = document.getElementById('settings-status');
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(form).entries());
    const payload = {};
    for (const [k, v] of Object.entries(data)) payload[k] = Number(v);
    const { res, body } = await apiJSON('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    status.textContent = res.ok ? 'saved.' : `failed: ${(body && body.error) || res.status}`;
    setTimeout(() => { status.textContent = ''; }, 2500);
  });

  const tokenInput = document.getElementById('api-token');
  const { body: tokRes } = await apiJSON('/api/auth/token');
  tokenInput.value = (tokRes && tokRes.api_token) || '';
  updateCurlExamples(tokenInput.value);

  document.getElementById('copy-token').addEventListener('click', async () => {
    await navigator.clipboard.writeText(tokenInput.value);
  });
  document.getElementById('regenerate-token').addEventListener('click', async () => {
    if (!await confirmDialog('Regenerate token? Existing scripts will need updating.', { confirmText: 'Regenerate' })) return;
    const { body } = await apiJSON('/api/auth/rotate-token', { method: 'POST' });
    tokenInput.value = (body && body.api_token) || '';
    updateCurlExamples(tokenInput.value);
  });

  const pform = document.getElementById('password-form');
  const pstatus = document.getElementById('password-status');
  pform.addEventListener('submit', async (e) => {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(pform).entries());
    const { res, body } = await apiJSON('/api/auth/change-password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    pstatus.textContent = res.ok ? 'password updated.' : `failed: ${(body && body.error) || res.status}`;
    if (res.ok) pform.reset();
    setTimeout(() => { pstatus.textContent = ''; }, 3000);
  });
}

function updateCurlExamples(token) {
  const base = `${location.origin}`;
  const t = token || '<TOKEN>';
  document.getElementById('curl-examples').textContent = `# Push text
echo "hello" | curl -H "Authorization: Bearer ${t}" -H "Content-Type: text/plain" --data-binary @- ${base}/api/clip

# Push an image (raw bytes — Content-Type picks the type)
curl -H "Authorization: Bearer ${t}" -H "Content-Type: image/png" --data-binary @screenshot.png ${base}/api/clip

# Push any file (multipart, keeps the original filename)
curl -H "Authorization: Bearer ${t}" -F "file=@/path/to/file" ${base}/api/clip

# Get latest as raw bytes with the original Content-Type
curl -H "Authorization: Bearer ${t}" ${base}/api/clip/latest

# Save latest to a file (works for images, text, anything)
curl -H "Authorization: Bearer ${t}" -o latest.bin ${base}/api/clip/latest

# Lazy curl: token in query string (logs warning — see README)
curl ${base}/api/clip/latest?token=${t}
`;
}

// --- boot -----------------------------------------------------------------

route();
