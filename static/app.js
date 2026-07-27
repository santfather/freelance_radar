const CATEGORIES = ["Web App", "Mobile App", "CMS", "Other IT"];
const CAT_ICONS = { "Web App": "🌐", "Mobile App": "📱", "CMS": "🔧", "Other IT": "💻" };
let logVisible = false;
let pollInterval = null;
let sortDir = 'desc';
let viewMode = 'grid';

async function pollUntilDone(options) {
  const { getButton, onComplete } = options;
  if (pollInterval) clearInterval(pollInterval);
  pollInterval = setInterval(async () => {
    const s = await fetch('/api/stats').then(r => r.json()).catch(() => ({}));
    updateProgressUI(s);
    updateScrapeStatus(s.scraping);
    updateAnalyzeStatus(s.analyzing, s.analyze_progress, s.analyze_total);
    if (s.log) document.getElementById('log-box').innerHTML = s.log.map(l => `<div>${escHtml(l)}</div>`).join('');
    ['total','analyzed','unanalyzed','take'].forEach(k => {
      const el = document.getElementById(`stat-${k}`);
      if (el) el.textContent = s[k] ?? '—';
    });
    if (!s.scraping && !s.analyzing) {
      clearInterval(pollInterval);
      pollInterval = null;
      if (getButton) getButton().disabled = false;
      if (onComplete) await onComplete();
      await loadJobs();
      await loadStats();
    }
  }, 1500);
}

async function loadStats() {
  const r = await fetch('/api/stats').then(r => r.json());
  document.getElementById('stat-total').textContent = r.total ?? '—';
  document.getElementById('stat-analyzed').textContent = r.analyzed ?? '—';
  document.getElementById('stat-unanalyzed').textContent = r.unanalyzed ?? '—';
  document.getElementById('stat-take').textContent = r.take ?? '—';

  const provEl = document.getElementById('provider-status');
  const prov = r.provider || 'ollama';
  const avail = r.available_providers?.[prov];
  if (avail?.ok) {
    provEl.className = 'provider-status ok';
    provEl.textContent = '🟢 ' + (avail.msg || prov + ' OK');
  } else if (avail) {
    provEl.className = 'provider-status err';
    provEl.textContent = '🔴 ' + (avail.msg || prov + ' недоступен');
  } else {
    provEl.className = 'provider-status unknown';
    provEl.textContent = '⏳ Информация...';
  }

  document.getElementById('provider-select').value = prov;

  if (r.log && r.log.length) {
    document.getElementById('log-box').innerHTML = r.log.map(l => `<div>${escHtml(l)}</div>`).join('');
  }

  updateScrapeStatus(r.scraping);
  updateAnalyzeStatus(r.analyzing, r.analyze_progress, r.analyze_total);
  updateProgressUI(r);

  document.getElementById('btn-scrape').disabled = !!r.scraping;
  document.getElementById('btn-analyze').disabled = !!r.analyzing;
  document.getElementById('btn-reanalyze').disabled = !!r.analyzing;

  return r;
}

function updateScrapeStatus(running) {
  const dot = document.getElementById('scrape-dot');
  const label = document.getElementById('scrape-label');
  if (running) {
    dot.className = 'status-dot active';
    label.textContent = 'Парсинг: выполняется...';
  } else {
    dot.className = 'status-dot';
    label.textContent = 'Парсинг: не запущен';
  }
}

function updateAnalyzeStatus(running, progress, total) {
  const dot = document.getElementById('analyze-dot');
  const label = document.getElementById('analyze-label');
  if (running) {
    dot.className = 'status-dot active';
    label.textContent = `Анализ: ${progress || 0} / ${total || '?'}`;
  } else {
    dot.className = 'status-dot';
    label.textContent = 'Анализ: не запущен';
  }
}

function updateProgressUI(s) {
  const wrap = document.getElementById('progress-wrap');
  const fill = document.getElementById('progress-fill');
  const label = document.getElementById('progress-label');

  if (s.analyzing && s.analyze_total > 0) {
    const total = s.analyze_total || 1;
    const done = s.analyze_progress || 0;
    const pct = Math.min(100, Math.round((done / total) * 100));
    fill.style.width = pct + '%';
    fill.className = 'progress-bar-fill analysis';
    label.textContent = `🧠 Анализ: ${done} / ${total} (${pct}%)`;
    wrap.classList.remove('hidden');
    label.classList.remove('hidden');
  } else if (s.scraping) {
    fill.style.width = '30%';
    fill.className = 'progress-bar-fill';
    label.textContent = '⏳ Парсинг вакансий...';
    label.classList.remove('hidden');
    wrap.classList.remove('hidden');
  } else {
    wrap.classList.add('hidden');
    label.classList.add('hidden');
  }
}

async function loadJobs() {
  const verdict = document.getElementById('filter-verdict').value;
  const category = document.getElementById('filter-category').value;
  const analyzed = document.getElementById('filter-analyzed').value;
  const params = new URLSearchParams({ verdict, category, analyzed, sort: sortDir });
  const jobs = await fetch(`/api/jobs?${params}`).then(r => r.json());

  const content = document.getElementById('content');
  if (!jobs.length) {
    content.innerHTML = '<div class="empty">Нет заказов по выбранным фильтрам</div>';
    return;
  }

  const byCategory = {};
  CATEGORIES.forEach(c => byCategory[c] = []);
  jobs.forEach(j => {
    const cat = j.category || 'Other IT';
    if (!byCategory[cat]) byCategory[cat] = [];
    byCategory[cat].push(j);
  });

  let html = '';
  for (const cat of CATEGORIES) {
    const list = byCategory[cat];
    if (!list.length) continue;
    html += `<div class="category-section">
      <div class="category-title">${CAT_ICONS[cat] || '📁'} ${cat} <span class="cnt">${list.length}</span></div>
      <div class="job-grid${viewMode === 'list' ? ' list-layout' : ''}">`;
    for (const job of list) {
      html += renderCard(job);
    }
    html += `</div></div>`;
  }
  content.innerHTML = html;
}

