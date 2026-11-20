const $ = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const formatTime = (value) => String(value || '').slice(5, 16);
const money = (value) => `¥${Number(value || 0).toLocaleString('zh-CN')}`;
let csrfToken = '';
let currentPlan = null;
let pendingProposal = null;

async function getJson(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`请求失败：${response.status}`);
  return response.json();
}

async function postJson(path, body) {
  if (!csrfToken) csrfToken = (await getJson('/api/session')).csrf_token;
  const response = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json', 'X-CSRF-Token':csrfToken}, body:JSON.stringify(body)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || `请求失败：${response.status}`);
  return result;
}

function bookingOptions(plan) {
  currentPlan = plan;
  pendingProposal = null;
  $('confirm-booking').hidden = true;
  const projects = plan.projects || [];
  $('booking-project').innerHTML = projects.map((p) => `<option value="${escapeHtml(p.code)}">${escapeHtml(p.name)}</option>`).join('');
  updateBookingAssets();
}

function updateBookingAssets() {
  pendingProposal = null;
  $('confirm-booking').hidden = true;
  const project = (currentPlan?.projects || []).find((p) => p.code === $('booking-project').value);
  const assets = (project?.requirements || []).flatMap((r) => r.assignments.map((a) => ({...a, model_name:r.model_name})));
  $('booking-asset').innerHTML = assets.map((a) => `<option value="${escapeHtml(a.asset_code)}">${escapeHtml(a.asset_code)} · ${escapeHtml(a.model_name)} · ${escapeHtml(a.warehouse)}</option>`).join('');
  $('booking-preview').textContent = assets.length ? '选择设备后点击“预览预订”。' : '这个项目目前没有可预订的自有设备。';
  $('preview-booking').disabled = !assets.length;
}

function appendMessage(text, kind, sources=[]) {
  const box = document.createElement('div');
  box.className = `message ${kind}`;
  box.textContent = text;
  if (sources.length) {
    const source = document.createElement('span');
    source.className = 'sources';
    source.textContent = `数据来源：${sources.join(' · ')}`;
    box.appendChild(source);
  }
  $('conversation').appendChild(box);
  $('conversation').scrollTop = $('conversation').scrollHeight;
}

function renderPlan(plan) {
  bookingOptions(plan);
  const projects = plan.projects || [];
  $('plan-content').innerHTML = `
    <div class="plan-summary">
      <div><span>待确认项目</span><strong>${projects.length}</strong></div>
      <div><span>跨仓调拨</span><strong>${plan.transfer_units || 0}</strong></div>
      <div><span>外租缺口</span><strong>${plan.external_units || 0}</strong></div>
    </div>
    <div class="plan-list">${projects.map((project) => {
      const needs = project.requirements.filter((item) => item.external_needed > 0).map((item) => `${escapeHtml(item.model_name)} × ${item.external_needed}`);
      return `<div class="plan-item"><div class="plan-item-head"><div><h3>${escapeHtml(project.name)}</h3><small>${escapeHtml(project.code)}</small></div><span class="status ${project.external_units ? 'warn' : 'good'}">${escapeHtml(project.status)}</span></div><p>${needs.length ? `待外租：${needs.join('、')}` : '自有设备可覆盖全部需求'}<br>跨仓 ${project.transfer_units} 件 · 替代 ${project.substitute_units} 件 · 增量成本 ${money(project.estimated_extra_cost)}</p></div>`;
    }).join('')}</div>
    <p class="muted" style="margin-top:16px">合计估算增量成本 ${money(plan.estimated_extra_cost)}。外租需人工确认。</p>`;
}

async function refreshPlan() {
  $('plan-content').innerHTML = '<div class="loading">正在核算项目…</div>';
  try { renderPlan(await getJson('/api/plan?city=%E4%B8%8A%E6%B5%B7')); }
  catch (error) { $('plan-content').textContent = error.message; }
}

