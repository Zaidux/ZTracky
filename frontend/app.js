/* ──────────────────────────────────────────────────────────────────────────
   ZTracky – Frontend Application
   Languages: JavaScript (frontend) · Python FastAPI (REST) · Go WebSocket (realtime)
   ────────────────────────────────────────────────────────────────────────── */

const API_BASE = (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')
  ? 'http://localhost:8000'
  : `${window.location.protocol}//${window.location.hostname}:8000`;

const WS_BASE = (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')
  ? 'ws://localhost:8001'
  : `ws://${window.location.hostname}:8001`;

// ── Constants ──────────────────────────────────────────────────────────────
const REFRESH_INTERVAL_MS  = 30_000;
const SETTINGS_KEY         = 'ztracky_settings';
const REMOTE_PERMS_KEY     = 'ztracky_remote_perms';
const STUN_CONFIG          = { iceServers: [{ urls: 'stun:stun.l.google.com:19302' }] };

const INTERVAL_VALUES    = [10, 20, 30, 60, 120, 300, 600, 900];
const THRESHOLD_VALUES   = [0, 5, 10, 25, 50, 100];
const BG_THROTTLE_VALUES = [1, 2, 5, 10];

const DEFAULT_SETTINGS = { intervalIdx: 2, thresholdIdx: 2, accuracyMode: 'balanced', bgThrottleIdx: 2 };
const DEFAULT_REMOTE_PERMS = { allowScreenView: false, allowLock: false, allowStealth: false };

// ── App State ──────────────────────────────────────────────────────────────
let token       = localStorage.getItem('ztracky_token');
let currentUser = JSON.parse(localStorage.getItem('ztracky_user') || 'null');
let map         = null;
let myMarker    = null;
let friendMarkers = {};
let friendList    = [];      // full friend objects [{id, username, email}]
let friendIDs     = [];      // accepted friend user IDs
let ws          = null;
let watchId     = null;

// Smart-tracking state
let lastSentTime = 0;
let lastSentPos  = null;

// Remote control state
let peerConnections = {};    // userID → RTCPeerConnection
let wakeLock        = null;
let stealthActive   = false;
let stealthTapCount = 0;
let stealthTapTimer = null;
let stealthClockId  = null;
let lockActive      = false;
let lockTapCount    = 0;
let lockTapTimer    = null;
let onlineFriendIDs = new Set();

// ── Init ───────────────────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', () => { if (token && currentUser) showApp(); });

// ── Auth ───────────────────────────────────────────────────────────────────
function showRegister() {
  document.getElementById('login-form').style.display = 'none';
  document.getElementById('register-form').style.display = '';
  clearAuthError();
}
function showLogin() {
  document.getElementById('register-form').style.display = 'none';
  document.getElementById('login-form').style.display = '';
  clearAuthError();
}
function clearAuthError() {
  const el = document.getElementById('auth-error');
  el.style.display = 'none'; el.textContent = '';
}
function showAuthError(msg) {
  const el = document.getElementById('auth-error');
  el.textContent = msg; el.style.display = '';
}

async function register() {
  const username = document.getElementById('reg-username').value.trim();
  const email    = document.getElementById('reg-email').value.trim();
  const password = document.getElementById('reg-password').value;
  if (!username || !email || !password) { showAuthError('All fields are required.'); return; }
  const res = await apiPost('/api/register', { username, email, password });
  if (res.error) { showAuthError(res.error); return; }
  saveSession(res); showApp();
}

async function login() {
  const username = document.getElementById('login-username').value.trim();
  const password = document.getElementById('login-password').value;
  if (!username || !password) { showAuthError('Username and password are required.'); return; }
  const res = await apiPostForm('/api/login', new URLSearchParams({ username, password }));
  if (res.error) { showAuthError(res.error); return; }
  saveSession(res); showApp();
}

function saveSession(data) {
  token = data.access_token; currentUser = data.user;
  localStorage.setItem('ztracky_token', token);
  localStorage.setItem('ztracky_user', JSON.stringify(currentUser));
}

function logout() {
  stopTracking(); disconnectWS(); deactivateStealth(); deactivateLock();
  Object.values(peerConnections).forEach(pc => pc.close());
  peerConnections = {};
  token = null; currentUser = null;
  localStorage.removeItem('ztracky_token');
  localStorage.removeItem('ztracky_user');
  document.getElementById('app-section').style.display = 'none';
  document.getElementById('auth-section').style.display = '';
}

// ── App Shell ──────────────────────────────────────────────────────────────
function showApp() {
  document.getElementById('auth-section').style.display = 'none';
  document.getElementById('app-section').style.display = '';
  document.getElementById('nav-user').textContent = `👤 ${currentUser.username}`;

  initMap();
  loadRequests();
  loadFriends();
  startTracking();
  connectWS();
  seedSettingsUI();
  seedRemotePermsUI();
  listenVisibilityChange();

  setInterval(() => { loadFriends(); loadRequests(); }, REFRESH_INTERVAL_MS);
}

// ── Tabs (includes premium) ────────────────────────────────────────────────
function showTab(name) {
  const tabs = ['map', 'requests', 'friends', 'chat', 'calltrack', 'remote', 'premium', 'settings', 'feedback'];
  tabs.forEach(t => {
    document.getElementById(`tab-${t}`).style.display = t === name ? '' : 'none';
  });
  document.querySelectorAll('.tab-btn').forEach((btn, i) => {
    btn.classList.toggle('active', tabs[i] === name);
  });
  if (name === 'map'       && map) setTimeout(() => map.invalidateSize(), 100);
  if (name === 'remote')           refreshControlPage();
  if (name === 'premium')          refreshPremiumUI();
  if (name === 'chat')             initChatTab();
  if (name === 'calltrack')        initCallTrackTab();
  if (name === 'feedback')         initFeedbackTab();
  if (name === 'settings')         initSettingsApiKeys();
}

// ── Map ────────────────────────────────────────────────────────────────────
function initMap() {
  if (map) return;
  map = L.map('map').setView([0, 0], 2);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    maxZoom: 19,
  }).addTo(map);
}

function setMyMarker(lat, lng) {
  if (!map) return;
  if (myMarker) { myMarker.setLatLng([lat, lng]); return; }
  myMarker = L.marker([lat, lng], {
    icon: L.divIcon({ className: '', html: '<div style="font-size:28px">📍</div>', iconSize: [28, 28], iconAnchor: [14, 28] })
  }).addTo(map).bindPopup(`<b>You</b> (${currentUser.username})`);
  map.setView([lat, lng], 14);
}

function setFriendMarker(userID, username, lat, lng, accuracy) {
  if (!map) return;
  const popup = `<b>${username}</b><br>Accuracy: ${accuracy ? accuracy.toFixed(0) + 'm' : 'unknown'}`;
  if (friendMarkers[userID]) {
    friendMarkers[userID].setLatLng([lat, lng]).getPopup().setContent(popup);
  } else {
    friendMarkers[userID] = L.marker([lat, lng], {
      icon: L.divIcon({ className: '', html: '<div style="font-size:24px">👤</div>', iconSize: [24, 24], iconAnchor: [12, 24] })
    }).addTo(map).bindPopup(popup);
  }
}

// ── Geolocation ────────────────────────────────────────────────────────────
function geoOptions(mode) {
  switch (mode) {
    case 'high': return { enableHighAccuracy: true,  maximumAge: 0,     timeout: 15000 };
    case 'low':  return { enableHighAccuracy: false, maximumAge: 30000, timeout: 30000 };
    default:     return { enableHighAccuracy: false, maximumAge: 5000,  timeout: 10000 };
  }
}

