import React, { useEffect, useState } from 'react';

const API_BASE = window.location.host;

export default function Dashboard() {
    const [alerts, setAlerts] = useState([]);

    useEffect(() => {
        const evtSource = new EventSource(`http://${API_BASE}/alerts/stream`);

        evtSource.onmessage = (event) => {
            const data = JSON.parse(event.data);
            setAlerts(prev => {
                if (prev.find(a => a.session_id === data.session_id)) return prev;
                return [data, ...prev];
            });
        };

        return () => evtSource.close();
    }, []);

    const intervene = (sessionId) => {
        alert(`Connecting agent to session ${sessionId}...`);
        setAlerts(prev => prev.filter(a => a.session_id !== sessionId));
    };

    return (
        <div className="container">
            <header>
                <h1><span style={{ color: 'var(--danger)' }}>🔴</span> Live Fraud Operations</h1>
                <div style={{ fontSize: '0.875rem', color: '#94a3b8' }}>Covert Security Protocol Monitoring</div>
            </header>

            <div className="dashboard-grid">
                {alerts.map(a => (
                    <div key={a.session_id} className="alert-card">
                        <div className="alert-header">
                            <span>⚠️ DURESS SIGNAL DETECTED</span>
                            <button className="btn" style={{ padding: '0.25rem 0.75rem', fontSize: '0.75rem' }} onClick={() => intervene(a.session_id)}>
                                Intervene
                            </button>
                        </div>
                        <div className="stat">
                            <span>Session ID</span>
                            <span className="stat-value">{a.session_id}</span>
                        </div>
                        <div className="stat">
                            <span>Target Amount</span>
                            <span className="stat-value" style={{ color: '#fbbf24' }}>₹{a.amount || 'Unknown'}</span>
                        </div>
                        <div className="stat">
                            <span>Risk Score</span>
                            <span className="stat-value" style={{ color: 'var(--danger)' }}>{a.risk_score.toFixed(2)}</span>
                        </div>
                        <div style={{ marginTop: '1rem' }}>
                            <div style={{ fontSize: '0.75rem', color: '#94a3b8', marginBottom: '0.5rem', textTransform: 'uppercase' }}>Live Transcript</div>
                            {a.transcript.map((t, i) => (
                                <div key={i} style={{ background: 'rgba(255,255,255,0.05)', padding: '0.5rem', borderRadius: '4px', marginBottom: '0.5rem', fontSize: '0.875rem' }}>
                                    "{t}"
                                </div>
                            ))}
                        </div>
                    </div>
                ))}
                {alerts.length === 0 && (
                    <div style={{ color: '#94a3b8' }}>No active alerts. Monitoring streams...</div>
                )}
            </div>
        </div>
    );
}
