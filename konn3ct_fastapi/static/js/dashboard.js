// dashboard.js — Main UI Controller and WebSocket handler

let socket = null;
let currentActiveSessionId = null;
let currentUser = null;

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
});

// Theme Management
function initTheme() {
    const btn = document.getElementById('themeToggleBtn');
    const body = document.body;
    
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
    const launchBtn = document.getElementById('launchTestBtn');
    if (launchBtn) launchBtn.disabled = true;
    
    const savePresetBtn = document.getElementById('savePresetBtn');
    if (savePresetBtn) savePresetBtn.disabled = true;
    
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

    document.getElementById('logoutBtn').addEventListener('click', async (e) => {
        e.preventDefault();
        const response = await fetch('/api/auth/logout', { method: 'POST' });
        if (response.ok) {
            window.location.href = '/login';
        }
    });
}

function switchTab(tabId) {
    document.querySelectorAll('.menu-item').forEach(item => {
        if (item.getAttribute('data-tab') === tabId) {
            item.classList.add('active');
        } else {
            item.classList.remove('active');
        }
    });

    document.querySelectorAll('.tab-pane').forEach(pane => {
        if (pane.id === `tab-${tabId}`) {
            pane.classList.add('active');
        } else {
            pane.classList.remove('active');
        }
    });

    const titles = {
        'monitoring': 'Monitoring Dashboard',
        'configurator': 'Configure New Test Session',
        'templates': 'Saved Configuration Presets',
        'history': 'Test Session Execution History'
    };
    document.getElementById('pageTitle').textContent = titles[tabId] || 'Dashboard';
}

function switchBottomTab(subTabId) {
    document.querySelectorAll('.tab-header-item').forEach(item => {
        if (item.getAttribute('onclick') && item.getAttribute('onclick').includes(subTabId)) {
            item.classList.add('active');
        } else {
            item.classList.remove('active');
        }
    });

    document.querySelectorAll('.tab-pane-item').forEach(pane => {
        if (pane.id === `btab-${subTabId}`) {
            pane.classList.add('active');
        } else {
            pane.classList.remove('active');
        }
    });
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

// Triggers reports generation/download with sliding progress bar
async function triggerReportDownload(sessionId, format) {
    const overlay = document.getElementById('downloadProgressOverlay');
    const title = document.getElementById('downloadProgressTitle');
    const percentText = document.getElementById('downloadProgressPercent');
    const barFill = document.getElementById('downloadProgressBarFill');
    const statusText = document.getElementById('downloadProgressStatus');

    if (!overlay) return;

    // Reset UI
    let formatLabel = format.toUpperCase();
    let icon = "fa-file-word text-cyan";
    if (format === 'pdf') icon = "fa-file-pdf text-red";
    if (format === 'csv') icon = "fa-file-csv text-green";

    title.innerHTML = `<i class="fa-solid ${icon}"></i> Generating ${formatLabel} Report...`;
    percentText.innerText = "1%";
    barFill.style.width = "1%";
    statusText.innerText = "Connecting to database pipeline...";
    
    overlay.classList.add('show');

    // Simulate progress while fetch is loading
    let currentPct = 1;
    const progressInterval = setInterval(() => {
        if (currentPct < 90) {
            // Gradually slow down as it gets closer to 90%
            let increment = Math.max(1, Math.floor((90 - currentPct) / 10));
            currentPct += increment;
            percentText.innerText = `${currentPct}%`;
            barFill.style.width = `${currentPct}%`;
            
            if (currentPct > 70) {
                statusText.innerText = "Compiling Word template metrics...";
            } else if (currentPct > 45) {
                statusText.innerText = "Analyzing WebRTC quality gates...";
            } else if (currentPct > 20) {
                statusText.innerText = "Correlating action-observation events...";
            }
        }
    }, 150);

    try {
        const response = await fetch(`/api/sessions/${sessionId}/download/${format}`);
        if (!response.ok) {
            throw new Error(`Server returned HTTP ${response.status}`);
        }

        const blob = await response.blob();
        
        // Finish progress bar
        clearInterval(progressInterval);
        percentText.innerText = "100%";
        barFill.style.width = "100%";
        statusText.innerText = "Done! Starting download...";

        // Trigger file download
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `session_${sessionId}_report.${format}`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        window.URL.revokeObjectURL(url);

        // Hide overlay after delay
        setTimeout(() => {
            overlay.classList.remove('show');
        }, 1500);

    } catch (err) {
        clearInterval(progressInterval);
        console.error("Report download failed: ", err);
        percentText.innerText = "Error";
        barFill.style.width = "100%";
        barFill.style.background = "#ef4444"; // Red error color
        statusText.innerText = "Failed to compile report. Check server logs.";
        
        setTimeout(() => {
            overlay.classList.remove('show');
            // reset back to default blue gradient after animation out
            setTimeout(() => {
                barFill.style.background = "";
            }, 500);
        }, 4000);
    }
}

// Active session scanner
async function checkForRunningSession() {
    try {
        const response = await fetch('/api/sessions');
        if (!response.ok) return;
        const data = await response.json();
        
        const active = data.find(s => s.status === 'running' || s.status === 'paused');
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
    
    // Show Top bar controls
    const banner = document.getElementById('activeTestBanner');
    banner.classList.remove('hidden');
    document.getElementById('bannerSessionName').textContent = sessionName;
    
    // 1. Fetch config and details
    try {
        const res = await fetch(`/api/sessions/${sessionId}`);
        if (res.ok) {
            const sess = await res.json();
            if (sess.config) {
                renderActiveConfigSummary(sess.config);
                const activeTimeoutEl = document.getElementById('webrtcActiveTimeout');
                if (activeTimeoutEl) {
                    activeTimeoutEl.textContent = (sess.config.confirm_timeout || 5.0).toFixed(1);
                }
            }
            
            // Sync precision session timer
            startPrecisionTimer(sess.elapsed_ms || 0, status === 'paused');
        }
    } catch (e) {
        console.error("Failed to load active session config: ", e);
    }
    
    updateBannerStatusText(status);

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
                const lResponse = await fetch(`/api/sessions/${sessionId}/logs?limit=2000`);
                if (lResponse.ok) {
                    const logs = await lResponse.json();
                    const currentLifecycle = aggregateLifecycleFromLogs(logs);
                    updateMetricsDashboard(mData[mData.length - 1], currentLifecycle);
                    
                    const consoleEl = document.getElementById('consoleTerminal');
                    consoleEl.innerHTML = '';
                    logs.forEach(evt => renderConsoleLog(evt));
                } else {
                    updateMetricsDashboard(mData[mData.length - 1], null);
                }
            }
        }
    } catch (e) {
        console.error("Failed to load historical metrics: ", e);
    }

    // 3. Initialise WebSockets
    initWebSocket(sessionId);
}