function haversineMetres(lat1, lng1, lat2, lng2) {
  const R = 6371000, toRad = d => d * Math.PI / 180;
  const dLat = toRad(lat2 - lat1), dLng = toRad(lng2 - lng1);
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLng / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function shouldSendLocation(lat, lng) {
  const s = loadSettings();
  const effectiveMs  = INTERVAL_VALUES[s.intervalIdx] * 1000 * (document.hidden ? BG_THROTTLE_VALUES[s.bgThrottleIdx] : 1);
  const thresholdM   = THRESHOLD_VALUES[s.thresholdIdx];
  if (Date.now() - lastSentTime < effectiveMs) return false;
  if (thresholdM > 0 && lastSentPos) {
    if (haversineMetres(lastSentPos.lat, lastSentPos.lng, lat, lng) < thresholdM) return false;
  }
  return true;
}

function startTracking() {
  if (!navigator.geolocation) {
    document.getElementById('location-status').textContent = '❌ Geolocation not supported'; return;
  }
  const s = loadSettings();
  watchId = navigator.geolocation.watchPosition(pos => {
    const { latitude, longitude, accuracy } = pos.coords;
    setMyMarker(latitude, longitude);
    if (!shouldSendLocation(latitude, longitude)) return;
    lastSentTime = Date.now();
    lastSentPos  = { lat: latitude, lng: longitude };
    document.getElementById('location-status').textContent =
      `📡 ${latitude.toFixed(5)}, ${longitude.toFixed(5)} ±${accuracy ? accuracy.toFixed(0) + 'm' : '?'}${document.hidden ? ' (bg)' : ''}`;
    apiPost('/api/location', { latitude, longitude, accuracy }).catch(() => {});
    if (ws && ws.readyState === WebSocket.OPEN)
      ws.send(JSON.stringify({ type: 'location', latitude, longitude, accuracy, friends: friendIDs }));
  }, err => {
    document.getElementById('location-status').textContent = `❌ ${err.message}`;
  }, geoOptions(s.accuracyMode));
}

function stopTracking() {
  if (watchId !== null) { navigator.geolocation.clearWatch(watchId); watchId = null; }
}

function restartTracking() { stopTracking(); lastSentTime = 0; lastSentPos = null; startTracking(); }

function listenVisibilityChange() {
  document.addEventListener('visibilitychange', () => { if (!document.hidden) lastSentTime = 0; });
}

// ── WebSocket ──────────────────────────────────────────────────────────────
function connectWS() {
  if (!token) return;
  ws = new WebSocket(`${WS_BASE}/ws?token=${encodeURIComponent(token)}&username=${encodeURIComponent(currentUser.username)}`);
  ws.addEventListener('open', () => {
    setWSStatus('connected', '● Live');
    updateRCConnectionStatus(true);
    if (friendIDs.length) checkPresence();
  });
  ws.addEventListener('close', () => {
    setWSStatus('disconnected', '● Offline');
    updateRCConnectionStatus(false);
    setTimeout(() => { if (token) connectWS(); }, 5000);
  });
  ws.addEventListener('error', () => setWSStatus('disconnected', '● Error'));
  ws.addEventListener('message', e => {
    try { handleIncomingWS(JSON.parse(e.data)); } catch (_) {}
  });
}

function disconnectWS() { if (ws) { ws.close(); ws = null; } }

function setWSStatus(cls, text) {
  const el = document.getElementById('ws-status');
  el.className = `ws-indicator ${cls}`; el.textContent = text;
}

/** Central dispatcher for all incoming WebSocket messages. */
function handleIncomingWS(msg) {
  switch (msg.type) {
    case 'location':
      setFriendMarker(msg.user_id, msg.username, msg.latitude, msg.longitude, msg.accuracy);
      break;

    case 'presence_status':
      onlineFriendIDs = new Set(msg.online_ids || []);
      renderControlCards();
      break;

    case 'remote_command':
      handleRemoteCommand(msg);
      break;

    // WebRTC signalling
    case 'peer_offer':  handlePeerOffer(msg);  break;
    case 'peer_answer': handlePeerAnswer(msg); break;
    case 'peer_ice':    handlePeerICE(msg);    break;
  }
}

// ── Friend Requests ────────────────────────────────────────────────────────
async function sendRequest() {
  const username = document.getElementById('req-username').value.trim();
  if (!username) return;
  const msgEl = document.getElementById('req-message');
  const res = await apiPost(`/api/requests/send?username=${encodeURIComponent(username)}`, null);
  if (res.error) { showMessage(msgEl, res.error, 'error'); }
  else { showMessage(msgEl, `Request sent to ${username}!`, 'success'); document.getElementById('req-username').value = ''; loadRequests(); }
}

async function acceptRequest(id) { await apiPost(`/api/requests/${id}/accept`, null); loadRequests(); loadFriends(); }
async function rejectRequest(id) { await apiPost(`/api/requests/${id}/reject`, null); loadRequests(); }

async function loadRequests() {
  const data = await apiGet('/api/requests');
  if (data.error) return;
  renderRequests('incoming-requests', data.filter(r => r.receiver_id === currentUser.id && r.status === 'pending'), true);
  renderRequests('sent-requests', data.filter(r => r.sender_id === currentUser.id), false);
}

function renderRequests(containerId, reqs, canAct) {
  const el = document.getElementById(containerId);
  if (!reqs.length) { el.innerHTML = '<p class="empty">None</p>'; return; }
  el.innerHTML = reqs.map(r => {
    const other  = canAct ? r.sender_username : r.receiver_username;
    const badge  = `<span class="badge badge-${r.status}">${r.status}</span>`;
    const actions = canAct && r.status === 'pending'
      ? `<div class="actions"><button class="btn-accept" onclick="acceptRequest(${r.id})">Accept</button><button class="btn-reject" onclick="rejectRequest(${r.id})">Reject</button></div>`
      : badge;
    return `<div class="req-card"><div class="info"><strong>${other}</strong><small>${new Date(r.created_at).toLocaleString()}</small></div>${actions}</div>`;
  }).join('');
}

// ── Friends ────────────────────────────────────────────────────────────────
async function loadFriends() {
  const friends = await apiGet('/api/friends');
  if (friends.error) return;
  friendList = friends;
  friendIDs  = friends.map(f => f.id);

  const el = document.getElementById('friends-list');
  if (!friends.length) { el.innerHTML = '<p class="empty">No friends yet. Send a tracking request!</p>'; return; }
  el.innerHTML = friends.map(f => `
    <div class="friend-card">
      <div class="info"><strong>${f.username}</strong><small>${f.email}</small></div>
      <div style="display:flex;gap:6px">
        <button class="btn-locate" onclick="locateFriend(${f.id}, '${f.username}')">📍 Locate</button>
        <button class="btn-locate" style="background:var(--accent2,#8b5cf6)" onclick="navigateToFriend(${f.id}, '${f.username}')">🧭 Navigate</button>
      </div>
    </div>`).join('');

  const locs = await apiGet('/api/friends/locations');
  if (!locs.error) locs.forEach(l => setFriendMarker(l.user_id, l.username, l.latitude, l.longitude, l.accuracy));

  if (ws && ws.readyState === WebSocket.OPEN) checkPresence();
}

async function locateFriend(userId, username) {
  const loc = await apiGet(`/api/location/${userId}`);
  if (loc.error) { alert(`Location unavailable for ${username}`); return; }
  if (map) {
    map.setView([loc.latitude, loc.longitude], 16);
    setFriendMarker(loc.user_id, loc.username, loc.latitude, loc.longitude, loc.accuracy);
    showTab('map');
    if (friendMarkers[userId]) friendMarkers[userId].openPopup();
  }
}

// ── Remote Control ─────────────────────────────────────────────────────────
function loadRemotePerms() {
  try { return { ...DEFAULT_REMOTE_PERMS, ...JSON.parse(localStorage.getItem(REMOTE_PERMS_KEY)) }; }
  catch (_) { return { ...DEFAULT_REMOTE_PERMS }; }
}
function saveRemotePerms(p) { localStorage.setItem(REMOTE_PERMS_KEY, JSON.stringify(p)); }

function seedRemotePermsUI() {
  const p = loadRemotePerms();
  document.getElementById('perm-screen').checked  = p.allowScreenView;
  document.getElementById('perm-lock').checked    = p.allowLock;
  document.getElementById('perm-stealth').checked = p.allowStealth;
}

function togglePerm(key) {
  const p = loadRemotePerms();
  p[key] = !p[key];
  saveRemotePerms(p);
}

function updateRCConnectionStatus(online) {
  const dot   = document.getElementById('rc-ws-dot');
  const label = document.getElementById('rc-ws-label');
  if (!dot) return;
  dot.className   = `online-dot ${online ? 'online' : 'offline'}`;
  label.textContent = online ? 'Connected to real-time network' : 'Offline – reconnecting…';
}

/** Ask the Go hub which friends are currently connected. */
function checkPresence() {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  ws.send(JSON.stringify({ type: 'check_presence', friends: friendIDs }));
}

function refreshControlPage() {
  if (friendIDs.length) checkPresence();
  else renderControlCards();
}

function renderControlCards() {
  const el = document.getElementById('control-list');
  if (!el) return;
  if (!friendList.length) { el.innerHTML = '<p class="empty">No friends yet.</p>'; return; }

  el.innerHTML = friendList.map(f => {
    const online = onlineFriendIDs.has(f.id);
    return `
    <div class="control-card">
      <div class="control-info">
        <span class="online-dot ${online ? 'online' : 'offline'}"></span>
        <div>
          <strong>${f.username}</strong>
          <small>${online ? 'Online' : 'Offline'}</small>
        </div>
      </div>
      <div class="control-actions ${online ? '' : 'disabled'}">
        <button class="rc-btn rc-btn-view"    title="View Screen"  onclick="requestScreenView(${f.id}, '${f.username}')">👁 Screen</button>
        <button class="rc-btn rc-btn-lock"    title="Lock Device"  onclick="sendCommand(${f.id}, 'lock', '')">🔒 Lock</button>
        <button class="rc-btn rc-btn-stealth" title="Stealth Mode" onclick="sendCommand(${f.id}, 'stealth', '')">📴 Stealth</button>
      </div>
    </div>`;
  }).join('');
}

/** Send a remote command to a specific user via the Go WebSocket relay. */
function sendCommand(targetId, command, payload) {
  if (!ws || ws.readyState !== WebSocket.OPEN) { alert('Not connected to real-time network.'); return; }
  ws.send(JSON.stringify({ type: 'remote_command', target_user_id: targetId, command, payload }));
}

/** Handle an incoming remote_command on THIS device. */
function handleRemoteCommand(msg) {
  const perms = loadRemotePerms();
  switch (msg.command) {
    case 'lock':
      if (perms.allowLock) activateLock();
      break;
    case 'stealth':
      if (perms.allowStealth) activateStealth();
      break;
    case 'request_screen':
      if (perms.allowScreenView) acceptScreenRequest(msg.sender_user_id, msg.sender_name);
      break;
    case 'unlock':
      deactivateLock();
      break;
    case 'deactivate_stealth':
      deactivateStealth();
      break;
  }
}

// ── WebRTC Screen Sharing ──────────────────────────────────────────────────
/** Owner side: ask the target to start sharing their screen. */
function requestScreenView(targetId, username) {
  sendCommand(targetId, 'request_screen', '');
  // Set up our peer connection to receive the offer
  const pc = getOrCreatePC(targetId);
  pc.ontrack = e => showScreenViewer(username, e.streams[0]);
}

/** Controlled device: the owner asked to see our screen — capture and offer. */
async function acceptScreenRequest(viewerId, viewerName) {
  let stream;
  try {
    stream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: false });
  } catch (e) {
    return; // user denied
  }
  const pc = getOrCreatePC(viewerId);
  stream.getTracks().forEach(t => pc.addTrack(t, stream));

  try {
    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    sendSignal(viewerId, 'peer_offer', JSON.stringify(offer));
  } catch (e) {
    console.error('offer error', e);
  }
}

