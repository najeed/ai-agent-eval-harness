import React, { createContext, useContext, useState, useEffect, useMemo } from 'react';

export type UserRole = 'System Admin' | 'Compliance Auditor' | 'Scenario Designer' | 'MultiAgentOps Eng.';

export interface AuthenticatedUser {
  id: string;
  name: string;
  role: UserRole;
  permissions: string[];
  type?: string;
  workspace_id?: string;
  is_dev_mode?: boolean;
}

interface RBACContextType {
  user: AuthenticatedUser | null;
  role: UserRole;
  setRole: (role: UserRole) => void;
  isDevMode: boolean;
  workspaceId: string;
  canEditScenario: boolean;
  canRunEval: boolean;
  canSignCert: boolean;
  canAccessSettings: boolean;
  canResolveHITL: boolean;
  refreshAuth: () => Promise<void>;
}

const RBACContext = createContext<RBACContextType | undefined>(undefined);

export const RBACProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<AuthenticatedUser | null>(null);
  const [isDevMode, setIsDevMode] = useState<boolean>(false);
  const [activeRole, setActiveRole] = useState<UserRole>('System Admin');
  const [workspaceId, setWorkspaceId] = useState<string>('ws-default');

  const fetchAuth = async () => {
    try {
      const res = await fetch('/api/auth/me');
      if (res.ok) {
        const data = await res.json();
        if (data.authenticated && data.user) {
          setUser(data.user);
          setIsDevMode(Boolean(data.user.is_dev_mode));
          setWorkspaceId(data.user.workspace_id || 'ws-default');
          setActiveRole(data.user.role || 'System Admin');
        } else {
          setIsDevMode(Boolean(data.is_dev_mode));
        }
      }
    } catch (err) {
      console.warn('[RBAC] Failed to fetch server identity:', err);
    }
  };

  useEffect(() => {
    fetchAuth();
  }, []);

  const setRole = (newRole: UserRole) => {
    if (!isDevMode) {
      console.warn('[RBAC] Persona switching is disabled in production environments.');
      window.dispatchEvent(new CustomEvent('agentv-toast', {
        detail: { message: 'Persona switching is disabled: Identity is server-authoritative.', type: 'warning' }
      }));
      return;
    }
    setActiveRole(newRole);
    window.dispatchEvent(new CustomEvent('agentv-toast', {
      detail: { message: `[Dev Simulator] Active Persona Context switched to: ${newRole}`, type: 'info' }
    }));
  };

  const perms = useMemo(() => new Set(user?.permissions || []), [user]);
  const isAdmin = activeRole === 'System Admin' || perms.has('*') || perms.has('system:config');

  const value = useMemo(() => ({
    user,
    role: activeRole,
    setRole,
    isDevMode,
    workspaceId,
    canEditScenario: isAdmin || activeRole === 'Scenario Designer' || perms.has('scenarios:write'),
    canRunEval: isAdmin || activeRole === 'MultiAgentOps Eng.' || activeRole === 'Scenario Designer' || perms.has('eval:trigger'),
    canSignCert: isAdmin || activeRole === 'Compliance Auditor' || perms.has('certify:write'),
    canAccessSettings: isAdmin || activeRole === 'MultiAgentOps Eng.' || perms.has('system:config'),
    canResolveHITL: isAdmin || activeRole === 'Compliance Auditor' || perms.has('hitl:resolve'),
    refreshAuth: fetchAuth,
  }), [user, activeRole, isDevMode, workspaceId, perms, isAdmin]);

  return (
    <RBACContext.Provider value={value}>
      {children}
    </RBACContext.Provider>
  );
};

export const useRBAC = () => {
  const context = useContext(RBACContext);
  if (!context) {
    throw new Error('useRBAC must be used within an RBACProvider');
  }
  return context;
};

