import React, { useState, useRef, useEffect } from 'react';
import { Link } from 'react-router-dom';

const API_BASE = window.location.host;

export default function CallerUI() {
    const [isCalling, setIsCalling] = useState(false);
    const [messages, setMessages] = useState([{ role: 'ai', content: 'Hello! I am your SecureBank AI assistant. How can I help you today?' }]);
    const wsRef = useRef(null);
    const processorRef = useRef(null);
    const mediaStreamRef = useRef(null);
    const audioContextRef = useRef(null);
    const chatRef = useRef(null);

    useEffect(() => {
        if (chatRef.current) {
            chatRef.current.scrollTop = chatRef.current.scrollHeight;
        }
    }, [messages]);

    const startCall = async () => {
        setIsCalling(true);
        wsRef.current = new WebSocket(`ws://${API_BASE}/call`);

        wsRef.current.onopen = async () => {
            try {
                mediaStreamRef.current = await navigator.mediaDevices.getUserMedia({ audio: true });
                audioContextRef.current = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
                const source = audioContextRef.current.createMediaStreamSource(mediaStreamRef.current);
                
                processorRef.current = audioContextRef.current.createScriptProcessor(4096, 1, 1);
                
                source.connect(processorRef.current);
                processorRef.current.connect(audioContextRef.current.destination);
                
                processorRef.current.onaudioprocess = (e) => {
                    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
                        const inputData = e.inputBuffer.getChannelData(0);
                        
                        const rms = Math.sqrt(inputData.reduce((acc, val) => acc + val * val, 0) / inputData.length);
                        if (rms > 0.01) {
                            const pcm16 = new Int16Array(inputData.length);
                            for (let i = 0; i < inputData.length; i++) {
                                pcm16[i] = Math.max(-1, Math.min(1, inputData[i])) * 0x7FFF;
                            }
                            wsRef.current.send(pcm16.buffer);
                        }
                    }
                };
            } catch (err) {
                console.error('Error accessing microphone:', err);
                setMessages(prev => [...prev, { role: 'ai', content: 'Error accessing microphone. Please allow permissions.' }]);
                stopCall();
            }
        };

        wsRef.current.onmessage = (e) => {
            const data = JSON.parse(e.data);
            if (data.type === 'response') {
                if (data.transcript) {
                    setMessages(prev => [...prev, { role: 'user', content: data.transcript, riskScore: data.risk_score }]);
                }
                if (data.reply) {
                    setMessages(prev => [...prev, { role: 'ai', content: data.reply }]);
                }
                
                if (data.audio) {
                    const audioStr = 'data:audio/wav;base64,' + data.audio;
                    const audio = new Audio(audioStr);
                    audio.play();
                }
            }
        };

        wsRef.current.onclose = () => {
            stopCall();
        };
    };

    const stopCall = () => {
        if (processorRef.current) {
            processorRef.current.disconnect();
            processorRef.current.onaudioprocess = null;
        }
        if (mediaStreamRef.current) {
            mediaStreamRef.current.getTracks().forEach(track => track.stop());
        }
        if (audioContextRef.current) {
            audioContextRef.current.close();
        }
        if (wsRef.current) {
            wsRef.current.close();
        }
        setIsCalling(false);
    };

    return (
        <div className="container">
            <header>
                <h1>SecureBank AI Assistant</h1>
                <Link to="/dashboard" className="btn" style={{ background: 'var(--panel)', border: '1px solid var(--border)' }} target="_blank">
                    Fraud Desk Dashboard
                </Link>
            </header>

            <div className="panel chat-box" ref={chatRef}>
                {messages.map((m, i) => (
                    <div key={i} className={`msg ${m.role}`}>
                        {m.content}
                        {m.riskScore !== undefined && (
                            <div style={{ fontSize: '0.75rem', opacity: '0.7', marginTop: '0.25rem' }}>
                                Stress Level: {m.riskScore.toFixed(2)}
                            </div>
                        )}
                    </div>
                ))}
            </div>

            <div className="controls">
                {!isCalling ? (
                    <button onClick={startCall} className="btn">
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"></path><path d="M19 10v2a7 7 0 0 1-14 0v-2"></path><line x1="12" y1="19" x2="12" y2="22"></line></svg>
                        Start Call
                    </button>
                ) : (
                    <button onClick={stopCall} className="btn danger">
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect></svg>
                        End Call
                    </button>
                )}
            </div>
        </div>
    );
}