async function handlePeerOffer(msg) {
  const pc = getOrCreatePC(msg.sender_user_id);
  pc.ontrack = e => showScreenViewer(msg.sender_name, e.streams[0]);
  try {
    await pc.setRemoteDescription(JSON.parse(msg.payload));
    const answer = await pc.createAnswer();
    await pc.setLocalDescription(answer);
    sendSignal(msg.sender_user_id, 'peer_answer', JSON.stringify(answer));
  } catch (e) { console.error('answer error', e); }
}

async function handlePeerAnswer(msg) {
  const pc = peerConnections[msg.sender_user_id];
  if (!pc) return;
  try { await pc.setRemoteDescription(JSON.parse(msg.payload)); }
  catch (e) { console.error('setRemoteDescription error', e); }
}

function handlePeerICE(msg) {
  const pc = peerConnections[msg.sender_user_id];
  if (!pc) return;
  try { pc.addIceCandidate(JSON.parse(msg.payload)); } catch (_) {}
}

function getOrCreatePC(userId) {
  if (peerConnections[userId]) return peerConnections[userId];
  const pc = new RTCPeerConnection(STUN_CONFIG);
  pc.onicecandidate = e => {
    if (e.candidate) sendSignal(userId, 'peer_ice', JSON.stringify(e.candidate));
  };
  pc.onconnectionstatechange = () => {
    if (pc.connectionState === 'failed' || pc.connectionState === 'closed') {
      delete peerConnections[userId];
    }
  };
  peerConnections[userId] = pc;
  return pc;
}

function sendSignal(targetId, type, payload) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  ws.send(JSON.stringify({ type, target_user_id: targetId, payload }));
}

function showScreenViewer(username, stream) {
  const wrap  = document.getElementById('screen-viewer-wrap');
  const video = document.getElementById('screen-video');
  const label = document.getElementById('screen-viewer-label');
  label.textContent = `👁 Viewing: ${username}`;
  video.srcObject = stream;
  wrap.style.display = '';
  stream.getTracks().forEach(t => t.addEventListener('ended', closeScreenViewer));
}

function closeScreenViewer() {
  const wrap  = document.getElementById('screen-viewer-wrap');
  const video = document.getElementById('screen-video');
  if (video.srcObject) { video.srcObject.getTracks().forEach(t => t.stop()); video.srcObject = null; }
  wrap.style.display = 'none';
}

// ── Stealth Mode (fake power-off) ──────────────────────────────────────────
async function activateStealth() {
  if (stealthActive) return;
  stealthActive = true;

  const overlay = document.getElementById('stealth-overlay');
  overlay.style.display = '';

  // Full-screen to make it more convincing
  try { await document.documentElement.requestFullscreen(); } catch (_) {}

  // Keep screen on
  try {
    if ('wakeLock' in navigator) wakeLock = await navigator.wakeLock.request('screen');
  } catch (_) {}

  updateStealthClock();
  stealthClockId = setInterval(updateStealthClock, 1000);

  // Show battery if available
  if ('getBattery' in navigator) {
    navigator.getBattery().then(bat => {
      document.getElementById('stealth-bat-pct').textContent = `${Math.round(bat.level * 100)}%`;
    });
  }

  // Intercept beforeunload so closing the tab shows a browser warning
  window._stealthUnloadFn = e => { e.preventDefault(); return e.returnValue = ''; };
  window.addEventListener('beforeunload', window._stealthUnloadFn);
}

function deactivateStealth() {
  if (!stealthActive) return;
  stealthActive = false;
  stealthTapCount = 0;
  clearInterval(stealthClockId);
  stealthClockId = null;
  document.getElementById('stealth-overlay').style.display = 'none';
  if (wakeLock) { wakeLock.release(); wakeLock = null; }
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
  if (window._stealthUnloadFn) {
    window.removeEventListener('beforeunload', window._stealthUnloadFn);
    window._stealthUnloadFn = null;
  }
}

/** Secret 5-tap deactivation in the stealth exit zone. */
function stealthTap() {
  stealthTapCount++;
  clearTimeout(stealthTapTimer);
  if (stealthTapCount >= 5) { deactivateStealth(); return; }
  stealthTapTimer = setTimeout(() => { stealthTapCount = 0; }, 2000);
}

function updateStealthClock() {
  const now = new Date();
  document.getElementById('stealth-time').textContent =
    now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  document.getElementById('stealth-date').textContent =
    now.toLocaleDateString([], { weekday: 'long', month: 'long', day: 'numeric' });
}

// ── Remote Lock ────────────────────────────────────────────────────────────
function activateLock() {
  if (lockActive) return;
  lockActive = true;
  document.getElementById('lock-overlay').style.display = '';
  try { document.documentElement.requestFullscreen(); } catch (_) {}
}

function deactivateLock() {
  if (!lockActive) return;
  lockActive = false;
  lockTapCount = 0;
  document.getElementById('lock-overlay').style.display = 'none';
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
}

/** Secret 5-tap deactivation for the lock screen. */
function lockTap() {
  lockTapCount++;
  clearTimeout(lockTapTimer);
  if (lockTapCount >= 5) { deactivateLock(); return; }
  document.getElementById('lock-tap-hint').textContent = `Tap ${5 - lockTapCount} more time${lockTapCount < 4 ? 's' : ''} to unlock`;
  lockTapTimer = setTimeout(() => { lockTapCount = 0; document.getElementById('lock-tap-hint').textContent = 'Tap 5× to unlock'; }, 2000);
}

// ── Settings ───────────────────────────────────────────────────────────────
function loadSettings() {
  try { return { ...DEFAULT_SETTINGS, ...JSON.parse(localStorage.getItem(SETTINGS_KEY)) }; }
  catch (_) { return { ...DEFAULT_SETTINGS }; }
}
function persistSettings(s) { localStorage.setItem(SETTINGS_KEY, JSON.stringify(s)); }

function seedSettingsUI() {
  const s = loadSettings();
  document.getElementById('s-interval').value  = s.intervalIdx;
  document.getElementById('s-threshold').value = s.thresholdIdx;
  document.getElementById('s-bgthrottle').value = s.bgThrottleIdx;
  document.querySelectorAll('input[name="accuracy"]').forEach(r => { r.checked = r.value === s.accuracyMode; });
  updateIntervalLabel(s.intervalIdx);
  updateThresholdLabel(s.thresholdIdx);
  updateBgThrottleLabel(s.bgThrottleIdx);
  updateImpactCard(s);
}

