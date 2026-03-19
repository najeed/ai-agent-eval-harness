const { useState, useEffect } = React;

const Demo = () => {
    useEffect(() => {
        // Init logic if needed
    }, []);

    const [step, setStep] = useState(1);
    const [fixing, setFixing] = useState(false);
    const [showSuccess, setShowSuccess] = useState(false);

    const DraggableCard = ({ children, initialPos = null, className = "", style = {} }) => {
        const [pos, setPos] = useState(initialPos);
        const [dragging, setDragging] = useState(false);
        const [rel, setRel] = useState({ x: 0, y: 0 });
        const ref = React.useRef(null);

        const onMouseDown = (e) => {
            if (e.button !== 0) return;
            const element = ref.current;
            if (!element) return;
            
            const rect = element.getBoundingClientRect();
            const currentX = pos ? pos.x : rect.left;
            const currentY = pos ? pos.y : rect.top;

            setDragging(true);
            setRel({
                x: e.pageX - currentX,
                y: e.pageY - currentY
            });
            e.stopPropagation();
        };

        useEffect(() => {
            const onMouseMove = (e) => {
                if (!dragging) return;
                setPos({
                    x: e.pageX - rel.x,
                    y: e.pageY - rel.y
                });
            };
            const onMouseUp = () => setDragging(false);

            if (dragging) {
                window.addEventListener('mousemove', onMouseMove);
                window.addEventListener('mouseup', onMouseUp);
            }
            return () => {
                window.removeEventListener('mousemove', onMouseMove);
                window.removeEventListener('mouseup', onMouseUp);
            };
        }, [dragging, rel]);

        const positionStyle = pos ? {
            position: 'fixed',
            left: pos.x,
            top: pos.y,
            margin: 0
        } : {};

        return (
            <div
                ref={ref}
                style={{
                    ...style,
                    ...positionStyle,
                    cursor: dragging ? 'grabbing' : 'grab',
                    touchAction: 'none',
                    zIndex: 100
                }}
                onMouseDown={onMouseDown}
                className={className}
            >
                {children}
            </div>
        );
    };

    const nextStep = () => setStep(s => Math.min(s + 1, 7));
    const prevStep = () => setStep(s => Math.max(s - 1, 1));
    const reset = () => { setStep(1); setFixing(false); };

    const handleFix = () => {
        setFixing(true);
        setTimeout(() => {
            setFixing(false);
            setShowSuccess(true);
        }, 3000);
    };

    const renderStep = () => {
        // Shared components from window
        const Icon = window.Icon;
        const VisualDebugger = window.VisualDebugger;

        switch (step) {
            case 1:
                return (
                    <div className="flex-1 flex flex-col items-center justify-center p-20 animate-in fade-in zoom-in duration-500">
                        <div className="max-w-2xl w-full text-center space-y-8">
                            <div className="inline-block p-4 bg-red-500/10 rounded-3xl border border-red-500/20 text-red-500 mb-4 scale-125">
                                <Icon name="alert" size={48} />
                            </div>
                            <h2 className="text-5xl font-black text-white leading-tight">Screen 1: The Failure</h2>
                            <p className="text-xl text-slate-400 italic font-medium">"This is a real-world type of failure we see: an agent incorrectly approving a high-risk loan."</p>

                            <div className="p-8 bg-red-500/10 border-2 border-red-500/20 rounded-[40px] text-left shadow-2xl animate-pulse">
                                <div className="flex justify-between items-center mb-6">
                                    <span className="text-[10px] font-black uppercase tracking-[0.3em] text-red-400 px-3 py-1 bg-red-400/10 rounded-full">CRITICAL FAILURE</span>
                                    <span className="text-xs text-slate-500 font-mono">10:45 AM</span>
                                </div>
                                <h3 className="text-2xl font-bold text-white mb-2">Loan Approval – Risk Check</h3>
                                <p className="text-slate-400 text-sm mb-6">Scenario: finance-loan-risk-check</p>
                                <div className="flex items-center gap-2 text-red-500 font-bold text-lg">
                                    <Icon name="alert" size={20} />
                                    <span>STATUS: ❌ FAILED (Safety Policy Violation)</span>
                                </div>
                            </div>
                            <button onClick={nextStep} className="mt-8 px-10 py-4 bg-white text-black font-black rounded-full hover:scale-105 active:scale-95 transition-all uppercase tracking-widest text-sm">Analyze Failure</button>
                        </div>
                    </div>
                );
            case 2:
                return (
                    <div className="flex-1 flex flex-col items-center justify-center p-20 animate-in slide-in-from-right duration-500">
                        <div className="max-w-4xl w-full space-y-8">
                            <div className="text-center mb-12">
                                <h2 className="text-4xl font-black text-white mb-4">What Teams Have Today</h2>
                                <p className="text-xl text-slate-400 font-medium italic">"This is what most teams rely on today—logs. You can see prompts, tool calls... but nothing tells you why the agent made the wrong decision."</p>
                            </div>
                            <div className="bg-[#0b0e14] border border-slate-800 rounded-3xl overflow-hidden shadow-2xl">
                                <div className="p-4 border-b border-slate-800 flex justify-between items-center bg-[#161b22]">
                                    <div className="flex gap-1.5">
                                        <div className="w-2.5 h-2.5 rounded-full bg-red-500/20"></div>
                                        <div className="w-2.5 h-2.5 rounded-full bg-amber-500/20"></div>
                                        <div className="w-2.5 h-2.5 rounded-full bg-emerald-500/20"></div>
                                    </div>
                                    <span className="text-[10px] font-bold text-slate-600 uppercase tracking-widest">production_logs_raw.jsonl</span>
                                </div>
                                <div className="p-8 font-mono text-[11px] text-slate-400 leading-relaxed overflow-y-auto max-h-96">
                                    <div className="space-y-1 opacity-80">
                                        <p>{`{"timestamp": "2026-03-19T04:10:00Z", "level": "INFO", "event": "request_started", "id": "8a9f"}`}</p>
                                        <p>{`{"timestamp": "2026-03-19T04:10:01Z", "level": "DEBUG", "msg": "Tool get_customer_profile"}`}</p>
                                        <p>{`{"timestamp": "2026-03-19T04:10:04Z", "level": "INFO", "msg": "HTTP 200 OK"}`}</p>
                                        <p>{`{"timestamp": "2026-03-19T04:10:05Z", "level": "DEBUG", "msg": "Transition: FETCH -> ANALYSE"}`}</p>
                                        <p>{`{"timestamp": "2026-03-19T04:10:08Z", "level": "DEBUG", "msg": "Tool get_risk_score"}`}</p>
                                        <p>{`{"timestamp": "2026-03-19T04:10:12Z", "level": "INFO", "msg": "Decision: APPROVE (0.70)"}`}</p>
                                        <p className="text-red-400 font-bold underline">{`{"timestamp": "2026-03-19T04:10:13Z", "level": "ERROR", "msg": "POLICY_FAIL"}`}</p>
                                        <p className="opacity-30 italic">... 1,200 more lines of unformatted telemetry ...</p>
                                        <p className="text-red-500 font-bold">{`{"timestamp": "2026-03-19T04:10:15Z", "level": "FATAL", "msg": "RUN_FAILED"}`}</p>
                                    </div>
                                </div>
                            </div>
                            <div className="text-center pt-8">
                                <button onClick={nextStep} className="px-10 py-4 bg-blue-600 text-white font-black rounded-full hover:scale-105 active:scale-95 transition-all shadow-xl shadow-blue-500/20 uppercase tracking-widest text-sm">The AgentEval Difference</button>
                            </div>
                        </div>
                    </div>
                );
            case 3:
                return (
                    <div className="flex-1 flex flex-col h-full animate-in zoom-in duration-700">
                        <div className="p-6 border-b border-slate-800 bg-[#0b0e14]/50 backdrop-blur-xl flex justify-between items-center">
                            <div>
                                <h2 className="text-xl font-black text-white">AgentEval Replay</h2>
                                <p className="text-xs text-slate-500 italic mt-1 font-medium">"Now let's replay the same run using AgentEval. We skip the logs and go straight to the execution timeline."</p>
                            </div>
                            <button onClick={nextStep} className="px-6 py-2 bg-white text-black font-black rounded-full text-[10px] uppercase tracking-widest z-50">Isolate Root Cause</button>
                        </div>
                        <div className="flex-1 overflow-hidden opacity-90 h-[500px] md:h-[600px] lg:h-[750px] border border-slate-800 rounded-2xl">
                            <VisualDebugger runId="run-loan-risk-fail" />
                        </div>
                    </div>
                );
            case 4:
                return (
                    <div className="flex-1 flex flex-col h-full relative overflow-hidden">
                        <DraggableCard className="absolute top-24 right-12 z-50 animate-in slide-in-from-right-8 duration-700">
                            <div className="bg-[#0b0e14]/90 backdrop-blur-xl text-white rounded-[32px] p-6 max-w-sm shadow-2xl border border-white/10 relative">
                                <div className="absolute -top-3 -left-3 w-10 h-10 bg-blue-600 rounded-xl flex items-center justify-center text-white shadow-xl rotate-[-6deg]">
                                    <Icon name="alert" size={20} />
                                </div>
                                <h3 className="text-lg font-black mb-3">Root Cause Isolation</h3>
                                <p className="text-[11px] font-bold mb-4 opacity-90 leading-relaxed text-blue-100">
                                    "The AgentEval Engine automatically highlighted the logic breach. The agent used a stale risk threshold of 0.65 instead of the current policy of 0.85."
                                </p>
                                <div className="space-y-2 font-mono text-[9px] bg-black/40 p-3 rounded-xl border border-white/5 mb-4">
                                    <div className="flex justify-between">
                                        <span className="opacity-50 uppercase tracking-widest">Target:</span>
                                        <span className="text-emerald-400 font-bold">0.85</span>
                                    </div>
                                    <div className="flex justify-between border-t border-white/5 pt-1.5">
                                        <span className="opacity-50 uppercase tracking-widest">Actual:</span>
                                        <span className="text-red-400 font-bold">0.65</span>
                                    </div>
                                </div>
                                <button onClick={nextStep} className="w-full py-3 bg-white text-slate-900 font-black rounded-xl hover:bg-slate-100 transition-all uppercase tracking-widest text-[9px] shadow-lg">Verify Fix & Re-run →</button>
                            </div>
                        </DraggableCard>
                        <div className="flex-1 h-[500px] md:h-[600px] lg:h-[750px] border border-slate-800 rounded-2xl overflow-hidden">
                            <VisualDebugger runId="run-loan-risk-fail" highlightFailure={true} />
                        </div>
                    </div>
                );
            case 5:
                return (
                    <div className="flex-1 flex flex-col h-full animate-in fade-in duration-500">
                        {fixing ? (
                            <div className="absolute inset-0 z-[60] bg-[#0b0e14]/90 flex flex-col items-center justify-center space-y-8 backdrop-blur-3xl animate-in fade-in">
                                <div className="w-32 h-32 relative">
                                    <div className="absolute inset-0 rounded-full border-4 border-blue-500/20"></div>
                                    <div className="absolute inset-0 rounded-full border-4 border-blue-500 border-t-transparent animate-spin"></div>
                                    <div className="absolute inset-0 flex items-center justify-center text-blue-500">
                                        <Icon name="activity" size={48} />
                                    </div>
                                </div>
                                <div className="text-center">
                                    <h3 className="text-3xl font-black text-white mb-2">Build Index</h3>
                                    <p className="text-slate-400 font-medium italic">"All fixes are automatically indexed for global regression testing."</p>
                                </div>
                            </div>
                        ) : null}
                        <div className="p-6 border-b border-slate-800 bg-[#0b0e14]/50 backdrop-blur-xl flex justify-between items-center">
                            <div className="text-center">
                                <h3 className="text-3xl font-black text-white mb-2">The Rerun</h3>
                                <p className="text-slate-400 font-medium italic">"We've deployed the fix. Let's watch the agent re-evaluate the risk in real-time."</p>
                            </div>
                            <div className="flex gap-4">
                                {showSuccess ? (
                                    <button onClick={nextStep} className="px-8 py-3 bg-emerald-500 text-white font-black rounded-full text-[10px] uppercase tracking-widest hover:bg-emerald-600 shadow-xl shadow-emerald-500/20 animate-in zoom-in duration-300">View CI Report & Regression Test →</button>
                                ) : !fixing && (
                                    <button onClick={handleFix} className="px-8 py-3 bg-white text-black font-black rounded-full text-[10px] uppercase tracking-widest hover:bg-slate-100 shadow-xl transition-all active:scale-95">Trigger Rerun & Verify Fix</button>
                                )}
                            </div>
                        </div>
                        <div className="flex-1 h-[500px] md:h-[600px] lg:h-[750px] border border-slate-800 rounded-2xl overflow-hidden">
                            <VisualDebugger runId={showSuccess ? "run-loan-risk-pass" : "run-loan-risk-fail"} highlightFailure={false} />
                        </div>
                        {!fixing && step === 5 && showSuccess && (
                            <DraggableCard className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-[55] animate-in zoom-in bounce-in-down duration-1000">
                                <div className="bg-emerald-600 text-white px-10 py-6 rounded-full shadow-[0_0_80px_rgba(16,185,129,0.5)] border-2 border-white/20 flex items-center gap-4">
                                    <div className="w-10 h-10 bg-white rounded-full flex items-center justify-center text-emerald-600">
                                        <Icon name="check" size={24} />
                                    </div>
                                    <span className="text-2xl font-black uppercase tracking-widest">PASSED</span>
                                </div>
                            </DraggableCard>
                        )}
                    </div>
                );
            case 6:
                return (
                    <div className="flex-1 flex flex-col items-center justify-center p-20 animate-in slide-in-from-bottom-20 duration-500">
                        <div className="max-w-5xl w-full">
                            <div className="text-center mb-16">
                                <h2 className="text-4xl font-black text-white mb-4">CI/CD for Agents</h2>
                                <p className="text-xl text-slate-400 font-medium italic">"With AgentEval, you don't just fix one bug. You build a regression suite that runs on every commit."</p>
                            </div>
                            <div className="grid grid-cols-5 gap-6">
                                <div className="space-y-4 pt-12">
                                    {['Loan Approval', 'Med Diagnosis', 'Fraud Detection', 'Data Migration', 'Policy Review', 'Legacy Backup'].map((label, i) => (
                                        <div key={i} className="h-12 flex items-center text-xs font-bold text-slate-500 uppercase tracking-tight pr-4 border-r border-slate-800/50">
                                            {label}
                                        </div>
                                    ))}
                                </div>
                                {['v1.2.0 (Stable)', 'v2.0-beta', 'GPT-4o', 'Claude 3.5'].map((col, i) => (
                                    <div key={i} className="space-y-4">
                                        <div className="text-[10px] font-black text-slate-100 uppercase tracking-widest text-center px-4 py-2 bg-blue-600/10 border border-blue-500/20 rounded-xl">{col}</div>
                                        {[1, 2, 3, 4, 5, 6].map(row => (
                                            <div key={row} className={`h-12 border rounded-xl flex items-center justify-center transition-all hover:scale-105 cursor-help ${(i === 2 && row === 3) || (i === 1 && row > 4)
                                                ? 'bg-red-500/10 border-red-500/20 text-red-500 shadow-[inset_0_0_20px_rgba(239,68,68,0.1)]'
                                                : 'bg-emerald-500/10 border-emerald-500/20 text-emerald-500 shadow-[inset_0_0_20px_rgba(16,185,129,0.1)]'
                                                }`}>
                                                <Icon name={(i === 2 && row === 3) || (i === 1 && row > 4) ? 'alert' : 'check'} size={18} />
                                            </div>
                                        ))}
                                    </div>
                                ))}
                            </div>
                            <div className="mt-8 flex justify-center gap-8">
                                <div className="flex items-center gap-2">
                                    <div className="w-3 h-3 rounded-full bg-emerald-500"></div>
                                    <span className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">Golden Trajectory Match</span>
                                </div>
                                <div className="flex items-center gap-2">
                                    <div className="w-3 h-3 rounded-full bg-red-500"></div>
                                    <span className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">Logic Regression Detected</span>
                                </div>
                            </div>
                            <div className="mt-16 text-center">
                                <button onClick={nextStep} className="px-12 py-5 bg-gradient-to-r from-blue-600 to-indigo-600 text-white font-black rounded-full hover:scale-105 transition-all shadow-2xl shadow-blue-500/30 uppercase tracking-[0.2em] text-sm">Finish Story</button>
                            </div>
                        </div>
                    </div>
                );
            case 7:
                return (
                    <div className="flex-1 flex flex-col items-center justify-center p-20 animate-in fade-in duration-1000">
                        <div className="max-w-3xl w-full text-center space-y-12">
                            <div className="relative inline-block">
                                <div className="absolute -inset-4 bg-gradient-to-r from-blue-600 to-emerald-500 rounded-full blur-2xl opacity-40 animate-pulse"></div>
                                <div className="w-40 h-40 bg-[#161b22] border-4 border-slate-800 rounded-[50px] flex items-center justify-center text-blue-500 relative shadow-2xl rotate-3">
                                    <Icon name="debugger" size={80} />
                                </div>
                            </div>
                            <div>
                                <h2 className="text-6xl font-black text-white leading-tight mb-4">Scaling With Confidence</h2>
                                <p className="text-2xl text-slate-400 leading-relaxed font-medium">
                                    "This is how teams turn agents from a liability into a competitive edge. Stop guessing. Start evaluating."
                                </p>
                            </div>
                            <div className="pt-12 flex gap-6 justify-center">
                                <button onClick={reset} className="px-10 py-5 border-2 border-slate-800 text-slate-400 font-black rounded-full hover:text-white hover:border-white transition-all uppercase tracking-widest text-sm">Re-watch</button>
                                <button onClick={() => window.location.href = '/docs'} className="px-10 py-5 bg-white text-black font-black rounded-full hover:shadow-2xl hover:shadow-white/20 transition-all uppercase tracking-widest text-sm">Start Your First Eval</button>
                            </div>
                        </div>
                    </div>
                );
        }
    };

    return (
        <div className="h-full bg-[#0b0e14] flex flex-col overflow-hidden relative">
            <div className="flex-1 overflow-y-auto overflow-x-hidden">
                {renderStep()}
            </div>

            <div className="absolute bottom-6 right-6 z-[100] flex items-center gap-4 bg-slate-900/80 backdrop-blur-md p-2 rounded-2xl border border-slate-800 shadow-2xl">
                <div className="flex gap-1 h-1 w-24 bg-slate-800 rounded-full overflow-hidden mx-2">
                    {[1, 2, 3, 4, 5, 6, 7].map(s => (
                        <div key={s} className={`flex-1 transition-all duration-500 ${step >= s ? (step === 7 ? 'bg-emerald-500' : 'bg-blue-600') : 'bg-transparent'}`}></div>
                    ))}
                </div>
                <div className="flex gap-1">
                    <button onClick={prevStep} className={`p-2 rounded-xl border border-slate-700 text-slate-400 hover:text-white hover:bg-slate-800 transition-all ${step === 1 ? 'opacity-0 pointer-events-none' : ''}`}>
                        <Icon name="chevron-left" size={14} />
                    </button>
                    <button onClick={nextStep} className={`p-2 rounded-xl border border-slate-700 text-slate-400 hover:text-white hover:bg-slate-800 transition-all ${step === 7 ? 'opacity-0 pointer-events-none' : ''}`}>
                        <Icon name="chevron-right" size={14} />
                    </button>
                    <div className="w-px h-6 bg-slate-800 mx-1"></div>
                    <button onClick={(e) => { e.stopPropagation(); reset(); window.location.href = '/'; }} className="p-2 rounded-xl border border-red-500/20 text-red-500 hover:bg-red-500/10 transition-all" title="Exit Demo">
                        <Icon name="x" size={14} />
                    </button>
                </div>
            </div>
        </div>
    );
};

window.Demo = Demo;
