import React, { createContext, useContext, useState, useEffect, useMemo } from 'react';

export type UserRole =
  | 'System Admin'
  | 'Compliance Auditor'
  | 'Scenario Designer'
  | 'MultiAgentOps Eng.'
  | 'Viewer';

export interface AuthenticatedUser {
  id: string;
  name: string;
  role: UserRole;
  permissions: string[];
  type?: string;
  tenant_id?: string;
  workspace_id?: string;
  is_dev_mode?: boolean;
}

/**
 * RBAC Context — PRESENTATION GATING ONLY.
 *
 * Client permissions are UX gating only. All API operations are
 * server-authorized; the browser role model is never a security boundary.
 * Identity, dev-mode flag and permissions derive exclusively from the
 * server (/api/auth/me). There is no client-side persona switching.
 */
interface RBACContextType {
  user: AuthenticatedUser | null;
  role: UserRole;
  isAuthenticated: boolean;
  isAuthResolving: boolean;
  isDevMode: boolean;
  workspaceId: string;
  tenantId: string;
  isLoginModalOpen: boolean;
  openLoginModal: () => void;
  closeLoginModal: () => void;
  logout: () => Promise<void>;
  hasPermission: (permission: string) => boolean;
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
  const [activeRole, setActiveRole] = useState<UserRole>('Viewer'); // Default-deny fail-closed
  const [workspaceId, setWorkspaceId] = useState<string>('ws-default');
  const [tenantId, setTenantId] = useState<string>('tenant-default');
  const [isAuthenticated, setIsAuthenticated] = useState<boolean>(false);
  const [isAuthResolving, setIsAuthResolving] = useState<boolean>(true);
  const [isLoginModalOpen, setIsLoginModalOpen] = useState<boolean>(false);

  const fetchAuth = async () => {
    try {
      const res = await fetch('/api/auth/me');
      if (res.ok) {
        const data = await res.json();
        if (data.authenticated && data.user) {
          setUser(data.user);
          setIsAuthenticated(true);
          setIsDevMode(Boolean(data.user.is_dev_mode));
          setWorkspaceId(data.user.workspace_id || 'ws-default');
          setTenantId(data.user.tenant_id || 'tenant-default');
          setActiveRole(data.user.role || 'Viewer');
          setIsLoginModalOpen(false);
          return;
        }
      }
      // Fail closed to Viewer role without forcing a disruptive modal overlay on initial load
      setIsAuthenticated(false);
      setUser(null);
      setActiveRole('Viewer');
    } catch (err) {
      console.warn('[RBAC] Default-deny: Server authentication unreachable. Enforcing Viewer role.', err);
      setIsAuthenticated(false);
      setUser(null);
      setActiveRole('Viewer');
    } finally {
      setIsAuthResolving(false);
    }
  };

  useEffect(() => {
    fetchAuth();

    const handleAuthRequired = () => {
      setIsAuthenticated(false);
      setIsLoginModalOpen(true);
    };

    window.addEventListener('agentv-auth-required', handleAuthRequired);
    return () => {
      window.removeEventListener('agentv-auth-required', handleAuthRequired);
    };
  }, []);

  const logout = async () => {
    try {
      await fetch('/api/auth/logout', { method: 'POST' });
    } catch (err) {
      console.warn('[RBAC] Error during logout:', err);
    } finally {
      setUser(null);
      setIsAuthenticated(false);
      setActiveRole('Viewer');
      setIsLoginModalOpen(true);
    }
  };

  const openLoginModal = () => setIsLoginModalOpen(true);
  const closeLoginModal = () => {
    if (isAuthenticated) {
      setIsLoginModalOpen(false);
    }
  };

  const ROLE_PERMISSIONS: Record<UserRole, string[]> = {
    'System Admin': ['*'],
    'Compliance Auditor': ['runs:read', 'scenarios:read', 'certify:write', 'hitl:resolve', 'reports:read', 'trust:read'],
    'Scenario Designer': ['scenarios:read', 'scenarios:write', 'eval:trigger', 'runs:read'],
    'MultiAgentOps Eng.': ['runs:read', 'eval:trigger', 'hitl:resolve', 'scenarios:read'],
    'Viewer': ['runs:read', 'scenarios:read'],
  };

  // In production (isDevMode === false) permissions derive SOLELY from the
  // server-provided user.permissions; the local role map is never consulted.
  const perms = useMemo(() => {
    if (!isDevMode) {
      return new Set(user?.permissions || []);
    }
    return new Set(ROLE_PERMISSIONS[activeRole] || ['runs:read', 'scenarios:read']);
  }, [user, activeRole, isDevMode]);

  const isAdmin = activeRole === 'System Admin' || (!isDevMode && (perms.has('*') || perms.has('system:config')));

  const hasPermission = (permission: string): boolean => {
    if (isAdmin) return true;
    return perms.has(permission);
  };

  const value = useMemo(
    () => ({
      user,
      role: activeRole,
      isAuthenticated,
      isAuthResolving,
      isDevMode,
      workspaceId,
      tenantId,
      isLoginModalOpen,
      openLoginModal,
      closeLoginModal,
      logout,
      hasPermission,
      canEditScenario: isAdmin || activeRole === 'Scenario Designer' || perms.has('scenarios:write'),
      canRunEval: isAdmin || activeRole === 'MultiAgentOps Eng.' || activeRole === 'Scenario Designer' || perms.has('eval:trigger'),
      canSignCert: isAdmin || activeRole === 'Compliance Auditor' || perms.has('certify:write'),
      canAccessSettings: isAdmin || perms.has('system:config'),
      canResolveHITL: isAdmin || activeRole === 'Compliance Auditor' || perms.has('hitl:resolve'),
      refreshAuth: fetchAuth,
    }),
    [user, activeRole, isAuthenticated, isAuthResolving, isDevMode, workspaceId, tenantId, perms, isAdmin, isLoginModalOpen]
  );

  return <RBACContext.Provider value={value}>{children}</RBACContext.Provider>;
};


export const useRBAC = () => {
  const context = useContext(RBACContext);
  if (!context) {
    throw new Error('useRBAC must be used within an RBACProvider');
  }
  return context;
};

/**
 * Route guard component enforcing server-authoritative authorization
 */
export const ProtectedRoute: React.FC<{
  requiredPermissions?: string[];
  requiredRole?: UserRole[];
  children: React.ReactNode;
  fallback?: React.ReactNode;
}> = ({ requiredPermissions = [], requiredRole = [], children, fallback }) => {
  const { role, hasPermission } = useRBAC();

  const roleAllowed = requiredRole.length === 0 || requiredRole.includes(role);
  const permsAllowed =
    requiredPermissions.length === 0 || requiredPermissions.every(p => hasPermission(p));

  if (!roleAllowed || !permsAllowed) {
    if (fallback) return <>{fallback}</>;
    return (
      <div className="p-8 text-center text-slate-400 bg-slate-900/60 rounded-xl border border-slate-800 m-6">
        <h3 className="text-lg font-semibold text-rose-400 mb-2">Access Denied (403 Forbidden)</h3>
        <p className="text-sm text-slate-500">
          Your active role ({role}) does not possess the requisite capabilities for this enterprise view.
        </p>
      </div>
    );
  }

  return <>{children}</>;
};