function onIntervalChange(idx)   { updateIntervalLabel(+idx);   updateImpactCard(liveSettings()); }
function onThresholdChange(idx)  { updateThresholdLabel(+idx);  updateImpactCard(liveSettings()); }
function onAccuracyChange(mode)  { updateImpactCard(liveSettings()); }
function onBgThrottleChange(idx) { updateBgThrottleLabel(+idx); updateImpactCard(liveSettings()); }

function liveSettings() {
  return {
    intervalIdx:  +document.getElementById('s-interval').value,
    thresholdIdx: +document.getElementById('s-threshold').value,
    accuracyMode: document.querySelector('input[name="accuracy"]:checked')?.value || 'balanced',
    bgThrottleIdx: +document.getElementById('s-bgthrottle').value,
  };
}

function updateIntervalLabel(idx)   { document.getElementById('s-interval-val').textContent  = fmtSeconds(INTERVAL_VALUES[idx]); }
function updateThresholdLabel(idx)  { document.getElementById('s-threshold-val').textContent = THRESHOLD_VALUES[idx] === 0 ? 'Always' : `${THRESHOLD_VALUES[idx]} m`; }
function updateBgThrottleLabel(idx) { document.getElementById('s-bgthrottle-val').textContent = `${BG_THROTTLE_VALUES[idx]}×`; }

function fmtSeconds(s) {
  if (s < 60)  return `${s} s`;
  if (s < 3600) return `${s / 60} min`;
  return `${s / 3600} h`;
}

function updateImpactCard(s) {
  const dots  = ['●○○○○', '●●○○○', '●●●○○', '●●●●○', '●●●●●'];
  const score = s.accuracyMode === 'high' ? 2 : (s.accuracyMode === 'low' ? -1 : 0)
              + (s.intervalIdx <= 1 ? 2 : s.intervalIdx <= 3 ? 1 : 0)
              + (s.thresholdIdx === 0 ? 1 : 0)
              + (s.bgThrottleIdx <= 1 ? 1 : 0);
  const clamp = v => Math.max(0, Math.min(4, v));
  const lvl = clamp(score);
  const labels = ['Ultra Low', 'Low', 'Balanced', 'High', 'Maximum'];
  const descs  = [
    'Sends only when moving · low-power GPS · heavy bg throttle',
    `Updates every ${fmtSeconds(INTERVAL_VALUES[s.intervalIdx])} · sends if moved ${THRESHOLD_VALUES[s.thresholdIdx] || 'any'} m · low-power GPS`,
    `Updates every ${fmtSeconds(INTERVAL_VALUES[s.intervalIdx])} · sends only if moved ${THRESHOLD_VALUES[s.thresholdIdx] || 'any'} m · low-power GPS`,
    `Updates every ${fmtSeconds(INTERVAL_VALUES[s.intervalIdx])} · high-accuracy GPS`,
    'Continuous · full GPS · no background throttle',
  ];
  document.getElementById('impact-label').textContent = labels[lvl];
  document.getElementById('impact-desc').textContent  = descs[lvl];
  document.getElementById('impact-badge').textContent = dots[lvl];
}

function saveSettings() {
  const s = liveSettings();
  persistSettings(s);
  restartTracking();
  const saved = document.getElementById('settings-saved');
  saved.style.display = '';
  setTimeout(() => { saved.style.display = 'none'; }, 3000);
}

// ── API helpers ────────────────────────────────────────────────────────────
async function apiGet(path) {
  try {
    const res  = await fetch(`${API_BASE}${path}`, { headers: authHeaders() });
    const data = await res.json();
    return res.ok ? data : { error: data.detail || 'Request failed' };
  } catch (e) { return { error: e.message }; }
}

async function apiPost(path, body) {
  try {
    const opts = { method: 'POST', headers: authHeaders() };
    if (body !== null) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
    const res  = await fetch(`${API_BASE}${path}`, opts);
    const data = await res.json();
    return res.ok ? data : { error: data.detail || 'Request failed' };
  } catch (e) { return { error: e.message }; }
}

async function apiPostForm(path, formBody) {
  try {
    const res  = await fetch(`${API_BASE}${path}`, { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body: formBody });
    const data = await res.json();
    return res.ok ? data : { error: data.detail || 'Request failed' };
  } catch (e) { return { error: e.message }; }
}

function authHeaders() { return token ? { Authorization: `Bearer ${token}` } : {}; }

function showMessage(el, text, type) {
  el.textContent = text; el.className = `message ${type}`; el.style.display = '';
  setTimeout(() => { el.style.display = 'none'; }, 5000);
}

// ── Premium UI ─────────────────────────────────────────────────────────────
// Smart-contract address deployed on the selected network (placeholder — replace after deploy)
const CONTRACT_ADDRESSES = {
  '0xaa36a7': '0x0000000000000000000000000000000000000000', // Sepolia
  '0x1':      '0x0000000000000000000000000000000000000000', // Mainnet
  '0x89':     '0x0000000000000000000000000000000000000000', // Polygon
};
// subscribe() 4-byte selector: keccak256("subscribe()")[0..3]
const SUBSCRIBE_SELECTOR = '0xa4bcfe00';

function refreshPremiumUI() {
  const isPrem = currentUser && currentUser.is_premium;
  document.getElementById('premium-status-banner').style.display = isPrem ? '' : 'none';
  document.getElementById('free-status-banner').style.display    = isPrem ? 'none' : '';
  document.getElementById('payment-section').style.display       = isPrem ? 'none' : '';
  document.getElementById('history-section').style.display       = isPrem ? '' : 'none';
  ['history', 'priority', 'friends', 'remote', 'chat', 'geo', 'nearby', 'calltrack', 'navigate'].forEach(f => {
    const el = document.getElementById(`feat-${f}`);
    if (el) el.textContent = isPrem ? '✅' : '🔒';
  });
  // Phone number field
  if (currentUser && currentUser.phone_number) {
    document.getElementById('phone-input').value = currentUser.phone_number;
  }
  // Show payment success banner if returning from Stripe
  if (window._PAYMENT_STATUS === 'success') {
    window._PAYMENT_STATUS = null;
    showMessage(document.getElementById('lost-msg'), '🎉 Payment successful! Refresh to activate premium.', 'success');
  }
}

async function savePhone() {
  const phone = document.getElementById('phone-input').value.trim();
  if (!phone) return;
  const res = await apiPost('/api/me/phone', { phone_number: phone });
  showMessage(document.getElementById('phone-msg'), res.error ? res.error : '✅ Phone number saved!',
              res.error ? 'error' : 'success');
  if (!res.error && currentUser) currentUser.phone_number = phone;
}

async function activateLostMode() {
  const msgEl = document.getElementById('lost-msg');
  const res   = await apiPost('/api/device/lost', null);
  if (res.error) { showMessage(msgEl, res.error, 'error'); return; }
  const smsNote = res.sms_sent ? ' An SMS was sent to your registered number.' : '';
  showMessage(msgEl, `📴 Lost mode activated.${smsNote} Deep link: ${res.deep_link}`, 'success');
}

// ── Lost-token: silent tracking triggered by SMS link ─────────────────────
function handleLostToken() {
  if (!window._LOST_TOKEN) return;
  const token = window._LOST_TOKEN;
  window._LOST_TOKEN = null;
  // Verify token and start silent tracking to the real owner
  fetch(`${API_BASE}/api/device/activate?lost_token=${encodeURIComponent(token)}`)
    .then(r => r.json())
    .then(data => {
      if (data.owner_user_id) {
        _lostOwnerID = data.owner_user_id;
        startSilentTracking();
      }
    }).catch(() => {});
}

let _lostOwnerID = null;

function startSilentTracking() {
  if (!navigator.geolocation) return;
  navigator.geolocation.watchPosition(pos => {
    const { latitude, longitude, accuracy } = pos.coords;
    // POST location without requiring a logged-in session
    fetch(`${API_BASE}/api/location`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ latitude, longitude, accuracy, lost_owner_id: _lostOwnerID }),
    }).catch(() => {});
  }, () => {}, { enableHighAccuracy: false, maximumAge: 10000, timeout: 30000 });
}