async function ask(question) {
  appendMessage(question, 'user');
  $('question').value = '';
  $('ask-button').disabled = true;
  try {
    const result = await postJson('/api/ask', {question});
    appendMessage(result.answer, 'assistant', result.sources || []);
    if (result.intent === 'project_plan') renderPlan(result.data);
  } catch (error) { appendMessage(`暂时无法回答：${error.message}`, 'assistant'); }
  finally { $('ask-button').disabled = false; $('question').focus(); }
}

async function loadDashboard() {
  try {
    const [overview, projects, inventory] = await Promise.all([
      getJson('/api/overview'), getJson('/api/projects'), getJson('/api/inventory')
    ]);
    $('connection').textContent = '数据库已连接';
    $('demo-day').textContent = overview.day;
    $('stat-projects').textContent = overview.draft_projects;
    $('stat-assets').textContent = overview.assets;
    $('stat-warehouses').textContent = overview.warehouses;
    $('stat-maintenance').textContent = overview.maintenance_assets;
    $('project-rows').innerHTML = projects.map((project) => `<tr><td><span class="project-name">${escapeHtml(project.name)}</span><span class="project-code">${escapeHtml(project.code)}</span></td><td>${escapeHtml(project.city)} · ${escapeHtml(project.venue)}</td><td>${formatTime(project.starts_at)} — ${formatTime(project.ends_at)}</td><td>${project.required_units} 件</td><td><span class="status ${project.status === 'confirmed' ? 'good' : 'warn'}">${project.status === 'confirmed' ? '已确认' : '待确认'}</span></td></tr>`).join('');
    $('inventory-rows').innerHTML = inventory.map((item) => `<tr><td><span class="project-name">${escapeHtml(item.name)}</span><span class="project-code">${escapeHtml(item.code)}</span></td><td>${escapeHtml(item.category)}</td><td>${escapeHtml(item.warehouse)}</td><td>${item.total}</td><td class="number-available">${item.available}</td></tr>`).join('');
  } catch (error) { $('connection').textContent = `连接失败：${error.message}`; }
  await refreshPlan();
}

const examples = [
  '下周六上海的三个活动能同时交付吗？',
  '浦东科技峰会缺什么设备？',
  '上海仓的 LED-P3 还有多少可用？',
  '哪些设备正在维修？'
];
for (const example of examples) {
  const button = document.createElement('button');
  button.type = 'button'; button.textContent = example;
  button.addEventListener('click', () => ask(example));
  $('suggestions').appendChild(button);
}
$('ask-form').addEventListener('submit', (event) => { event.preventDefault(); const text = $('question').value.trim(); if (text) ask(text); });
$('refresh-plan').addEventListener('click', refreshPlan);
$('booking-project').addEventListener('change', updateBookingAssets);
$('booking-asset').addEventListener('change', () => { pendingProposal = null; $('confirm-booking').hidden = true; $('booking-preview').textContent = '选择设备后点击“预览预订”。'; });
$('preview-booking').addEventListener('click', async () => {
  $('preview-booking').disabled = true;
  try {
    pendingProposal = await postJson('/api/booking-proposals', {project_code:$('booking-project').value, asset_code:$('booking-asset').value});
    $('booking-preview').textContent = `${pendingProposal.project_name} · ${pendingProposal.asset_code} · ${pendingProposal.warehouse}\n占用：${pendingProposal.window_start} 至 ${pendingProposal.window_end}\n方案 10 分钟内有效。确认后写入数据库。`;
    $('confirm-booking').hidden = false;
  } catch (error) { await refreshPlan(); $('booking-preview').textContent = error.message; }
  finally { $('preview-booking').disabled = false; }
});
$('confirm-booking').addEventListener('click', async () => {
  if (!pendingProposal) return;
  $('confirm-booking').disabled = true;
  try {
    const result = await postJson('/api/bookings/confirm', {token:pendingProposal.token});
    pendingProposal = null;
    $('confirm-booking').hidden = true;
    await loadDashboard();
    $('booking-preview').textContent = `预订已写入数据库，编号 ${result.reservation_id}。`;
  } catch (error) { pendingProposal = null; $('confirm-booking').hidden = true; await refreshPlan(); $('booking-preview').textContent = error.message; }
  finally { $('confirm-booking').disabled = false; }
});
loadDashboard();
