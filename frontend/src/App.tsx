import React, { useState, useEffect } from 'react';
import { User } from '@/types/forensic';
import { INITIAL_CASES, INITIAL_AUDIT_LOGS, MockCase, MockAuditEntry } from '@/lib/mockData';
import { api } from '@/lib/api';
import { LoginGate } from '@/components/LoginGate';
import { AppShell } from '@/components/AppShell';
import { DashboardView } from '@/components/DashboardView';
import { TransactionsView } from '@/components/TransactionsView';
import { CaseInspectorView } from '@/components/CaseInspectorView';
import { IngestFootageView } from '@/components/IngestFootageView';
import { AuditTrailView } from '@/components/AuditTrailView';
import { CapabilitiesModal } from '@/components/CapabilitiesModal';

export const App: React.FC = () => {
  const [user, setUser] = useState<User | null>(() => {
    const saved = localStorage.getItem('strix_user');
    return saved ? JSON.parse(saved) : null;
  });

  const [currentView, setCurrentView] = useState<string>('dashboard');
  const [cases, setCases] = useState<MockCase[]>(INITIAL_CASES);
  const [activeCase, setActiveCase] = useState<MockCase>(INITIAL_CASES[0]);
  const [auditLogs, setAuditLogs] = useState<MockAuditEntry[]>(INITIAL_AUDIT_LOGS);
  const [capabilitiesModalOpen, setCapabilitiesModalOpen] = useState<boolean>(false);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  useEffect(() => {
    const handleAuthExpired = () => {
      setUser(null);
      showToast('Session expired. Please sign in again.');
    };
    window.addEventListener('strix:auth_expired', handleAuthExpired);
    return () => window.removeEventListener('strix:auth_expired', handleAuthExpired);
  }, []);

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 3000);
  };

  const addAuditEntry = (action: string, refId: string, details: string) => {
    const newEntry: MockAuditEntry = {
      timestamp: new Date().toISOString().replace('T', ' ').substring(0, 19),
      investigator: user?.full_name || 'Insp. R. Sharma',
      action,
      refId,
      details,
      hash: Array.from({ length: 64 }, () => Math.floor(Math.random() * 16).toString(16)).join(''),
    };
    setAuditLogs((prev) => [newEntry, ...prev]);
  };

  const handleLoginSuccess = (authenticatedUser: User) => {
    setUser(authenticatedUser);
    addAuditEntry('SESSION_AUTH', 'Console Access', `User ${authenticatedUser.username} signed in from local node`);
    showToast(`Signed in as ${authenticatedUser.full_name || authenticatedUser.username}`);
  };

  const handleSignOut = () => {
    addAuditEntry('SESSION_END', 'Console Logout', `User ${user?.username} signed out`);
    api.logout();
    setUser(null);
    setCurrentView('dashboard');
  };

  const handleOpenCase = (c: MockCase) => {
    setActiveCase(c);
    setCurrentView('inspector');
    addAuditEntry('Inspection', `${c.caseId} / ${c.txnId}`, `Opened incident for forensic inspection`);
  };

  const handleCycleStatus = (caseId: string) => {
    setCases((prev) =>
      prev.map((c) => {
        if (c.caseId === caseId) {
          const statuses: MockCase['status'][] = ['In Progress', 'Pending Review', 'Verified', 'Flagged', 'Archived'];
          const idx = statuses.indexOf(c.status);
          const nextStatus = statuses[idx !== -1 ? (idx + 1) % statuses.length : 0];
          addAuditEntry('Status Update', `${c.caseId} / ${c.txnId}`, `Status changed to ${nextStatus}`);
          return { ...c, status: nextStatus };
        }
        return c;
      })
    );
  };

  const handleSaveActiveCase = (updatedCase?: MockCase) => {
    const targetCase = updatedCase || activeCase;
    setCases((prev) => prev.map((c) => (c.caseId === targetCase.caseId ? targetCase : c)));
    setActiveCase(targetCase);
    addAuditEntry('Save Case', `${targetCase.caseId} / ${targetCase.txnId}`, `Saved modified case state and parameters`);
    showToast(`Saved ${targetCase.caseId} successfully.`);
  };

  const handleCaseCreated = (newCase: MockCase) => {
    setCases((prev) => [newCase, ...prev]);
    setActiveCase(newCase);
    showToast(`New case indexed: ${newCase.caseId}`);
  };

  const handleRunFullDemo = async () => {
    showToast('Starting Automated Strix Forensic Demo...');
    setCurrentView('dashboard');
    await new Promise((r) => setTimeout(r, 1200));

    setCurrentView('transactions');
    await new Promise((r) => setTimeout(r, 1200));

    setCurrentView('inspector');
    await new Promise((r) => setTimeout(r, 1200));

    setCurrentView('ingest');
    await new Promise((r) => setTimeout(r, 1200));

    setCurrentView('audit');
    await new Promise((r) => setTimeout(r, 1200));

    setCurrentView('inspector');
    showToast('Demo complete! Active on Case Inspector.');
  };

  if (!user) {
    return <LoginGate onLoginSuccess={handleLoginSuccess} />;
  }

  return (
    <>
      <AppShell
        user={user}
        currentView={currentView}
        onNavigate={setCurrentView}
        activeCase={activeCase}
        txnCount={cases.length}
        auditCount={auditLogs.length}
        onSignOut={handleSignOut}
        onSaveCase={() => handleSaveActiveCase()}
        onRunFullDemo={handleRunFullDemo}
      >
        {currentView === 'dashboard' && (
          <DashboardView
            cases={cases}
            onNavigate={setCurrentView}
            onOpenCase={handleOpenCase}
            onCycleStatus={handleCycleStatus}
            onOpenCapabilities={() => setCapabilitiesModalOpen(true)}
          />
        )}

        {currentView === 'transactions' && (
          <TransactionsView cases={cases} onOpenCase={handleOpenCase} onNavigate={setCurrentView} />
        )}

        {currentView === 'inspector' && (
          <CaseInspectorView
            activeCase={activeCase}
            onSaveCase={handleSaveActiveCase}
            onAuditAction={addAuditEntry}
          />
        )}

        {currentView === 'ingest' && (
          <IngestFootageView
            onCaseCreated={handleCaseCreated}
            onOpenCase={handleOpenCase}
            onAuditAction={addAuditEntry}
          />
        )}

        {currentView === 'audit' && <AuditTrailView auditLogs={auditLogs} />}
      </AppShell>

      <CapabilitiesModal isOpen={capabilitiesModalOpen} onClose={() => setCapabilitiesModalOpen(false)} />

      {/* Floating Action Toast */}
      {toastMessage && (
        <div className="fixed bottom-5 right-5 z-50 bg-slate-900 text-white border border-slate-700 px-4 py-2.5 rounded shadow-xl font-mono text-xs flex items-center gap-2 animate-in fade-in slide-in-from-bottom-2">
          <span className="w-2 h-2 rounded-full bg-status-emerald"></span>
          <span>{toastMessage}</span>
        </div>
      )}
    </>
  );
};
