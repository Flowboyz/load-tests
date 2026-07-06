# Konn3ct Load Testing - Enhanced Analytics Report

## 1. Executive Performance Summary
- **Total Simulated Bots**: 5
- **Peak Concurrent Connections**: 5
- **Test Duration**: N/A
- **WebSocket Connection Drops**: 0
- **WebRTC Reconnection Count**: 0

## 2. Browser Performance Rankings
| Rank | Browser Client | Success Rate | Average Join Time | Packet Loss |
| :--- | :--- | :---: | :---: | :---: |
| #1 | Chrome_Mobile | 100.0% | 1000 ms | 0.00% |
| #2 | Firefox | 100.0% | 1000 ms | 0.00% |
| #3 | Chrome | 72.7% | 1000 ms | 0.00% |

## 3. Operating System Stability Rankings
| Rank | Operating System | Success Rate | Average RTT | Failure Count |
| :--- | :--- | :---: | :---: | :---: |
| #1 | Macos | 100.0% | 35.0 ms | 0 |
| #2 | Windows | 82.4% | 35.0 ms | 1 |

## 4. Simulated Device Cohort Rankings
| Rank | Device Profile | Success Rate | Average Latency | Stability Verdict |
| :--- | :--- | :---: | :---: | :---: |
| #1 | Desktop | 100.0% | 35.0 ms | Stable |
| #2 | Mobile | 66.7% | 35.0 ms | Degraded |

## 5. Failure & Error Analysis Breakdown
| Error Standard Code | Occurrences Count | Description |
| :--- | :---: | :--- |
| `CHAT_ACK_TIMEOUT` | 12 | Telemetry recorded action failure |
| `SCREEN_SHARE_UNSUPPORTED` | 2 | Telemetry recorded action failure |

## 6. Bucketed Event Timeline
| Time Delta | Event Description | Severity |
| :--- | :--- | :---: |
| 0s | Test Session Start Triggered | **Low** |
| +55s | Error Spike: 1 errors logged. | **Medium** |
| +70s | Error Spike: 1 errors logged. | **Medium** |
| +80s | Error Spike: 1 errors logged. | **Medium** |

## 7. Automated Recommendations Engine
### [Low] General Performance
- **Issue Detected**: All quality gates satisfied.
- **Evidence-Based Remediation Action**: No adjustments are recommended at this time.

## 8. WebRTC Telemetry Performance Results
The table below summarizes the measured session results for each of the core WebRTC telemetry metrics defined in the glossary:

| WebRTC Telemetry Metric | Session Result | Status / Layman Assessment |
| :--- | :---: | :--- |
| **1. RTT (Round Trip Time)** | 30 ms | Good: Under 200ms is healthy; lag is imperceptible. |
| **2. Jitter** | 3.9 ms | Stable: Low packet arrival variation. Smooth streaming. |
| **3. Packet Loss** | 0.00% | Excellent: Zero or minimal packet loss. Voices sound clear. |
| **4. ICE State** | Connected | Successful: Network paths between browsers and SFU are established. |
| **5. Send Bitrate** | 0 kbps (Muted) | Normal: Pushing active mic stream data up to meeting. |
| **6. Recv (Receive) Bitrate** | 0 kbps | Active: Downloading participant audio/video streams. |
| **7. Avail Out Bitrate** | 141 kbps (Estimated) | Healthy: Browser estimates sufficient local bandwidth margin. |
| **8. FPS (Frames Per Second)** | 0 FPS (Muted) | Normal: Camera is muted. |
| **9. Frames Dropped** | 0 (Perfect) | Excellent: Hardware running cool; zero video rendering stutter. |
| **10. Reconnects** | 0 | Stable: Zero connection drops detected. |

