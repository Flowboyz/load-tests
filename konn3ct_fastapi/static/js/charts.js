// charts.js — Real-Time Telemetry Charts Configurations

let botsChart = null;
let latencyChart = null;
let joinChart = null;
let networkChart = null;
let resourcesChart = null;
let throughputChart = null;
let activityChart = null;

const MAX_CHART_POINTS = 150; // Larger history window for panning and zooming depth

function initCharts() {
    const isDarkMode = document.body.classList.contains('dark-mode');
    const gridColor = isDarkMode ? '#2D3748' : '#E2E8F0';
    const textColor = isDarkMode ? '#A0AEC0' : '#4A5568';
    
    const chartDefaults = {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: {
                display: true,
                position: 'top',
                labels: {
                    color: textColor,
                    boxWidth: 10,
                    padding: 8,
                    font: { size: 10, family: 'Inter', weight: '500' }
                }
            },
            zoom: {
                pan: {
                    enabled: true,
                    mode: 'x',
                    modifierKey: 'ctrl', // ctrl + drag to pan
                },
                zoom: {
                    wheel: {
                        enabled: true,
                        speed: 0.05
                    },
                    pinch: {
                        enabled: true
                    },
                    mode: 'x'
                }
            }
        },
        scales: {
            x: {
                grid: { color: gridColor, drawBorder: false },
                ticks: { color: textColor, font: { size: 9, family: 'Inter' }, maxRotation: 0, autoSkip: true, maxTicksLimit: 8 }
            },
            y: {
                grid: { color: gridColor, drawBorder: false },
                ticks: { color: textColor, font: { size: 9, family: 'Inter' } }
            }
        }
    };

    // Helper to clone defaults with minor changes
    const getOptions = (overrides = {}) => {
        return JSON.parse(JSON.stringify(chartDefaults));
    };

    // 1. Bots Connection Chart
    const ctxBots = document.getElementById('botsChart').getContext('2d');
    botsChart = new Chart(ctxBots, {
        type: 'line',
        data: {
            labels: [],
            datasets: [
                {
                    label: 'Connected',
                    borderColor: '#06B6D4', // cyan
                    backgroundColor: 'rgba(6, 182, 212, 0.05)',
                    data: [],
                    borderWidth: 2,
                    fill: true,
                    tension: 0.3
                },
                {
                    label: 'Active (WebRTC)',
                    borderColor: '#10B981', // green
                    backgroundColor: 'rgba(16, 185, 129, 0.05)',
                    data: [],
                    borderWidth: 2,
                    fill: true,
                    tension: 0.3
                },
                {
                    label: 'Connecting',
                    borderColor: '#60A5FA', // blue
                    data: [],
                    borderWidth: 1.5,
                    pointRadius: 0,
                    tension: 0.3
                },
                {
                    label: 'Reconnecting',
                    borderColor: '#F59E0B', // yellow
                    data: [],
                    borderWidth: 1.5,
                    pointRadius: 0,
                    tension: 0.3
                },
                {
                    label: 'Failed',
                    borderColor: '#EF4444', // red
                    backgroundColor: 'rgba(239, 68, 68, 0.05)',
                    data: [],
                    borderWidth: 2,
                    fill: true,
                    tension: 0.3
                }
            ]
        },
        options: chartDefaults // chartDefaults registers zoom plugin options natively
    });

    // 2. Latency Profile Chart
    const ctxLatency = document.getElementById('latencyChart').getContext('2d');
    latencyChart = new Chart(ctxLatency, {
        type: 'line',
        data: {
            labels: [],
            datasets: [
                {
                    label: 'Avg Action Latency (ms)',
                    borderColor: '#8B5CF6', // purple
                    data: [],
                    borderWidth: 2,
                    tension: 0.3
                },
                {
                    label: 'ACK Latency (ms)',
                    borderColor: '#6366F1', // indigo
                    data: [],
                    borderWidth: 1.5,
                    tension: 0.3
                },
                {
                    label: 'Peak Latency (ms)',
                    borderColor: '#EF4444', // red
                    data: [],
                    borderWidth: 1.5,
                    borderDash: [4, 4],
                    tension: 0.3
                }
            ]
        },
        options: chartDefaults
    });

    // 3. Join Performance Chart
    const ctxJoin = document.getElementById('joinChart').getContext('2d');
    joinChart = new Chart(ctxJoin, {
        type: 'line',
        data: {
            labels: [],
            datasets: [
                {
                    label: 'Join Rate (bots/sec)',
                    borderColor: '#06B6D4',
                    yAxisID: 'yJoinRate',
                    data: [],
                    borderWidth: 2,
                    tension: 0.2
                },
                {
                    label: 'Avg Join Time (ms)',
                    borderColor: '#EC4899', // pink
                    yAxisID: 'yJoinTime',
                    data: [],
                    borderWidth: 2,
                    tension: 0.2
                }
            ]
        },
        options: {
            ...chartDefaults,
            scales: {
                x: chartDefaults.scales.x,
                yJoinRate: {
                    type: 'linear',
                    position: 'left',
                    grid: { color: gridColor, drawBorder: false },
                    ticks: { color: textColor, font: { size: 9 } },
                    title: { display: true, text: 'Joins/Sec', color: textColor, font: { size: 9 } }
                },
                yJoinTime: {
                    type: 'linear',
                    position: 'right',
                    grid: { drawOnChartArea: false }, // no overlapping grids
                    ticks: { color: textColor, font: { size: 9 } },
                    title: { display: true, text: 'Avg Duration (ms)', color: textColor, font: { size: 9 } }
                }
            }
        }
    });

    // 4. WebRTC Quality Chart (Packet Loss & Jitter)
    const ctxNetwork = document.getElementById('networkChart').getContext('2d');
    networkChart = new Chart(ctxNetwork, {
        type: 'line',
        data: {
            labels: [],
            datasets: [
                {
                    label: 'Packet Loss (%)',
                    borderColor: '#EF4444',
                    yAxisID: 'yLoss',
                    data: [],
                    borderWidth: 2,
                    tension: 0.3
                },
                {
                    label: 'Jitter (ms)',
                    borderColor: '#F59E0B',
                    yAxisID: 'yJitter',
                    data: [],
                    borderWidth: 2,
                    tension: 0.3
                }
            ]
        },
        options: {
            ...chartDefaults,
            scales: {
                x: chartDefaults.scales.x,
                yLoss: {
                    type: 'linear',
                    position: 'left',
                    grid: { color: gridColor, drawBorder: false },
                    ticks: { color: textColor, font: { size: 9 } },
                    title: { display: true, text: 'Packet Loss %', color: textColor, font: { size: 9 } }
                },
                yJitter: {
                    type: 'linear',
                    position: 'right',
                    grid: { drawOnChartArea: false },
                    ticks: { color: textColor, font: { size: 9 } },
                    title: { display: true, text: 'Jitter ms', color: textColor, font: { size: 9 } }
                }
            }
        }
    });

    // 5. System Host Resources Chart (CPU & RAM)
    const ctxResources = document.getElementById('resourcesChart').getContext('2d');
    resourcesChart = new Chart(ctxResources, {
        type: 'line',
        data: {
            labels: [],
            datasets: [
                {
                    label: 'CPU Usage (%)',
                    borderColor: '#8B5CF6',
                    data: [],
                    borderWidth: 2,
                    tension: 0.2
                },
                {
                    label: 'RAM Usage (%)',
                    borderColor: '#3B82F6',
                    data: [],
                    borderWidth: 2,
                    tension: 0.2
                }
            ]
        },
        options: chartDefaults
    });

    // 6. Data Throughput Profile Chart (Network kbps & WebRTC bitrate)
    const ctxThroughput = document.getElementById('throughputChart').getContext('2d');
    throughputChart = new Chart(ctxThroughput, {
        type: 'line',
        data: {
            labels: [],
            datasets: [
                {
                    label: 'Host Net Throughput (Mbps)',
                    borderColor: '#10B981',
                    yAxisID: 'yMbps',
                    data: [],
                    borderWidth: 2,
                    tension: 0.3
                },
                {
                    label: 'Avg WebRTC Bitrate (kbps)',
                    borderColor: '#3B82F6',
                    yAxisID: 'yKbps',
                    data: [],
                    borderWidth: 1.5,
                    tension: 0.3
                }
            ]
        },
        options: {
            ...chartDefaults,
            scales: {
                x: chartDefaults.scales.x,
                yMbps: {
                    type: 'linear',
                    position: 'left',
                    grid: { color: gridColor, drawBorder: false },
                    ticks: { color: textColor, font: { size: 9 } },
                    title: { display: true, text: 'Throughput (Mbps)', color: textColor, font: { size: 9 } }
                },
                yKbps: {
                    type: 'linear',
                    position: 'right',
                    grid: { drawOnChartArea: false },
                    ticks: { color: textColor, font: { size: 9 } },
                    title: { display: true, text: 'WebRTC (kbps)', color: textColor, font: { size: 9 } }
                }
            }
        }
    });

    // 7. Event Stream Activity Chart (EPS/MPS)
    const ctxActivity = document.getElementById('activityChart').getContext('2d');
    activityChart = new Chart(ctxActivity, {
        type: 'line',
        data: {
            labels: [],
            datasets: [
                {
                    label: 'Events / Sec (EPS)',
                    borderColor: '#F59E0B',
                    data: [],
                    borderWidth: 2,
                    tension: 0.2
                },
                {
                    label: 'Messages / Sec (MPS)',
                    borderColor: '#06B6D4',
                    data: [],
                    borderWidth: 2,
                    tension: 0.2
                }
            ]
        },
        options: chartDefaults
    });
}