function renderCard(job) {
  const v = job.verdict || 'UNKNOWN';
  const cls = v === 'TAKE' ? 'take' : v === 'SKIP' ? 'skip' : 'unknown';
  let badge;
  if (v === 'TAKE') badge = '✅ БРАТЬ';
  else if (v === 'SKIP') badge = '❌ Пропустить';
  else if (job.analyzed) badge = '❓ Неизвестно';
  else badge = '⏳ Ожидает анализа';
  const complexity = job.complexity || 0;
  const dots = Array.from({length: 5}, (_, i) =>
    `<div class="dot${i < complexity ? ' on' : ''}"></div>`
  ).join('');

  const budget = job.budget_raw ? `💰 ${job.budget_raw}` : '';
  const hours = job.estimated_hours ? `⏱ ~${job.estimated_hours}h` : '';
  const source = job.source ? `📌 ${job.source}` : '';
  const posted = job.posted_at ? `🕐 ${job.posted_at}` : '';

  const descPreview = job.description
    ? escHtml(job.description.slice(0, 180)) + (job.description.length > 180 ? '…' : '')
    : '';

  return `<div class="job-card ${cls}">
    <div class="job-header">
      <span class="verdict-badge ${v}">${badge}</span>
      <div class="job-title"><a href="${job.url}" target="_blank">${escHtml(job.title)}</a></div>
    </div>
    ${descPreview ? `<div class="job-desc">${descPreview}</div>` : ''}
    <div class="job-meta">
      ${budget ? `<span class="meta-item">${escHtml(budget)}</span>` : ''}
      ${hours ? `<span class="meta-item">${hours}</span>` : ''}
      ${complexity ? `<span class="meta-item">Сложность <div class="complexity-dots">${dots}</div></span>` : ''}
      ${source ? `<span class="meta-item">${escHtml(source)}</span>` : ''}
      ${posted ? `<span class="meta-item">${escHtml(posted)}</span>` : ''}
    </div>
    ${job.verdict_reason ? `<div class="job-reason">💬 ${escHtml(job.verdict_reason)}</div>` : ''}
  </div>`;
}

function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

async function startScrape() {
  const btn = document.getElementById('btn-scrape');
  btn.disabled = true;
  btn.textContent = '⏳ Парсинг...';
  document.getElementById('log-box').classList.add('visible');
  logVisible = true;
  await fetch('/api/refresh', {method: 'POST'});
  pollUntilDone({
    getButton: () => {
      const b = document.getElementById('btn-scrape');
      b.textContent = '🔄 Запустить парсинг';
      return b;
    },
  });
}

async function startAnalysis() {
  const btn = document.getElementById('btn-analyze');
  btn.disabled = true;
  btn.textContent = '⏳ Анализ...';
  document.getElementById('log-box').classList.add('visible');
  logVisible = true;
  const r = await fetch('/api/analyze', {method: 'POST'}).then(r => r.json());
  if (r.status === 'already_running') {
    btn.disabled = false;
    btn.textContent = '🧠 Запустить анализ';
    return;
  }
  pollUntilDone({
    getButton: () => {
      const b = document.getElementById('btn-analyze');
      b.textContent = '🧠 Запустить анализ';
      return b;
    },
  });
}

async function startReanalysis() {
  const btn = document.getElementById('btn-reanalyze');
  const btnAnalyze = document.getElementById('btn-analyze');
  if (!confirm(`Сбросить все вердикты и переанализировать все ${document.getElementById('stat-total').textContent} заказов?`)) return;
  btn.disabled = true;
  btnAnalyze.disabled = true;
  btn.textContent = '⏳ Переанализ...';
  document.getElementById('log-box').classList.add('visible');
  logVisible = true;
  await fetch('/api/analyze?force=true', {method: 'POST'});
  pollUntilDone({
    getButton: () => {
      const b = document.getElementById('btn-reanalyze');
      b.textContent = '🔄 Переанализировать всё';
      document.getElementById('btn-analyze').disabled = false;
      return b;
    },
  });
}

async function changeProvider(provider) {
  await fetch('/api/settings', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({provider}),
  });
  await loadStats();
}

function toggleLog() {
  logVisible = !logVisible;
  document.getElementById('log-box').classList.toggle('visible', logVisible);
}

function toggleSort() {
  sortDir = sortDir === 'desc' ? 'asc' : 'desc';
  const btn = document.getElementById('btn-sort');
  btn.textContent = sortDir === 'desc' ? '↑ Новые' : '↓ Старые';
  loadJobs();
}

function setView(mode) {
  viewMode = mode;
  document.getElementById('btn-grid').classList.toggle('active', mode === 'grid');
  document.getElementById('btn-list').classList.toggle('active', mode === 'list');
  loadJobs();
}

(async () => {
  await loadStats();
  await loadJobs();
})();
