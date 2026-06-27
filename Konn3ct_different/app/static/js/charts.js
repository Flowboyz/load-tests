// charts.js — Real-Time Chart.js Configuration

let botsChart = null;
let latencyChart = null;
let resourcesChart = null;

const MAX_CHART_POINTS = 30;

function initCharts() {
    const isDarkMode = document.body.classList.contains('dark-mode');
    const gridColor = isDarkMode ? '#374151' : '#E5E7EB';
    const textColor = isDarkMode ? '#9CA3AF' : '#4B5563';
    
    const chartDefaults = {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: {
                display: true,
                position: 'top',
                labels: {
                    color: textColor,
                    boxWidth: 12,
                    font: { size: 10, family: 'Inter' }
                }
            }
        },
        scales: {
            x: {
                grid: { color: gridColor },
                ticks: { color: textColor, font: { size: 9 } }
            },
            y: {
                grid: { color: gridColor },
                ticks: { color: textColor, font: { size: 9 } }
            }
        }
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
                    borderColor: '#10B981', // green
                    backgroundColor: 'rgba(16, 185, 129, 0.1)',
                    data: [],
                    borderWidth: 2.5,
                    fill: true,
                    tension: 0.3
                },
                {
                    label: 'Connecting',
                    borderColor: '#06B6D4', // cyan
                    data: [],
                    borderWidth: 1.5,
                    pointStyle: 'circle',
                    pointRadius: 0,
                    tension: 0.3
                },
                {
                    label: 'Failed',
                    borderColor: '#EF4444', // red
                    backgroundColor: 'rgba(239, 68, 68, 0.1)',
                    data: [],
                    borderWidth: 2.5,
                    fill: true,
                    tension: 0.3
                },
                {
                    label: 'Reconnecting',
                    borderColor: '#F59E0B', // yellow
                    data: [],
                    borderWidth: 1.5,
                    pointStyle: 'circle',
                    pointRadius: 0,
                    tension: 0.3
                }
            ]
        },
        options: chartDefaults
    });

    // 2. Latency and Jitter Chart
    const ctxLatency = document.getElementById('latencyChart').getContext('2d');
    latencyChart = new Chart(ctxLatency, {
        type: 'line',
        data: {
            labels: [],
            datasets: [
                {
                    label: 'Avg Latency (ms)',
                    borderColor: '#F59E0B',
                    backgroundColor: 'rgba(245, 158, 11, 0.05)',
                    data: [],
                    borderWidth: 2,
                    tension: 0.3
                },
                {
                    label: 'Jitter (ms)',
                    borderColor: '#EC4899', // pink
                    data: [],
                    borderWidth: 1.5,
                    tension: 0.3
                }
            ]
        },
        options: chartDefaults
    });

    // 3. Resources Chart (CPU & RAM)
    const ctxResources = document.getElementById('resourcesChart').getContext('2d');
    resourcesChart = new Chart(ctxResources, {
        type: 'line',
        data: {
            labels: [],
            datasets: [
                {
                    label: 'CPU Usage (%)',
                    borderColor: '#8B5CF6', // purple
                    data: [],
                    borderWidth: 2,
                    tension: 0.2
                },
                {
                    label: 'RAM Usage (%)',
                    borderColor: '#0EA5E9', // blue
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
    if (!botsChart || !latencyChart || !resourcesChart) return;

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

    // Bots Connection Chart updates
    pushLabel(botsChart, timeStr);
    pushData(botsChart, 0, metrics.connected_bots);
    pushData(botsChart, 1, metrics.connecting_bots);
    pushData(botsChart, 2, metrics.failed_bots);
    pushData(botsChart, 3, metrics.reconnecting_bots);
    botsChart.update('none'); // Update without animation for rendering performance

    // Latency Chart updates
    pushLabel(latencyChart, timeStr);
    pushData(latencyChart, 0, metrics.avg_latency);
    pushData(latencyChart, 1, metrics.jitter);
    latencyChart.update('none');

    // Resources Chart updates
    pushLabel(resourcesChart, timeStr);
    pushData(resourcesChart, 0, metrics.cpu_usage);
    pushData(resourcesChart, 1, metrics.ram_usage);
    resourcesChart.update('none');
}

function clearCharts() {
    if (!botsChart || !latencyChart || !resourcesChart) return;
    
    [botsChart, latencyChart, resourcesChart].forEach(chart => {
        chart.data.labels = [];
        chart.data.datasets.forEach(ds => {
            ds.data = [];
        });
        chart.update();
    });
}

// Adjust colors dynamically when theme shifts
function rethemeCharts(isDarkMode) {
    const gridColor = isDarkMode ? '#374151' : '#E5E7EB';
    const textColor = isDarkMode ? '#9CA3AF' : '#4B5563';

    [botsChart, latencyChart, resourcesChart].forEach(chart => {
        if (!chart) return;
        chart.options.scales.x.grid.color = gridColor;
        chart.options.scales.x.ticks.color = textColor;
        chart.options.scales.y.grid.color = gridColor;
        chart.options.scales.y.ticks.color = textColor;
        chart.options.plugins.legend.labels.color = textColor;
        chart.update();
    });
}
