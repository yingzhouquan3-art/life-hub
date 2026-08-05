/* 生活中枢 · 手机端
 *
 * 三件事：一句话记录、待确认捕获、今日已记内容。
 * 报表、复盘、人生方格留在桌面端——手机上只解决「来不及记」。
 *
 * 离线优先：写入请求先进本地队列，联网后自动补发。
 * 队列只存「用户已经确认过的写入」，解析这类只读请求不入队。
 */
'use strict';

const API = '';
const TOKEN_KEY = 'lifehub.token';
const QUEUE_KEY = 'lifehub.queue';

// ---------- token ----------
// 首次打开时地址里带 ?token=，存下来之后就从 URL 里抹掉，避免留在历史记录里。
function initToken() {
  const fromUrl = new URLSearchParams(location.search).get('token');
  if (fromUrl) {
    localStorage.setItem(TOKEN_KEY, fromUrl);
    history.replaceState(null, '', location.pathname);
  }
  return localStorage.getItem(TOKEN_KEY) || '';
}
let token = initToken();

async function api(path, options = {}) {
  const headers = Object.assign({ 'Content-Type': 'application/json' }, options.headers || {});
  if (token) headers['X-Life-Token'] = token;
  const response = await fetch(API + path, Object.assign({}, options, { headers }));
  if (response.status === 401) {
    throw new Error('访问令牌无效，请在电脑上重新扫码配对');
  }
  if (!response.ok) {
    let detail = response.statusText;
    try { detail = (await response.json()).detail || detail; } catch (e) { /* 保留状态码文本 */ }
    throw new Error(detail);
  }
  return response.json();
}

// ---------- 离线队列 ----------
function readQueue() {
  try { return JSON.parse(localStorage.getItem(QUEUE_KEY) || '[]'); } catch (e) { return []; }
}
function writeQueue(items) {
  localStorage.setItem(QUEUE_KEY, JSON.stringify(items));
  renderConnection();
}
function enqueue(item) {
  const items = readQueue();
  items.push(Object.assign({ queued_at: new Date().toISOString() }, item));
  writeQueue(items);
}

/** 逐条补发。失败的留在队列里，不丢；顺序保持先进先出。 */
async function flushQueue() {
  if (!navigator.onLine) return { sent: 0, left: readQueue().length };
  let items = readQueue();
  let sent = 0;
  while (items.length) {
    const item = items[0];
    try {
      await api(item.path, { method: 'POST', body: JSON.stringify(item.body) });
      items = items.slice(1);
      writeQueue(items);
      sent += 1;
    } catch (error) {
      break;  // 网络或服务端问题，留着下次再试
    }
  }
  if (sent) { showBanner(`已补发 ${sent} 条离线记录`, 'ok'); refresh(); }
  return { sent, left: items.length };
}

// ---------- 界面 ----------
const $ = (id) => document.getElementById(id);

function showBanner(text, kind) {
  const banner = $('banner');
  banner.textContent = text;
  banner.className = 'banner ' + (kind || '');
  if (kind === 'ok') setTimeout(() => banner.classList.add('hidden'), 2600);
}

function renderConnection() {
  const queued = readQueue().length;
  const parts = [];
  parts.push(navigator.onLine ? '在线' : '离线');
  parts.push(token ? '已配对' : '未配对');
  if (queued) parts.push(`${queued} 条待补发`);
  $('connInfo').textContent = parts.join(' · ');
  if (!navigator.onLine) {
    showBanner(queued ? `离线中，${queued} 条记录已暂存` : '离线中，记录会先存在手机上', 'offline');
  } else {
    $('banner').classList.add('hidden');
  }
}

