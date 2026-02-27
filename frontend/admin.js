/* ─────────────────────────────────────────────────────────────────────────
   ZTracky Admin Panel — JavaScript
   Handles: stats · user management · MetaMask crypto wallet ·
            WebAuthn biometric 2FA · Stripe Connect bank payouts
   ───────────────────────────────────────────────────────────────────────── */

const API = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
  ? 'http://localhost:8000' : `${location.protocol}//${location.hostname}:8000`;

let adminKey = '';
let transferTokens = {};   // 'eth'|'erc20'|'bank' → transfer_token
let walletAddress  = null;
let currentTab     = 'overview';

// ── Login ──────────────────────────────────────────────────────────────────
async function adminLogin() {
  adminKey = document.getElementById('admin-key-input').value.trim();
  const res = await aGet('/api/admin/stats');
  if (res.error) {
    document.getElementById('admin-login-error').textContent = res.error;
    document.getElementById('admin-login-error').style.display = '';
    return;
  }
  document.getElementById('admin-login').style.display = 'none';
  document.getElementById('admin-dashboard').style.display = '';
  renderStats(res);
  loadUsers();
  checkBankStatus();
}

function adminLogout() {
  adminKey = '';
  document.getElementById('admin-dashboard').style.display = 'none';
  document.getElementById('admin-login').style.display = '';
  document.getElementById('admin-key-input').value = '';
}

function adminTab(name) {
  ['overview','users','reports','wallet','bank'].forEach(t => {
    document.getElementById(`atab-${t}`).style.display = t === name ? '' : 'none';
  });
  document.querySelectorAll('.tab-btn').forEach((b, i) => {
    b.classList.toggle('active', ['overview','users','reports','wallet','bank'][i] === name);
  });
  currentTab = name;
  if (name === 'overview') loadStats();
  if (name === 'users')    loadUsers();
  if (name === 'reports')  loadBugReports();
  if (name === 'wallet')   { loadWalletHistory(); refreshBalances(); }
  if (name === 'bank')     checkBankStatus();
}

// ── Stats ──────────────────────────────────────────────────────────────────
async function loadStats() {
  const res = await aGet('/api/admin/stats');
  if (!res.error) renderStats(res);
  // Also load bug report stats
  const bugStats = await aGet('/api/admin/bug-reports/stats');
  if (!bugStats.error) renderBugStats(bugStats);
}

function renderStats(d) {
  document.getElementById('s-total').textContent   = d.total_users   ?? '–';
  document.getElementById('s-online').textContent  = d.online_count  ?? '–';
  document.getElementById('s-premium').textContent = d.premium_users ?? '–';
  document.getElementById('s-revenue').textContent = d.revenue_usd != null ? `$${d.revenue_usd.toFixed(2)}` : '–';
}

function renderBugStats(d) {
  const bugsEl = document.getElementById('s-bugs');
  const featuresEl = document.getElementById('s-features');
  const openEl = document.getElementById('s-open-reports');
  if (bugsEl) bugsEl.textContent = d.bugs ?? '–';
  if (featuresEl) featuresEl.textContent = d.features ?? '–';
  if (openEl) openEl.textContent = d.open ?? '–';
}

// ── Users ──────────────────────────────────────────────────────────────────
async function loadUsers() {
  const users = await aGet('/api/admin/users');
  if (users.error) return;
  const tbody = document.getElementById('users-tbody');
  tbody.innerHTML = users.map(u => `
    <tr>
      <td>${u.id}</td>
      <td><strong>${u.username}</strong></td>
      <td>${u.email}</td>
      <td>${u.phone_number || '–'}</td>
      <td>${u.is_premium ? '<span class="badge badge-accepted">Premium</span>' : '<span class="badge badge-pending">Free</span>'}</td>
      <td><small>${new Date(u.created_at).toLocaleDateString()}</small></td>
      <td>
        ${u.is_premium
          ? `<button class="rc-btn rc-btn-lock" onclick="downgrade(${u.id})">Downgrade</button>`
          : `<button class="rc-btn rc-btn-view" onclick="upgrade(${u.id})">Upgrade</button>`}
      </td>
    </tr>`).join('');
}

async function upgrade(id) {
  await aPost(`/api/admin/users/${id}/upgrade`, null);
  loadUsers(); loadStats();
}
async function downgrade(id) {
  await aPost(`/api/admin/users/${id}/downgrade`, null);
  loadUsers(); loadStats();
}