// Precision Session Timer logic
let timerAnimationId = null;
let timerSyncMs = 0;
let timerSyncTimestamp = null;
let isTimerPaused = false;

function startPrecisionTimer(elapsedMs, isPaused) {
    stopPrecisionTimer();
    
    timerSyncMs = elapsedMs;
    timerSyncTimestamp = Date.now();
    isTimerPaused = isPaused;

    const timerEl = document.getElementById('bannerSessionTimer');
    if (!timerEl) return;

    function tick() {
        if (!timerEl) return;
        
        let elapsed = timerSyncMs;
        if (!isTimerPaused && timerSyncTimestamp) {
            elapsed += (Date.now() - timerSyncTimestamp);
        }
        
        timerEl.textContent = formatMsPrecision(elapsed);
        timerAnimationId = requestAnimationFrame(tick);
    }
    
    timerAnimationId = requestAnimationFrame(tick);
}

function stopPrecisionTimer() {
    if (timerAnimationId) {
        cancelAnimationFrame(timerAnimationId);
        timerAnimationId = null;
    }
}

function formatMsPrecision(ms) {
    if (ms < 0) ms = 0;
    const hrs = Math.floor(ms / 3600000);
    const mins = Math.floor((ms % 3600000) / 60000);
    const secs = Math.floor((ms % 60000) / 1000);
    const msecs = Math.floor(ms % 1000);
    
    let timeStr = "";
    if (hrs > 0) {
        timeStr += String(hrs).padStart(2, '0') + ":";
    }
    timeStr += String(mins).padStart(2, '0') + ":" + 
               String(secs).padStart(2, '0') + "." + 
               String(msecs).padStart(3, '0');
    return timeStr;
}

// Sync session state after reconnecting or refreshing
async function syncSessionState(sessionId) {
    try {
        const response = await fetch(`/api/sessions/${sessionId}`);
        if (response.ok) {
            const sess = await response.json();
            startPrecisionTimer(sess.elapsed_ms || 0, sess.status === 'paused');
            updateBannerStatusText(sess.status);
            if (sess.config) {
                renderActiveConfigSummary(sess.config);
            }
        }
    } catch (err) {
        console.error("Failed to sync session state: ", err);
    }
}

// Render Configuration sidebar overview
function renderActiveConfigSummary(config) {
    const container = document.getElementById('activeConfigSummaryBody');
    if (!container) return;
    
    const formatDist = (str) => {
        if (!str) return 'Default';
        const parts = str.split(',').map(s => {
            const item = s.split(':');
            return item[0] ? `${item[0].replace(/_/g, ' ')} (${parseFloat(item[1]).toFixed(0)}%)` : '';
        }).filter(Boolean);
        return parts.slice(0, 3).join(', ') + (parts.length > 3 ? '...' : '');
    };

    container.innerHTML = `
        <div class="config-detail-row"><span class="lbl">Room Slug</span><span class="val">${escapeHtml(config.room)}</span></div>
        <div class="config-detail-row"><span class="lbl">Bot Count</span><span class="val">${config.bots}</span></div>
        <div class="config-detail-row"><span class="lbl">Batch / Concurrency</span><span class="val">${config.batch} / ${config.concurrency}</span></div>
        <div class="config-detail-row"><span class="lbl">WebRTC Stream</span><span class="val">${config.webrtc_enabled ? 'Active ('+config.media_quality+')' : 'Disabled'}</span></div>
        <div class="config-detail-row"><span class="lbl">Downlink Limit</span><span class="val">${config.max_subscriptions} subs</span></div>
        <div class="config-detail-row"><span class="lbl">Network Profile</span><span class="val">${formatDist(config.network_conditions)}</span></div>
        <div class="config-detail-row"><span class="lbl">Browser Mix</span><span class="val">${formatDist(config.browser_distribution)}</span></div>
        <div class="config-detail-row"><span class="lbl">Hardware Mix</span><span class="val">${formatDist(config.device_distribution)}</span></div>
        <div class="config-detail-row"><span class="lbl">Operating System</span><span class="val">${formatDist(config.os_distribution)}</span></div>
        <div class="config-detail-row"><span class="lbl">Active Scenarios</span><span class="val" title="${escapeHtml(config.test_scenarios)}">${escapeHtml(config.test_scenarios)}</span></div>
    `;
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
        isTimerPaused = false;
    } else if (status === 'paused') {
        badge.className = 'badge badge-running'; // keep pulsing
        badge.style.backgroundColor = 'var(--warning-soft)';
        badge.style.color = 'var(--warning)';
        pauseBtn.classList.add('hidden');
        resumeBtn.classList.remove('hidden');
        isTimerPaused = true;
    }
}