const FIELD_LABELS = {
  occurred_on: '日期', amount: '金额', note: '备注', activity: '类型',
  duration_minutes: '时长(分钟)', intensity: '强度', meal_type: '餐次', name: '内容',
  calories: '热量', protein_g: '蛋白质(g)', water_ml: '饮水(ml)', sleep_hours: '睡眠(小时)',
  energy: '精力', mood: '心情', subject: '科目', focus: '专注', title: '待办', due_on: '截止日',
  type: '收支', category: '分类', source: '收入来源',
};
const HIDDEN_FIELDS = new Set(['account_name', 'account_id', 'sleep_quality', 'priority']);

let current = null;   // { module, preview, alternatives }

function renderPreview(parsed) {
  current = { module: parsed.module, preview: Object.assign({}, parsed.preview),
              alternatives: parsed.alternatives || [] };
  $('preview').classList.remove('hidden');

  const pills = [parsed.module].concat(current.alternatives.filter((m) => m !== parsed.module));
  $('modulePills').innerHTML = pills.map((key) =>
    `<span class="pill ${key === current.module ? 'on' : ''}" data-module="${key}">${MODULE_NAMES[key] || key}</span>`
  ).join('');
  $('modulePills').querySelectorAll('.pill').forEach((pill) => {
    pill.onclick = () => { current.module = pill.dataset.module; renderPreviewFields(); };
  });

  renderPreviewFields();
  $('previewWarnings').innerHTML = (parsed.warnings || [])
    .map((w) => `<div class="warn">· ${w}</div>`).join('');
}

function renderPreviewFields() {
  $('modulePills').querySelectorAll('.pill').forEach((pill) => {
    pill.classList.toggle('on', pill.dataset.module === current.module);
  });
  const entries = Object.entries(current.preview)
    .filter(([key]) => !HIDDEN_FIELDS.has(key));
  $('previewFields').innerHTML = entries.map(([key, value]) => `
    <div class="field">
      <label>${FIELD_LABELS[key] || key}</label>
      <input data-key="${key}" value="${value === null || value === undefined ? '' : String(value)}">
    </div>`).join('');
  $('previewFields').querySelectorAll('input').forEach((input) => {
    input.oninput = () => {
      const raw = input.value.trim();
      const numeric = raw !== '' && !isNaN(Number(raw));
      current.preview[input.dataset.key] = raw === '' ? null : (numeric ? Number(raw) : raw);
    };
  });
}

const MODULE_NAMES = {
  finance: '账本', fitness: '健身', nutrition: '饮食',
  recovery: '睡眠', study: '学习', rhythm: '待办',
};

async function doParse() {
  const text = $('quickText').value.trim();
  if (!text) return;
  if (!navigator.onLine) {
    showBanner('离线时无法解析，请联网后再记，或到电脑上补录', 'offline');
    return;
  }
  $('parseBtn').disabled = true;
  try {
    const parsed = await api('/api/quick/parse', { method: 'POST', body: JSON.stringify({ text }) });
    if (!parsed.matched) {
      showBanner(parsed.reason || '认不出这句话', 'offline');
      $('preview').classList.add('hidden');
      return;
    }
    renderPreview(parsed);
  } catch (error) {
    showBanner(error.message, 'offline');
  } finally {
    $('parseBtn').disabled = false;
  }
}

async function doCommit() {
  if (!current) return;
  const payload = { module: current.module, payload: current.preview };
  if (!navigator.onLine) {
    enqueue({ path: '/api/quick/commit', body: payload });
    showBanner('离线，已存进手机队列，联网后自动补发', 'offline');
    resetForm();
    return;
  }
  $('commitBtn').disabled = true;
  try {
    await api('/api/quick/commit', { method: 'POST', body: JSON.stringify(payload) });
    showBanner('已记下', 'ok');
    resetForm();
    refresh();
  } catch (error) {
    enqueue({ path: '/api/quick/commit', body: payload });
    showBanner('写入失败，已存进队列稍后重试：' + error.message, 'offline');
    resetForm();
  } finally {
    $('commitBtn').disabled = false;
  }
}

