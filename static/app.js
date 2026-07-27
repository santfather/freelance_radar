const CATEGORIES = ["Web App", "Mobile App", "CMS", "Other IT"];
const CAT_ICONS = { "Web App": "🌐", "Mobile App": "📱", "CMS": "🔧", "Other IT": "💻" };
let logVisible = false;
let pollInterval = null;
let sortDir = 'desc';
let viewMode = 'grid';
let currentUser = null;

// 🦄 Состояние бегущего единорога
let unicornActive = false;
let unicornSpeed = 1;

// 📋 Состояние лога
let logIndex = 0;           // сколько сообщений уже обработано
let logEntries = [];        // массив всех сообщений (для экспорта)
const MAX_LOG = 100;        // лимит записей
let starsInterval = null;   // интервал звездопада
let scrapingActive = false;
let analyzingActive = false;

// 🎌 Японские словечки для трэш-эффекта
const JP_WORDS = [
  'かわいい', 'すごい', 'はい!', 'お願い!', 'ありがとう',
  'すみません', 'やった!', '頑張って!', '最高!', '最高だ!',
  'エラー!', '警告!', '完了!', '進行中', '待って!',
  'ファイト!', 'ドキドキ', 'わくわく', 'にこにこ', 'ぴょんぴょん',
  '🌈', '💖', '🌟', '🎀', '✨', '⭐', '🌸', '🦄'
];

// 🎨 Определение типа сообщения по тексту
function detectLogType(text) {
  const t = text.toLowerCase();
  if (/^(error|ошибк|fail|failed|fatal|exception|❌)/i.test(t) || /(error|ошибк|fail|exception)/i.test(t)) return 'error';
  if (/^(warn|warning|предупрежд|⚠️)/i.test(t) || /(warning|вниман|предупрежд)/i.test(t)) return 'warning';
  if (/^(progress|progress|⏳|🔄)/i.test(t) || /(прогресс|progress)/i.test(t)) return 'progress';
  if (/^(info|✅|done|complete|завершен|готово|успеш)/i.test(t) || /(завершен|успешно|готово|complete|done)/i.test(t)) return 'info';
  if (scrapingActive && !analyzingActive) return 'progress';
  return 'info';
}

// Иконки для типов
const TYPE_ICONS = {
  info: '✅',
  warning: '⚠️',
  error: '❌',
  progress: '⏳'
};

// Случайный элемент из массива
function randomItem(arr) {
  return arr[Math.floor(Math.random() * arr.length)];
}

// ── Вкладки ──
function switchTab(tab) {
  document.getElementById('tab-jobs').classList.toggle('active', tab === 'jobs');
  document.getElementById('tab-settings').classList.toggle('active', tab === 'settings');
  document.getElementById('jobs-content').classList.toggle('hidden', tab !== 'jobs');
  document.getElementById('jobs-toolbar').classList.toggle('hidden', tab !== 'jobs');
  document.getElementById('settings-content').classList.toggle('hidden', tab !== 'settings');
  if (tab === 'settings') {
    initSettingsTab();
  }
}

// ── Auth helpers ──
function getToken() {
  return localStorage.getItem('auth_token');
}

function setToken(token) {
  if (token) {
    localStorage.setItem('auth_token', token);
  } else {
    localStorage.removeItem('auth_token');
  }
}