// ── Ethereum / MetaMask Payment ────────────────────────────────────────────
async function ethSubscribe() {
  const msgEl = document.getElementById('eth-pay-msg');
  if (!window.ethereum) {
    showMessage(msgEl, 'MetaMask not installed. Install it at metamask.io', 'error'); return;
  }
  try {
    const accounts = await window.ethereum.request({ method: 'eth_requestAccounts' });
    const from = accounts[0];
    const chainId = document.getElementById('eth-network').value;
    // Switch to selected network
    await window.ethereum.request({ method: 'wallet_switchEthereumChain', params: [{ chainId }] })
          .catch(() => {});

    const contractAddr = CONTRACT_ADDRESSES[chainId];
    if (!contractAddr || contractAddr === '0x' + '0'.repeat(40)) {
      showMessage(msgEl, '⚠️ Smart contract not deployed on this network yet.', 'error'); return;
    }
    // Price: 0.005 ETH = 5_000_000_000_000_000 wei
    const value = '0x' + (5_000_000_000_000_000).toString(16);
    showMessage(msgEl, '⏳ Waiting for MetaMask confirmation…', 'success');
    const txHash = await window.ethereum.request({
      method: 'eth_sendTransaction',
      params: [{ from, to: contractAddr, value, data: '0xa4bcfe00', gas: '0x15F90' }],
    });
    showMessage(msgEl, `✅ Transaction sent! Tx: ${txHash.slice(0, 18)}…`, 'success');
    // Notify backend to mark user as premium
    const res = await apiPost('/api/payments/crypto/verify',
      { tx_hash: txHash, chain: chainId, wallet_address: from });
    if (!res.error) {
      currentUser.is_premium = true;
      localStorage.setItem('ztracky_user', JSON.stringify(currentUser));
      refreshPremiumUI();
      showMessage(msgEl, '🎉 Premium activated!', 'success');
    }
  } catch (e) {
    showMessage(document.getElementById('eth-pay-msg'), `❌ ${e.message}`, 'error');
  }
}

// ── Stripe Checkout ────────────────────────────────────────────────────────
async function stripeCheckout() {
  const res = await apiPost('/api/payments/stripe/checkout', null);
  if (res.error) { alert(res.error); return; }
  window.location.href = res.checkout_url;
}

// ── Route Playback (premium) ───────────────────────────────────────────────
let routePolyline = null;

async function playbackRoute() {
  const history = await apiGet('/api/location/history/me');
  if (history.error) { alert(history.error); return; }
  if (!history.length) { alert('No location history recorded yet.'); return; }

  const points = history.reverse().map(h => [h.latitude, h.longitude]);
  if (!map) { showTab('map'); }
  showTab('map');

  if (routePolyline) map.removeLayer(routePolyline);
  routePolyline = L.polyline(points, { color: '#3b82f6', weight: 3, opacity: 0.8 }).addTo(map);
  map.fitBounds(routePolyline.getBounds(), { padding: [20, 20] });

  // Animate a marker along the route
  let idx = 0;
  const dot = L.circleMarker(points[0], { radius: 8, color: '#ef4444', fillOpacity: 1 }).addTo(map);
  const timer = setInterval(() => {
    if (idx >= points.length) { clearInterval(timer); dot.remove(); return; }
    dot.setLatLng(points[idx++]);
  }, 300);
}

// ── Offline indicator ──────────────────────────────────────────────────────
function updateOnlineStatus() {
  const el = document.getElementById('location-status');
  if (!el) return;
  if (!navigator.onLine) {
    el.textContent = '📵 Offline — location queued for sync';
  }
}
window.addEventListener('online',  () => { lastSentTime = 0; });
window.addEventListener('offline', updateOnlineStatus);

// ── Init additions (call from showApp) ─────────────────────────────────────
const _origShowApp = showApp;
// Patch showApp to also handle lost token and premium init
window.addEventListener('DOMContentLoaded', () => {
  handleLostToken();
  if (token && currentUser) {
    // showApp is already called via the existing DOMContentLoaded handler
  }
});

// ── Geofence Management ────────────────────────────────────────────────────
let geofenceCircles = [];
let geofencePanelOpen = false;

function toggleGeofencePanel() {
  geofencePanelOpen = !geofencePanelOpen;
  document.getElementById('geofence-panel').style.display = geofencePanelOpen ? '' : 'none';
  if (geofencePanelOpen) { loadGeofences(); loadGeofenceAlerts(); }
}

async function loadGeofences() {
  const data = await apiGet('/api/geofences');
  if (data.error) return;
  // Remove old circles
  geofenceCircles.forEach(c => map && map.removeLayer(c));
  geofenceCircles = [];
  // Draw on map
  data.forEach(g => {
    if (!map) return;
    const circle = L.circle([g.latitude, g.longitude], {
      radius: g.radius_meters, color: '#f59e0b', fillColor: '#f59e0b44',
      weight: 2, fillOpacity: 0.2,
    }).bindTooltip(g.label).addTo(map);
    geofenceCircles.push(circle);
  });
  // Render list
  const el = document.getElementById('geofence-list');
  if (!data.length) { el.innerHTML = '<p class="empty">No geofences set</p>'; return; }
  el.innerHTML = data.map(g => `
    <div class="perm-card" style="margin-bottom:6px">
      <div class="perm-info"><span class="perm-icon">🔔</span>
        <div><strong>${g.label}</strong><small>${g.radius_meters}m radius</small></div>
      </div>
      <button class="rc-btn rc-btn-lock" onclick="removeGeofence(${g.id})">Remove</button>
    </div>`).join('');
}

async function addGeofenceAtCurrentLocation() {
  const label  = document.getElementById('gf-label').value.trim();
  const radius = parseFloat(document.getElementById('gf-radius').value) || 200;
  const msgEl  = document.getElementById('gf-msg');
  if (!label) { showMessage(msgEl, 'Please enter a label', 'error'); return; }
  if (!myMarker) { showMessage(msgEl, 'Your location is not known yet', 'error'); return; }
  const { lat, lng } = myMarker.getLatLng();
  const res = await apiPost('/api/geofences', { label, latitude: lat, longitude: lng, radius_meters: radius });
  if (res.error) { showMessage(msgEl, res.error, 'error'); return; }
  showMessage(msgEl, `✅ Geofence "${label}" created!`, 'success');
  document.getElementById('gf-label').value = '';
  loadGeofences();
  // Request notification permission for alerts
  if ('Notification' in window && Notification.permission === 'default') {
    Notification.requestPermission();
  }
}

async function removeGeofence(id) {
  await fetch(`${API_BASE}/api/geofences/${id}`, {
    method: 'DELETE', headers: { Authorization: `Bearer ${token}` },
  });
  loadGeofences();
}

async function loadGeofenceAlerts() {
  const data = await apiGet('/api/geofences/alerts');
  const el   = document.getElementById('geofence-alerts-list');
  if (!data || data.error || !data.length) { el.innerHTML = '<p class="empty">No alerts yet</p>'; return; }
  el.innerHTML = data.slice(0, 8).map(a => `
    <div style="display:flex;gap:8px;align-items:center;padding:4px 0;border-bottom:1px solid var(--border)">
      <span>${a.event_type === 'enter' ? '🟢' : '🔴'}</span>
      <span><strong>${a.label}</strong> — ${a.event_type}</span>
      <small style="margin-left:auto;color:var(--text-muted)">${new Date(a.created_at).toLocaleTimeString()}</small>
    </div>`).join('');
}

// Poll for geofence alerts and fire browser notifications
let lastAlertId = 0;
async function pollGeofenceAlerts() {
  if (!token) return;
  const data = await apiGet('/api/geofences/alerts');
  if (!data || data.error) return;
  const newAlerts = data.filter(a => a.id > lastAlertId);
  if (newAlerts.length && lastAlertId > 0) {
    newAlerts.forEach(a => {
      if ('Notification' in window && Notification.permission === 'granted') {
        new Notification(`ZTracky Geofence: ${a.event_type.toUpperCase()}`, {
          body: `You ${a.event_type === 'enter' ? 'entered' : 'left'} "${a.label}"`,
          icon: '/favicon.ico',
        });
      }
    });
  }
  if (data.length) lastAlertId = Math.max(...data.map(a => a.id));
  // Refresh alert list if panel is open
  if (geofencePanelOpen) loadGeofenceAlerts();
}
setInterval(pollGeofenceAlerts, 30_000);

// ── Route Playback fix (called from Premium tab ▶ button) ─────────────────
async function playbackRoute() {
  const history = await apiGet('/api/location/history/me');
  if (history.error) { alert(history.error); return; }
  if (!history.length) { alert('No location history recorded yet. Location history is saved automatically as you move.'); return; }

  const points = history.map(h => [h.latitude, h.longitude]).reverse();
  // Switch to map tab first, then draw
  showTab('map');
  // Give Leaflet time to resize before fitting bounds
  setTimeout(() => {
    if (routePolyline) map.removeLayer(routePolyline);
    routePolyline = L.polyline(points, { color: '#3b82f6', weight: 3, opacity: 0.8 }).addTo(map);
    map.fitBounds(routePolyline.getBounds(), { padding: [20, 20] });
    // Animate a marker along the route
    let idx = 0;
    const dot = L.circleMarker(points[0], { radius: 8, color: '#ef4444', fillOpacity: 1 }).addTo(map);
    const timer = setInterval(() => {
      if (idx >= points.length) { clearInterval(timer); dot.remove(); return; }
      dot.setLatLng(points[idx++]);
    }, 300);
  }, 200);
}

