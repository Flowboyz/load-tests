// dashboard.js — Main UI Controller and WebSocket handler

let socket = null;
let currentActiveSessionId = null;
let currentUser = null;

// New Dashboard Global States for Buffering, Searching and Accurate Timing
window.consoleLogsBuffer = [];
window.maxConsoleLogs = 1000;
window.botsFingerprints = {};
window.botsMetadata = {};
window.autoScroll = true;
window.searchDebounce = null;
window.eventCountLastSecond = 0;
window.eventsRateInterval = null;

// Timer Globals
let sessionTimerInterval = null;
let localTimerStartRealTime = null;
let localTimerBaseSeconds = 0;
let localElapsedSeconds = 0;

// Tab Routing Configuration
const TABS = ['monitoring', 'configurator', 'templates', 'history'];

document.addEventListener('DOMContentLoaded', async () => {
    // 1. Theme Configuration
    initTheme();

    // 2. Fetch User Profile
    await fetchUserProfile();

    // 3. Setup Navigation & Menu Listeners
    initNavigation();

    // 4. Initialise Real-Time Charts
    initCharts();

    // 5. Load Presets & Session History Tables
    loadSavedPresets();
    loadSessionHistory();

    // 6. Monitor Active Sessions on Launch
    checkForRunningSession();

    // 7. Setup Form Actions & Form submissions
    setupFormActions();

    // 8. Populate Accordion Checkbox Grids
    populateGrids();
    updateSerializedInputs('network');
    updateSerializedInputs('browser');
    updateSerializedInputs('device');
    updateSerializedInputs('os');

    // 9. Setup Console Live Filters & Events rate ticker
    setupConsoleFilters();
    startEventsRateCounter();
});

// Theme Management
function initTheme() {
    const btn = document.getElementById('themeToggleBtn');
    const body = document.body;
    
    // Check localStorage
    const theme = localStorage.getItem('theme') || 'dark';
    if (theme === 'light') {
        body.classList.remove('dark-mode');
        body.classList.add('light-mode');
        btn.querySelector('i').className = 'fa-solid fa-sun';
        btn.querySelector('span').textContent = 'Light Mode';
    }

    btn.addEventListener('click', () => {
        const isDark = body.classList.contains('dark-mode');
        if (isDark) {
            body.classList.remove('dark-mode');
            body.classList.add('light-mode');
            btn.querySelector('i').className = 'fa-solid fa-sun';
            btn.querySelector('span').textContent = 'Light Mode';
            localStorage.setItem('theme', 'light');
            rethemeCharts(false);
        } else {
            body.classList.remove('light-mode');
            body.classList.add('dark-mode');
            btn.querySelector('i').className = 'fa-solid fa-moon';
            btn.querySelector('span').textContent = 'Dark Mode';
            localStorage.setItem('theme', 'dark');
            rethemeCharts(true);
        }
    });
}

// User Info
async function fetchUserProfile() {
    try {
        const response = await fetch('/api/auth/me');
        if (response.ok) {
            currentUser = await response.json();
            document.getElementById('sidebarUsername').textContent = currentUser.username;
            document.getElementById('sidebarRole').textContent = currentUser.role;
            
            // Adjust permission constraints based on role
            if (currentUser.role === 'Viewer') {
                disableWriteControls();
            }
        } else {
            window.location.href = '/login';
        }
    } catch (err) {
        window.location.href = '/login';
    }
}

function disableWriteControls() {
    // Hide or disable fields that Viewers shouldn't interact with
    const launchBtn = document.getElementById('launchTestBtn');
    if (launchBtn) launchBtn.disabled = true;
    
    const savePresetBtn = document.getElementById('savePresetBtn');
    if (savePresetBtn) savePresetBtn.disabled = true;
    
    // Disable control buttons on active session banners
    const controlButtons = ['bannerPauseBtn', 'bannerResumeBtn', 'bannerStopBtn'];
    controlButtons.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.disabled = true;
    });
}

// Navigation Handling
function initNavigation() {
    const items = document.querySelectorAll('.menu-item');
    items.forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            const tabId = item.getAttribute('data-tab');
            switchTab(tabId);
        });
    });

    // Logout
    document.getElementById('logoutBtn').addEventListener('click', async (e) => {
        e.preventDefault();
        const response = await fetch('/api/auth/logout', { method: 'POST' });
        if (response.ok) {
            window.location.href = '/login';
        }
    });
}

function switchTab(tabId) {
    // Update active tab buttons
    document.querySelectorAll('.menu-item').forEach(item => {
        if (item.getAttribute('data-tab') === tabId) {
            item.classList.add('active');
        } else {
            item.classList.remove('active');
        }
    });

    // Update active tab pane
    document.querySelectorAll('.tab-pane').forEach(pane => {
        if (pane.id === `tab-${tabId}`) {
            pane.classList.add('active');
        } else {
            pane.classList.remove('active');
        }
    });

    // Update header page title
    const titles = {
        'monitoring': 'Monitoring Dashboard',
        'configurator': 'Configure New Test Session',
        'templates': 'Saved Configuration Presets',
        'history': 'Test Session Execution History'
    };
    document.getElementById('pageTitle').textContent = titles[tabId] || 'Dashboard';
}

// Load configurations list
async function loadSavedPresets() {
    try {
        const response = await fetch('/api/configurations');
        if (!response.ok) return;
        const data = await response.json();
        
        const container = document.getElementById('presetsGridContainer');
        container.innerHTML = '';
        
        if (data.length === 0) {
            container.innerHTML = `<div class="text-center text-muted" style="padding: 40px; grid-column: 1 / -1;">No saved presets found. Create and save one from the "New Test" tab!</div>`;
            return;
        }

        // Helpers to parse distribution stats beautifully
        const parseDistribution = (str) => {
            const result = {};
            if (!str) return result;
            str.split(',').forEach(item => {
                const parts = item.split(':');
                if (parts[0] && parts[1]) {
                    result[parts[0].trim().toLowerCase()] = parseFloat(parts[1]);
                }
            });
            return result;
        };

        const formatNetworkSummary = (str) => {
            const dist = parseDistribution(str);
            const entries = Object.entries(dist);
            if (entries.length === 0) return 'Generic';
            // Pick the one with the highest weight
            entries.sort((a, b) => b[1] - a[1]);
            return `${entries[0][0].replace(/_/g, ' ').toUpperCase()} (${entries[0][1].toFixed(0)}%)`;
        };

        const buildProgressBar = (str) => {
            const dist = parseDistribution(str);
            let html = '';
            const colors = {
                'desktop': 'desktop', 'laptop': 'desktop', 'workstation': 'desktop',
                'android_phone': 'mobile', 'iphone': 'mobile', 'phablet': 'mobile',
                'android_tablet': 'tablet', 'ipad': 'tablet', 'windows_tablet': 'tablet'
            };
            
            Object.entries(dist).forEach(([key, val]) => {
                if (val <= 0) return;
                const type = colors[key] || 'other';
                html += `<div class="dist-segment ${type}" style="width: ${val}%;" title="${key}: ${val.toFixed(1)}%"></div>`;
            });
            return html || '<div class="dist-segment other" style="width: 100%;"></div>';
        };

        const buildLabels = (str) => {
            const dist = parseDistribution(str);
            const counts = { desktop: 0, mobile: 0, tablet: 0, other: 0 };
            
            const desktopKeys = ['desktop', 'laptop', 'workstation', 'chromebook', 'windows_2_in_1'];
            const mobileKeys = ['android_phone', 'iphone', 'phablet', 'android_webview', 'ios_webview', 'pwa_runtime_mobile'];
            const tabletKeys = ['android_tablet', 'ipad', 'windows_tablet', 'android_foldable', 'pwa_runtime_tablet'];

            Object.entries(dist).forEach(([key, val]) => {
                if (desktopKeys.includes(key)) counts.desktop += val;
                else if (mobileKeys.includes(key)) counts.mobile += val;
                else if (tabletKeys.includes(key)) counts.tablet += val;
                else counts.other += val;
            });

            let labels = [];
            if (counts.desktop > 0) labels.push(`<span>💻 Desk: ${counts.desktop.toFixed(0)}%</span>`);
            if (counts.mobile > 0) labels.push(`<span>📱 Mob: ${counts.mobile.toFixed(0)}%</span>`);
            if (counts.tablet > 0) labels.push(`<span>平板 Tab: ${counts.tablet.toFixed(0)}%</span>`);
            if (counts.other > 0) labels.push(`<span>⚙️ Other: ${counts.other.toFixed(0)}%</span>`);

            return labels.join(' | ') || 'Default Mix';
        };

        data.forEach(cfg => {
            const card = document.createElement('div');
            card.className = 'preset-card';
            card.innerHTML = `
                <div class="preset-card-header">
                    <div class="preset-title-wrap">
                        <span class="preset-icon"><i class="fa-solid fa-bookmark"></i></span>
                        <h4>${escapeHtml(cfg.name)}</h4>
                    </div>
                    ${currentUser.role === 'Admin' ? `<button class="btn-delete" onclick="deletePreset(${cfg.id})" title="Delete Preset"><i class="fa-solid fa-trash"></i></button>` : ''}
                </div>
                <div class="preset-card-body">
                    <div class="preset-meta-row">
                        <span><i class="fa-solid fa-door-open" style="margin-right: 4px;"></i> Room: <code>${escapeHtml(cfg.room)}</code></span>
                        <span><i class="fa-solid fa-users" style="margin-right: 4px;"></i> Bots: <strong>${cfg.bots}</strong></span>
                    </div>
                    <div class="preset-meta-row">
                        <span><i class="fa-solid fa-wifi" style="margin-right: 4px;"></i> Net: <strong>${formatNetworkSummary(cfg.network_conditions)}</strong></span>
                        <span><i class="fa-solid fa-circle-nodes" style="margin-right: 4px;"></i> WebRTC: <span class="badge ${cfg.webrtc_enabled ? 'badge-running' : 'badge-stopped'}">${cfg.webrtc_enabled ? 'Active' : 'Disabled'}</span></span>
                    </div>
                    <div class="preset-dist-bar-wrap">
                        <label>Hardware Device Distribution</label>
                        <div class="dist-progress-bar">
                            ${buildProgressBar(cfg.device_distribution)}
                        </div>
                        <div class="dist-labels">
                            ${buildLabels(cfg.device_distribution)}
                        </div>
                    </div>
                </div>
                <div class="preset-card-footer">
                    <button class="btn btn-primary btn-load-preset" onclick="loadConfigIntoForm(${cfg.id})"><i class="fa-solid fa-folder-open" style="margin-right: 6px;"></i> Load Preset Config</button>
                </div>
            `;
            container.appendChild(card);
        });
    } catch (err) {
        console.error("Failed to load presets: ", err);
    }
}