async function apiFetch(url, options = {}) {
  const token = getToken();
  const headers = { ...options.headers };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  if (options.body && typeof options.body === 'object' && !(options.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(options.body);
  }
  const res = await fetch(url, { ...options, headers });
  const data = await res.json();
  if (res.status === 401) {
    setToken(null);
    currentUser = null;
    if (!document.getElementById('settings-content').classList.contains('hidden')) {
      updateAuthUI();
    }
  }
  return data;
}

// ── 🎊 Конфетти ──
function burstConfetti() {
  const container = document.getElementById('confetti-container');
  const colors = ['#FF69B4', '#9B59B6', '#1ABC9C', '#F1C40F', '#FFA500', '#48D1CC', '#FF6B6B', '#E6E6FA'];
  const emojis = ['🌟', '💖', '✨', '🎀', '⭐', '🌈', '🦄', '🌸'];

  for (let i = 0; i < 40; i++) {
    const piece = document.createElement('div');
    piece.className = 'confetti-piece';
    const isEmoji = Math.random() > 0.5;
    if (isEmoji) {
      piece.textContent = emojis[Math.floor(Math.random() * emojis.length)];
      piece.style.fontSize = (12 + Math.random() * 16) + 'px';
    } else {
      piece.style.width = (6 + Math.random() * 10) + 'px';
      piece.style.height = (6 + Math.random() * 10) + 'px';
      piece.style.background = colors[Math.floor(Math.random() * colors.length)];
      piece.style.borderRadius = Math.random() > 0.5 ? '50%' : '2px';
    }
    piece.style.left = Math.random() * 100 + '%';
    piece.style.animationDuration = (2 + Math.random() * 2) + 's';
    piece.style.animationDelay = Math.random() * 0.5 + 's';
    container.appendChild(piece);
    setTimeout(() => piece.remove(), 4000);
  }
}

// ── ✨ Золотые звёзды (при ховере на сердечки и единорога) ──
function burstGoldenStars() {
  const container = document.getElementById('confetti-container');
  const stars = ['⭐', '🌟', '✨', '💫', '🌟', '⭐'];

  for (let i = 0; i < 15; i++) {
    const piece = document.createElement('div');
    piece.className = 'confetti-piece';
    piece.textContent = stars[Math.floor(Math.random() * stars.length)];
    piece.style.fontSize = (14 + Math.random() * 20) + 'px';
    piece.style.color = '#FFD700';
    piece.style.textShadow = '0 0 6px rgba(255, 215, 0, 0.8)';
    piece.style.left = Math.random() * 100 + '%';
    piece.style.animationDuration = (1.5 + Math.random() * 1.5) + 's';
    piece.style.animationDelay = Math.random() * 0.3 + 's';
    container.appendChild(piece);
    setTimeout(() => piece.remove(), 3000);
  }
}

// ── Навешиваем ховер-эффекты ──
document.addEventListener('DOMContentLoaded', () => {
  const unicorn = document.getElementById('kawaii-unicorn');
  const hearts = document.querySelector('.floating-hearts');

  if (unicorn) {
    unicorn.addEventListener('mouseenter', () => { burstGoldenStars(); });
    unicorn.addEventListener('click', () => { burstGoldenStars(); });
  }
  if (hearts) {
    hearts.classList.add('interactive');
    hearts.addEventListener('mouseenter', () => { burstGoldenStars(); });
    hearts.addEventListener('click', () => { burstGoldenStars(); });
  }
});

async function pollUntilDone(options) {
  const { getButton, onComplete } = options;
  if (pollInterval) clearInterval(pollInterval);
  logIndex = 0; // сбрасываем счётчик при старте
  pollInterval = setInterval(async () => {
    const s = await fetch('/api/stats').then(r => r.json()).catch(() => ({}));
    updateProgressUI(s);
    updateScrapeStatus(s.scraping);
    updateAnalyzeStatus(s.analyzing, s.analyze_progress, s.analyze_total);

    // 🦄 Управление единорогом
    scrapingActive = !!s.scraping;
    analyzingActive = !!s.analyzing;
    if (s.scraping || s.analyzing) {
      showUnicorn();
    } else {
      hideUnicorn();
    }

    // 🌟 Звездопад во время анализа
    if (s.analyzing) {
      startFallingStars();
    } else {
      stopFallingStars();
    }

    // 📋 Обновление лога — добавляем только новые записи
    if (s.log && s.log.length > logIndex) {
      for (let i = logIndex; i < s.log.length; i++) {
        addLogEntry(s.log[i]);
      }
      logIndex = s.log.length;
    }

    ['total','analyzed','unanalyzed','take'].forEach(k => {
      const el = document.getElementById(`stat-${k}`);
      if (el) {
        el.textContent = s[k] ?? '—';
        el.style.transform = 'scale(1.15)';
        setTimeout(() => el.style.transform = '', 300);
      }
    });

    if (!s.scraping && !s.analyzing) {
      clearInterval(pollInterval);
      pollInterval = null;
      scrapingActive = false;
      analyzingActive = false;
      if (getButton) getButton().disabled = false;
      burstConfetti();
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

  // 📋 Инициализация лога через новую систему
  if (r.log && r.log.length) {
    logIndex = r.log.length;
    const entriesEl = document.getElementById('log-entries');
    entriesEl.innerHTML = '';
    logEntries = [];
    r.log.forEach(l => addLogEntry(l));
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
    label.textContent = '🍬 Парсинг: выполняется...';
  } else {
    dot.className = 'status-dot';
    label.textContent = '🍬 Парсинг: не запущен';
  }
}

function updateAnalyzeStatus(running, progress, total) {
  const dot = document.getElementById('analyze-dot');
  const label = document.getElementById('analyze-label');
  if (running) {
    dot.className = 'status-dot active';
    label.textContent = `🌟 Анализ: ${progress || 0} / ${total || '?'}`;
  } else {
    dot.className = 'status-dot';
    label.textContent = '🌟 Анализ: не запущен';
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

  const content = document.getElementById('jobs-content');
  if (!jobs.length) {
    content.innerHTML = '<div class="empty">🌸 Нет заказов по выбранным фильтрам 🌸</div>';
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
  let cardIndex = 0;
  for (const cat of CATEGORIES) {
    const list = byCategory[cat];
    if (!list.length) continue;
    html += `<div class="category-section">
      <div class="category-title">${CAT_ICONS[cat] || '📁'} ${cat} <span class="cnt">${list.length}</span></div>
      <div class="job-grid${viewMode === 'list' ? ' list-layout' : ''}">`;
    for (const job of list) {
      html += renderCard(job, cardIndex++);
    }
    html += `</div></div>`;
  }
  content.innerHTML = html;
}

function renderCard(job, index) {
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

  // Staggered animation delay for cards
  const delay = (index % 12) * 0.05;

  return `<div class="job-card ${cls}" style="animation-delay: ${delay}s">
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
  document.getElementById('log-container').classList.add('visible');
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
  document.getElementById('log-container').classList.add('visible');
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
  if (!confirm(`🌸 Сбросить все вердикты и переанализировать все ${document.getElementById('stat-total').textContent} заказов? 🌸`)) return;
  btn.disabled = true;
  btnAnalyze.disabled = true;
  btn.textContent = '⏳ Переанализ...';
  document.getElementById('log-container').classList.add('visible');
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
  document.getElementById('log-container').classList.toggle('visible', logVisible);
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

// ═══════════════════════════════════════════════════════════════
// 🔐 Аутентификация и настройки
// ═══════════════════════════════════════════════════════════════

function showLogin() {
  document.getElementById('login-form').classList.remove('hidden');
  document.getElementById('register-form').classList.add('hidden');
}

function showRegister() {
  document.getElementById('login-form').classList.add('hidden');
  document.getElementById('register-form').classList.remove('hidden');
}

function showAuthError(elId, msg) {
  const el = document.getElementById(elId);
  el.textContent = msg;
  el.classList.remove('hidden');
}

function hideAuthErrors() {
  document.getElementById('login-error').classList.add('hidden');
  document.getElementById('reg-error').classList.add('hidden');
}

async function doLogin() {
  hideAuthErrors();
  const email = document.getElementById('login-email').value.trim();
  const password = document.getElementById('login-password').value;
  if (!email || !password) {
    showAuthError('login-error', 'Пожалуйста, заполните все поля');
    return;
  }
  const res = await apiFetch('/api/login', {
    method: 'POST',
    body: { email, password },
  });
  if (res.access_token) {
    setToken(res.access_token);
    currentUser = res.user;
    updateAuthUI();
  } else {
    showAuthError('login-error', res.message || 'Ошибка входа');
  }
}

async function doRegister() {
  hideAuthErrors();
  const email = document.getElementById('reg-email').value.trim();
  const password = document.getElementById('reg-password').value;
  const password2 = document.getElementById('reg-password2').value;
  if (!email || !password || !password2) {
    showAuthError('reg-error', 'Пожалуйста, заполните все поля');
    return;
  }
  if (password !== password2) {
    showAuthError('reg-error', 'Пароли не совпадают');
    return;
  }
  if (password.length < 6) {
    showAuthError('reg-error', 'Пароль должен быть минимум 6 символов');
    return;
  }
  const res = await apiFetch('/api/register', {
    method: 'POST',
    body: { email, password },
  });
  if (res.access_token) {
    setToken(res.access_token);
    currentUser = res.user;
    updateAuthUI();
    burstConfetti();
  } else {
    showAuthError('reg-error', res.message || 'Ошибка регистрации');
  }
}

async function doLogout() {
  setToken(null);
  currentUser = null;
  updateAuthUI();
}

async function updateAuthUI() {
  const token = getToken();
  if (token) {
    // Проверяем токен на сервере
    const me = await apiFetch('/api/me');
    if (me.id) {
      currentUser = { id: me.id, email: me.email, is_admin: me.is_admin };
      document.getElementById('auth-section').classList.add('hidden');
      document.getElementById('settings-section').classList.remove('hidden');
      document.getElementById('settings-user-info').textContent = `👋 Привет, ${me.email}!`;
      await loadUserSettings();
      return;
    }
  }
  // Не авторизован
  currentUser = null;
  document.getElementById('auth-section').classList.remove('hidden');
  document.getElementById('settings-section').classList.add('hidden');
}

async function loadUserSettings() {
  const res = await apiFetch('/api/user/settings');
  if (res.deepseek_api_key !== undefined) {
    document.getElementById('set-deepseek-key').value = res.deepseek_api_key || '';
    document.getElementById('set-deepseek-model').value = res.deepseek_model || 'deepseek-chat';
    document.getElementById('set-gemini-key').value = res.gemini_api_key || '';
    document.getElementById('set-gemini-model').value = res.gemini_model || 'gemini-1.5-flash';
    document.getElementById('set-ollama-model').value = res.ollama_model || 'qwen2.5:14b';
    document.getElementById('set-ollama-host').value = res.ollama_host || 'http://localhost:11434';
  }
}

async function saveSettings() {
  const btn = document.getElementById('btn-save-settings');
  btn.disabled = true;
  btn.textContent = '⏳ Сохранение...';
  document.getElementById('settings-save-result').textContent = '';

  const data = {
    deepseek_api_key: document.getElementById('set-deepseek-key').value,
    deepseek_model: document.getElementById('set-deepseek-model').value,
    gemini_api_key: document.getElementById('set-gemini-key').value,
    gemini_model: document.getElementById('set-gemini-model').value,
    ollama_model: document.getElementById('set-ollama-model').value,
    ollama_host: document.getElementById('set-ollama-host').value,
  };

  const res = await apiFetch('/api/user/settings', {
    method: 'PUT',
    body: data,
  });

  btn.disabled = false;
  btn.textContent = '💾 Сохранить настройки';

  const resultEl = document.getElementById('settings-save-result');
  if (res.status === 'ok') {
    resultEl.className = 'settings-save-result success';
    resultEl.textContent = '✅ Настройки сохранены!';
    // Reload with masked keys
    await loadUserSettings();
  } else {
    resultEl.className = 'settings-save-result error';
    resultEl.textContent = '❌ Ошибка сохранения';
  }
  setTimeout(() => { resultEl.textContent = ''; }, 3000);
}

async function testConnection(provider) {
  const resultEl = document.getElementById(`test-${provider}-result`);
  const btn = document.getElementById(`test-${provider}`);
  btn.disabled = true;
  btn.textContent = '⏳...';
  resultEl.className = 'test-result';
  resultEl.textContent = '⏳ Проверка...';

  let api_key = null;
  let model = null;

  if (provider === 'deepseek') {
    api_key = document.getElementById('set-deepseek-key').value || null;
    model = document.getElementById('set-deepseek-model').value || null;
  } else if (provider === 'gemini') {
    api_key = document.getElementById('set-gemini-key').value || null;
    model = document.getElementById('set-gemini-model').value || null;
  } else if (provider === 'ollama') {
    api_key = document.getElementById('set-ollama-host').value || null;
    model = document.getElementById('set-ollama-model').value || null;
  }

  const res = await apiFetch('/api/test-connection', {
    method: 'POST',
    body: { provider, api_key, model },
  });

  btn.disabled = false;
  btn.textContent = '🧪 Test';

  if (res.success) {
    resultEl.className = 'test-result success';
    resultEl.textContent = '✅ ' + (res.message || 'OK');
  } else {
    resultEl.className = 'test-result error';
    resultEl.textContent = '❌ ' + (res.message || 'Ошибка');
  }
  setTimeout(() => {
    if (resultEl.textContent.startsWith('✅') || resultEl.textContent.startsWith('❌')) {
      // keep visible for a bit
    }
  }, 5000);
}

async function initSettingsTab() {
  await updateAuthUI();
}

/* ═══════════════════════════════════════════════════════════════
   🦄 Функции бегущего единорога
   ═══════════════════════════════════════════════════════════════ */

function showUnicorn() {
  if (unicornActive) return;
  unicornActive = true;
  const el = document.getElementById('running-unicorn');
  el.classList.add('visible');
  // Показываем кнопку ускорения
  document.getElementById('btn-unicorn-speed').classList.remove('hidden');
}

function hideUnicorn() {
  if (!unicornActive) return;
  unicornActive = false;
  const el = document.getElementById('running-unicorn');
  el.classList.remove('visible');
  el.classList.remove('speedy');
  document.getElementById('btn-unicorn-speed').classList.add('hidden');
  unicornSpeed = 1;
}

function speedUpUnicorn() {
  const el = document.getElementById('running-unicorn');
  if (!el.classList.contains('visible')) return;
  unicornSpeed = Math.min(unicornSpeed + 0.5, 3);
  if (unicornSpeed >= 2) {
    el.classList.add('speedy');
  }
}

/* ═══════════════════════════════════════════════════════════════
   📋 Функции нового лога
   ═══════════════════════════════════════════════════════════════ */

function addLogEntry(text) {
  const entriesEl = document.getElementById('log-entries');
  const placeholder = document.getElementById('log-placeholder');
  const countEl = document.getElementById('log-count');

  // Убираем плейсхолдер
  if (placeholder) placeholder.remove();

  // Определяем тип и иконку
  const type = detectLogType(text);
  const icon = TYPE_ICONS[type] || '•';
  const jpWord = Math.random() < 0.4 ? randomItem(JP_WORDS) : null;

  // Создаём DOM-элемент
  const entry = document.createElement('div');
  entry.className = `log-entry log-${type}`;

  // Иконка + текст + японское словечко
  let html = `<span class="log-entry-icon">${icon}</span>${escHtml(text)}`;
  if (jpWord) {
    html += ` <span class="log-entry-jp">${jpWord}</span>`;
  }
  entry.innerHTML = html;

  // Иногда добавляем эффект печати (для не-ошибок, с вероятностью 20%)
  if (type !== 'error' && Math.random() < 0.2) {
    entry.classList.add('typing');
  }

  entriesEl.appendChild(entry);

  // Сохраняем в массив для экспорта
  logEntries.push({ text, type, icon });

  // Ограничение длины
  if (logEntries.length > MAX_LOG) {
    const excess = logEntries.length - MAX_LOG;
    const children = entriesEl.children;
    for (let i = 0; i < excess && children.length > 0; i++) {
      children[0].remove();
    }
    logEntries.splice(0, excess);
  }

  // Авто-скролл вниз
  const container = document.getElementById('log-container');
  container.scrollTop = container.scrollHeight;

  // Обновляем счётчик
  countEl.textContent = logEntries.length;
}

function clearLog() {
  const entriesEl = document.getElementById('log-entries');
  entriesEl.innerHTML = '<span class="log-placeholder" id="log-placeholder">💬 Лог очищен. Жду новых сообщений...</span>';
  logEntries = [];
  logIndex = 0;
  document.getElementById('log-count').textContent = '0';
}

function exportLog() {
  const lines = logEntries.map(e => `[${e.type.toUpperCase()}] ${e.text}`).join('\n');
  const blob = new Blob([`🎯 Freelance Radar Log Export 🎯\n${'═'.repeat(50)}\n${lines}\n${'═'.repeat(50)}\nЭкспортировано: ${new Date().toLocaleString()}\n`], { type: 'text/plain;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `freelance-radar-log-${Date.now()}.txt`;
  a.click();
  URL.revokeObjectURL(url);
}

/* ═══════════════════════════════════════════════════════════════
   🌟 Звездопад — падающие звёздочки
   ═══════════════════════════════════════════════════════════════ */

function startFallingStars() {
  if (starsInterval) return;
  const container = document.getElementById('stars-container');
  const starEmojis = ['✨', '🌟', '⭐', '💫', '✦', '✧'];

  function dropStar() {
    const star = document.createElement('div');
    star.className = 'falling-star';
    star.textContent = randomItem(starEmojis);
    star.style.left = Math.random() * 100 + '%';
    star.style.fontSize = (12 + Math.random() * 18) + 'px';
    star.style.animationDuration = (3 + Math.random() * 4) + 's';
    star.style.animationDelay = '0s';
    container.appendChild(star);
    // Удаляем после анимации
    setTimeout(() => { if (star.parentNode) star.remove(); }, 8000);
  }

  // Сразу кидаем несколько
  for (let i = 0; i < 8; i++) {
    setTimeout(dropStar, i * 200);
  }
  starsInterval = setInterval(dropStar, 600);
}

function stopFallingStars() {
  if (starsInterval) {
    clearInterval(starsInterval);
    starsInterval = null;
  }
}

/* ═══════════════════════════════════════════════════════════════
   🎀 Ховер-эффекты на бегущем единороге
   ═══════════════════════════════════════════════════════════════ */

// Добавляем конфетти при клике на бегущего единорога
document.addEventListener('DOMContentLoaded', () => {
  const runningUnicorn = document.getElementById('running-unicorn');
  if (runningUnicorn) {
    runningUnicorn.addEventListener('click', () => { burstGoldenStars(); });
  }
});

// ── Init ──
(async () => {
  await loadStats();
  await loadJobs();
  // Check auth on load
  const token = getToken();
  if (token) {
    const me = await apiFetch('/api/me');
    if (me.id) {
      currentUser = { id: me.id, email: me.email, is_admin: me.is_admin };
    } else {
      setToken(null);
    }
  }
})();
