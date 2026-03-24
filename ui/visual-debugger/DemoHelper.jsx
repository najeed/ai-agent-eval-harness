const { useState, useEffect, useRef } = React;

/**
 * Shared components for AgentEval Demos
 */

const DraggableCard = ({ children, initialPos = null, className = "", style = {} }) => {
    const [pos, setPos] = useState(initialPos);
    const [dragging, setDragging] = useState(false);
    const [rel, setRel] = useState({ x: 0, y: 0 });
    const ref = useRef(null);

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

const TerminalLine = ({ command, output, delay = 0 }) => {
    const [showOutput, setShowOutput] = useState(false);
    useEffect(() => {
        const timer = setTimeout(() => setShowOutput(true), delay + 1000);
        return () => clearTimeout(timer);
    }, [delay]);

    return (
        <div className="font-mono text-sm space-y-1 mb-4">
            <div className="flex gap-2 text-emerald-400">
                <span>$</span>
                <span className="text-slate-300">{command}</span>
            </div>
            {showOutput && (
                <div className="text-blue-400 pl-4 animate-in fade-in duration-300">
                    {output}
                </div>
            )}
        </div>
    );
};

const StatusBadge = ({ label, type = "info" }) => {
    const colors = {
        success: "bg-emerald-500/10 text-emerald-500 border-emerald-500/20",
        error: "bg-red-500/10 text-red-500 border-red-500/20",
        info: "bg-blue-500/10 text-blue-500 border-blue-500/20",
        warning: "bg-amber-500/10 text-amber-500 border-amber-500/20"
    };

    return (
        <span className={`text-[10px] font-black uppercase tracking-[0.2em] px-3 py-1 rounded-full border ${colors[type]}`}>
            {label}
        </span>
    );
};

// Export to window for JIT loading in App.jsx
window.DemoHelper = {
    DraggableCard,
    TerminalLine,
    StatusBadge
};