// ── Nearby Phones ──────────────────────────────────────────────────────────
let nearbyMarkers = [];

async function pollNearbyPhones() {
  if (!token) return;
  const data = await apiGet('/api/nearby?radius=500');
  if (data.error || data.count === undefined) return;

  const badge = document.getElementById('nearby-badge');
  const countEl = document.getElementById('nearby-count');
  if (data.count > 0) {
    badge.style.display = '';
    countEl.textContent = data.count;
  } else {
    badge.style.display = 'none';
  }

  // Remove previous nearby markers from map
  nearbyMarkers.forEach(m => map && map.removeLayer(m));
  nearbyMarkers = [];
}
// Poll every 60 s — lightweight since it's just a DB query
setInterval(pollNearbyPhones, 60_000);

// ── Chat ───────────────────────────────────────────────────────────────────
let chatFriendId  = null;
let chatPollTimer = null;
let friendsList   = [];

async function initChatTab() {
  // Populate friend picker
  const friends = await apiGet('/api/friends');
  if (friends.error) return;
  friendsList = friends;
  const sel = document.getElementById('chat-friend-select');
  sel.innerHTML = '<option value="">— Select a friend to chat —</option>' +
    friends.map(f => `<option value="${f.id}">${f.username}</option>`).join('');
  // Pre-select if a chat was already open
  if (chatFriendId) sel.value = chatFriendId;
  openChat();
  // Pre-fill social links
  if (currentUser) {
    if (currentUser.linked_whatsapp) document.getElementById('my-wa').value = currentUser.linked_whatsapp;
    if (currentUser.linked_facebook) document.getElementById('my-fb').value = currentUser.linked_facebook;
  }
}

async function openChat() {
  const sel    = document.getElementById('chat-friend-select');
  const fid    = parseInt(sel.value);
  const area   = document.getElementById('chat-area');
  const socBar = document.getElementById('social-links-bar');

  if (!fid) { area.style.display = 'none'; socBar.style.display = 'none'; chatFriendId = null; return; }
  chatFriendId = fid;
  area.style.display = '';

  // Load social links for this friend
  const social = await apiGet(`/api/friends/social/${fid}`);
  if (!social.error) {
    const waLink = document.getElementById('social-wa-link');
    const fbLink = document.getElementById('social-fb-link');
    if (social.linked_whatsapp) {
      const num = social.linked_whatsapp.replace(/\D/g, '');
      waLink.href = `https://wa.me/${num}`;
      waLink.style.display = '';
    } else { waLink.style.display = 'none'; }
    if (social.linked_facebook) {
      const handle = social.linked_facebook.startsWith('http') ? social.linked_facebook : `https://m.me/${social.linked_facebook}`;
      fbLink.href = handle;
      fbLink.style.display = '';
    } else { fbLink.style.display = 'none'; }
    socBar.style.display = (social.linked_whatsapp || social.linked_facebook) ? 'flex' : 'none';
  }

  // Show premium note for non-premium users
  document.getElementById('chat-premium-note').style.display = (currentUser && currentUser.is_premium) ? 'none' : '';

  await loadMessages();
  // Poll for new messages every 10 s
  clearInterval(chatPollTimer);
  chatPollTimer = setInterval(loadMessages, 10_000);
}

async function loadMessages() {
  if (!chatFriendId) return;
  const msgs = await apiGet(`/api/chat/${chatFriendId}`);
  if (msgs.error) return;
  const el = document.getElementById('chat-messages');
  if (!msgs.length) { el.innerHTML = '<p class="empty">No messages yet. Say hello!</p>'; return; }
  const myId = currentUser ? currentUser.id : 0;
  el.innerHTML = msgs.map(m => `
    <div class="chat-msg ${m.sender_id === myId ? 'chat-msg-me' : 'chat-msg-them'}">
      <div class="chat-bubble">${escapeHtml(m.content)}</div>
      <small class="chat-time">${new Date(m.created_at).toLocaleTimeString()}</small>
    </div>`).join('');
  el.scrollTop = el.scrollHeight;
}

async function sendChatMessage() {
  const input   = document.getElementById('chat-input');
  const content = input.value.trim();
  if (!content || !chatFriendId) return;
  if (!currentUser || !currentUser.is_premium) {
    showMessage(document.getElementById('chat-premium-note'), '⭐ Chat requires Premium', 'error');
    return;
  }
  const res = await apiPost(`/api/chat/${chatFriendId}`, { content });
  if (res.error) { alert(res.error); return; }
  input.value = '';
  // Also push via WebSocket for zero-latency delivery to recipient
  sendChatViaWS(chatFriendId, content);
  await loadMessages();
}

// Also relay chat messages via WebSocket for real-time delivery (no polling lag)
function sendChatViaWS(friendId, content) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  ws.send(JSON.stringify({
    type: 'remote_command', target_user_id: friendId,
    command: 'chat', payload: content,
  }));
}

function escapeHtml(str) {
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

async function saveSocialLinks() {
  const wa  = document.getElementById('my-wa').value.trim();
  const fb  = document.getElementById('my-fb').value.trim();
  const res = await apiPatch('/api/me/social', { linked_whatsapp: wa || null, linked_facebook: fb || null });
  showMessage(document.getElementById('social-save-msg'), res.error ? res.error : '✅ Social links saved!',
              res.error ? 'error' : 'success');
  if (!res.error && currentUser) {
    currentUser.linked_whatsapp = wa || null;
    currentUser.linked_facebook = fb || null;
    localStorage.setItem('ztracky_user', JSON.stringify(currentUser));
  }
}

// apiPatch helper
async function apiPatch(path, body) {
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    return res.ok ? data : { error: data.detail || 'Error' };
  } catch (e) { return { error: e.message }; }
}

// Unread chat badge on tab
async function refreshChatUnread() {
  if (!token) return;
  const data = await apiGet('/api/chat/unread/count');
  if (!data || data.error) return;
  const btn = Array.from(document.querySelectorAll('.tab-btn')).find(b => b.textContent.startsWith('💬'));
  if (btn) btn.textContent = data.unread > 0 ? `💬 Chat (${data.unread})` : '💬 Chat';
}
setInterval(refreshChatUnread, 15_000);

// ── Call-Based Tracking ────────────────────────────────────────────────────
let _lastCallTrackResult = null;
let callTrackCircle = null;

async function initCallTrackTab() {
  await loadCallTrackHistory();
}

async function submitCallTrack() {
  const phone = document.getElementById('ct-phone').value.trim();
  const msgEl = document.getElementById('ct-msg');
  if (!phone) { showMessage(msgEl, 'Please enter a phone number in international format (+1234567890)', 'error'); return; }

  showMessage(msgEl, '🔍 Looking up…', 'success');

  const res = await apiPost('/api/call-tracking', { caller_phone: phone });
  if (res.error) {
    showMessage(msgEl, res.error, 'error');
    return;
  }
  msgEl.style.display = 'none';
  _lastCallTrackResult = res;

  // Populate result card
  document.getElementById('ct-result').style.display = '';
  document.getElementById('ct-result-phone').textContent = res.caller_phone;
  const carrierParts = [res.carrier_name, res.carrier_country, res.line_type].filter(Boolean);
  document.getElementById('ct-result-carrier').textContent = carrierParts.join(' · ') || 'Carrier unknown';
  document.getElementById('ct-result-notes').textContent   = res.notes || '';

  await loadCallTrackHistory();
}

function showCallTrackOnMap() {
  const r = _lastCallTrackResult;
  if (!r || r.estimated_latitude == null) {
    alert('No location estimate available for this call. Ensure your location is shared and Twilio Lookup is configured.');
    return;
  }
  showTab('map');
  setTimeout(() => {
    if (callTrackCircle) map.removeLayer(callTrackCircle);
    const radiusM = (r.confidence_radius_km || 500) * 1000;
    callTrackCircle = L.circle([r.estimated_latitude, r.estimated_longitude], {
      radius: radiusM,
      color: '#ef4444', fillColor: '#ef444433', weight: 2, fillOpacity: 0.25,
    })
    .bindPopup(
      `<strong>📞 ${escapeHtml(r.caller_phone)}</strong><br>` +
      `${escapeHtml(r.carrier_name || 'Unknown carrier')}<br>` +
      `Confidence radius: ~${(r.confidence_radius_km || 0).toFixed(0)} km`
    )
    .addTo(map);
    map.fitBounds(callTrackCircle.getBounds(), { padding: [30, 30] });
    callTrackCircle.openPopup();
  }, 200);
}