function updateCharts(timeStr, metrics) {
    if (!botsChart || !latencyChart || !joinChart || !networkChart || !resourcesChart || !throughputChart || !activityChart) return;

    // Helper to push and shift label/data
    const pushData = (chart, index, val) => {
        chart.data.datasets[index].data.push(val);
        if (chart.data.datasets[index].data.length > MAX_CHART_POINTS) {
            chart.data.datasets[index].data.shift();
        }
    };

    const pushLabel = (chart, label) => {
        if (chart.data.labels.length === 0 || chart.data.labels[chart.data.labels.length - 1] !== label) {
            chart.data.labels.push(label);
            if (chart.data.labels.length > MAX_CHART_POINTS) {
                chart.data.labels.shift();
            }
        }
    };

    // Bots Connection Chart
    pushLabel(botsChart, timeStr);
    pushData(botsChart, 0, metrics.connected_bots);
    pushData(botsChart, 1, metrics.active_bots);
    pushData(botsChart, 2, metrics.connecting_bots);
    pushData(botsChart, 3, metrics.reconnecting_bots);
    pushData(botsChart, 4, metrics.failed_bots);
    botsChart.update('none');

    // Latency Chart
    pushLabel(latencyChart, timeStr);
    pushData(latencyChart, 0, metrics.avg_latency);
    pushData(latencyChart, 1, metrics.ack_latency);
    pushData(latencyChart, 2, metrics.peak_latency);
    latencyChart.update('none');

    // Join Chart
    pushLabel(joinChart, timeStr);
    pushData(joinChart, 0, metrics.join_rate);
    pushData(joinChart, 1, metrics.avg_join_time);
    joinChart.update('none');

    // WebRTC Network Quality Chart
    pushLabel(networkChart, timeStr);
    pushData(networkChart, 0, metrics.packet_loss);
    pushData(networkChart, 1, metrics.jitter);
    networkChart.update('none');

    // Resources Chart
    pushLabel(resourcesChart, timeStr);
    pushData(resourcesChart, 0, metrics.cpu_usage);
    pushData(resourcesChart, 1, metrics.ram_usage);
    resourcesChart.update('none');

    // Throughput Chart (Convert net_throughput_kbps to Mbps for readability)
    const mbps = (metrics.net_throughput_kbps || 0.0) / 1024.0;
    pushLabel(throughputChart, timeStr);
    pushData(throughputChart, 0, mbps);
    pushData(throughputChart, 1, metrics.bitrate || 0);
    throughputChart.update('none');

    // Activity Chart
    pushLabel(activityChart, timeStr);
    pushData(activityChart, 0, metrics.eps || 0.0);
    pushData(activityChart, 1, metrics.mps || 0.0);
    activityChart.update('none');
}

