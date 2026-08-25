import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { AlertTriangle } from 'lucide-react';
/**
 * Generic fallback rendered whenever a dynamically-registered extension route
 * fails to load or violates the RuntimeExtension contract. Replaces the
 * former ControlPlane-branded gate so the OSS runtime stays brand-neutral.
 */
export const ExtensionLoadError = ({ title = 'Extension unavailable', entryUrl, violations = [], message, }) => (_jsx("div", { className: "flex h-full min-h-[400px] flex-col items-center justify-center p-8 text-center", children: _jsxs("div", { className: "p-6 bg-red-500/10 border border-red-500/20 rounded-2xl max-w-lg shadow-xl backdrop-blur", children: [_jsx(AlertTriangle, { className: "w-10 h-10 mx-auto mb-3 text-red-400" }), _jsx("h3", { className: "font-bold text-base text-red-300", children: title }), entryUrl && (_jsx("p", { className: "text-xs text-slate-400 mt-2 font-mono break-all bg-slate-950/60 p-2.5 rounded-lg border border-slate-900", children: entryUrl })), message && _jsx("p", { className: "text-[11px] text-red-400/80 mt-2", children: message }), violations.length > 0 && (_jsx("ul", { className: "mt-3 text-left space-y-1 bg-slate-950/80 p-3 rounded-lg border border-red-500/20 font-mono text-[10px] text-red-300", children: violations.map((v, i) => (_jsxs("li", { children: ["\u2022 ", v] }, i))) })), _jsx("p", { className: "text-[11px] text-slate-500 mt-3", children: "This route is served by a signed extension. The runtime refused to mount it because it failed integrity, trust or contract validation." })] }) }));
export default ExtensionLoadError;
