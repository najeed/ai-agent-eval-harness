import React, { createContext, useContext, useState, useMemo } from 'react';

export type UserRole = 'System Admin' | 'Compliance Auditor' | 'Scenario Designer' | 'MultiAgentOps Eng.';

interface RBACContextType {
  role: UserRole;
  setRole: (role: UserRole) => void;
  canEditScenario: boolean;
  canRunEval: boolean;
  canSignCert: boolean;
  canAccessSettings: boolean;
  canResolveHITL: boolean;
}

const RBACContext = createContext<RBACContextType | undefined>(undefined);

export const RBACProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [role, setRoleState] = useState<UserRole>(() => {
    const saved = localStorage.getItem('agentv-role');
    return (saved as UserRole) || 'System Admin';
  });

  const setRole = (newRole: UserRole) => {
    setRoleState(newRole);
    localStorage.setItem('agentv-role', newRole);
    window.dispatchEvent(new CustomEvent('agentv-toast', {
      detail: { message: `Active Persona Context switched to: ${newRole}`, type: 'info' }
    }));
  };

  // Computed as direct boolean values from role — no stale closure risk
  const value = useMemo(() => ({
    role,
    setRole,
    canEditScenario: role === 'System Admin' || role === 'Scenario Designer',
    canRunEval: role === 'System Admin' || role === 'MultiAgentOps Eng.' || role === 'Scenario Designer',
    canSignCert: role === 'System Admin' || role === 'Compliance Auditor',
    canAccessSettings: role === 'System Admin' || role === 'MultiAgentOps Eng.',
    canResolveHITL: role === 'System Admin' || role === 'Compliance Auditor' || role === 'MultiAgentOps Eng.',
  }), [role]);

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