// ── MetaMask Wallet ────────────────────────────────────────────────────────
async function connectMetaMask() {
  if (!window.ethereum) { alert('MetaMask not installed.'); return; }
  const accounts = await window.ethereum.request({ method: 'eth_requestAccounts' });
  walletAddress = accounts[0];
  document.getElementById('wallet-addr').textContent = `${walletAddress.slice(0,6)}…${walletAddress.slice(-4)}`;
  refreshBalances();
}

async function switchNetwork() {
  if (!window.ethereum) return;
  const chainId = document.getElementById('wallet-network').value;
  try {
    await window.ethereum.request({ method: 'wallet_switchEthereumChain', params: [{ chainId }] });
  } catch (e) {
    console.warn('Chain switch failed:', e.message);
  }
  refreshBalances();
}

async function refreshBalances() {
  if (!window.ethereum || !walletAddress) return;
  const wei = await window.ethereum.request({ method: 'eth_getBalance', params: [walletAddress, 'latest'] });
  const eth = (parseInt(wei, 16) / 1e18).toFixed(6);
  document.getElementById('wallet-bal').textContent = `${eth} ETH`;
  document.getElementById('contract-bal').textContent = 'N/A (no contract deployed)';
}

// ── WebAuthn Biometric 2FA ─────────────────────────────────────────────────
async function registerBiometric() {
  const msgEl = document.getElementById('biometric-reg-msg');
  try {
    const opts = await aGet('/api/admin/webauthn/register-options');
    if (opts.error) throw new Error(opts.error);

    // Decode base64url challenge
    const challenge = base64urlToBuffer(opts.challenge);
    const userId    = base64urlToBuffer(opts.user.id);

    const credential = await navigator.credentials.create({
      publicKey: {
        ...opts,
        challenge,
        user: { ...opts.user, id: userId },
        pubKeyCredParams: opts.pubKeyCredParams || [
          { type: 'public-key', alg: -7 },
          { type: 'public-key', alg: -257 },
        ],
      },
    });

    const body = credentialToJSON(credential);
    const res  = await aPost('/api/admin/webauthn/register-verify', { credential: body });
    if (res.error) throw new Error(res.error);
    msgEl.textContent = '✅ Biometric registered successfully!';
    msgEl.className   = 'message success';
    msgEl.style.display = '';
  } catch (e) {
    msgEl.textContent = `❌ ${e.message}`;
    msgEl.className   = 'message error';
    msgEl.style.display = '';
  }
}

async function startBiometricAuth(purpose) {
  const statusEl = document.getElementById(`bio-status-${purpose}`);
  const btnEl    = document.getElementById(`btn-send-${purpose === 'eth' ? 'eth' : purpose === 'erc20' ? 'erc20' : 'payout'}`);
  statusEl.textContent = '⏳ Authenticating…';

  try {
    const opts = await aGet('/api/admin/webauthn/auth-options');
    if (opts.error) throw new Error(opts.error);

    const challenge = base64urlToBuffer(opts.challenge);
    const allowCreds = (opts.allowCredentials || []).map(c => ({
      ...c, id: base64urlToBuffer(c.id),
    }));

    const assertion = await navigator.credentials.get({
      publicKey: { ...opts, challenge, allowCredentials: allowCreds },
    });

    const body = assertionToJSON(assertion);
    const res  = await aPost('/api/admin/webauthn/auth-verify', { credential: body });
    if (res.error) throw new Error(res.error);

    transferTokens[purpose] = res.transfer_token;
    statusEl.textContent = `✅ Authenticated (valid 60 s)`;
    if (btnEl) btnEl.disabled = false;

    // Auto-expire after 60 s
    setTimeout(() => {
      delete transferTokens[purpose];
      statusEl.textContent = 'Expired — re-authenticate';
      if (btnEl) btnEl.disabled = true;
    }, 60_000);
  } catch (e) {
    statusEl.textContent = `❌ ${e.message}`;
  }
}