async function loadCallTrackHistory() {
  const data = await apiGet('/api/call-tracking');
  const el   = document.getElementById('ct-history');
  if (!data || data.error) { el.innerHTML = '<p class="empty">No lookups yet</p>'; return; }
  if (!data.length)        { el.innerHTML = '<p class="empty">No lookups yet</p>'; return; }
  el.innerHTML = data.map(e => {
    const carrier = [e.carrier_name, e.carrier_country, e.line_type].filter(Boolean).join(' · ') || 'unknown';
    const hasLoc  = e.estimated_latitude != null;
    return `
      <div class="perm-card" style="margin-bottom:6px;cursor:default">
        <div class="perm-info">
          <span class="perm-icon">📞</span>
          <div>
            <strong>${escapeHtml(e.caller_phone)}</strong>
            <small>${escapeHtml(carrier)}</small>
            <small style="opacity:.6">${new Date(e.created_at).toLocaleString()}</small>
          </div>
        </div>
        ${hasLoc ? `<button class="rc-btn rc-btn-view" onclick='_showHistoryEventOnMap(${JSON.stringify(e)})'>🗺</button>` : '<span style="color:var(--text-muted);font-size:.8rem">No location</span>'}
      </div>`;
  }).join('');
}

function _showHistoryEventOnMap(e) {
  _lastCallTrackResult = e;
  showCallTrackOnMap();
}

// ── Trail Navigation ────────────────────────────────────────────────────────
let navPolyline  = null;
let navDestMarker = null;

async function navigateToFriend(friendId, friendName) {
  const modeSelect = await _promptNavigationMode(friendName);
  if (!modeSelect) return;
  const { mode, avoidHighways } = modeSelect;

  const res = await apiGet(
    `/api/navigate/${friendId}?mode=${mode}&avoid_highways=${avoidHighways}`
  );
  if (res.error) { alert(`Navigation error: ${res.error}`); return; }

  _renderNavigation(res, friendName);
}

async function _promptNavigationMode(friendName) {
  // Simple prompt using a small inline modal is cleaner, but to keep it
  // dependency-free we use the native prompt.
  const choice = prompt(
    `Navigate to ${friendName}.\n\nChoose mode:\n  1 = driving (default)\n  2 = walking\n  3 = cycling\n\nEnter 1, 2 or 3:`
  );
  if (choice === null) return null;
  const modeMap = { '1': 'driving', '2': 'walking', '3': 'cycling' };
  const mode = modeMap[choice] || 'driving';
  const avoidHighways = (mode === 'driving') &&
    confirm('Avoid highways / motorways?');
  return { mode, avoidHighways };
}

function _renderNavigation(res, friendName) {
  // Switch to map
  showTab('map');
  setTimeout(() => {
    // Clear old nav layers
    if (navPolyline)   { map.removeLayer(navPolyline);   navPolyline   = null; }
    if (navDestMarker) { map.removeLayer(navDestMarker); navDestMarker = null; }

    if (!res.geometry || res.geometry.length < 2) {
      alert('No route geometry returned.'); return;
    }

    // Draw route polyline
    navPolyline = L.polyline(res.geometry, {
      color: '#8b5cf6', weight: 5, opacity: 0.85,
    }).addTo(map);

    // Destination marker
    const dest = res.geometry[res.geometry.length - 1];
    navDestMarker = L.marker(dest, {
      icon: L.divIcon({ className: '', html: '<div style="font-size:26px">🎯</div>', iconSize: [26, 26], iconAnchor: [13, 26] }),
    }).bindPopup(
      `<strong>🎯 ${escapeHtml(res.friend_username || friendName)}</strong><br>` +
      `${_fmtDistance(res.distance_meters)} · ${_fmtDuration(res.duration_seconds)}`
    ).addTo(map);

    map.fitBounds(navPolyline.getBounds(), { padding: [30, 30] });
    navDestMarker.openPopup();

    // Show steps in the calltrack tab nav panel (reuse the panel there)
    _showNavPanel(res, friendName);
  }, 200);
}

function _showNavPanel(res, friendName) {
  // Populate and reveal the navigation overlay on the map tab
  document.getElementById('nav-panel').style.display = '';
  document.getElementById('nav-info').innerHTML =
    `<strong>🧭 To ${escapeHtml(res.friend_username || friendName)}</strong> · ` +
    `${_fmtDistance(res.distance_meters)} · ${_fmtDuration(res.duration_seconds)} · ${res.mode}` +
    (res.avoid_highways ? ' (no highways)' : '');

  const stepsEl = document.getElementById('nav-steps');
  if (!res.steps || !res.steps.length) {
    stepsEl.innerHTML = '<p class="empty">No step details available</p>';
    return;
  }
  stepsEl.innerHTML = res.steps.map((s, i) => `
    <div class="nav-step">
      <span class="nav-step-num">${i + 1}</span>
      <span class="nav-step-instr">${escapeHtml(s.instruction)}</span>
      <span class="nav-step-dist">${_fmtDistance(s.distance_meters)}</span>
    </div>`).join('');
}

function closeNavigation() {
  if (navPolyline)   { map.removeLayer(navPolyline);   navPolyline   = null; }
  if (navDestMarker) { map.removeLayer(navDestMarker); navDestMarker = null; }
  document.getElementById('nav-panel').style.display = 'none';
}

function _fmtDistance(m) {
  if (!m) return '0 m';
  if (m < 1000) return `${m} m`;
  return `${(m / 1000).toFixed(1)} km`;
}

function _fmtDuration(s) {
  if (!s) return '0 min';
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h ? `${h}h ${m}min` : `${m} min`;
}

// ── Bug Reports / Feedback ─────────────────────────────────────────────────
let currentReportId = null;

async function submitFeedback() {
  const reportType = document.getElementById('feedback-type').value;
  const title = document.getElementById('feedback-title').value.trim();
  const description = document.getElementById('feedback-description').value.trim();
  const msgEl = document.getElementById('feedback-msg');

  if (!title) { showMessage(msgEl, 'Please enter a title', 'error'); return; }
  if (!description) { showMessage(msgEl, 'Please enter a description', 'error'); return; }

  const res = await apiPost('/api/bug-reports', { report_type: reportType, title, description });
  if (res.error) { showMessage(msgEl, res.error, 'error'); return; }

  showMessage(msgEl, '✅ Feedback submitted! Thank you.', 'success');
  document.getElementById('feedback-title').value = '';
  document.getElementById('feedback-description').value = '';
  loadMyBugReports();
}

async function loadMyBugReports() {
  const data = await apiGet('/api/bug-reports');
  const el = document.getElementById('my-bug-reports');
  if (data.error) { el.innerHTML = `<p class="empty">Error: ${data.error}</p>`; return; }
  if (!data.length) { el.innerHTML = '<p class="empty">No reports submitted yet</p>'; return; }

  el.innerHTML = data.map(r => `
    <div class="req-card" onclick="openBugReportModal(${r.id})" style="cursor:pointer">
      <div class="info" style="flex:1">
        <strong>${escapeHtml(r.title)}</strong>
        <small style="display:flex;gap:8px;flex-wrap:wrap">
          <span class="badge ${r.report_type === 'bug' ? 'badge-rejected' : 'badge-accepted'}">${r.report_type === 'bug' ? '🐛 Bug' : '✨ Feature'}</span>
          <span class="badge badge-${r.status === 'resolved' ? 'accepted' : r.status === 'open' ? 'pending' : 'pending'}">${r.status}</span>
          ${r.reply_count > 0 ? `<span>💬 ${r.reply_count}</span>` : ''}
        </small>
      </div>
      <small>${new Date(r.created_at).toLocaleDateString()}</small>
    </div>
  `).join('');
}

async function openBugReportModal(reportId) {
  currentReportId = reportId;
  const res = await apiGet(`/api/bug-reports/${reportId}`);
  if (res.error) { alert(res.error); return; }

  document.getElementById('modal-report-type').textContent = res.report_type === 'bug' ? '🐛 Bug' : '✨ Feature';
  document.getElementById('modal-report-type').className = `badge ${res.report_type === 'bug' ? 'badge-rejected' : 'badge-accepted'}`;
  document.getElementById('modal-report-title').textContent = res.title;
  document.getElementById('modal-report-desc').textContent = res.description;
  document.getElementById('modal-report-status').textContent = res.status;
  document.getElementById('modal-report-status').className = `badge badge-${res.status === 'resolved' ? 'accepted' : res.status === 'open' ? 'pending' : 'pending'}`;
  document.getElementById('modal-report-date').textContent = new Date(res.created_at).toLocaleString();

  const repliesEl = document.getElementById('modal-replies');
  if (!res.replies || !res.replies.length) {
    repliesEl.innerHTML = '<p class="empty">No replies yet. The admin will respond soon!</p>';
  } else {
    repliesEl.innerHTML = res.replies.map(reply => `
      <div class="bug-reply ${reply.is_admin_reply ? 'admin-reply' : 'user-reply'}">
        <div class="bug-reply-header">
          <strong>${reply.is_admin_reply ? '🛡 Admin' : '👤 You'}</strong>
          <small>${new Date(reply.created_at).toLocaleString()}</small>
        </div>
        <div class="bug-reply-content">${escapeHtml(reply.content)}</div>
      </div>
    `).join('');
  }

  document.getElementById('modal-reply-input').value = '';
  document.getElementById('bug-report-modal').style.display = '';
}