// Load session history list
async function loadSessionHistory() {
    try {
        const response = await fetch('/api/sessions');
        if (!response.ok) return;
        const data = await response.json();
        
        const tbody = document.getElementById('historyTableBody');
        tbody.innerHTML = '';
        
        if (data.length === 0) {
            tbody.innerHTML = `<tr><td colspan="7" class="text-center text-muted">No previous sessions found.</td></tr>`;
            return;
        }

        data.forEach(sess => {
            const duration = calculateDuration(sess.started_at, sess.ended_at);
            const badgeClass = {
                'running': 'badge-running',
                'paused': 'badge-stopped',
                'completed': 'badge-completed',
                'stopped': 'badge-stopped',
                'failed': 'badge-failed'
            }[sess.status] || 'badge-stopped';

            const isFinished = sess.status === 'completed' || sess.status === 'stopped' || sess.status === 'failed';

            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>#${sess.id}</td>
                <td><strong>${escapeHtml(sess.name)}</strong></td>
                <td><span class="badge ${badgeClass}">${sess.status}</span></td>
                <td>${sess.started_at ? new Date(sess.started_at).toLocaleString() : 'N/A'}</td>
                <td>${duration}</td>
                <td>
                    <div class="btn-group">
                        <button class="btn btn-sm btn-secondary" onclick="viewHistoricalLogs(${sess.id})" title="View Logs"><i class="fa-solid fa-terminal"></i> Logs</button>
                        ${isFinished ? `<button class="btn btn-sm btn-secondary" onclick="triggerReportDownload(${sess.id}, 'docx')" title="Download Word"><i class="fa-solid fa-file-word text-cyan"></i> DOCX</button>` : ''}
                        ${isFinished ? `<button class="btn btn-sm btn-secondary" onclick="triggerReportDownload(${sess.id}, 'pdf')" title="Download PDF"><i class="fa-solid fa-file-pdf text-red"></i> PDF</button>` : ''}
                        ${isFinished ? `<button class="btn btn-sm btn-secondary" onclick="triggerReportDownload(${sess.id}, 'csv')" title="Download CSV"><i class="fa-solid fa-file-csv text-green"></i> CSV</button>` : ''}
                    </div>
                </td>
                <td>
                    <button class="btn btn-sm btn-primary" onclick="cloneSession(${sess.id})" title="Clone Config"><i class="fa-solid fa-clone"></i> Clone</button>
                </td>
            `;
            tbody.appendChild(tr);
        });
    } catch (err) {
        console.error("Failed to load history: ", err);
    }
}

// Active session scanner
async function checkForRunningSession() {
    try {
        const response = await fetch('/api/sessions');
        if (!response.ok) return;
        const data = await response.json();
        
        const active = data.find(s => s.status === 'running' || s.status === 'paused' || s.status === 'pending');
        if (active) {
            setupActiveSession(active.id, active.name, active.status);
        }
    } catch (err) {
        console.error("Failed to check active sessions: ", err);
    }
}

// Set UI state for active load test session
async function setupActiveSession(sessionId, sessionName, status) {
    currentActiveSessionId = sessionId;
    
    // Hide placeholder, show live dashboard grids
    document.getElementById('noActiveSessionPrompt').classList.add('hidden');
    document.getElementById('monitoringGrid').classList.remove('hidden');
    
    // Disable Launch Button on form configurator
    const launchBtn = document.getElementById('launchTestBtn');
    if (launchBtn) launchBtn.disabled = true;
    
    // Show Top bar controls
    const banner = document.getElementById('activeTestBanner');
    banner.classList.remove('hidden');
    document.getElementById('bannerSessionName').textContent = sessionName;
    
    updateBannerStatusText(status);

    // 1. Fetch session config details to apply and show the timeout on the WebRTC card
    try {
        const res = await fetch(`/api/sessions/${sessionId}`);
        if (res.ok) {
            const sess = await res.json();
            if (sess.config) {
                window.activeSessionTotalBots = sess.config.bots;
                const activeTimeoutEl = document.getElementById('webrtcActiveTimeout');
                if (activeTimeoutEl) {
                    activeTimeoutEl.textContent = (sess.config.confirm_timeout || 5.0).toFixed(1);
                }
                
                // Store active SLA thresholds
                window.activeSessionSlaSuccess = sess.config.sla_success_rate !== undefined ? sess.config.sla_success_rate : 95.0;
                window.activeSessionSlaLatency = sess.config.sla_latency !== undefined ? sess.config.sla_latency : 500.0;
                window.activeSessionSlaLoss = sess.config.sla_packet_loss !== undefined ? sess.config.sla_packet_loss : 2.0;
                window.activeSessionSlaJitter = sess.config.sla_jitter !== undefined ? sess.config.sla_jitter : 30.0;
                
                // Populate dashboard SLA labels
                const targetSuccessEl = document.getElementById('slaTargetSuccess');
                const targetLatencyEl = document.getElementById('slaTargetLatency');
                const targetLossEl = document.getElementById('slaTargetLoss');
                
                if (targetSuccessEl) targetSuccessEl.textContent = window.activeSessionSlaSuccess.toFixed(1);
                if (targetLatencyEl) targetLatencyEl.textContent = window.activeSessionSlaLatency.toFixed(0);
                if (targetLossEl) targetLossEl.textContent = window.activeSessionSlaLoss.toFixed(1);
            }
        }
    } catch (e) {
        console.error("Failed to load active session config: ", e);
    }

    // 2. Pre-populate metrics cards and charts with existing history
    try {
        const mResponse = await fetch(`/api/sessions/${sessionId}/metrics`);
        if (mResponse.ok) {
            const mData = await mResponse.json();
            clearCharts();
            mData.forEach(m => {
                const timeStr = new Date(m.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
                updateCharts(timeStr, m);
            });
            if (mData.length > 0) {
                // Read logs to get final lifecycle counts
                const lResponse = await fetch(`/api/sessions/${sessionId}/logs?limit=2000`);
                if (lResponse.ok) {
                    const logs = await lResponse.json();
                    
                    window.consoleLogsBuffer = [];
                    logs.forEach(evt => pushToConsoleBuffer(evt));
                    renderAllConsoleLogs();
                    
                    const currentLifecycle = aggregateLifecycleFromLogs(logs);
                    updateMetricsCards(mData[mData.length - 1], currentLifecycle);
                } else {
                    updateMetricsCards(mData[mData.length - 1], null);
                }
            }
        }
    } catch (e) {
        console.error("Failed to load historical metrics: ", e);
    }

    // 3. Initialise WebSockets Socket.IO client connection
    initWebSocket(sessionId);
    
    // 4. Start the session timer ticking
    startSessionTimer(sessionId);
}

function startSessionTimer(sessionId) {
    if (sessionTimerInterval) {
        clearInterval(sessionTimerInterval);
        sessionTimerInterval = null;
    }
    
    fetch(`/api/sessions/${sessionId}`)
        .then(res => {
            if (res.ok) return res.json();
        })
        .then(sess => {
            if (!sess) return;
            syncTimer(sess.elapsed_seconds || 0, sess.status);
            
            if (sess.status === 'running') {
                sessionTimerInterval = setInterval(() => {
                    updateTimerDisplay(sess.status);
                }, 1000);
            }
        })
        .catch(err => console.error("Error starting session timer: ", err));
}

function syncTimer(backendSeconds, status) {
    localTimerBaseSeconds = backendSeconds;
    localTimerStartRealTime = Date.now();
    localElapsedSeconds = backendSeconds;
    renderTimerDisplay(localElapsedSeconds);
}

function renderTimerDisplay(secsCount) {
    const timerEl = document.getElementById('bannerSessionTimer');
    if (!timerEl) return;
    
    const hrs = Math.floor(secsCount / 3600);
    const mins = Math.floor((secsCount % 3600) / 60);
    const secs = secsCount % 60;
    
    let timeStr = "";
    if (hrs > 0) {
        timeStr += String(hrs).padStart(2, '0') + ":";
    }
    timeStr += String(mins).padStart(2, '0') + ":" + String(secs).padStart(2, '0');
    timerEl.textContent = timeStr;
}

function updateTimerDisplay(status) {
    if (status !== 'running') {
        clearInterval(sessionTimerInterval);
        sessionTimerInterval = null;
        return;
    }
    
    const deltaSecs = Math.floor((Date.now() - localTimerStartRealTime) / 1000);
    localElapsedSeconds = localTimerBaseSeconds + deltaSecs;
    renderTimerDisplay(localElapsedSeconds);
}

function updateBannerStatusText(status) {
    const badge = document.getElementById('bannerSessionStatus');
    badge.textContent = status.toUpperCase();
    badge.className = 'badge';
    
    const pauseBtn = document.getElementById('bannerPauseBtn');
    const resumeBtn = document.getElementById('bannerResumeBtn');
    
    if (status === 'running') {
        badge.className = 'badge badge-running';
        pauseBtn.classList.remove('hidden');
        resumeBtn.classList.add('hidden');
        if (!sessionTimerInterval && currentActiveSessionId) {
            startSessionTimer(currentActiveSessionId);
        }
    } else if (status === 'paused') {
        badge.className = 'badge badge-running'; // Keep flashing
        badge.style.backgroundColor = 'var(--warning-soft)';
        badge.style.color = 'var(--warning)';
        pauseBtn.classList.add('hidden');
        resumeBtn.classList.remove('hidden');
        if (sessionTimerInterval) {
            clearInterval(sessionTimerInterval);
            sessionTimerInterval = null;
        }
    } else if (status === 'pending') {
        badge.className = 'badge badge-stopped';
        badge.style.backgroundColor = 'var(--warning-soft)';
        badge.style.color = 'var(--warning)';
        pauseBtn.classList.add('hidden');
        resumeBtn.classList.add('hidden');
        const timerEl = document.getElementById('bannerSessionTimer');
        if (timerEl) timerEl.textContent = '00:00';
        if (sessionTimerInterval) {
            clearInterval(sessionTimerInterval);
            sessionTimerInterval = null;
        }
    }
}

// WebSocket connection setup
function initWebSocket(sessionId) {
    if (socket) {
        socket.disconnect();
    }

    socket = io();

    socket.on('connect', () => {
        console.log("WebSocket connected. Joining session room: " + sessionId);
        socket.emit('join', { session_id: sessionId });
        
        // Update server status to online
        const statusIndicator = document.querySelector('.status-indicator');
        const statusText = document.querySelector('.status-text');
        if (statusIndicator && statusText) {
            statusIndicator.className = 'status-indicator online';
            statusIndicator.style.backgroundColor = 'var(--success)';
            statusIndicator.style.boxShadow = '0 0 8px var(--success)';
            statusText.textContent = 'Server Status: Online';
        }
        
        // Append system message in log terminal
        const consoleEl = document.getElementById('consoleTerminal');
        const placeholder = consoleEl.querySelector('.console-placeholder');
        if (placeholder) placeholder.remove();
        
        const entry = document.createElement('div');
        entry.className = 'log-entry';
        entry.innerHTML = `<span class="ts">[SYSTEM]</span> <span class="info" style="color: var(--success); font-weight: 500;">Connected to real-time event streaming.</span>`;
        consoleEl.appendChild(entry);
        consoleEl.scrollTop = consoleEl.scrollHeight;
    });

    socket.on('disconnect', (reason) => {
        console.warn("WebSocket disconnected: ", reason);
        const statusIndicator = document.querySelector('.status-indicator');
        const statusText = document.querySelector('.status-text');
        if (statusIndicator && statusText) {
            statusIndicator.className = 'status-indicator offline';
            statusIndicator.style.backgroundColor = 'var(--error)';
            statusIndicator.style.boxShadow = '0 0 8px var(--error)';
            statusText.textContent = 'Server Status: Offline (Reconnecting...)';
        }
    });

    socket.on('connect_error', (error) => {
        console.error("WebSocket connection error: ", error);
        const statusIndicator = document.querySelector('.status-indicator');
        const statusText = document.querySelector('.status-text');
        if (statusIndicator && statusText) {
            statusIndicator.className = 'status-indicator offline';
            statusIndicator.style.backgroundColor = 'var(--error)';
            statusIndicator.style.boxShadow = '0 0 8px var(--error)';
            statusText.textContent = 'Server Status: Offline (Connection Error)';
        }
    });

    // Listen for raw logs in batch
    socket.on('session_raw_events_batch', (payload) => {
        if (payload.session_id !== sessionId) return;
        payload.events.forEach(evt => {
            pushToConsoleBuffer(evt);
        });
        renderAllConsoleLogs();
    });

    // Listen for fallback stdout console logs
    socket.on('session_console_log', (payload) => {
        if (payload.session_id !== sessionId) return;
        const consoleEl = document.getElementById('consoleTerminal');
        const placeholder = consoleEl.querySelector('.console-placeholder');
        if (placeholder) placeholder.remove();
        
        const entry = document.createElement('div');
        entry.className = 'log-entry';
        entry.innerHTML = `
            <span class="ts">[STDOUT]</span>
            <span class="info">${escapeHtml(payload.log)}</span>
        `;
        consoleEl.appendChild(entry);
        if (window.autoScroll) {
            consoleEl.scrollTop = consoleEl.scrollHeight;
        }
    });

    // Listen for metrics updates
    socket.on('session_metrics', (payload) => {
        if (payload.session_id !== sessionId) return;
        
        // Sync local timer base
        if (payload.elapsed_seconds !== undefined) {
            localTimerBaseSeconds = payload.elapsed_seconds;
            localTimerStartRealTime = Date.now();
        }
        
        updateMetricsCards(payload.metrics, payload.lifecycle_summary);
    });

    // Listen for session completion status
    socket.on('session_status_changed', (payload) => {
        if (payload.session_id !== sessionId) return;
        
        if (payload.status === 'completed' || payload.status === 'stopped' || payload.status === 'failed') {
            handleSessionFinished(payload.status);
        } else {
            updateBannerStatusText(payload.status);
        }
    });
}

// Log Terminal data storage and filter helpers
function pushToConsoleBuffer(evt) {
    if (!evt) return;
    
    // Track event throughput
    window.eventCountLastSecond++;
    
    // Save bot fingerprints / metadata dynamically
    const etype = evt.event;
    if (etype === "bot_joined" && evt.bot_id) {
        window.botsFingerprints[evt.bot_id] = evt.fingerprint || {};
        window.botsMetadata[evt.bot_id] = {
            name: evt.name,
            email: evt.email,
            role: "attendee"
        };
    } else if (etype === "action_logged" && evt.bot_id) {
        if (!window.botsMetadata[evt.bot_id]) {
            window.botsMetadata[evt.bot_id] = {
                name: evt.name,
                email: evt.email,
                role: evt.role || "attendee"
            };
        } else if (evt.role) {
            window.botsMetadata[evt.bot_id].role = evt.role;
        }
        const fp = evt.fingerprint;
        if (fp) {
            window.botsFingerprints[evt.bot_id] = fp;
        }
    }
    
    window.consoleLogsBuffer.push(evt);
    if (window.consoleLogsBuffer.length > window.maxConsoleLogs) {
        window.consoleLogsBuffer.shift();
    }
}

function getLogHtmlAndMessage(evt) {
    const etype = evt.event;
    let logMsg = "";
    let statusClass = "info";
    
    const botId = evt.bot_id;
    let metaStr = "";
    if (botId) {
        const fp = window.botsFingerprints[botId];
        if (fp) {
            const browser = fp.browser_name || fp.browser_type || "unknown";
            const device = fp.device_type || "unknown";
            metaStr = ` <span class="log-meta">[${browser} | ${device}]</span>`;
        }
    }
    
    if (etype === "test_started") {
        logMsg = `🚀 Load test started at ${evt.ts}`;
        statusClass = "info";
    } else if (etype === "test_config") {
        logMsg = `⚙️ Configuration applied: Room=${evt.room}, Bots=${evt.bots}, Concurrency=${evt.concurrency}, WebRTC=${evt.webrtc_enabled}`;
        statusClass = "info";
    } else if (etype === "bot_joined") {
        logMsg = `🌐 Bot-${evt.bot_id} (${evt.name}) joined via browser emulator [${evt.fingerprint.browser_name} | ${evt.fingerprint.device_type} | ${evt.fingerprint.os_type}]`;
        statusClass = "tag";
    } else if (etype === "action_logged") {
        const value = evt.action_value;
        const latency = evt.latency_ms ? ` (propagation: ${evt.latency_ms.toFixed(1)}ms)` : "";
        if (evt.status === "confirmed") {
            logMsg = `✅ Bot-${evt.bot_id} (${evt.name}) action confirmed: ${evt.action_type} → ${value}${latency}${metaStr}`;
            statusClass = "info";
        } else if (evt.status.startsWith("observed:")) {
            logMsg = `👀 Bot-${evt.bot_id} (${evt.name}) observed ${evt.status.split(":", 2)[1]} performing: ${evt.action_type} → ${value}${latency}${metaStr}`;
            statusClass = "tag";
        } else if (evt.status === "timed_out") {
            logMsg = `⚠️ Bot-${evt.bot_id} (${evt.name}) action confirmation timeout on: ${evt.action_type}${metaStr}`;
            statusClass = "warn";
        } else {
            logMsg = `❌ Bot-${evt.bot_id} (${evt.name}) action failed: ${evt.action_type}${metaStr}`;
            statusClass = "error";
        }
    } else if (etype === "error_logged") {
        logMsg = `🚨 Bot-${evt.bot_id} (${evt.name}) error on action [${evt.action}]: ${evt.error}${metaStr}`;
        statusClass = "error";
    } else if (etype === "test_finished") {
        logMsg = `📊 Load test finished. Summary written to log database.`;
        statusClass = "info";
    }

    if (!logMsg) return null;

    const timeStr = new Date(evt.ts).toLocaleTimeString();
    const html = `
        <span class="ts">[${timeStr}]</span>
        <span class="${statusClass}">${logMsg}</span>
    `;
    const plainText = `[${timeStr}] Bot-${evt.bot_id || ''} ${logMsg}`;
    
    return { html, text: plainText };
}

function renderAllConsoleLogs() {
    const consoleEl = document.getElementById('consoleTerminal');
    if (!consoleEl) return;
    
    const filter = document.getElementById('logLevelFilter').value;
    const search = document.getElementById('logSearchInput').value.toLowerCase();
    
    const fragment = document.createDocumentFragment();
    let matchCount = 0;
    
    window.consoleLogsBuffer.forEach(evt => {
        const etype = evt.event;
        if (filter !== 'all' && filter !== etype) return;
        
        const logData = getLogHtmlAndMessage(evt);
        if (!logData) return;
        
        if (search && !logData.text.toLowerCase().includes(search)) return;
        
        const entry = document.createElement('div');
        entry.className = 'log-entry';
        entry.innerHTML = logData.html;
        fragment.appendChild(entry);
        matchCount++;
    });
    
    // Detach or write innerHTML in single pass
    consoleEl.innerHTML = '';
    if (matchCount === 0) {
        consoleEl.innerHTML = `<div class="console-placeholder">No matching logs found.</div>`;
    } else {
        consoleEl.appendChild(fragment);
        if (window.autoScroll) {
            consoleEl.scrollTop = consoleEl.scrollHeight;
        }
    }
}

function setupConsoleFilters() {
    // 1. Search filter input listener with 150ms debounce
    const searchInput = document.getElementById('logSearchInput');
    if (searchInput) {
        searchInput.addEventListener('input', () => {
            if (window.searchDebounce) clearTimeout(window.searchDebounce);
            window.searchDebounce = setTimeout(() => {
                renderAllConsoleLogs();
            }, 150);
        });
    }

    // 2. Dropdown type filter change
    const levelFilter = document.getElementById('logLevelFilter');
    if (levelFilter) {
        levelFilter.addEventListener('change', () => {
            renderAllConsoleLogs();
        });
    }

    // 3. Scroll Toggle click
    const toggleScrollBtn = document.getElementById('toggleScrollBtn');
    if (toggleScrollBtn) {
        toggleScrollBtn.addEventListener('click', () => {
            window.autoScroll = !window.autoScroll;
            if (window.autoScroll) {
                toggleScrollBtn.innerHTML = '<i class="fa-solid fa-pause"></i> Pause Scroll';
                toggleScrollBtn.classList.remove('btn-warning');
                toggleScrollBtn.classList.add('btn-secondary');
                const consoleEl = document.getElementById('consoleTerminal');
                if (consoleEl) consoleEl.scrollTop = consoleEl.scrollHeight;
            } else {
                toggleScrollBtn.innerHTML = '<i class="fa-solid fa-play"></i> Resume Scroll';
                toggleScrollBtn.classList.remove('btn-secondary');
                toggleScrollBtn.classList.add('btn-warning');
            }
        });
    }
}

function startEventsRateCounter() {
    if (window.eventsRateInterval) {
        clearInterval(window.eventsRateInterval);
    }
    
    window.eventsRateInterval = setInterval(() => {
        const eventsRateEl = document.getElementById('metricEventsRate');
        if (eventsRateEl) {
            eventsRateEl.textContent = window.eventCountLastSecond;
        }
        window.eventCountLastSecond = 0;
    }, 1000);
}

// Live card values updater
function updateMetricsCards(metrics, lifecycleSummary) {
    const totalBots = window.activeSessionTotalBots || 0;
    document.getElementById('metricConnectedBots').textContent = `${metrics.connected_bots} / ${totalBots}`;
    document.getElementById('metricConnectingBots').textContent = metrics.connecting_bots;
    document.getElementById('metricReconnectingBots').textContent = metrics.reconnecting_bots;
    document.getElementById('metricFailedBots').textContent = metrics.failed_bots;
    const leftEl = document.getElementById('metricLeftBots');
    if (leftEl) {
        leftEl.textContent = metrics.left_bots !== undefined ? metrics.left_bots : 0;
    }
    
    document.getElementById('metricLatency').textContent = metrics.avg_latency ? metrics.avg_latency.toFixed(1) : '0';
    document.getElementById('metricPacketLoss').textContent = metrics.packet_loss ? metrics.packet_loss.toFixed(2) : '0.00';
    document.getElementById('metricBitrate').textContent = metrics.bitrate || '0';

    // SLA violation evaluations for Latency and Packet Loss
    const latencyCard = document.getElementById('metricLatency').closest('.metric-card');
    if (latencyCard && window.activeSessionSlaLatency) {
        if (metrics.avg_latency > window.activeSessionSlaLatency) {
            latencyCard.classList.add('sla-violated');
        } else {
            latencyCard.classList.remove('sla-violated');
        }
    }

    const lossCard = document.getElementById('metricPacketLoss').closest('.metric-card');
    if (lossCard && window.activeSessionSlaLoss) {
        if (metrics.packet_loss > window.activeSessionSlaLoss) {
            lossCard.classList.add('sla-violated');
        } else {
            lossCard.classList.remove('sla-violated');
        }
    }

    // Update real-time lifecycle widgets if available
    if (lifecycleSummary) {
        // Calculate and display Action Success Rate
        if (lifecycleSummary.status_counts) {
            const sc = lifecycleSummary.status_counts;
            const totalActions = (sc.sent || 0) + (sc.acknowledged || 0) + (sc.broadcasted || 0) + (sc.observed || 0) + (sc.rendered || 0) + (sc['timed-out'] || 0) + (sc.failed || 0);
            const successActions = (sc.acknowledged || 0) + (sc.broadcasted || 0) + (sc.observed || 0) + (sc.rendered || 0);
            const successRate = totalActions > 0 ? ((successActions / totalActions) * 100.0) : 100.0;
            
            const rateEl = document.getElementById('metricSuccessRate');
            if (rateEl) rateEl.textContent = successRate.toFixed(1);
            
            // Success Rate SLA Check
            const successCard = rateEl.closest('.metric-card');
            if (successCard && window.activeSessionSlaSuccess) {
                if (successRate < window.activeSessionSlaSuccess) {
                    successCard.classList.add('sla-violated');
                } else {
                    successCard.classList.remove('sla-violated');
                }
            }
            
            document.getElementById('lifecycleSent').textContent = sc.sent || 0;
            document.getElementById('lifecycleAcknowledged').textContent = sc.acknowledged || 0;
            document.getElementById('lifecycleBroadcasted').textContent = sc.broadcasted || 0;
            document.getElementById('lifecycleObserved').textContent = sc.observed || 0;
            document.getElementById('lifecycleRendered').textContent = sc.rendered || 0;
        }

        // Update peak latency in Average Latency sublabel
        if (lifecycleSummary.webrtc_advanced) {
            const webrtc = lifecycleSummary.webrtc_advanced;
            const peakEl = document.getElementById('metricPeakLatency');
            if (peakEl) peakEl.textContent = webrtc.peak_latency ? webrtc.peak_latency.toFixed(0) : '0';
            
            document.getElementById('webrtcAvgRtt').textContent = webrtc.rtt ? webrtc.rtt.toFixed(1) : '0';
            document.getElementById('webrtcAvgJitter').textContent = webrtc.jitter ? webrtc.jitter.toFixed(1) : '0';
            document.getElementById('webrtcTurnCount').textContent = webrtc.turn_count || 0;
            document.getElementById('webrtcRelayCount').textContent = webrtc.relay_count || 0;
        }
        
        // Dynamically update signaling socket and ICE states if active bots > 0
        if (metrics.connected_bots > 0) {
            document.getElementById('webrtcSignalSocket').textContent = "CONNECTED";
            document.getElementById('webrtcSignalSocket').className = "badge badge-running";
            document.getElementById('webrtcIceState').textContent = "COMPLETED";
            document.getElementById('webrtcIceState').className = "badge badge-completed";
        } else {
            document.getElementById('webrtcSignalSocket').textContent = "DISCONNECTED";
            document.getElementById('webrtcSignalSocket').className = "badge badge-failed";
            document.getElementById('webrtcIceState').textContent = "CHECKING";
            document.getElementById('webrtcIceState').className = "badge badge-stopped";
        }

        // 3. Timeout Stage Breakdown
        if (lifecycleSummary.timeout_stages) {
            const to = lifecycleSummary.timeout_stages;
            document.getElementById('timeoutAck').textContent = to['ack-timeout'] || 0;
            document.getElementById('timeoutBroadcast').textContent = to['broadcast-timeout'] || 0;
            document.getElementById('timeoutObserver').textContent = to['observer-timeout'] || 0;
            document.getElementById('timeoutUiRender').textContent = to['ui-render-timeout'] || 0;
            document.getElementById('timeoutIdMismatch').textContent = to['id-correlation-mismatch'] || 0;
        }

        // 4. Unsupported Actions Breakdown List
        if (lifecycleSummary.unsupported_reasons) {
            const listEl = document.getElementById('unsupportedBreakdownList');
            if (listEl) {
                listEl.innerHTML = '';
                const entries = Object.entries(lifecycleSummary.unsupported_reasons);
                if (entries.length === 0) {
                    listEl.innerHTML = '<div class="text-center text-muted" style="padding: 20px 0;">No unsupported actions logged.</div>';
                } else {
                    entries.forEach(([reason, count]) => {
                        const row = document.createElement('div');
                        row.className = 'prop-stage';
                        row.style.display = 'flex';
                        row.style.justify = 'space-between';
                        row.style.alignItems = 'center';
                        row.style.borderBottom = '1px solid var(--border-color)';
                        row.style.paddingBottom = '6px';
                        row.innerHTML = `
                            <span style="font-size: 12px; color: var(--text-secondary); text-overflow: ellipsis; overflow: hidden; white-space: nowrap; max-width: 80%;" title="${escapeHtml(reason)}">
                                <i class="fa-solid fa-circle-minus" style="color: var(--text-muted); margin-right: 6px;"></i>${escapeHtml(reason)}
                            </span>
                            <span class="badge badge-stopped" style="font-size: 11px; min-width: 25px; text-align: center; background-color: var(--border-color); color: var(--text-primary);">${count}</span>
                        `;
                        listEl.appendChild(row);
                    });
                }
            }
        }
    }

    // Append to charts
    const timeStr = new Date(metrics.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    updateCharts(timeStr, metrics);
}

// Close session actions on completion
function handleSessionFinished(status) {
    if (socket) {
        socket.disconnect();
        socket = null;
    }
    
    if (sessionTimerInterval) {
        clearInterval(sessionTimerInterval);
        sessionTimerInterval = null;
    }
    
    // Clear events rate interval
    if (window.eventsRateInterval) {
        clearInterval(window.eventsRateInterval);
        window.eventsRateInterval = null;
    }
    const eventsRateEl = document.getElementById('metricEventsRate');
    if (eventsRateEl) eventsRateEl.textContent = '0';
    
    const timerEl = document.getElementById('bannerSessionTimer');
    if (timerEl) timerEl.textContent = '00:00';
    
    currentActiveSessionId = null;
    
    // Enable Launch Button on form configurator
    const launchBtn = document.getElementById('launchTestBtn');
    if (launchBtn) launchBtn.disabled = false;
    
    // Hide controls
    document.getElementById('activeTestBanner').classList.add('hidden');
    
    // Show completed indicator alert
    alert(`Load test session finished with status: ${status.toUpperCase()}. You can now download the docx and pdf reports from the history tab.`);
    
    // Refresh history
    loadSessionHistory();
    
    // Reset monitoring prompts
    document.getElementById('noActiveSessionPrompt').classList.remove('hidden');
    document.getElementById('monitoringGrid').classList.add('hidden');
    clearCharts();
}

// Setup Form Submission handlers
function setupFormActions() {
    // Form Configurator submit
    const form = document.getElementById('testConfigForm');
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        if (currentActiveSessionId) {
            alert("A load test session is currently running. Stop it before spawning a new one.");
            return;
        }

        const formData = getFormData();
        
        try {
            const response = await fetch('/api/sessions/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(formData)
            });
            
            const data = await response.json();
            if (response.ok) {
                switchTab('monitoring');
                setupActiveSession(data.id, data.name, 'running');
                loadSessionHistory();
            } else {
                alert("Launch failed: " + data.message);
            }
        } catch (err) {
            alert("Launch request failed.");
        }
    });

    // Save Preset button click
    document.getElementById('savePresetBtn').addEventListener('click', async () => {
        const name = prompt("Enter a unique name for this Configuration Preset:");
        if (!name) return;
        
        const formData = getFormData();
        formData.name = name;
        
        try {
            const response = await fetch('/api/configurations', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(formData)
            });
            
            const data = await response.json();
            if (response.ok) {
                alert("Preset configuration saved successfully!");
                loadSavedPresets();
            } else {
                alert("Failed to save: " + data.message);
            }
        } catch (err) {
            alert("Save request failed.");
        }
    });

    // Active session banners action click
    document.getElementById('bannerPauseBtn').addEventListener('click', async () => {
        if (!currentActiveSessionId) return;
        const resp = await fetch(`/api/sessions/${currentActiveSessionId}/pause`, { method: 'POST' });
        if (!resp.ok) alert("Pause request failed.");
    });

    document.getElementById('bannerResumeBtn').addEventListener('click', async () => {
        if (!currentActiveSessionId) return;
        const resp = await fetch(`/api/sessions/${currentActiveSessionId}/resume`, { method: 'POST' });
        if (!resp.ok) alert("Resume request failed.");
    });

    document.getElementById('bannerStopBtn').addEventListener('click', async () => {
        if (!currentActiveSessionId) return;
        if (!confirm("Are you sure you want to stop the load test? This will disconnect all bots and compile the reports.")) return;
        const resp = await fetch(`/api/sessions/${currentActiveSessionId}/stop`, { method: 'POST' });
        if (!resp.ok) alert("Stop request failed.");
    });

    // RAM & Scenario Optimization Fields Disable Toggle
    const disableCheckbox = document.getElementById('formDisableRamScenarioOpt');
    if (disableCheckbox) {
        disableCheckbox.addEventListener('change', toggleRamFields);
    }

    // Scenario Preset Select Change handler
    const presetSelect = document.getElementById('scenarioPresetSelect');
    if (presetSelect) {
        presetSelect.addEventListener('change', () => {
            document.getElementById('formTestScenarios').value = presetSelect.value;
        });
    }

    // Clear Console Console
    document.getElementById('clearConsoleBtn').addEventListener('click', () => {
        document.getElementById('consoleTerminal').innerHTML = '';
    });
}

function getFormData() {
    return {
        session_name: document.getElementById('formConfigName').value,
        room: document.getElementById('formRoom').value,
        bots: parseInt(document.getElementById('formBots').value),
        batch: parseInt(document.getElementById('formBatch').value),
        stagger: parseFloat(document.getElementById('formStagger').value),
        concurrency: parseInt(document.getElementById('formConcurrency').value),
        leave: parseInt(document.getElementById('formLeave').value),
        webrtc_enabled: document.getElementById('formWebrtcEnabled').checked,
        media_quality: document.getElementById('formMediaQuality').value,
        max_subscriptions: parseInt(document.getElementById('formMaxSubscriptions').value),
        decode_downlink: document.getElementById('formDecodeDownlink').checked,
        host_bot_id: parseInt(document.getElementById('formHostBotId').value),
        presenter_bot_id: parseInt(document.getElementById('formPresenterBotId').value),
        test_scenarios: document.getElementById('formTestScenarios').value,
        action_interval: parseFloat(document.getElementById('formActionInterval').value),
        chat_interval: parseFloat(document.getElementById('formChatInterval').value),
        confirm_timeout: parseFloat(document.getElementById('formConfirmTimeout').value),
        max_retries: parseInt(document.getElementById('formMaxRetries').value),
        no_chat: document.getElementById('formNoChat').checked,
        no_camera: document.getElementById('formNoCamera').checked,
        no_mic: document.getElementById('formNoMic').checked,
        no_handraise: document.getElementById('formNoHandraise').checked,
        no_screen_share: document.getElementById('formNoScreenShare').checked,
        no_cross_confirm: document.getElementById('formNoCrossConfirm').checked,
        frontend: document.getElementById('formFrontend').value,
        signal: document.getElementById('formSignal').value,
        jwt_secret: document.getElementById('formJwtSecret').value || null,
        network_conditions: document.getElementById('formNetworkConditions').value,
        network_degradation: document.getElementById('formNetworkDegradation').checked,
        degradation_interval: parseInt(document.getElementById('formDegradationInterval').value),
        browser_distribution: document.getElementById('formBrowserDistribution').value,
        device_distribution: document.getElementById('formDeviceDistribution').value,
        os_distribution: document.getElementById('formOsDistribution').value,
        sla_success_rate: parseFloat(document.getElementById('formSlaSuccessRate').value) || 95.0,
        sla_latency: parseFloat(document.getElementById('formSlaLatency').value) || 500.0,
        sla_packet_loss: parseFloat(document.getElementById('formSlaPacketLoss').value) || 2.0,
        sla_jitter: parseFloat(document.getElementById('formSlaJitter').value) || 30.0,
        cross_confirm_limit: parseInt(document.getElementById('formCrossConfirmLimit').value) || 10,
        camera_publishers: document.getElementById('formCameraPublishers').value,
        screen_share_publishers: document.getElementById('formScreenSharePublishers').value,
        mic_publishers: document.getElementById('formMicPublishers').value,
        viewer_bots: document.getElementById('formViewerBotIds').value,
        viewer_mode: document.getElementById('formViewerMode').value,
        auto_camera: document.getElementById('formAutoCamera').checked,
        auto_mic: document.getElementById('formAutoMic').checked,
        auto_screen_share: document.getElementById('formAutoScreenShare').checked,
        disable_ram_scenario_opt: document.getElementById('formDisableRamScenarioOpt').checked,
        refresh_bots: parseInt(document.getElementById('formRefreshBots').value) || 0,
        disable_abnormal_behavior: document.getElementById('formDisableAbnormalBehavior').checked
    };
}

function toggleRamFields() {
    const disableCheckbox = document.getElementById('formDisableRamScenarioOpt');
    if (!disableCheckbox) return;
    const disabled = disableCheckbox.checked;
    const ramFields = [
        'formCrossConfirmLimit', 'formViewerMode', 'formCameraPublishers', 
        'formMicPublishers', 'formScreenSharePublishers', 'formViewerBotIds',
        'formAutoCamera', 'formAutoMic', 'formAutoScreenShare'
    ];
    ramFields.forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.disabled = disabled;
            const fg = el.closest('.form-group');
            const ci = el.closest('.checkbox-item');
            if (fg) fg.style.opacity = disabled ? '0.5' : '1';
            if (ci) ci.style.opacity = disabled ? '0.5' : '1';
        }
    });
}

// Load template variables into the configuration form
async function loadConfigIntoForm(cfgId) {
    try {
        const response = await fetch(`/api/configurations/${cfgId}`);
        if (!response.ok) return;
        const cfg = await response.json();
        
        document.getElementById('formConfigName').value = cfg.name + " - Clone";
        document.getElementById('formRoom').value = cfg.room;
        document.getElementById('formBots').value = cfg.bots;
        document.getElementById('formBatch').value = cfg.batch;
        document.getElementById('formStagger').value = cfg.stagger;
        document.getElementById('formConcurrency').value = cfg.concurrency;
        document.getElementById('formLeave').value = cfg.leave;
        document.getElementById('formWebrtcEnabled').checked = cfg.webrtc_enabled;
        document.getElementById('formMediaQuality').value = cfg.media_quality;
        document.getElementById('formMaxSubscriptions').value = cfg.max_subscriptions;
        document.getElementById('formDecodeDownlink').checked = cfg.decode_downlink;
        document.getElementById('formHostBotId').value = cfg.host_bot_id;
        document.getElementById('formPresenterBotId').value = cfg.presenter_bot_id;
        document.getElementById('formTestScenarios').value = cfg.test_scenarios;
        document.getElementById('formActionInterval').value = cfg.action_interval;
        document.getElementById('formChatInterval').value = cfg.chat_interval;
        document.getElementById('formConfirmTimeout').value = cfg.confirm_timeout;
        document.getElementById('formMaxRetries').value = cfg.max_retries;
        document.getElementById('formNoChat').checked = cfg.no_chat;
        document.getElementById('formNoCamera').checked = cfg.no_camera;
        document.getElementById('formNoMic').checked = cfg.no_mic;
        document.getElementById('formNoHandraise').checked = cfg.no_handraise;
        document.getElementById('formNoScreenShare').checked = cfg.no_screen_share;
        document.getElementById('formNoCrossConfirm').checked = cfg.no_cross_confirm;
        document.getElementById('formFrontend').value = cfg.frontend;
        document.getElementById('formSignal').value = cfg.signal;
        document.getElementById('formJwtSecret').value = cfg.jwt_secret || '';
        document.getElementById('formNetworkConditions').value = cfg.network_conditions;
        document.getElementById('formNetworkDegradation').checked = cfg.network_degradation;
        document.getElementById('formDegradationInterval').value = cfg.degradation_interval;
        document.getElementById('formBrowserDistribution').value = cfg.browser_distribution;
        document.getElementById('formDeviceDistribution').value = cfg.device_distribution;
        document.getElementById('formOsDistribution').value = cfg.os_distribution;
        document.getElementById('formSlaSuccessRate').value = cfg.sla_success_rate !== undefined ? cfg.sla_success_rate : 95.0;
        document.getElementById('formSlaLatency').value = cfg.sla_latency !== undefined ? cfg.sla_latency : 500.0;
        document.getElementById('formSlaPacketLoss').value = cfg.sla_packet_loss !== undefined ? cfg.sla_packet_loss : 2.0;
        document.getElementById('formSlaJitter').value = cfg.sla_jitter !== undefined ? cfg.sla_jitter : 30.0;
        
        document.getElementById('formCrossConfirmLimit').value = cfg.cross_confirm_limit !== undefined ? cfg.cross_confirm_limit : 10;
        document.getElementById('formCameraPublishers').value = cfg.camera_publishers !== undefined ? cfg.camera_publishers : '1,2,3,4,5';
        document.getElementById('formScreenSharePublishers').value = cfg.screen_share_publishers !== undefined ? cfg.screen_share_publishers : '2';
        document.getElementById('formMicPublishers').value = cfg.mic_publishers !== undefined ? cfg.mic_publishers : '1,2,3,4,5';
        document.getElementById('formViewerBotIds').value = cfg.viewer_bots !== undefined ? cfg.viewer_bots : '6-1000';
        document.getElementById('formViewerMode').value = cfg.viewer_mode !== undefined ? cfg.viewer_mode : 'receive_only';
        document.getElementById('formAutoCamera').checked = cfg.auto_camera !== undefined ? cfg.auto_camera : false;
        document.getElementById('formAutoMic').checked = cfg.auto_mic !== undefined ? cfg.auto_mic : false;
        document.getElementById('formAutoScreenShare').checked = cfg.auto_screen_share !== undefined ? cfg.auto_screen_share : false;
        document.getElementById('formDisableRamScenarioOpt').checked = cfg.disable_ram_scenario_opt !== undefined ? cfg.disable_ram_scenario_opt : false;
        document.getElementById('formRefreshBots').value = cfg.refresh_bots !== undefined ? cfg.refresh_bots : 0;
        document.getElementById('formDisableAbnormalBehavior').checked = cfg.disable_abnormal_behavior !== undefined ? cfg.disable_abnormal_behavior : false;
        toggleRamFields();
        
        loadCheckboxesFromSerialized('network');
        loadCheckboxesFromSerialized('browser');
        loadCheckboxesFromSerialized('device');
        loadCheckboxesFromSerialized('os');
        
        switchTab('configurator');
    } catch (err) {
        alert("Failed to load preset configuration details.");
    }
}

// Clone previous run
async function cloneSession(sessId) {
    try {
        const response = await fetch(`/api/sessions/${sessId}`);
        if (!response.ok) return;
        const sess = await response.json();
        if (sess.config_id) {
            loadConfigIntoForm(sess.config_id);
        } else {
            alert("No configuration config_id reference found for this session.");
        }
    } catch (err) {
        alert("Failed to clone session details.");
    }
}

// Delete configuration preset
async function deletePreset(cfgId) {
    if (!confirm("Are you sure you want to delete this configuration template?")) return;
    try {
        const response = await fetch(`/api/configurations/${cfgId}`, { method: 'DELETE' });
        if (response.ok) {
            alert("Preset configuration template deleted.");
            loadSavedPresets();
        } else {
            alert("Delete failed.");
        }
    } catch (err) {
        alert("Delete failed.");
    }
}

// Helper to aggregate lifecycle metrics from log array
function aggregateLifecycleFromLogs(logs) {
    const summary = {
        status_counts: { sent: 0, acknowledged: 0, broadcasted: 0, observed: 0, rendered: 0, 'timed-out': 0, failed: 0, unsupported: 0 },
        timeout_stages: { 'ack-timeout': 0, 'broadcast-timeout': 0, 'observer-timeout': 0, 'ui-render-timeout': 0, 'id-correlation-mismatch': 0 },
        unsupported_reasons: {},
        webrtc_advanced: { rtt: 0, loss: 0, jitter: 0, bitrate: 0, turn_count: 0, relay_count: 0 }
    };
    
    let rtts = [];
    let losses = [];
    let jitters = [];
    let bitrates = [];
    
    logs.forEach(evt => {
        const etype = evt.event;
        if (etype === "action_logged") {
            const status = evt.status;
            const final_status = evt.final_status;
            
            let resolved_status = final_status || status;
            if (resolved_status === "confirmed") {
                resolved_status = "acknowledged";
            } else if (resolved_status === "timeout" || resolved_status === "timed_out") {
                resolved_status = "timed-out";
            } else if (resolved_status && resolved_status.indexOf("observed") === 0) {
                resolved_status = "observed";
            }
            
            if (summary.status_counts[resolved_status] !== undefined) {
                summary.status_counts[resolved_status]++;
            }
            
            if (resolved_status === "timed-out") {
                const t_stage = evt.timeout_stage;
                if (summary.timeout_stages[t_stage] !== undefined) {
                    summary.timeout_stages[t_stage]++;
                }
            }
            
            if (resolved_status === "unsupported") {
                const reason = evt.unsupported_reason || "unknown";
                summary.unsupported_reasons[reason] = (summary.unsupported_reasons[reason] || 0) + 1;
            }
        } else if (etype === "webrtc_stats_logged") {
            if (evt.rtt !== undefined && evt.rtt !== null) rtts.push(evt.rtt);
            if (evt.packet_loss !== undefined && evt.packet_loss !== null) losses.push(evt.packet_loss);
            if (evt.jitter !== undefined && evt.jitter !== null) jitters.push(evt.jitter);
            if (evt.bitrate !== undefined && evt.bitrate !== null) bitrates.push(evt.bitrate);
            
            if (evt.turn_usage === true || evt.turn_usage === "true") {
                summary.webrtc_advanced.turn_count++;
            }
            if (evt.candidate_pair_type === 'relay') {
                summary.webrtc_advanced.relay_count++;
            }
        }
    });
    
    if (rtts.length > 0) summary.webrtc_advanced.rtt = rtts.reduce((a, b) => a + b, 0) / rtts.length;
    if (losses.length > 0) summary.webrtc_advanced.loss = losses.reduce((a, b) => a + b, 0) / losses.length;
    if (jitters.length > 0) summary.webrtc_advanced.jitter = jitters.reduce((a, b) => a + b, 0) / jitters.length;
    if (bitrates.length > 0) summary.webrtc_advanced.bitrate = bitrates.reduce((a, b) => a + b, 0) / bitrates.length;
    
    return summary;
}

// View logs of completed/historical session
async function viewHistoricalLogs(sessId) {
    try {
        const response = await fetch(`/api/sessions/${sessId}/logs?limit=2000`);
        if (!response.ok) return;
        const logs = await response.json();
        
        switchTab('monitoring');
        
        const consoleEl = document.getElementById('consoleTerminal');
        consoleEl.innerHTML = '';
        
        if (logs.length === 0) {
            consoleEl.innerHTML = `<div class="console-placeholder">No logs found for this session.</div>`;
            return;
        }

        document.getElementById('noActiveSessionPrompt').classList.add('hidden');
        document.getElementById('monitoringGrid').classList.remove('hidden');
        
        // Hide banner since it's not active
        document.getElementById('activeTestBanner').classList.add('hidden');
        
        // Load session config for SLA targets
        try {
            const configResponse = await fetch(`/api/sessions/${sessId}`);
            if (configResponse.ok) {
                const sess = await configResponse.json();
                if (sess.config) {
                    window.activeSessionTotalBots = sess.config.bots;
                    window.activeSessionSlaSuccess = sess.config.sla_success_rate !== undefined ? sess.config.sla_success_rate : 95.0;
                    window.activeSessionSlaLatency = sess.config.sla_latency !== undefined ? sess.config.sla_latency : 500.0;
                    window.activeSessionSlaLoss = sess.config.sla_packet_loss !== undefined ? sess.config.sla_packet_loss : 2.0;
                    window.activeSessionSlaJitter = sess.config.sla_jitter !== undefined ? sess.config.sla_jitter : 30.0;
                    
                    const targetSuccessEl = document.getElementById('slaTargetSuccess');
                    const targetLatencyEl = document.getElementById('slaTargetLatency');
                    const targetLossEl = document.getElementById('slaTargetLoss');
                    
                    if (targetSuccessEl) targetSuccessEl.textContent = window.activeSessionSlaSuccess.toFixed(1);
                    if (targetLatencyEl) targetLatencyEl.textContent = window.activeSessionSlaLatency.toFixed(0);
                    if (targetLossEl) targetLossEl.textContent = window.activeSessionSlaLoss.toFixed(1);
                }
            }
        } catch (ec) {
            console.error("Failed to load historical config for SLA: ", ec);
        }

        // Load static metrics if session has any
        const mResponse = await fetch(`/api/sessions/${sessId}/metrics`);
        if (mResponse.ok) {
            const mData = await mResponse.json();
            clearCharts();
            mData.forEach(m => {
                const timeStr = new Date(m.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
                updateCharts(timeStr, m, false); // Keep shift = false for history
            });
            if (mData.length > 0) {
                const finalLifecycle = aggregateLifecycleFromLogs(logs);
                updateMetricsCards(mData[mData.length - 1], finalLifecycle);
            }
        }

        window.consoleLogsBuffer = [];
        logs.forEach(evt => pushToConsoleBuffer(evt));
        renderAllConsoleLogs();
    } catch (err) {
        alert("Failed to load historical logs.");
    }
}

// Helpers
function escapeHtml(text) {
    if (!text) return '';
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    return text.toString().replace(/[&<>"']/g, m => map[m]);
}

function calculateDuration(start, end) {
    if (!start) return 'N/A';
    const t0 = new Date(start);
    const t1 = end ? new Date(end) : new Date();
    const diff = Math.floor((t1 - t0) / 1000);
    const mins = Math.floor(diff / 60);
    const secs = diff % 60;
    return `${mins}m ${secs}s`;
}

// --- Accordion Multi-Select logic ---
const DEFAULT_NETWORK_WEIGHTS = { "ethernet": 20, "wi-fi": 50, "4g": 20, "3g": 10, "5g": 20, "poor": 5 };
const DEFAULT_BROWSER_WEIGHTS = {
    "chrome_149": 10, "chrome_148": 8, "chrome_147": 6, "chrome_146": 6,
    "edge_149": 8, "edge_148": 6, "edge_147": 6,
    "firefox_152": 10, "firefox_151": 8, "firefox_150": 6,
    "firefox_esr_140": 5,
    "safari_18": 10, "safari_17": 8, "safari_16": 6,
    "brave_149": 8, "brave_148": 6, "brave_147": 6,
    "opera_119": 6, "opera_118": 5, "opera_117": 5,
    "chrome_mobile_149": 8, "chrome_mobile_148": 6, "chrome_mobile_147": 6,
    "safari_mobile_18": 8, "safari_mobile_17": 6, "safari_mobile_16": 6,
    "samsung_internet_28": 6, "samsung_internet_27": 5, "samsung_internet_26": 5,
    "firefox_mobile_152": 8, "firefox_mobile_151": 6, "firefox_mobile_150": 6,
    "opera_mobile_89": 5, "opera_mobile_88": 5,
    "edge_mobile_149": 5, "edge_mobile_148": 5,
    "duckduckgo_mobile_5": 5,
    "uc_browser_mobile_15": 5,
    "yandex_browser_25": 8,
    "vivaldi_7": 8
};
const DEFAULT_DEVICE_WEIGHTS = {
    "desktop": 10.0, "laptop": 18.0, "workstation": 1.5, "chromebook": 2.0,
    "android_phone": 28.5, "iphone": 13.0, "android_tablet": 5.0, "ipad": 4.0,
    "windows_tablet": 1.0, "android_foldable": 1.0, "phablet": 1.5,
    "windows_2_in_1": 2.0, "smart_tv": 1.5, "conference_room_device": 0.5,
    "kiosk": 0.5, "virtual_desktop": 1.0, "headless_browser": 1.0,
    "recorder_bot": 0.5, "android_webview": 5.0, "ios_webview": 2.5
};
const OS_KEYS = [
    "windows_11_26h1", "windows_11_25h2", "windows_11_24h2", "windows_11_23h2", "windows_11_22h2",
    "windows_10_22h2", "windows_10_21h2", "windows_10_20h2", "windows_8_1", "windows_8", "windows_7",
    "windows_server_2025", "windows_server_2022", "windows_server_2019", "windows_server_2016",
    "macos_15_sequoia", "macos_14_sonoma", "macos_13_ventura", "macos_12_monterey", "macos_11_big_sur", "macos_10_15_catalina",
    "macos_26_tahoe", "macos_25_shasta", "macos_24_hood", "macos_23_lassen",
    "linux_ubuntu_24_04_lts", "linux_ubuntu_22_04_lts", "linux_debian_12", "linux_debian_11", "linux_fedora_40", "linux_fedora_39",
    "linux_centos_stream_9", "linux_rhel_9", "linux_rhel_8", "linux_arch_latest", "linux_ubuntu_server_24_04",
    "ios_18", "ios_17", "ios_16", "ios_15", "ipados_18", "ipados_17", "ipados_16", "android_15", "android_14", "android_13", "android_12",
    "android_11", "android_10", "android_go_15", "harmonyos_4", "harmonyos_next", "fireos_8", "tizen_os_8", "webos_24", "tvos_18", "visionos_2",
    "freebsd_14", "openbsd_7_5", "netbsd_10", "solaris_illumos_latest", "yocto_linux_5_0", "openwrt_23_05", "ios_webview_os",
    "pwa_runtime_desktop", "pwa_runtime_tablet", "pwa_runtime_mobile", "headless_os", "virtual_os", "unknown_other"
];
const DEFAULT_OS_WEIGHTS = {};
OS_KEYS.forEach(k => { DEFAULT_OS_WEIGHTS[k] = 1.0; });

function toggleAccordion(id) {
    const panel = document.getElementById(id);
    panel.classList.toggle('show');
}

function populateGrids() {
    const populate = (gridId, weights, type) => {
        const grid = document.getElementById(gridId);
        grid.innerHTML = '';
        Object.keys(weights).forEach(key => {
            const labelText = key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
            const div = document.createElement('div');
            div.className = 'checkbox-item';
            div.innerHTML = `<input type="checkbox" class="cb-${type}" value="${key}" checked onchange="updateSerializedInputs('${type}')"> <label>${labelText}</label>`;
            grid.appendChild(div);
        });
    };
    populate('grid-network', DEFAULT_NETWORK_WEIGHTS, 'network');
    populate('grid-browser', DEFAULT_BROWSER_WEIGHTS, 'browser');
    populate('grid-device', DEFAULT_DEVICE_WEIGHTS, 'device');
    populate('grid-os', DEFAULT_OS_WEIGHTS, 'os');
}

function selectAllOptions(type) {
    const cbs = document.querySelectorAll(`.cb-${type}`);
    cbs.forEach(cb => { cb.checked = true; });
    updateSerializedInputs(type);
}

function selectNoneOptions(type) {
    const cbs = document.querySelectorAll(`.cb-${type}`);
    cbs.forEach(cb => { cb.checked = false; });
    updateSerializedInputs(type);
}

function updateSerializedInputs(type) {
    const cbs = document.querySelectorAll(`.cb-${type}`);
    const selected = [];
    cbs.forEach(cb => {
        if (cb.checked) selected.push(cb.value);
    });

    const badge = document.getElementById(`badge-${type}`);
    badge.textContent = `${selected.length} selected`;

    let defaultWeights = DEFAULT_NETWORK_WEIGHTS;
    let inputId = 'formNetworkConditions';
    if (type === 'browser') { defaultWeights = DEFAULT_BROWSER_WEIGHTS; inputId = 'formBrowserDistribution'; }
    if (type === 'device') { defaultWeights = DEFAULT_DEVICE_WEIGHTS; inputId = 'formDeviceDistribution'; }
    if (type === 'os') { defaultWeights = DEFAULT_OS_WEIGHTS; inputId = 'formOsDistribution'; }

    let sum = 0.0;
    selected.forEach(k => { sum += (defaultWeights[k] || 1.0); });

    const serializedParts = [];
    selected.forEach(k => {
        const relativeWeight = sum > 0 ? (((defaultWeights[k] || 1.0) / sum) * 100.0) : 0.0;
        serializedParts.push(`${k}:${relativeWeight.toFixed(2)}`);
    });

    document.getElementById(inputId).value = serializedParts.join(',');
}

function loadCheckboxesFromSerialized(type) {
    let inputId = 'formNetworkConditions';
    if (type === 'browser') inputId = 'formBrowserDistribution';
    if (type === 'device') inputId = 'formDeviceDistribution';
    if (type === 'os') inputId = 'formOsDistribution';

    const val = document.getElementById(inputId).value || '';
    const keysInSerialized = new Set();
    val.split(',').forEach(item => {
        const parts = item.split(':');
        if (parts[0]) keysInSerialized.add(parts[0].trim().toLowerCase());
    });

    const cbs = document.querySelectorAll(`.cb-${type}`);
    cbs.forEach(cb => {
        cb.checked = keysInSerialized.has(cb.value);
    });

    const badge = document.getElementById(`badge-${type}`);
    badge.textContent = `${keysInSerialized.size} selected`;
}

// Custom interactive download handler with smooth progress animation overlay
async function triggerReportDownload(sessionId, format) {
    const modal = document.getElementById('reportProgressModal');
    const progressFill = document.getElementById('progressBarFill');
    const percentageLabel = document.getElementById('progressPercentageLabel');
    const statusText = document.getElementById('progressStatusText');
    const subDetails = document.getElementById('progressSubDetails');
    
    if (!modal) return;
    
    // Show modal overlay
    modal.style.display = 'flex';
    
    // Reset indicators
    progressFill.style.width = '0%';
    percentageLabel.textContent = '0%';
    statusText.textContent = 'Contacting server...';
    subDetails.textContent = 'Requesting file conversion session...';
    
    // Wire up close overlay callback
    let isCancelled = false;
    const closeBtn = document.getElementById('closeProgressModalBtn');
    if (closeBtn) {
        closeBtn.onclick = () => {
            isCancelled = true;
            modal.style.display = 'none';
        };
    }
    
    // Setup incremental smooth ease-out progress steps
    let progress = 0;
    const progressSteps = [
        { limit: 25, label: "Parsing raw action logs...", speed: 1.5 },
        { limit: 55, label: "Running WebRTC SLA analytics...", speed: 0.8 },
        { limit: 80, label: "Building document templates...", speed: 0.4 },
        { limit: 95, label: "Applying layouts and formatting...", speed: 0.1 }
    ];
    
    let stepIdx = 0;
    const timer = setInterval(() => {
        if (isCancelled) {
            clearInterval(timer);
            return;
        }
        
        const currentStep = progressSteps[stepIdx];
        if (progress < currentStep.limit) {
            progress += currentStep.speed;
            if (progress > currentStep.limit) progress = currentStep.limit;
            
            const displayPct = Math.min(Math.floor(progress), 95);
            progressFill.style.width = `${displayPct}%`;
            percentageLabel.textContent = `${displayPct}%`;
            statusText.textContent = `Converting to ${format.toUpperCase()}...`;
            subDetails.textContent = currentStep.label;
        } else if (stepIdx < progressSteps.length - 1) {
            stepIdx++;
        }
    }, 50);
    
    try {
        const response = await fetch(`/api/sessions/${sessionId}/download/${format}`);
        if (isCancelled) return;
        
        if (!response.ok) {
            clearInterval(timer);
            const errData = await response.json().catch(() => ({}));
            alert(errData.message || `Failed to download ${format.toUpperCase()} report.`);
            modal.style.display = 'none';
            return;
        }
        
        // Finalize progress bar
        clearInterval(timer);
        progressFill.style.width = '100%';
        percentageLabel.textContent = '100%';
        statusText.textContent = 'Download Ready!';
        subDetails.textContent = 'Saving file to your browser downloads...';
        
        // Fetch the file as blob
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.style.display = 'none';
        a.href = url;
        
        // Extract filename if returned
        const contentDisposition = response.headers.get('content-disposition');
        let filename = `session_${sessionId}_report.${format}`;
        if (contentDisposition) {
            const filenameMatch = contentDisposition.match(/filename=\"?([^\"]+)\"?/);
            if (filenameMatch) filename = filenameMatch[1];
        }
        
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        
        // Release URL and elements
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);
        
        // Close modal after success animation pause
        setTimeout(() => {
            modal.style.display = 'none';
        }, 800);
        
    } catch (err) {
        clearInterval(timer);
        console.error(err);
        alert("An error occurred during report compilation.");
        modal.style.display = 'none';
    }
}

// Make globally accessible from onclick handlers
window.triggerReportDownload = triggerReportDownload;