// WebSocket setup with auto-reconnection backoff
let reconnectTimer = null;
let reconnectInterval = 1000;
let isSocketIntentionallyClosed = false;

function initWebSocket(sessionId) {
    if (socket) {
        try {
            socket.close();
        } catch (e) {}
    }
    
    isSocketIntentionallyClosed = false;
    updateServerStatusIndicator("connecting");

    const wsScheme = window.location.protocol === "https:" ? "wss" : "ws";
    socket = new WebSocket(`${wsScheme}://${window.location.host}/ws`);

    socket.onopen = () => {
        console.log("WebSocket connected. Joining session room: " + sessionId);
        updateServerStatusIndicator("online");
        reconnectInterval = 1000; // Reset backoff
        socket.send(JSON.stringify({ action: 'join', session_id: sessionId }));
        
        syncSessionState(sessionId);
    };

    socket.onmessage = (event) => {
        try {
            const payload = JSON.parse(event.data);
            if (payload.session_id !== sessionId) return;

            const etype = payload.event_type;

            if (etype === "session_raw_event") {
                renderConsoleLog(payload.event);
            } else if (etype === "session_raw_events") {
                payload.events.forEach(evt => renderConsoleLog(evt));
            } else if (etype === "session_console_log") {
                appendStdoutLog(payload.log);
            } else if (etype === "session_console_logs") {
                payload.logs.forEach(log => appendStdoutLog(log));
            } else if (etype === "session_metrics") {
                updateMetricsDashboard(payload.metrics, payload.lifecycle_summary);
            } else if (etype === "session_status_changed") {
                if (payload.status === 'completed' || payload.status === 'stopped' || payload.status === 'failed') {
                    handleSessionFinished(payload.status);
                } else {
                    updateBannerStatusText(payload.status);
                }
            }
        } catch (e) {
            console.error("WebSocket message error: ", e);
        }
    };

    socket.onerror = (error) => {
        console.error("WebSocket error: ", error);
        updateServerStatusIndicator("error");
    };

    socket.onclose = (event) => {
        console.log("WebSocket closed: ", event);
        if (!isSocketIntentionallyClosed) {
            updateServerStatusIndicator("offline");
            
            clearTimeout(reconnectTimer);
            reconnectTimer = setTimeout(() => {
                console.log(`WebSocket reconnecting (delay: ${reconnectInterval}ms)...`);
                reconnectInterval = Math.min(reconnectInterval * 2, 15000);
                initWebSocket(sessionId);
            }, reconnectInterval);
        }
    };
}

function updateServerStatusIndicator(state) {
    const indicator = document.querySelector('.status-indicator');
    const textEl = document.querySelector('.status-text');
    if (!indicator || !textEl) return;
    
    if (state === "online") {
        indicator.className = "status-indicator online";
        textEl.textContent = "Server Status: Connected";
        indicator.style.animation = "";
    } else if (state === "connecting") {
        indicator.className = "status-indicator";
        indicator.style.backgroundColor = "var(--warning)";
        indicator.style.boxShadow = "0 0 8px var(--warning)";
        indicator.style.animation = "pulse 1.5s infinite";
        textEl.textContent = "Server Status: Reconnecting...";
    } else {
        indicator.className = "status-indicator";
        indicator.style.backgroundColor = "var(--error)";
        indicator.style.boxShadow = "0 0 8px var(--error)";
        indicator.style.animation = "pulse 1s infinite";
        textEl.textContent = "Server Status: Offline (Trying to Reconnect)";
    }
}

// Log Terminal renderer with DOM capping for performance
function renderConsoleLog(evt) {
    const consoleEl = document.getElementById('consoleTerminal');
    if (!consoleEl) return;
    
    const placeholder = consoleEl.querySelector('.console-placeholder');
    if (placeholder) placeholder.remove();
    
    const etype = evt.event;
    const filter = document.getElementById('logLevelFilter').value;
    const search = document.getElementById('logSearchInput').value.toLowerCase();
    
    if (filter !== 'all' && filter !== etype) return;
    
    let logMsg = "";
    let statusClass = "info";
    
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
        if (evt.status === "confirmed" || evt.status === "acknowledged") {
            logMsg = `✅ Bot-${evt.bot_id} (${evt.name}) action confirmed: ${evt.action_type} → ${value}${latency}`;
            statusClass = "info";
        } else if (evt.status.startsWith("observed:")) {
            logMsg = `👀 Bot-${evt.bot_id} (${evt.name}) observed ${evt.status.split(":", 2)[1]} performing: ${evt.action_type} → ${value}${latency}`;
            statusClass = "tag";
        } else if (evt.status === "observed") {
            logMsg = `👀 Bot-${evt.bot_id} (${evt.name}) observed action: ${evt.action_type} → ${value}${latency}`;
            statusClass = "tag";
        } else if (evt.status === "rendered") {
            logMsg = `🖥️ Bot-${evt.bot_id} (${evt.name}) rendered action: ${evt.action_type} → ${value}${latency}`;
            statusClass = "info";
        } else if (evt.status === "timed_out" || evt.status === "timeout") {
            logMsg = `⚠️ Bot-${evt.bot_id} (${evt.name}) action timeout on stage [${evt.timeout_stage || 'ack-timeout'}]: ${evt.action_type}`;
            statusClass = "warn";
        } else {
            logMsg = `❌ Bot-${evt.bot_id} (${evt.name}) action failed: ${evt.action_type}`;
            statusClass = "error";
        }
    } else if (etype === "error_logged") {
        logMsg = `🚨 Bot-${evt.bot_id} (${evt.name}) error on action [${evt.action}]: ${evt.error}`;
        statusClass = "error";
    } else if (etype === "test_finished") {
        logMsg = `📊 Load test finished. Summary written to log database.`;
        statusClass = "info";
    }

    if (!logMsg) return;
    if (search && !logMsg.toLowerCase().includes(search)) return;

    const timeStr = new Date(evt.ts).toLocaleTimeString();
    
    const entry = document.createElement('div');
    entry.className = 'log-entry';
    entry.innerHTML = `
        <span class="ts">[${timeStr}]</span>
        <span class="${statusClass}">${logMsg}</span>
    `;
    
    consoleEl.appendChild(entry);
    
    // Capping DOM elements to 500 max lines to prevent DOM bloat and crash
    while (consoleEl.children.length > 500) {
        consoleEl.removeChild(consoleEl.firstChild);
    }
    
    consoleEl.scrollTop = consoleEl.scrollHeight;
}

