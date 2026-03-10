const { useState, useEffect } = React;

const Timeline = ({ events, onSelect }) => {
    return (
        <div className="flex flex-col gap-4 p-4 overflow-y-auto max-h-[80vh]">
            {events.map((event, idx) => (
                <div
                    key={idx}
                    className="timeline-item cursor-pointer group"
                    onClick={() => onSelect(event)}
                >
                    <div className="timeline-dot group-hover:scale-125 transition-transform"></div>
                    <div className="flex flex-col">
                        <span className="text-xs uppercase tracking-widest text-slate-500 font-bold mb-1">
                            {event.event.replace('_', ' ')}
                        </span>
                        <div className="glass p-3 group-hover:border-sky-500/50 transition-colors">
                            {event.role && <span className="font-bold text-sky-400 mr-2">[{event.role.toUpperCase()}]</span>}
                            <span className="text-slate-200 line-clamp-2">
                                {event.content || event.tool || event.metric || "N/A"}
                            </span>
                        </div>
                        <span className="text-[10px] text-slate-600 mt-1 mono">{new Date(event.timestamp).toLocaleTimeString()}</span>
                    </div>
                </div>
            ))}
        </div>
    );
};

const EventDetails = ({ event }) => {
    if (!event) return (
        <div className="flex items-center justify-center h-full text-slate-500 italic">
            Select an event to view details
        </div>
    );

    return (
        <div className="p-6 h-full overflow-y-auto">
            <h2 className="text-xl font-bold mb-4 text-sky-400 border-b border-slate-700 pb-2">Event Details</h2>
            <div className="space-y-4">
                <div>
                    <label className="text-xs uppercase text-slate-500 font-bold block mb-1">Type</label>
                    <span className="mono p-1 bg-slate-800 rounded text-slate-300">{event.event}</span>
                </div>
                <div>
                    <label className="text-xs uppercase text-slate-500 font-bold block mb-1">Raw Payload</label>
                    <pre className="glass p-4 mono text-xs overflow-x-auto text-emerald-400">
                        {JSON.stringify(event, null, 2)}
                    </pre>
                </div>
            </div>
        </div>
    );
};

const App = () => {
    const [events, setEvents] = useState([]);
    const [selectedEvent, setSelectedEvent] = useState(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        // Mock data for the demonstration
        const mockData = [
            { event: "run_start", timestamp: new Date().toISOString(), run_id: "test-123", scenario: "customer_refund" },
            { event: "prompt", role: "user", content: "I want a refund for my cancelled flight UA483.", timestamp: new Date().toISOString() },
            { event: "agent_response", step: 1, content: "I'm sorry to hear that. Let me check the flight database.", timestamp: new Date().toISOString() },
            { event: "tool_call", tool: "flight_db", arguments: { flight_id: "UA483" }, timestamp: new Date().toISOString() },
            { event: "tool_result", tool: "flight_db", result: { status: "cancelled", refund_eligibility: "full" }, timestamp: new Date().toISOString() },
            { event: "evaluation", metric: "refund_processed", value: true, timestamp: new Date().toISOString() },
            { event: "run_end", status: "success", timestamp: new Date().toISOString() }
        ];
        setEvents(mockData);
        setLoading(false);
    }, []);

    const handleImport = (e) => {
        const file = e.target.files[0];
        if (!file) return;

        const reader = new FileReader();
        reader.onload = (event) => {
            const content = event.target.result;
            const lines = content.split('\n').filter(line => line.trim());
            try {
                const importedEvents = lines.map(line => JSON.parse(line));
                setEvents(importedEvents);
                setSelectedEvent(null);
            } catch (err) {
                console.error("Error parsing JSONL:", err);
                alert("Failed to parse JSONL file. Please check the format.");
            }
        };
        reader.readAsText(file);
    };

    const handleExport = () => {
        const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(events, null, 2));
        const downloadAnchorNode = document.createElement('a');
        downloadAnchorNode.setAttribute("href",     dataStr);
        downloadAnchorNode.setAttribute("download", "trace.json");
        document.body.appendChild(downloadAnchorNode);
        downloadAnchorNode.click();
        downloadAnchorNode.remove();
    };

    return (
        <div className="flex flex-col h-screen">
            <header className="p-4 border-b border-slate-800 flex justify-between items-center bg-slate-900/50 sticky top-0 z-10">
                <div className="flex items-center gap-3">
                    <div className="w-8 h-8 bg-sky-500 rounded flex items-center justify-center text-slate-900 font-bold">A</div>
                    <h1 className="text-lg font-bold tracking-tight">Agent Visual Debugger <span className="text-xs font-normal text-slate-500 bg-slate-800 px-2 py-0.5 rounded-full ml-2">OpenCore v0.1</span></h1>
                </div>
                <div className="flex gap-2">
                    <input
                        type="file"
                        id="import-jsonl"
                        className="hidden"
                        accept=".jsonl"
                        onChange={handleImport}
                    />
                    <button 
                        className="text-xs text-slate-400 hover:text-slate-200 px-3 py-1 rounded border border-slate-700"
                        onClick={() => document.getElementById('import-jsonl').click()}
                    >
                        Import run.jsonl
                    </button>
                    <button 
                        className="btn-primary text-xs"
                        onClick={handleExport}
                    >
                        Export Trace
                    </button>
                </div>
            </header>

            <main className="flex flex-1 overflow-hidden">
                <aside className="w-1/3 border-r border-slate-800 bg-slate-900/20">
                    <div className="p-4 border-b border-slate-800 bg-slate-900/40">
                        <h3 className="text-xs font-bold text-slate-400 uppercase tracking-widest">Timeline</h3>
                    </div>
                    <Timeline events={events} onSelect={setSelectedEvent} />
                </aside>
                <section className="flex-1 bg-slate-900/10">
                    <EventDetails event={selectedEvent} />
                </section>
            </main>

            <footer className="p-2 border-t border-slate-800 text-[10px] text-slate-600 text-center bg-slate-900/80">
                &copy; 2026 AI Agent Evaluation Harness • Powered by JetBrains Mono & Tailwind
            </footer>
        </div>
    );
};

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(<App />);
