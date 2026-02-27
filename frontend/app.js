// REFRESH_INTERVAL_MS is how often the frontend polls for updated friend/request lists.
const REFRESH_INTERVAL_MS = 30_000;
   ZTracky – Frontend Application (JavaScript)
   Communicates with:
     • Python FastAPI backend  (REST)
     • Go WebSocket service    (real-time location)
   ────────────────────────────────────────── */

const API_BASE = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
  ? 'http://localhost:8000'
  : `${window.location.protocol}//${window.location.hostname}:8000`;

const WS_BASE = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
  ? 'ws://localhost:8001'
  : `ws://${window.location.hostname}:8001`;

// ── State ──────────────────────────────────────────────────────────────────
let token = localStorage.getItem('ztracky_token');
let currentUser = JSON.parse(localStorage.getItem('ztracky_user') || 'null');
let map = null;
let myMarker = null;
let friendMarkers = {};   // userID → Leaflet marker
let friendIDs = [];       // accepted friend user IDs (kept in sync)
let ws = null;
let watchId = null;

// ── Initialise on page load ────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', () => {
  if (token && currentUser) {
    showApp();
  }
});

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
  el.style.display = 'none';
  el.textContent = '';
}

function showAuthError(msg) {
  const el = document.getElementById('auth-error');
  el.textContent = msg;
  el.style.display = '';
}

async function register() {
  const username = document.getElementById('reg-username').value.trim();
  const email = document.getElementById('reg-email').value.trim();
  const password = document.getElementById('reg-password').value;
  if (!username || !email || !password) { showAuthError('All fields are required.'); return; }

  const res = await apiPost('/api/register', { username, email, password });
  if (res.error) { showAuthError(res.error); return; }

  saveSession(res);
  showApp();
}

async function login() {
  const username = document.getElementById('login-username').value.trim();
  const password = document.getElementById('login-password').value;
  if (!username || !password) { showAuthError('Username and password are required.'); return; }

  // OAuth2PasswordRequestForm expects form-encoded body
  const body = new URLSearchParams({ username, password });
  const res = await apiPostForm('/api/login', body);
  if (res.error) { showAuthError(res.error); return; }

  saveSession(res);
  showApp();
}

function saveSession(data) {
  token = data.access_token;
  currentUser = data.user;
  localStorage.setItem('ztracky_token', token);
  localStorage.setItem('ztracky_user', JSON.stringify(currentUser));
}

function logout() {
  stopTracking();
  disconnectWS();
  token = null;
  currentUser = null;
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

  // Refresh friend list periodically so WS broadcasts reach new friends
  setInterval(() => { loadFriends(); loadRequests(); }, REFRESH_INTERVAL_MS);
}

function showTab(name) {
  ['map', 'requests', 'friends'].forEach(t => {
    document.getElementById(`tab-${t}`).style.display = t === name ? '' : 'none';
    document.getElementById(`tab-${t}`).classList.toggle('active', t === name);
  });
  document.querySelectorAll('.tab-btn').forEach((btn, i) => {
    btn.classList.toggle('active', ['map', 'requests', 'friends'][i] === name);
  });
  if (name === 'map' && map) { setTimeout(() => map.invalidateSize(), 100); }
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
  if (myMarker) {
    myMarker.setLatLng([lat, lng]);
  } else {
    myMarker = L.marker([lat, lng], {
      icon: L.divIcon({ className: '', html: '<div style="font-size:28px">📍</div>', iconSize: [28, 28], iconAnchor: [14, 28] })
    }).addTo(map).bindPopup(`<b>You</b> (${currentUser.username})`);
    map.setView([lat, lng], 14);
  }
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

// ── Geolocation & location push ────────────────────────────────────────────
function startTracking() {
  if (!navigator.geolocation) {
    document.getElementById('location-status').textContent = '❌ Geolocation not supported';
    return;
  }

  watchId = navigator.geolocation.watchPosition(
    pos => {
      const { latitude, longitude, accuracy } = pos.coords;
      document.getElementById('location-status').textContent =
        `📡 ${latitude.toFixed(5)}, ${longitude.toFixed(5)} ±${accuracy ? accuracy.toFixed(0) + 'm' : '?'}`;
      setMyMarker(latitude, longitude);

      // Push to REST API for persistence
      apiPost('/api/location', { latitude, longitude, accuracy }).catch(() => {});

      // Push to WebSocket for real-time broadcast to friends
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'location', latitude, longitude, accuracy, friends: friendIDs }));
      }
    },
    err => {
      document.getElementById('location-status').textContent = `❌ ${err.message}`;
    },
    { enableHighAccuracy: true, maximumAge: 5000, timeout: 10000 }
  );
}

function stopTracking() {
  if (watchId !== null) { navigator.geolocation.clearWatch(watchId); watchId = null; }
}