function closeBugReportModal() {
  document.getElementById('bug-report-modal').style.display = 'none';
  currentReportId = null;
}

async function sendBugReportReply() {
  if (!currentReportId) return;
  const content = document.getElementById('modal-reply-input').value.trim();
  if (!content) return;

  const res = await apiPost(`/api/bug-reports/${currentReportId}/reply`, { content });
  if (res.error) { alert(res.error); return; }

  document.getElementById('modal-reply-input').value = '';
  openBugReportModal(currentReportId);  // Refresh
}

// Initialize feedback tab
function initFeedbackTab() {
  loadMyBugReports();
}

// ── API Key Management ─────────────────────────────────────────────────────

async function checkTwoFAStatus() {
  const res = await apiGet('/api/webauthn/has-credentials');
  if (res.error) return;
  const has2FA = res.has_credentials;
  document.getElementById('twofa-icon').textContent = has2FA ? '✅' : '🔒';
  document.getElementById('twofa-label').textContent = has2FA ? '2FA Active' : '2FA Not Set Up';
  document.getElementById('twofa-desc').textContent = has2FA
    ? `${res.count} credential(s) registered`
    : 'Register your fingerprint to create API keys';
  document.getElementById('btn-register-fingerprint').textContent = has2FA
    ? '🖐 Add Another Fingerprint'
    : '🖐 Register Fingerprint / Face ID';
  document.getElementById('apikey-create-section').style.display = has2FA ? '' : 'none';
  if (has2FA) loadApiKeys();
}

async function registerFingerprint() {
  const msgEl = document.getElementById('twofa-msg');
  try {
    showMessage(msgEl, 'Starting fingerprint registration...', 'success');
    // Get registration options from server
    const options = await apiGet('/api/webauthn/register-options');
    if (options.error) { showMessage(msgEl, options.error, 'error'); return; }

    // Convert challenge and user.id from base64url to ArrayBuffer
    options.challenge = _b64ToArrayBuffer(options.challenge);
    options.user.id = _b64ToArrayBuffer(options.user.id);
    if (options.excludeCredentials) {
      options.excludeCredentials = options.excludeCredentials.map(c => ({
        ...c, id: _b64ToArrayBuffer(c.id)
      }));
    }

    // Prompt user for biometric
    const credential = await navigator.credentials.create({ publicKey: options });

    // Send response to server
    const credJSON = {
      id: credential.id,
      rawId: _arrayBufferToB64(credential.rawId),
      type: credential.type,
      response: {
        attestationObject: _arrayBufferToB64(credential.response.attestationObject),
        clientDataJSON: _arrayBufferToB64(credential.response.clientDataJSON),
      },
    };
    const result = await apiPost('/api/webauthn/register-verify', { credential: credJSON });
    if (result.error) { showMessage(msgEl, result.error, 'error'); return; }

    showMessage(msgEl, '✅ Fingerprint registered! You can now create API keys.', 'success');
    checkTwoFAStatus();
  } catch (e) {
    showMessage(msgEl, 'Fingerprint registration failed: ' + (e.message || e), 'error');
  }
}

async function createApiKey() {
  const msgEl = document.getElementById('apikey-create-msg');
  try {
    showMessage(msgEl, 'Verifying fingerprint...', 'success');

    // Step 1: Get WebAuthn auth options
    const options = await apiGet('/api/webauthn/auth-options');
    if (options.error) { showMessage(msgEl, options.error, 'error'); return; }

    options.challenge = _b64ToArrayBuffer(options.challenge);
    if (options.allowCredentials) {
      options.allowCredentials = options.allowCredentials.map(c => ({
        ...c, id: _b64ToArrayBuffer(c.id)
      }));
    }

    // Step 2: Prompt biometric
    const assertion = await navigator.credentials.get({ publicKey: options });

    const assertJSON = {
      id: assertion.id,
      rawId: _arrayBufferToB64(assertion.rawId),
      type: assertion.type,
      response: {
        authenticatorData: _arrayBufferToB64(assertion.response.authenticatorData),
        clientDataJSON: _arrayBufferToB64(assertion.response.clientDataJSON),
        signature: _arrayBufferToB64(assertion.response.signature),
        userHandle: assertion.response.userHandle ? _arrayBufferToB64(assertion.response.userHandle) : null,
      },
    };

    // Step 3: Verify and get auth token
    const authResult = await apiPost('/api/webauthn/auth-verify', { credential: assertJSON });
    if (authResult.error) { showMessage(msgEl, authResult.error, 'error'); return; }

    // Step 4: Create API key with auth token
    const label = document.getElementById('apikey-label').value.trim() || 'CLI';
    const scopeEls = document.querySelectorAll('#apikey-scopes input[type=checkbox]:checked');
    const scopes = Array.from(scopeEls).map(el => el.value);

    const res = await fetch(`${API_BASE}/api/api-keys`, {
      method: 'POST',
      headers: {
        ...apiAuthHeaders(),
        'Content-Type': 'application/json',
        'X-Auth-Token': authResult.auth_token,
      },
      body: JSON.stringify({ label, scopes }),
    });
    const data = await res.json();
    if (!res.ok) { showMessage(msgEl, data.detail || 'Failed to create key', 'error'); return; }

    // Show the key (one-time)
    document.getElementById('apikey-value').textContent = data.key;
    document.getElementById('apikey-reveal').style.display = '';
    showMessage(msgEl, '✅ API key created! Copy it now — it won\'t be shown again.', 'success');
    document.getElementById('apikey-label').value = '';
    loadApiKeys();
  } catch (e) {
    showMessage(msgEl, 'Failed: ' + (e.message || e), 'error');
  }
}

function copyApiKey() {
  const key = document.getElementById('apikey-value').textContent;
  navigator.clipboard.writeText(key).then(() => {
    alert('API key copied to clipboard!');
  });
}

async function loadApiKeys() {
  const res = await apiGet('/api/api-keys');
  const el = document.getElementById('apikey-list');
  if (res.error) { el.innerHTML = `<p class="empty">Error: ${escapeHtml(res.error)}</p>`; return; }
  if (!res.length) { el.innerHTML = '<p class="empty">No API keys yet</p>'; return; }

  el.innerHTML = res.map(k => `
    <div class="req-card">
      <div class="info" style="flex:1">
        <strong>🔑 ${escapeHtml(k.label)}</strong>
        <small style="display:flex;gap:8px;flex-wrap:wrap">
          <code>${escapeHtml(k.key_prefix)}…</code>
          <span class="badge badge-accepted">${escapeHtml(k.scopes)}</span>
          ${k.last_used_at ? `<span>Last used: ${new Date(k.last_used_at).toLocaleDateString()}</span>` : '<span class="badge badge-pending">Never used</span>'}
        </small>
      </div>
      <button class="btn-danger" style="padding:6px 12px;font-size:.8rem" onclick="revokeApiKey(${k.id})">Revoke</button>
    </div>
  `).join('');
}

async function revokeApiKey(keyId) {
  if (!confirm('Revoke this API key? Any CLI sessions using it will lose access.')) return;
  const res = await fetch(`${API_BASE}/api/api-keys/${keyId}`, {
    method: 'DELETE',
    headers: apiAuthHeaders(),
  });
  if (res.ok) loadApiKeys();
  else alert('Failed to revoke key');
}

function apiAuthHeaders() {
  return { 'Authorization': `Bearer ${token}` };
}

// WebAuthn helper: base64url → ArrayBuffer
function _b64ToArrayBuffer(b64) {
  const pad = b64.length % 4 === 0 ? '' : '='.repeat(4 - (b64.length % 4));
  const base64 = (b64 + pad).replace(/-/g, '+').replace(/_/g, '/');
  const raw = atob(base64);
  const arr = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) arr[i] = raw.charCodeAt(i);
  return arr.buffer;
}

// WebAuthn helper: ArrayBuffer → base64url
function _arrayBufferToB64(buf) {
  const bytes = new Uint8Array(buf);
  let binary = '';
  bytes.forEach(b => binary += String.fromCharCode(b));
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

// Initialize settings tab with 2FA status check
const _origSeedSettingsUI = typeof seedSettingsUI === 'function' ? seedSettingsUI : null;
function initSettingsApiKeys() {
  checkTwoFAStatus();
}