function clearCharts() {
    const list = [botsChart, latencyChart, joinChart, networkChart, resourcesChart, throughputChart, activityChart];
    list.forEach(chart => {
        if (!chart) return;
        chart.data.labels = [];
        chart.data.datasets.forEach(ds => {
            ds.data = [];
        });
        chart.update();
    });
}

function resetChartZoom(chartId) {
    const chart = getChartInstanceById(chartId);
    if (chart && typeof chart.resetZoom === 'function') {
        chart.resetZoom();
    }
}

function downloadChartPNG(chartId) {
    const chart = getChartInstanceById(chartId);
    if (chart) {
        const url = chart.toBase64Image();
        const link = document.createElement('a');
        link.download = `${chartId}_export_${Date.now()}.png`;
        link.href = url;
        link.click();
    }
}

function getChartInstanceById(chartId) {
    const instances = {
        'botsChart': botsChart,
        'latencyChart': latencyChart,
        'joinChart': joinChart,
        'networkChart': networkChart,
        'resourcesChart': resourcesChart,
        'throughputChart': throughputChart,
        'activityChart': activityChart
    };
    return instances[chartId];
}

// Adjust colors dynamically when theme shifts
function rethemeCharts(isDarkMode) {
    const gridColor = isDarkMode ? '#2D3748' : '#E2E8F0';
    const textColor = isDarkMode ? '#A0AEC0' : '#4A5568';
    const list = [botsChart, latencyChart, joinChart, networkChart, resourcesChart, throughputChart, activityChart];

    list.forEach(chart => {
        if (!chart) return;
        
        // Update scales tick & grid colors
        if (chart.options.scales.x) {
            chart.options.scales.x.grid.color = gridColor;
            chart.options.scales.x.ticks.color = textColor;
        }
        
        // Adjust multiple y-axes if they exist
        if (chartIdMatchesAxes(chart)) {
            Object.keys(chart.options.scales).forEach(key => {
                if (key.startsWith('y')) {
                    if (chart.options.scales[key].grid) {
                        chart.options.scales[key].grid.color = gridColor;
                    }
                    chart.options.scales[key].ticks.color = textColor;
                    if (chart.options.scales[key].title) {
                        chart.options.scales[key].title.color = textColor;
                    }
                }
            });
        } else if (chart.options.scales.y) {
            chart.options.scales.y.grid.color = gridColor;
            chart.options.scales.y.ticks.color = textColor;
        }
        
        chart.options.plugins.legend.labels.color = textColor;
        chart.update();
    });
}

function chartIdMatchesAxes(chart) {
    return chart === joinChart || chart === networkChart || chart === throughputChart;
}