function appendStdoutLog(logLine) {
    const consoleEl = document.getElementById('consoleTerminal');
    if (!consoleEl) return;
    
    const placeholder = consoleEl.querySelector('.console-placeholder');
    if (placeholder) placeholder.remove();
    
    const entry = document.createElement('div');
    entry.className = 'log-entry';
    entry.innerHTML = `
        <span class="ts">[STDOUT]</span>
        <span class="info">${escapeHtml(logLine)}</span>
    `;
    consoleEl.appendChild(entry);
    
    while (consoleEl.children.length > 500) {
        consoleEl.removeChild(consoleEl.firstChild);
    }
    consoleEl.scrollTop = consoleEl.scrollHeight;
}

// Update KPIs, sidebar metrics, distributions progress-bars, and error table
function updateMetricsDashboard(metrics, lifecycleSummary) {
    // 1. Top Summary cards
    document.getElementById('metricConnectedBots').textContent = metrics.connected_bots;
    document.getElementById('metricConnectingBots').textContent = metrics.connecting_bots;
    document.getElementById('metricReconnectingBots').textContent = metrics.reconnecting_bots;
    document.getElementById('metricActiveBots').textContent = metrics.active_bots || 0;
    document.getElementById('metricFailedBots').textContent = metrics.failed_bots;
    
    // Compute success rate percentage
    let succRate = 100.0;
    if (lifecycleSummary && lifecycleSummary.status_counts) {
        const counts = lifecycleSummary.status_counts;
        const total = (counts.acknowledged || 0) + (counts["timed-out"] || 0) + (counts.failed || 0);
        if (total > 0) {
            succRate = ((counts.acknowledged || 0) / total) * 100.0;
        }
    }
    document.getElementById('metricSuccessRate').textContent = succRate.toFixed(1);
    
    document.getElementById('metricCpu').textContent = metrics.cpu_usage ? metrics.cpu_usage.toFixed(1) : '0.0';
    document.getElementById('metricRam').textContent = metrics.ram_usage ? metrics.ram_usage.toFixed(1) : '0.0';
    
    const mbps = (metrics.net_throughput_kbps || 0.0) / 1024.0;
    document.getElementById('metricNetThroughput').textContent = mbps.toFixed(2);
    document.getElementById('metricWebRtcBitrate').textContent = metrics.bitrate || '0';

    // 2. Sidebar Parameters
    if (lifecycleSummary) {
        // Status stage counts
        if (lifecycleSummary.status_counts) {
            const counts = lifecycleSummary.status_counts;
            document.getElementById('lifecycleSent').textContent = counts.sent || 0;
            document.getElementById('lifecycleAcknowledged').textContent = counts.acknowledged || 0;
            document.getElementById('lifecycleBroadcasted').textContent = counts.broadcasted || 0;
            document.getElementById('lifecycleObserved').textContent = counts.observed || 0;
            document.getElementById('lifecycleRendered').textContent = counts.rendered || 0;
        }

        // WebRTC quality
        if (lifecycleSummary.webrtc_advanced) {
            const webrtc = lifecycleSummary.webrtc_advanced;
            document.getElementById('webrtcAvgRtt').textContent = webrtc.rtt ? webrtc.rtt.toFixed(1) : '0';
            document.getElementById('webrtcAvgJitter').textContent = webrtc.jitter ? webrtc.jitter.toFixed(1) : '0';
            document.getElementById('webrtcTurnCount').textContent = webrtc.turn_count || 0;
            document.getElementById('webrtcRelayCount').textContent = webrtc.relay_count || 0;
        }
        
        // Signaling status
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

        // Timeout stages
        if (lifecycleSummary.timeout_stages) {
            const to = lifecycleSummary.timeout_stages;
            document.getElementById('timeoutAck').textContent = to['ack-timeout'] || 0;
            document.getElementById('timeoutBroadcast').textContent = to['broadcast-timeout'] || 0;
            document.getElementById('timeoutObserver').textContent = to['observer-timeout'] || 0;
            document.getElementById('timeoutUiRender').textContent = to['ui-render-timeout'] || 0;
            document.getElementById('timeoutIdMismatch').textContent = to['id-correlation-mismatch'] || 0;
        }

        // 3. Render Browser and Device Distributions
        if (lifecycleSummary.distributions) {
            renderDistributionsGroup('distBrowserList', lifecycleSummary.distributions.browser);
            renderDistributionsGroup('distDeviceList', lifecycleSummary.distributions.device);
            renderDistributionsGroup('distOsList', lifecycleSummary.distributions.os);
            renderDistributionsGroup('distNetworkList', lifecycleSummary.distributions.network);
        }

        // 4. Render Error Telemetry Dashboard
        if (lifecycleSummary.errors) {
            renderErrorTelemetryDashboard(lifecycleSummary.errors);
        }
    }

    // 5. precision timer tick sync
    if (metrics.elapsed_ms !== undefined) {
        startPrecisionTimer(metrics.elapsed_ms, metrics.paused || false);
    }

    // Update SLA Compliance UI
    if (metrics.sla_status) {
        updateSlaComplianceUI(metrics.sla_status);
    } else {
        document.getElementById('slaComplianceSidebarCard').style.display = 'none';
    }

    // 6. Push data points to charts
    const timeStr = new Date(metrics.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    updateCharts(timeStr, metrics);
}

function renderDistributionsGroup(elementId, distGroup) {
    const container = document.getElementById(elementId);
    if (!container) return;
    
    if (!distGroup || Object.keys(distGroup).length === 0) {
        container.innerHTML = '<div class="text-center text-muted" style="padding: 10px 0;">No active distributions data.</div>';
        return;
    }

    const items = Object.entries(distGroup).sort((a, b) => b[1].count - a[1].count);
    let html = '';
    
    items.forEach(([key, val]) => {
        const title = key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
        html += `
            <div class="dist-item-flat">
                <div class="dist-item-info">
                    <span class="lbl" title="${title}">${title}</span>
                    <span>${val.count} (${val.pct.toFixed(1)}%)</span>
                </div>
                <div class="dist-progress-flat">
                    <div class="dist-progress-val" style="width: ${val.pct.toFixed(1)}%;"></div>
                </div>
            </div>
        `;
    });
    
    container.innerHTML = html;
}

function renderErrorTelemetryDashboard(errors) {
    const tbody = document.getElementById('errorTelemetryBody');
    const badgeCount = document.getElementById('bottomTabErrorCount');
    if (!tbody) return;
    
    const entries = Object.entries(errors);
    let totalErrors = 0;
    let html = '';

    // Sort: show error groups with counts > 0 first
    entries.sort((a, b) => b[1].count - a[1].count);

    entries.forEach(([cat, val]) => {
        totalErrors += val.count;
        const lastSeen = val.last_occurrence ? new Date(val.last_occurrence).toLocaleTimeString() : 'N/A';
        const sevClass = (val.severity === 'Critical' || val.severity === 'High') ? 'badge-failed' : 'badge-stopped';
        
        html += `
            <tr>
                <td><strong>${cat}</strong></td>
                <td><span class="badge ${val.count > 0 ? 'badge-failed' : 'badge-completed'}">${val.count}</span></td>
                <td>${lastSeen}</td>
                <td><span class="badge ${sevClass}">${val.severity}</span></td>
                <td><span style="color: var(--text-secondary);">${escapeHtml(val.suggested_cause)}</span></td>
            </tr>
        `;
    });

    tbody.innerHTML = html;

    // Update bottom tab error counts badge
    if (badgeCount) {
        if (totalErrors > 0) {
            badgeCount.textContent = totalErrors;
            badgeCount.style.display = 'inline-block';
        } else {
            badgeCount.style.display = 'none';
        }
    }
}

// Close session actions on completion
function handleSessionFinished(status) {
    if (socket) {
        try {
            isSocketIntentionallyClosed = true;
            socket.close();
        } catch (e) {}
        socket = null;
    }
    
    stopPrecisionTimer();
    const timerEl = document.getElementById('bannerSessionTimer');
    if (timerEl) timerEl.textContent = '00:00.000';
    
    currentActiveSessionId = null;
    document.getElementById('activeTestBanner').classList.add('hidden');
    
    alert(`Load test session finished with status: ${status.toUpperCase()}. You can now download the reports from the history tab.`);
    
    loadSessionHistory();
    document.getElementById('noActiveSessionPrompt').classList.remove('hidden');
    document.getElementById('monitoringGrid').classList.add('hidden');
    clearCharts();
}

// Setup Form Submission handlers
function setupFormActions() {
    const form = document.getElementById('testConfigForm');
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        if (currentActiveSessionId) {
            alert("A load test session is currently running. Stop it before spawning a new one.");
            return;
        }

        if (!confirm("Are you sure you want to launch this Load Test? This will spawn background emulation workers.")) return;

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

    document.getElementById('clearConsoleBtn').addEventListener('click', () => {
        if (confirm("Clear terminal console lines?")) {
            document.getElementById('consoleTerminal').innerHTML = '';
        }
    });

    // SLA Actions (Import, Export, Reset)
    document.getElementById('resetSlaBtn').addEventListener('click', () => {
        setSlaData({
            max_ack_latency: 500,
            max_join_time: 2000,
            max_connection_time: 15000,
            max_webrtc_setup_time: 5000,
            max_ice_negotiation_time: 500,
            max_dtls_handshake_time: 500,
            max_packet_loss: 2.0,
            max_jitter: 30.0,
            min_success_rate: 99.0,
            max_cpu_usage: 60.0,
            max_memory_usage: 70.0
        });
        alert("SLA thresholds reset to defaults.");
    });

    document.getElementById('exportSlaBtn').addEventListener('click', () => {
        const sla = getSlaData();
        const blob = new Blob([JSON.stringify(sla, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'sla_thresholds.json';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    });

    const importFileInput = document.getElementById('slaImportFileInput');
    document.getElementById('importSlaBtn').addEventListener('click', () => {
        importFileInput.click();
    });

    importFileInput.addEventListener('change', (e) => {
        const file = e.target.files[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = (event) => {
            try {
                const sla = JSON.parse(event.target.result);
                setSlaData(sla);
                alert("SLA thresholds imported successfully!");
            } catch(err) {
                alert("Invalid SLA JSON file.");
            }
        };
        reader.readAsText(file);
    });

    // Launch Presets Selection
    const LAUNCH_PROFILES = {
        default: {
            use_fake_ui_for_media_stream: true,
            use_fake_device_for_media_stream: true,
            autoplay_policy: "no-user-gesture-required",
            disable_notifications: true,
            disable_popup_blocking: true,
            disable_infobars: true,
            disable_dev_shm_usage: true,
            no_sandbox: true,
            ignore_certificate_errors: true,
            disable_web_security: true,
            allow_running_insecure_content: true,
            custom_flags: ""
        },
        security: {
            use_fake_ui_for_media_stream: true,
            use_fake_device_for_media_stream: true,
            autoplay_policy: "user-gesture-required",
            disable_notifications: true,
            disable_popup_blocking: true,
            disable_infobars: true,
            disable_dev_shm_usage: false,
            no_sandbox: false,
            ignore_certificate_errors: false,
            disable_web_security: false,
            allow_running_insecure_content: false,
            custom_flags: ""
        },
        media: {
            use_fake_ui_for_media_stream: true,
            use_fake_device_for_media_stream: true,
            autoplay_policy: "no-user-gesture-required",
            disable_notifications: true,
            disable_popup_blocking: true,
            disable_infobars: true,
            disable_dev_shm_usage: true,
            no_sandbox: true,
            ignore_certificate_errors: true,
            disable_web_security: true,
            allow_running_insecure_content: true,
            custom_flags: "--disable-audio-processing --disable-background-timer-throttling"
        }
    };

    document.getElementById('launchProfileSelector').addEventListener('change', (e) => {
        const val = e.target.value;
        const profile = LAUNCH_PROFILES[val];
        if (profile) {
            setLaunchOptions(profile);
        }
    });

    document.getElementById('resetLaunchBtn').addEventListener('click', () => {
        setLaunchOptions(LAUNCH_PROFILES.default);
        document.getElementById('launchProfileSelector').value = 'default';
        alert("Launch profile reset to defaults.");
    });
}

function getSlaData() {
    return {
        max_ack_latency: parseInt(document.getElementById('slaAckLatency').value),
        max_join_time: parseInt(document.getElementById('slaJoinTime').value),
        max_connection_time: parseInt(document.getElementById('slaConnectionTime').value),
        max_webrtc_setup_time: parseInt(document.getElementById('slaWebrtcSetup').value),
        max_ice_negotiation_time: parseInt(document.getElementById('slaIceNegotiation').value),
        max_dtls_handshake_time: parseInt(document.getElementById('slaDtlsHandshake').value),
        max_packet_loss: parseFloat(document.getElementById('slaPacketLoss').value),
        max_jitter: parseFloat(document.getElementById('slaJitter').value),
        min_success_rate: parseFloat(document.getElementById('slaSuccessRate').value),
        max_cpu_usage: parseFloat(document.getElementById('slaCpuUsage').value),
        max_memory_usage: parseFloat(document.getElementById('slaMemoryUsage').value)
    };
}

function setSlaData(sla) {
    if (!sla) return;
    document.getElementById('slaAckLatency').value = sla.max_ack_latency || 500;
    document.getElementById('slaJoinTime').value = sla.max_join_time || 2000;
    document.getElementById('slaConnectionTime').value = sla.max_connection_time || 15000;
    document.getElementById('slaWebrtcSetup').value = sla.max_webrtc_setup_time || 5000;
    document.getElementById('slaIceNegotiation').value = sla.max_ice_negotiation_time || 500;
    document.getElementById('slaDtlsHandshake').value = sla.max_dtls_handshake_time || 500;
    document.getElementById('slaPacketLoss').value = sla.max_packet_loss || 2.0;
    document.getElementById('slaJitter').value = sla.max_jitter || 30.0;
    document.getElementById('slaSuccessRate').value = sla.min_success_rate || 99.0;
    document.getElementById('slaCpuUsage').value = sla.max_cpu_usage || 60.0;
    document.getElementById('slaMemoryUsage').value = sla.max_memory_usage || 70.0;
}

function getLaunchOptions() {
    return {
        use_fake_ui_for_media_stream: document.getElementById('optFakeUi').checked,
        use_fake_device_for_media_stream: document.getElementById('optFakeDevice').checked,
        autoplay_policy: document.getElementById('optAutoplay').value,
        disable_notifications: document.getElementById('optDisableNotifications').checked,
        disable_popup_blocking: document.getElementById('optDisablePopup').checked,
        disable_infobars: document.getElementById('optDisableInfobars').checked,
        disable_dev_shm_usage: document.getElementById('optDisableDevShm').checked,
        no_sandbox: document.getElementById('optNoSandbox').checked,
        ignore_certificate_errors: document.getElementById('optIgnoreCert').checked,
        disable_web_security: document.getElementById('optDisableWebSecurity').checked,
        allow_running_insecure_content: document.getElementById('optAllowInsecure').checked,
        custom_flags: document.getElementById('optCustomFlags').value
    };
}

function setLaunchOptions(opts) {
    if (!opts) return;
    document.getElementById('optFakeUi').checked = opts.use_fake_ui_for_media_stream !== false;
    document.getElementById('optFakeDevice').checked = opts.use_fake_device_for_media_stream !== false;
    document.getElementById('optAutoplay').value = opts.autoplay_policy || "no-user-gesture-required";
    document.getElementById('optDisableNotifications').checked = opts.disable_notifications !== false;
    document.getElementById('optDisablePopup').checked = opts.disable_popup_blocking !== false;
    document.getElementById('optDisableInfobars').checked = opts.disable_infobars !== false;
    document.getElementById('optDisableDevShm').checked = opts.disable_dev_shm_usage !== false;
    document.getElementById('optNoSandbox').checked = opts.no_sandbox !== false;
    document.getElementById('optIgnoreCert').checked = opts.ignore_certificate_errors !== false;
    document.getElementById('optDisableWebSecurity').checked = opts.disable_web_security !== false;
    document.getElementById('optAllowInsecure').checked = opts.allow_running_insecure_content !== false;
    document.getElementById('optCustomFlags').value = opts.custom_flags || "";
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
        viewer_bots: document.getElementById('formViewerBotIds').value,
        
        // SLA & Browser Launch serialized options
        sla_thresholds: JSON.stringify(getSlaData()),
        browser_launch_options: JSON.stringify(getLaunchOptions())
    };
}

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
        document.getElementById('formViewerBotIds').value = cfg.viewer_bots !== undefined && cfg.viewer_bots !== null ? cfg.viewer_bots : '6-10000';
        
        // Parse and load SLA & launch options
        if (cfg.sla_thresholds) {
            try {
                setSlaData(JSON.parse(cfg.sla_thresholds));
            } catch(e) {}
        }
        if (cfg.browser_launch_options) {
            try {
                setLaunchOptions(JSON.parse(cfg.browser_launch_options));
            } catch(e) {}
        }
        
        loadCheckboxesFromSerialized('network');
        loadCheckboxesFromSerialized('browser');
        loadCheckboxesFromSerialized('device');
        loadCheckboxesFromSerialized('os');
        
        switchTab('configurator');
    } catch (err) {
        alert("Failed to load preset configuration details.");
    }
}

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

// Helper to aggregate lifecycle metrics from log array (historical runs logs viewer)
function aggregateLifecycleFromLogs(logs) {
    const summary = {
        status_counts: { sent: 0, acknowledged: 0, broadcasted: 0, observed: 0, rendered: 0, 'timed-out': 0, failed: 0, unsupported: 0 },
        timeout_stages: { 'ack-timeout': 0, 'broadcast-timeout': 0, 'observer-timeout': 0, 'ui-render-timeout': 0, 'id-correlation-mismatch': 0 },
        unsupported_reasons: {},
        webrtc_advanced: { rtt: 0, loss: 0, jitter: 0, bitrate: 0, turn_count: 0, relay_count: 0 },
        distributions: { browser: {}, device: {}, os: {}, network: {} },
        errors: {
            "WebSocket": { "count": 0, "severity": "High", "suggested_cause": "WebSocket connection to edge signaling server interrupted." },
            "WebRTC": { "count": 0, "severity": "Critical", "suggested_cause": "WebRTC peer connection establishment failed." },
            "ICE": { "count": 0, "severity": "High", "suggested_cause": "ICE candidate gathering or connection failed." },
            "DTLS": { "count": 0, "severity": "Critical", "suggested_cause": "DTLS handshake failed between emulator and media server." },
            "Authentication": { "count": 0, "severity": "Critical", "suggested_cause": "Authentication failed. Check JWT signing key." },
            "Signaling": { "count": 0, "severity": "High", "suggested_cause": "Signaling command failed or rejected by server." },
            "Media": { "count": 0, "severity": "Medium", "suggested_cause": "Media track creation or codec negotiation failed." },
            "Network": { "count": 0, "severity": "High", "suggested_cause": "General socket connection or packet loss error." },
            "Timeout": { "count": 0, "severity": "Medium", "suggested_cause": "Action acknowledgement or observation timed out." },
            "Unknown": { "count": 0, "severity": "Low", "suggested_cause": "Unclassified warning or event error." }
        }
    };
    
    let rtts = [];
    let losses = [];
    let jitters = [];
    let bitrates = [];
    let joined = new Set();

    const classify_error = (err_msg, action) => {
        const err_lower = err_msg ? err_msg.lower() : "";
        const act_lower = action ? action.lower() : "";
        if (err_lower.includes("websocket") || err_lower.includes("ws")) return "WebSocket";
        if (err_lower.includes("ice") || err_lower.includes("stun") || err_lower.includes("turn")) return "ICE";
        if (err_lower.includes("dtls") || err_lower.includes("handshake")) return "DTLS";
        if (err_lower.includes("webrtc") || err_lower.includes("peerconnection")) return "WebRTC";
        if (err_lower.includes("auth") || err_lower.includes("jwt") || err_lower.includes("token")) return "Authentication";
        if (err_lower.includes("signaling") || err_lower.includes("signal")) return "Signaling";
        if (err_lower.includes("media") || err_lower.includes("track")) return "Media";
        if (err_lower.includes("network") || err_lower.includes("connect")) return "Network";
        if (err_lower.includes("timeout") || err_lower.includes("time out")) return "Timeout";
        if (act_lower.includes("webrtc")) return "WebRTC";
        return "Unknown";
    };
    
    logs.forEach(evt => {
        const etype = evt.event;
        if (etype === "bot_joined" && evt.bot_id) {
            joined.add(evt.bot_id);
            const fp = evt.fingerprint || {};
            const b = fp.browser_name || "Chrome";
            const d = fp.device_type || "desktop";
            const o = fp.os_type || "windows";
            const n = evt.network_condition || fp.network_profile || "wi-fi";
            
            summary.distributions.browser[b] = (summary.distributions.browser[b] || 0) + 1;
            summary.distributions.device[d] = (summary.distributions.device[d] || 0) + 1;
            summary.distributions.os[o] = (summary.distributions.os[o] || 0) + 1;
            summary.distributions.network[n] = (summary.distributions.network[n] || 0) + 1;
        } else if (etype === "action_logged") {
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
                const t_stage = evt.timeout_stage || "ack-timeout";
                if (summary.timeout_stages[t_stage] !== undefined) {
                    summary.timeout_stages[t_stage]++;
                }
                const cat = classify_error("timeout", evt.action_type);
                summary.errors[cat].count = (summary.errors[cat].count || 0) + 1;
                summary.errors[cat].last_occurrence = evt.ts;
            }
            if (resolved_status === "unsupported") {
                const reason = evt.unsupported_reason || "unknown";
                summary.unsupported_reasons[reason] = (summary.unsupported_reasons[reason] || 0) + 1;
                const cat = classify_error("unsupported: " + reason, evt.action_type);
                summary.errors[cat].count = (summary.errors[cat].count || 0) + 1;
                summary.errors[cat].last_occurrence = evt.ts;
            }
            if (resolved_status === "failed") {
                const cat = classify_error("failed", evt.action_type);
                summary.errors[cat].count = (summary.errors[cat].count || 0) + 1;
                summary.errors[cat].last_occurrence = evt.ts;
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
        } else if (etype === "error_logged") {
            const cat = classify_error(evt.error, evt.action);
            summary.errors[cat].count = (summary.errors[cat].count || 0) + 1;
            summary.errors[cat].last_occurrence = evt.ts;
        }
    });
    
    if (rtts.length > 0) summary.webrtc_advanced.rtt = rtts.reduce((a, b) => a + b, 0) / rtts.length;
    if (losses.length > 0) summary.webrtc_advanced.loss = losses.reduce((a, b) => a + b, 0) / losses.length;
    if (jitters.length > 0) summary.webrtc_advanced.jitter = jitters.reduce((a, b) => a + b, 0) / jitters.length;
    if (bitrates.length > 0) summary.webrtc_advanced.bitrate = bitrates.reduce((a, b) => a + b, 0) / bitrates.length;
    
    // Convert counts to counts/pct structure for distributions
    const totalJ = joined.size || 1;
    ['browser', 'device', 'os', 'network'].forEach(g => {
        const formatted = {};
        Object.entries(summary.distributions[g]).forEach(([k, v]) => {
            formatted[k] = { count: v, pct: (v / totalJ) * 100.0 };
        });
        summary.distributions[g] = formatted;
    });

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
        document.getElementById('activeTestBanner').classList.add('hidden');
        stopPrecisionTimer();

        // Load static metrics if session has any
        const mResponse = await fetch(`/api/sessions/${sessId}/metrics`);
        if (mResponse.ok) {
            const mData = await mResponse.json();
            clearCharts();
            mData.forEach(m => {
                const timeStr = new Date(m.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
                updateCharts(timeStr, m);
            });
            
            const finalLifecycle = aggregateLifecycleFromLogs(logs);
            if (mData.length > 0) {
                updateMetricsDashboard(mData[mData.length - 1], finalLifecycle);
            }
            
            // Sync historical timer
            const sRes = await fetch(`/api/sessions/${sessId}`);
            if (sRes.ok) {
                const sess = await sRes.json();
                const timerEl = document.getElementById('bannerSessionTimer');
                if (timerEl) {
                    timerEl.textContent = formatMsPrecision(sess.elapsed_ms || 0);
                }
                if (sess.config) {
                    renderActiveConfigSummary(sess.config);
                }
            }
        }

        logs.forEach(evt => renderConsoleLog(evt));
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

function updateSlaComplianceUI(slaStatus) {
    const card = document.getElementById('slaComplianceSidebarCard');
    const container = document.getElementById('slaComplianceList');
    const overallBadge = document.getElementById('slaOverallBadge');
    
    if (!slaStatus || Object.keys(slaStatus).length === 0) {
        card.style.display = 'none';
        return;
    }
    
    card.style.display = 'block';
    container.innerHTML = '';
    
    let overallPassed = true;
    
    const labels = {
        max_ack_latency: "ACK Latency",
        max_join_time: "Join Latency",
        max_connection_time: "Connection Latency",
        max_webrtc_setup_time: "WebRTC Setup",
        max_ice_negotiation_time: "ICE Negotiation",
        max_dtls_handshake_time: "DTLS Handshake",
        max_packet_loss: "Packet Loss",
        max_jitter: "Jitter",
        min_success_rate: "Success Rate",
        max_cpu_usage: "Host CPU Load",
        max_memory_usage: "Host RAM Load"
    };
    
    for (const [key, value] of Object.entries(slaStatus)) {
        if (!value) continue;
        const pass = value.pass;
        if (!pass) overallPassed = false;
        
        const label = labels[key] || key;
        const measured = typeof value.measured === 'number' ? value.measured.toFixed(1) : value.measured;
        const limit = typeof value.limit === 'number' ? value.limit.toFixed(1) : value.limit;
        const unit = (key.includes('rate') || key.includes('loss') || key.includes('usage') || key.includes('cpu') || key.includes('memory')) ? '%' : 'ms';
        
        const item = document.createElement('div');
        item.className = 'telemetry-item';
        item.style.borderLeft = pass ? '3px solid var(--emerald)' : '3px solid var(--red)';
        item.style.paddingLeft = '8px';
        item.style.marginBottom = '6px';
        item.style.display = 'flex';
        item.style.justifyContent = 'space-between';
        
        item.innerHTML = `
            <span class="label" style="font-weight: 500;">${label}</span>
            <span style="font-size:12px; color: ${pass ? 'var(--emerald)' : 'var(--red)'}; font-weight:bold;">
                ${measured}${unit} <span style="font-weight:normal; color:var(--text-muted);">/ limit ${limit}${unit}</span>
            </span>
        `;
        container.appendChild(item);
    }
    
    if (overallPassed) {
        overallBadge.textContent = "PASSED";
        overallBadge.className = "badge badge-completed";
    } else {
        overallBadge.textContent = "VIOLATED";
        overallBadge.className = "badge badge-failed";
    }
}