function resetForm() {
  current = null;
  $('quickText').value = '';
  $('preview').classList.add('hidden');
}

async function loadCaptures() {
  try {
    const state = await api('/api/capture');
    const pending = state.pending || [];
    if (!pending.length) {
      $('captureList').innerHTML =
        '<div class="muted">没有待确认的捕获。<br>这只说明监听通道当前没抓到东西，不代表没有消费。</div>';
      return;
    }
    $('captureList').innerHTML = pending.map((item) => `
      <div class="cap">
        <div class="amt">¥${item.amount}</div>
        <div class="muted">${item.merchant || item.raw_text}</div>
        <div class="muted">${(item.channel_labels || []).join(' + ')} · ${item.occurred_on}</div>
        <div class="row">
          <button data-confirm="${item.id}">确认记账</button>
          <button class="ghost" data-dismiss="${item.id}">忽略</button>
        </div>
      </div>`).join('');
    $('captureList').querySelectorAll('[data-confirm]').forEach((button) => {
      button.onclick = () => resolveCapture(button.dataset.confirm, 'confirm');
    });
    $('captureList').querySelectorAll('[data-dismiss]').forEach((button) => {
      button.onclick = () => resolveCapture(button.dataset.dismiss, 'dismiss');
    });
  } catch (error) {
    $('captureList').innerHTML = `<div class="warn">${error.message}</div>`;
  }
}

async function resolveCapture(id, action) {
  const path = `/api/capture/${id}/${action}`;
  const body = action === 'confirm' ? { category: 'other' } : {};
  if (!navigator.onLine) {
    enqueue({ path, body });
    showBanner('离线，操作已排队', 'offline');
    return;
  }
  try {
    await api(path, { method: 'POST', body: JSON.stringify(body) });
    refresh();
  } catch (error) {
    showBanner(error.message, 'offline');
  }
}

async function loadToday() {
  try {
    const life = await api('/api/life/overview');
    const pick = (path, fallback = 0) =>
      path.split('.').reduce((node, key) => (node == null ? null : node[key]), life) ?? fallback;
    const rows = [
      ['今日支出', `¥${pick('finance.today_expense')}`],
      ['运动', `${pick('fitness.today.minutes')} 分钟`],
      ['饮食记录', `${pick('nutrition.today.count')} 条`],
      ['学习', `${pick('study.today.minutes')} 分钟`],
      ['待办未完成', `${pick('rhythm.task_summary.today_pending')} 条`],
      ['逾期待办', `${pick('rhythm.task_summary.overdue')} 条`],
    ];
    $('todayList').innerHTML = rows.map(([k, v]) =>
      `<div class="stat"><span class="muted">${k}</span><span>${v}</span></div>`).join('');
  } catch (error) {
    $('todayList').innerHTML = `<div class="warn">${error.message}</div>`;
  }
}

/* 不拿有没有 token 当前提：本机打开时服务端本来就放行，
 * 真的没权限会从 401 里得到一句人话，比永远停在「加载中…」强。 */
function refresh() {
  renderConnection();
  if (!navigator.onLine) {
    $('captureList').innerHTML = '<div class="muted">离线中，无法读取待确认捕获</div>';
    $('todayList').innerHTML = '<div class="muted">离线中，无法读取今日汇总</div>';
    return;
  }
  loadCaptures();
  loadToday();
}

// ---------- 启动 ----------
$('parseBtn').onclick = doParse;
$('commitBtn').onclick = doCommit;
$('cancelBtn').onclick = resetForm;
$('syncBtn').onclick = flushQueue;
window.addEventListener('online', () => { renderConnection(); flushQueue(); });
window.addEventListener('offline', renderConnection);

if (!token) {
  $('subtitle').textContent = '还没配对：请在电脑上打开配对页面，用带 token 的地址进入';
}
refresh();
flushQueue();

if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('./sw.js').catch(() => { /* 离线外壳不可用不影响记录 */ });
}