// ── Send ETH ───────────────────────────────────────────────────────────────
async function sendETH() {
  if (!walletAddress) { alert('Connect MetaMask first'); return; }
  const to     = document.getElementById('send-to').value.trim();
  const amount = parseFloat(document.getElementById('send-amount').value);
  const note   = document.getElementById('send-note').value.trim();
  if (!to || !amount) { alert('Fill in recipient and amount'); return; }

  const amountWei = BigInt(Math.floor(amount * 1e18));
  const amountHex = '0x' + amountWei.toString(16);
  try {
    const txHash = await window.ethereum.request({
      method: 'eth_sendTransaction',
      params: [{ from: walletAddress, to, value: amountHex, gas: '0x5208' }],
    });
    // Record on server (audit log — requires biometric transfer token)
    await aPostWithToken('/api/admin/wallet/send-crypto', transferTokens['eth'],
      { recipient: to, amount_wei: Number(amountWei), network: getSelectedNetwork(), tx_hash: txHash });
    delete transferTokens['eth'];
    document.getElementById('btn-send-eth').disabled = true;
    document.getElementById('bio-status-eth').textContent = 'Not authenticated';
    alert(`✅ Transaction sent!\nTx hash: ${txHash}`);
    loadWalletHistory();
  } catch (e) {
    alert(`❌ ${e.message}`);
  }
}

// ── Send ERC-20 ────────────────────────────────────────────────────────────
async function sendERC20() {
  if (!walletAddress) { alert('Connect MetaMask first'); return; }
  const token  = document.getElementById('erc20-token').value.trim();
  const to     = document.getElementById('erc20-to').value.trim();
  const amount = document.getElementById('erc20-amount').value;
  if (!token || !to || !amount) { alert('Fill in all ERC-20 fields'); return; }

  // ABI-encode transfer(address,uint256)
  const paddedTo     = to.replace('0x', '').padStart(64, '0');
  const paddedAmount = BigInt(amount).toString(16).padStart(64, '0');
  const data = `0xa9059cbb${paddedTo}${paddedAmount}`;

  try {
    const txHash = await window.ethereum.request({
      method: 'eth_sendTransaction',
      params: [{ from: walletAddress, to: token, data }],
    });
    await aPostWithToken('/api/admin/wallet/send-crypto', transferTokens['erc20'],
      { recipient: to, amount_wei: parseInt(amount), network: getSelectedNetwork(), tx_hash: txHash });
    delete transferTokens['erc20'];
    document.getElementById('btn-send-erc20').disabled = true;
    document.getElementById('bio-status-erc20').textContent = 'Not authenticated';
    alert(`✅ ERC-20 transfer sent!\nTx: ${txHash}`);
    loadWalletHistory();
  } catch (e) {
    alert(`❌ ${e.message}`);
  }
}

function getSelectedNetwork() {
  const sel = document.getElementById('wallet-network');
  return sel.options[sel.selectedIndex].text;
}

async function loadWalletHistory() {
  const data = await aGet('/api/admin/wallet/history');
  if (data.error) return;
  const el = document.getElementById('tx-history');
  if (!data.length) { el.innerHTML = '<p class="empty">No transactions yet</p>'; return; }
  el.innerHTML = `<table class="admin-table"><thead><tr>
    <th>Type</th><th>Recipient</th><th>Amount</th><th>Network</th><th>Tx Hash</th><th>Status</th><th>Date</th>
  </tr></thead><tbody>${data.map(t => `<tr>
    <td>${t.tx_type}</td>
    <td><small>${t.recipient.slice(0,10)}…</small></td>
    <td>${t.tx_type === 'stripe_payout' ? `$${(t.amount_wei_or_cents/100).toFixed(2)}` : `${(t.amount_wei_or_cents/1e18).toFixed(6)} ETH`}</td>
    <td>${t.network || '–'}</td>
    <td>${t.tx_hash ? `<a href="https://etherscan.io/tx/${t.tx_hash}" target="_blank" rel="noopener">View ↗</a>` : '–'}</td>
    <td><span class="badge badge-${t.status === 'confirmed' ? 'accepted' : 'pending'}">${t.status}</span></td>
    <td><small>${new Date(t.created_at).toLocaleString()}</small></td>
  </tr>`).join('')}</tbody></table>`;
}