// ── WebSocket (Go real-time service) ──────────────────────────────────────
function connectWS() {
  if (!token) return;
  const url = `${WS_BASE}/ws?token=${encodeURIComponent(token)}&username=${encodeURIComponent(currentUser.username)}`;
  ws = new WebSocket(url);

  ws.addEventListener('open', () => setWSStatus('connected', '● Live'));
  ws.addEventListener('close', () => {
    setWSStatus('disconnected', '● Offline');
    // Reconnect after 5s
    setTimeout(() => { if (token) connectWS(); }, 5000);
  });
  ws.addEventListener('error', () => setWSStatus('disconnected', '● Error'));
  ws.addEventListener('message', e => {
    try {
      const msg = JSON.parse(e.data);
      if (msg.type === 'location') {
        setFriendMarker(msg.user_id, msg.username, msg.latitude, msg.longitude, msg.accuracy);
      }
    } catch (_) {}
  });
}

function disconnectWS() {
  if (ws) { ws.close(); ws = null; }
}

function setWSStatus(className, text) {
  const el = document.getElementById('ws-status');
  el.className = `ws-indicator ${className}`;
  el.textContent = text;
}

// ── Friend Requests ────────────────────────────────────────────────────────
async function sendRequest() {
  const username = document.getElementById('req-username').value.trim();
  if (!username) return;
  const msgEl = document.getElementById('req-message');

  const res = await apiPost(`/api/requests/send?username=${encodeURIComponent(username)}`, null);
  if (res.error) {
    showMessage(msgEl, res.error, 'error');
  } else {
    showMessage(msgEl, `Request sent to ${username}!`, 'success');
    document.getElementById('req-username').value = '';
    loadRequests();
  }
}

async function acceptRequest(id) {
  await apiPost(`/api/requests/${id}/accept`, null);
  loadRequests();
  loadFriends();
}

async function rejectRequest(id) {
  await apiPost(`/api/requests/${id}/reject`, null);
  loadRequests();
}

async function loadRequests() {
  const data = await apiGet('/api/requests');
  if (data.error) return;

  const incoming = data.filter(r => r.receiver_id === currentUser.id && r.status === 'pending');
  const sent = data.filter(r => r.sender_id === currentUser.id);

  renderRequests('incoming-requests', incoming, true);
  renderRequests('sent-requests', sent, false);
}

function renderRequests(containerId, reqs, canAct) {
  const el = document.getElementById(containerId);
  if (!reqs.length) { el.innerHTML = '<p class="empty">None</p>'; return; }
  el.innerHTML = reqs.map(r => {
    const other = canAct ? r.sender_username : r.receiver_username;
    const badge = `<span class="badge badge-${r.status}">${r.status}</span>`;
    const actions = canAct && r.status === 'pending'
      ? `<div class="actions">
           <button class="btn-accept" onclick="acceptRequest(${r.id})">Accept</button>
           <button class="btn-reject" onclick="rejectRequest(${r.id})">Reject</button>
         </div>`
      : badge;
    return `<div class="req-card">
      <div class="info"><strong>${other}</strong><small>${new Date(r.created_at).toLocaleString()}</small></div>
      ${actions}
    </div>`;
  }).join('');
}

// ── Friends ────────────────────────────────────────────────────────────────
async function loadFriends() {
  const friends = await apiGet('/api/friends');
  if (friends.error) return;

  friendIDs = friends.map(f => f.id);
  const el = document.getElementById('friends-list');
  if (!friends.length) { el.innerHTML = '<p class="empty">No friends yet. Send a tracking request!</p>'; return; }

  el.innerHTML = friends.map(f => `
    <div class="friend-card">
      <div class="info"><strong>${f.username}</strong><small>${f.email}</small></div>
      <button class="btn-locate" onclick="locateFriend(${f.id}, '${f.username}')">📍 Locate</button>
    </div>
  `).join('');

  // Also load their locations on the map
  const locs = await apiGet('/api/friends/locations');
  if (!locs.error) {
    locs.forEach(loc => setFriendMarker(loc.user_id, loc.username, loc.latitude, loc.longitude, loc.accuracy));
  }
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

// ── API helpers ────────────────────────────────────────────────────────────
async function apiGet(path) {
  try {
    const res = await fetch(`${API_BASE}${path}`, { headers: authHeaders() });
    const data = await res.json();
    if (!res.ok) return { error: data.detail || 'Request failed' };
    return data;
  } catch (e) {
    return { error: e.message };
  }
}

async function apiPost(path, body) {
  try {
    const opts = { method: 'POST', headers: authHeaders() };
    if (body !== null) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    const res = await fetch(`${API_BASE}${path}`, opts);
    const data = await res.json();
    if (!res.ok) return { error: data.detail || 'Request failed' };
    return data;
  } catch (e) {
    return { error: e.message };
  }
}

async function apiPostForm(path, formBody) {
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: formBody,
    });
    const data = await res.json();
    if (!res.ok) return { error: data.detail || 'Request failed' };
    return data;
  } catch (e) {
    return { error: e.message };
  }
}

function authHeaders() {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function showMessage(el, text, type) {
  el.textContent = text;
  el.className = `message ${type}`;
  el.style.display = '';
  setTimeout(() => { el.style.display = 'none'; }, 5000);
}
