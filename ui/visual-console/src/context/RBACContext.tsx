import React, { createContext, useContext, useState, useEffect, useMemo } from 'react';
import {
  clearRuntimeAuthCaches,
  getRuntimeAuthContext,
  logoutRuntimeAuth,
  switchRuntimeContext,
  type AuthorizedContext,
} from '../auth/runtimeAuthContext';

export type UserRole = string;

export interface AuthenticatedUser {
  id: string;
  name: string;
  role: UserRole;
  permissions: string[];
  type?: string;
  tenant_id?: string;
  org_id?: string;
  workspace_id?: string;
  active_environment?: string;
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
  authorizedContexts: AuthorizedContext[];
  switchContext: (workspaceId: string, activeEnvironment: string) => Promise<void>;
  isLoginModalOpen: boolean;
  openLoginModal: () => void;
  closeLoginModal: () => void;
  logout: () => Promise<void>;
  hasPermission: (permission: string) => boolean;
  canEditScenario: boolean;
  canRunEval: boolean;
  canVerifyCert: boolean;
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
  const [workspaceId, setWorkspaceId] = useState<string>('');
  const [tenantId, setTenantId] = useState<string>('');
  const [authorizedContexts, setAuthorizedContexts] = useState<AuthorizedContext[]>([]);
  const [isAuthenticated, setIsAuthenticated] = useState<boolean>(false);
  const [isAuthResolving, setIsAuthResolving] = useState<boolean>(true);
  const [isLoginModalOpen, setIsLoginModalOpen] = useState<boolean>(false);

  const fetchAuth = async () => {
    try {
      const res = await fetch('/api/auth/me');
      if (res.ok) {
        const data = await res.json();
        if (data.authenticated && data.user) {
          const runtimeContext = await getRuntimeAuthContext();
          const normalizedUser = { ...data.user, ...(runtimeContext.context || {}) } as AuthenticatedUser;
          setUser(normalizedUser);
          setIsAuthenticated(true);
          setIsDevMode(Boolean(normalizedUser.is_dev_mode));
          setWorkspaceId(runtimeContext.context?.workspace_id || '');
          setTenantId(runtimeContext.context?.tenant_id || '');
          setAuthorizedContexts(runtimeContext.authorized_contexts);
          setActiveRole(normalizedUser.role || 'Viewer');
          setIsLoginModalOpen(false);
          return;
        }
      }
      // Fail closed to Viewer role without forcing a disruptive modal overlay on initial load
      setIsAuthenticated(false);
      setUser(null);
      setActiveRole('Viewer');
      setAuthorizedContexts([]);
      clearRuntimeAuthCaches();
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
      await logoutRuntimeAuth();
    } catch (err) {
      console.warn('[RBAC] Error during logout:', err);
    } finally {
      setUser(null);
      setIsAuthenticated(false);
      setActiveRole('Viewer');
      setWorkspaceId('');
      setTenantId('');
      setAuthorizedContexts([]);
      setIsLoginModalOpen(true);
    }
  };

  const openLoginModal = () => setIsLoginModalOpen(true);
  const closeLoginModal = () => {
    if (isAuthenticated) {
      setIsLoginModalOpen(false);
    }
  };

  // Permissions returned by Runtime are the only presentation-gating input.
  const perms = useMemo(() => new Set(user?.permissions || []), [user]);

  const isAdmin = perms.has('*') || perms.has('system:config');

  const hasPermission = (permission: string): boolean => {
    if (isAdmin) return true;
    return perms.has(permission);
  };

  const switchContext = async (workspaceId: string, activeEnvironment: string) => {
    const context = await switchRuntimeContext(workspaceId, activeEnvironment);
    setWorkspaceId(context.context?.workspace_id || '');
    setTenantId(context.context?.tenant_id || '');
    setAuthorizedContexts(context.authorized_contexts);
    setUser(current => current ? { ...current, ...(context.context || {}) } : current);
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
      authorizedContexts,
      switchContext,
      isLoginModalOpen,
      openLoginModal,
      closeLoginModal,
      logout,
      hasPermission,
      canEditScenario: hasPermission('scenarios:write'),
      canRunEval: hasPermission('eval:trigger'),
      canVerifyCert: hasPermission('runs:read') || hasPermission('trust:read'),
      canSignCert: hasPermission('certify:write'),
      canAccessSettings: isAdmin || perms.has('system:config'),
      canResolveHITL: hasPermission('hitl:resolve'),
      refreshAuth: fetchAuth,
    }),
    [user, activeRole, isAuthenticated, isAuthResolving, isDevMode, workspaceId, tenantId, authorizedContexts, perms, isAdmin, isLoginModalOpen]
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
  children: React.ReactNode;
  fallback?: React.ReactNode;
}> = ({ requiredPermissions = [], children, fallback }) => {
  const { hasPermission } = useRBAC();

  const permsAllowed =
    requiredPermissions.length === 0 || requiredPermissions.every(p => hasPermission(p));

  if (!permsAllowed) {
    if (fallback) return <>{fallback}</>;
    return (
      <div className="p-8 text-center text-slate-400 bg-slate-900/60 rounded-xl border border-slate-800 m-6">
        <h3 className="text-lg font-semibold text-rose-400 mb-2">Access Denied (403 Forbidden)</h3>
        <p className="text-sm text-slate-500">
          Your verified permissions do not include the required capabilities.
        </p>
      </div>
    );
  }

  return <>{children}</>;
};


