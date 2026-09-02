import React, { useState } from 'react';
import { Shield, Key, Lock, AlertCircle, ArrowRight, CheckCircle2, X } from 'lucide-react';
import { useRBAC } from '../context/RBACContext';

interface LoginModalProps {
  isOpen: boolean;
  onClose?: () => void;
  canDismiss?: boolean;
}

export const LoginModal: React.FC<LoginModalProps> = ({
  isOpen,
  onClose,
  canDismiss = false,
}) => {
  const { refreshAuth } = useRBAC();
  const [apiKey, setApiKey] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmedKey = apiKey.trim();
    if (!trimmedKey) {
      setErrorMessage('Please enter an API Key or Bearer Token.');
      return;
    }

    setIsLoading(true);
    setErrorMessage(null);

    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ apiKey: trimmedKey }),
      });

      const data = await res.json().catch(() => ({}));

      if (!res.ok) {
        setErrorMessage(
          data.error || 'Authentication failed: Invalid API Key. Please verify against your server configuration.'
        );
        setIsLoading(false);
        return;
      }

      setSuccess(true);
      await refreshAuth();
      setTimeout(() => {
        setSuccess(false);
        setApiKey('');
        if (onClose) onClose();
      }, 600);
    } catch (err: any) {
      setErrorMessage(err?.message || 'Network error: Failed to connect to authentication server.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 backdrop-blur-md p-4 animate-in fade-in duration-200">
      <div className="relative w-full max-w-md bg-slate-900 border border-slate-700/80 rounded-2xl shadow-2xl shadow-cyan-950/20 overflow-hidden">
        {/* Top Gradient Banner */}
        <div className="h-1.5 bg-gradient-to-r from-cyan-500 via-indigo-500 to-purple-500" />

        {canDismiss && onClose && (
          <button
            onClick={onClose}
            className="absolute top-4 right-4 text-slate-400 hover:text-slate-200 p-1 rounded-lg hover:bg-slate-800 transition-colors"
            title="Close"
          >
            <X className="w-5 h-5" />
          </button>
        )}

        <div className="p-6 sm:p-8">
          {/* Header */}
          <div className="flex items-center gap-3 mb-6">
            <div className="p-3 bg-cyan-500/10 border border-cyan-500/30 rounded-xl text-cyan-400">
              <Shield className="w-6 h-6" />
            </div>
            <div>
              <h2 className="text-xl font-bold text-slate-100 tracking-tight">
                AgentV Security Gateway
              </h2>
              <p className="text-xs text-slate-400">
                PBAC Protected Console Access
              </p>
            </div>
          </div>

          <p className="text-xs text-slate-350 mb-6 leading-relaxed">
            Authentication is required to inspect scenarios, view traces, and evaluate AI agent runs. Please authenticate with your authorized Service or Operator API Key.
          </p>

          {/* Error Alert */}
          {errorMessage && (
            <div className="mb-5 p-3.5 bg-rose-500/10 border border-rose-500/30 rounded-xl flex items-start gap-2.5 text-rose-400 text-xs">
              <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
              <span className="leading-snug">{errorMessage}</span>
            </div>
          )}

          {/* Success Alert */}
          {success && (
            <div className="mb-5 p-3.5 bg-emerald-500/10 border border-emerald-500/30 rounded-xl flex items-center gap-2.5 text-emerald-400 text-xs">
              <CheckCircle2 className="w-4 h-4 shrink-0" />
              <span>Authentication successful! Initializing session...</span>
            </div>
          )}

          {/* Form */}
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1.5 uppercase tracking-wider">
                API Key or Access Token
              </label>
              <div className="relative">
                <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-slate-500">
                  <Key className="w-4 h-4" />
                </div>
                <input
                  type="password"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder="Enter SERVICE_API_KEY or DASHBOARD_API_KEY..."
                  autoFocus
                  disabled={isLoading || success}
                  className="w-full pl-10 pr-4 py-2.5 bg-slate-950/80 border border-slate-700 rounded-xl text-slate-100 placeholder-slate-500 text-sm focus:outline-none focus:ring-2 focus:ring-cyan-500/50 focus:border-cyan-500 transition-all font-mono"
                />
              </div>
              <p className="text-[11px] text-slate-500 mt-1.5">
                Matches the <code className="text-slate-400 font-mono">SERVICE_API_KEY</code> configured in your server environment.
              </p>
            </div>

            <button
              type="submit"
              disabled={isLoading || success || !apiKey.trim()}
              className="w-full mt-2 py-2.5 px-4 bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-400 hover:to-blue-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-medium text-sm rounded-xl shadow-lg shadow-cyan-950/40 flex items-center justify-center gap-2 transition-all cursor-pointer"
            >
              {isLoading ? (
                <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              ) : success ? (
                <>
                  <CheckCircle2 className="w-4 h-4" />
                  Authenticated
                </>
              ) : (
                <>
                  <Lock className="w-4 h-4" />
                  Authenticate Session
                  <ArrowRight className="w-4 h-4 ml-1" />
                </>
              )}
            </button>
          </form>

          {/* Footer Security Notice */}
          <div className="mt-6 pt-4 border-t border-slate-800 text-[10px] text-slate-500 text-center flex items-center justify-center gap-1.5">
            <Lock className="w-3 h-3 text-slate-600" />
            <span>Encrypted Session Cookie &bull; PBAC Deny-by-Default</span>
          </div>
        </div>
      </div>
    </div>
  );
};
