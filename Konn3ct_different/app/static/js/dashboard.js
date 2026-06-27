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
                        ${isFinished ? `<a class="btn btn-sm btn-secondary" href="/api/sessions/${sess.id}/download/docx" title="Download Word"><i class="fa-solid fa-file-word text-cyan"></i> DOCX</a>` : ''}
                        ${isFinished ? `<a class="btn btn-sm btn-secondary" href="/api/sessions/${sess.id}/download/pdf" title="Download PDF"><i class="fa-solid fa-file-pdf text-red"></i> PDF</a>` : ''}
                        ${isFinished ? `<a class="btn btn-sm btn-secondary" href="/api/sessions/${sess.id}/download/csv" title="Download CSV"><i class="fa-solid fa-file-csv text-green"></i> CSV</a>` : ''}
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
        
        const active = data.find(s => s.status === 'running' || s.status === 'paused');
        if (active) {
            setupActiveSession(active.id, active.name, active.status);
        }
    } catch (err) {
        console.error("Failed to check active sessions: ", err);
    }
}

// Set UI state for active load test session
function setupActiveSession(sessionId, sessionName, status) {
    currentActiveSessionId = sessionId;
    
    // Hide placeholder, show live dashboard grids
    document.getElementById('noActiveSessionPrompt').classList.add('hidden');
    document.getElementById('monitoringGrid').classList.remove('hidden');
    
    // Show Top bar controls
    const banner = document.getElementById('activeTestBanner');
    banner.classList.remove('hidden');
    document.getElementById('bannerSessionName').textContent = sessionName;
    
    updateBannerStatusText(status);

    // Initialise WebSockets Socket.IO client connection
    initWebSocket(sessionId);
}

function updateBannerStatusText(status) {
    const badge = document.getElementById('bannerSessionStatus');
    badge.textContent = status.toUpperCase();
    badge.className = 'badge';
    
    const pauseBtn = document.getElementById('bannerPauseBtn');
    const resumeBtn = document.getElementById('bannerResumeBtn');
    
    if (status === 'running') {
        badge.classList.add('badge-running');
        pauseBtn.classList.remove('hidden');
        resumeBtn.classList.add('hidden');
    } else if (status === 'paused') {
        badge.classList.add('badge-running'); // Keep flashing
        badge.style.backgroundColor = 'var(--warning-soft)';
        badge.style.color = 'var(--warning)';
        pauseBtn.classList.add('hidden');
        resumeBtn.classList.remove('hidden');
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
        
        // Add log separator in console
        const consoleEl = document.getElementById('consoleTerminal');
        consoleEl.innerHTML = `<div class="log-entry"><span class="ts">[SYSTEM]</span> <span class="tag">INFO:</span> <span class="info">Connected to real-time event streaming.</span></div>`;
    });

    // Listen for raw logs
    socket.on('session_raw_event', (payload) => {
        if (payload.session_id !== sessionId) return;
        renderConsoleLog(payload.event);
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
        consoleEl.scrollTop = consoleEl.scrollHeight;
    });

    // Listen for metrics updates
    socket.on('session_metrics', (payload) => {
        if (payload.session_id !== sessionId) return;
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

// Log Terminal renderer
function renderConsoleLog(evt) {
    const consoleEl = document.getElementById('consoleTerminal');
    
    // Clear placeholder
    const placeholder = consoleEl.querySelector('.console-placeholder');
    if (placeholder) placeholder.remove();
    
    const etype = evt.event;
    const filter = document.getElementById('logLevelFilter').value;
    const search = document.getElementById('logSearchInput').value.toLowerCase();
    
    // Filters check
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
        if (evt.status === "confirmed") {
            logMsg = `✅ Bot-${evt.bot_id} (${evt.name}) action confirmed: ${evt.action_type} → ${value}${latency}`;
            statusClass = "info";
        } else if (evt.status.startsWith("observed:")) {
            logMsg = `👀 Bot-${evt.bot_id} (${evt.name}) observed ${evt.status.split(":", 2)[1]} performing: ${evt.action_type} → ${value}${latency}`;
            statusClass = "tag";
        } else if (evt.status === "timed_out") {
            logMsg = `⚠️ Bot-${evt.bot_id} (${evt.name}) action confirmation timeout on: ${evt.action_type}`;
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
    
    // Search check
    if (search && !logMsg.toLowerCase().includes(search)) return;

    const timeStr = new Date(evt.ts).toLocaleTimeString();
    
    const entry = document.createElement('div');
    entry.className = 'log-entry';
    entry.innerHTML = `
        <span class="ts">[${timeStr}]</span>
        <span class="${statusClass}">${logMsg}</span>
    `;
    
    consoleEl.appendChild(entry);
    
    // Auto scroll to bottom
    consoleEl.scrollTop = consoleEl.scrollHeight;
}

// Live card values updater
function updateMetricsCards(metrics, lifecycleSummary) {
    document.getElementById('metricConnectedBots').textContent = metrics.connected_bots;
    document.getElementById('metricConnectingBots').textContent = metrics.connecting_bots;
    document.getElementById('metricReconnectingBots').textContent = metrics.reconnecting_bots;
    
    document.getElementById('metricLatency').textContent = metrics.avg_latency ? metrics.avg_latency.toFixed(1) : '0';
    document.getElementById('metricPacketLoss').textContent = metrics.packet_loss ? metrics.packet_loss.toFixed(2) : '0.00';
    document.getElementById('metricBitrate').textContent = metrics.bitrate || '0';

    // Update real-time lifecycle widgets if available
    if (lifecycleSummary) {
        // 1. Action Lifecycle Propagation
        if (lifecycleSummary.status_counts) {
            document.getElementById('lifecycleSent').textContent = lifecycleSummary.status_counts.sent || 0;
            document.getElementById('lifecycleAcknowledged').textContent = lifecycleSummary.status_counts.acknowledged || 0;
            document.getElementById('lifecycleBroadcasted').textContent = lifecycleSummary.status_counts.broadcasted || 0;
            document.getElementById('lifecycleObserved').textContent = lifecycleSummary.status_counts.observed || 0;
            document.getElementById('lifecycleRendered').textContent = lifecycleSummary.status_counts.rendered || 0;
        }

        // 2. Advanced WebRTC Parameters
        if (lifecycleSummary.webrtc_advanced) {
            const webrtc = lifecycleSummary.webrtc_advanced;
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
    
    currentActiveSessionId = null;
    
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
        os_distribution: document.getElementById('formOsDistribution').value
    };
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
        
        // Load static metrics if session has any
        const mResponse = await fetch(`/api/sessions/${sessId}/metrics`);
        if (mResponse.ok) {
            const mData = await mResponse.json();
            clearCharts();
            mData.forEach(m => {
                const timeStr = new Date(m.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
                updateCharts(timeStr, m);
            });
            if (mData.length > 0) {
                const finalLifecycle = aggregateLifecycleFromLogs(logs);
                updateMetricsCards(mData[mData.length - 1], finalLifecycle);
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