// ── Stripe Connect Bank ────────────────────────────────────────────────────
async function checkBankStatus() {
  const res = await aGet('/api/admin/stripe/status');
  const icon  = document.getElementById('bank-status-icon');
  const label = document.getElementById('bank-status-label');
  const detail = document.getElementById('bank-status-detail');
  if (res.connected && res.payouts_enabled) {
    icon.textContent  = '✅';
    label.textContent = 'Bank account linked & payouts enabled';
    detail.textContent = `Stripe ID: ${res.stripe_account_id}`;
  } else if (res.connected) {
    icon.textContent  = '⏳';
    label.textContent = 'Stripe account connected — finish verification';
    detail.textContent = `Stripe ID: ${res.stripe_account_id}`;
  } else {
    icon.textContent  = '🏦';
    label.textContent = 'Bank account not linked';
    detail.textContent = 'Connect via Stripe to receive bank payouts';
  }
}

async function connectBank() {
  const res = await aPost('/api/admin/stripe/connect', null);
  if (res.error) { alert(res.error); return; }
  window.open(res.onboarding_url, '_blank');
}

async function sendPayout() {
  const amount = parseInt(document.getElementById('payout-amount').value);
  const dest   = document.getElementById('payout-dest').value.trim();
  if (!amount || !dest) { alert('Fill in amount and destination account'); return; }

  const res = await aPostWithToken('/api/admin/stripe/payout', transferTokens['bank'],
    { amount_cents: amount, destination: dest });
  if (res.error) { alert(res.error); return; }
  delete transferTokens['bank'];
  document.getElementById('btn-send-payout').disabled = true;
  document.getElementById('bio-status-bank').textContent = 'Not authenticated';
  alert(`✅ Payout initiated!\nStatus: ${res.status}`);
  loadStats();
}

// ── API helpers ────────────────────────────────────────────────────────────
async function aGet(path) {
  try {
    const res = await fetch(`${API}${path}`, { headers: { 'X-Admin-Key': adminKey } });
    const data = await res.json();
    return res.ok ? data : { error: data.detail || 'Error' };
  } catch (e) { return { error: e.message }; }
}
async function aPost(path, body) {
  try {
    const opts = { method: 'POST', headers: { 'X-Admin-Key': adminKey } };
    if (body !== null) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
    const res  = await fetch(`${API}${path}`, opts);
    const data = await res.json();
    return res.ok ? data : { error: data.detail || 'Error' };
  } catch (e) { return { error: e.message }; }
}
async function aPostWithToken(path, transferToken, body) {
  try {
    const res  = await fetch(`${API}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Admin-Key': adminKey, 'X-Transfer-Token': transferToken || '' },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    return res.ok ? data : { error: data.detail || 'Error' };
  } catch (e) { return { error: e.message }; }
}

// ── WebAuthn encoding helpers ──────────────────────────────────────────────
function base64urlToBuffer(b64) {
  const padded = b64.replace(/-/g, '+').replace(/_/g, '/') + '=='.slice(0, (4 - b64.length % 4) % 4);
  return Uint8Array.from(atob(padded), c => c.charCodeAt(0)).buffer;
}
function bufferToBase64url(buf) {
  return btoa(String.fromCharCode(...new Uint8Array(buf))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '');
}
function credentialToJSON(cred) {
  return {
    id: cred.id, type: cred.type,
    rawId: bufferToBase64url(cred.rawId),
    response: {
      clientDataJSON:    bufferToBase64url(cred.response.clientDataJSON),
      attestationObject: bufferToBase64url(cred.response.attestationObject),
    },
  };
}
function assertionToJSON(assertion) {
  return {
    id: assertion.id, type: assertion.type,
    rawId: bufferToBase64url(assertion.rawId),
    response: {
      clientDataJSON:    bufferToBase64url(assertion.response.clientDataJSON),
      authenticatorData: bufferToBase64url(assertion.response.authenticatorData),
      signature:         bufferToBase64url(assertion.response.signature),
      userHandle: assertion.response.userHandle ? bufferToBase64url(assertion.response.userHandle) : null,
    },
  };
}

// ── Bug Reports ────────────────────────────────────────────────────────────
let currentAdminReportId = null;
let currentReportUserId = null;

async function loadBugReports() {
  const filter = document.getElementById('reports-filter')?.value || '';
  const url = filter ? `/api/admin/bug-reports?status=${filter}` : '/api/admin/bug-reports';
  const reports = await aGet(url);
  if (reports.error) return;

  const tbody = document.getElementById('reports-tbody');
  if (!reports.length) {
    tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;padding:20px;color:var(--text-muted)">No reports found</td></tr>';
    return;
  }

  tbody.innerHTML = reports.map(r => `
    <tr>
      <td>${r.id}</td>
      <td><span class="badge ${r.report_type === 'bug' ? 'badge-rejected' : 'badge-accepted'}">${r.report_type === 'bug' ? '🐛 Bug' : '✨ Feature'}</span></td>
      <td><strong>${escapeHtml(r.title)}</strong></td>
      <td>${escapeHtml(r.username)}</td>
      <td><span class="badge badge-${r.status === 'resolved' ? 'accepted' : r.status === 'closed' ? 'rejected' : 'pending'}">${r.status}</span></td>
      <td>${r.reply_count || 0}</td>
      <td><small>${new Date(r.created_at).toLocaleDateString()}</small></td>
      <td>
        <button class="rc-btn rc-btn-view" onclick="openAdminReportModal(${r.id})">View</button>
      </td>
    </tr>
  `).join('');
}

async function openAdminReportModal(reportId) {
  currentAdminReportId = reportId;
  const res = await aGet(`/api/admin/bug-reports/${reportId}`);
  if (res.error) { alert(res.error); return; }

  currentReportUserId = res.user_id;

  document.getElementById('admin-modal-type').textContent = res.report_type === 'bug' ? '🐛 Bug' : '✨ Feature';
  document.getElementById('admin-modal-type').className = `badge ${res.report_type === 'bug' ? 'badge-rejected' : 'badge-accepted'}`;
  document.getElementById('admin-modal-title').textContent = res.title;
  document.getElementById('admin-modal-desc').textContent = res.description;
  document.getElementById('admin-modal-user').textContent = res.username;
  document.getElementById('admin-modal-status').textContent = res.status;
  document.getElementById('admin-modal-status').className = `badge badge-${res.status === 'resolved' ? 'accepted' : res.status === 'closed' ? 'rejected' : 'pending'}`;
  document.getElementById('admin-modal-date').textContent = new Date(res.created_at).toLocaleString();

  const repliesEl = document.getElementById('admin-modal-replies');
  if (!res.replies || !res.replies.length) {
    repliesEl.innerHTML = '<p class="empty" style="color:var(--text-muted);font-size:.9rem">No conversation yet. Send a reply to help the user!</p>';
  } else {
    repliesEl.innerHTML = res.replies.map(reply => `
      <div class="bug-reply ${reply.is_admin_reply ? 'admin-reply' : 'user-reply'}">
        <div class="bug-reply-header">
          <strong>${reply.is_admin_reply ? '🛡 Admin' : '👤 ' + escapeHtml(reply.username)}</strong>
          <small>${new Date(reply.created_at).toLocaleString()}</small>
        </div>
        <div class="bug-reply-content">${escapeHtml(reply.content)}</div>
      </div>
    `).join('');
  }

  document.getElementById('admin-reply-input').value = '';
  document.getElementById('admin-report-modal').style.display = '';
}

function closeAdminReportModal() {
  document.getElementById('admin-report-modal').style.display = 'none';
  currentAdminReportId = null;
  currentReportUserId = null;
}

async function sendAdminReply() {
  if (!currentAdminReportId) return;
  const content = document.getElementById('admin-reply-input').value.trim();
  if (!content) return;

  const res = await aPost(`/api/admin/bug-reports/${currentAdminReportId}/reply`, { content });
  if (res.error) { alert(res.error); return; }

  document.getElementById('admin-reply-input').value = '';
  openAdminReportModal(currentAdminReportId);  // Refresh
}

async function updateReportStatus(newStatus) {
  if (!currentAdminReportId) return;
  const res = await aPost(`/api/admin/bug-reports/${currentAdminReportId}/status?new_status=${newStatus}`, null);
  if (res.error) { alert(res.error); return; }
  openAdminReportModal(currentAdminReportId);  // Refresh
  loadBugReports();  // Refresh list
}

async function grantPremiumToReporter() {
  if (!currentReportUserId) return;
  if (!confirm('Grant free premium access to this user?')) return;
  const res = await aPost(`/api/admin/users/${currentReportUserId}/grant-free-premium`, { reason: 'Awarded for helpful bug report' });
  if (res.error) { alert(res.error); return; }
  alert('✅ Premium access granted!');
}

function escapeHtml(text) {
  if (!text) return '';
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}
