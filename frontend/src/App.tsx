import React, { useState, useEffect } from 'react';
import { User, PublicConfig } from '@/types/forensic';
import { INITIAL_CASES, INITIAL_AUDIT_LOGS, MockCase, MockAuditEntry } from '@/lib/mockData';
import { api, isMockMode, MOCK_MODE, API_BASE_URL } from '@/lib/api';
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
  const [publicConfig, setPublicConfig] = useState<PublicConfig | null>(null);
  const [backendUnreachable, setBackendUnreachable] = useState<boolean>(false);

  useEffect(() => {
    api
      .getPublicConfig()
      .then((cfg) => {
        setPublicConfig(cfg);
        setBackendUnreachable(false);
      })
      .catch(() => {
        if (!isMockMode) {
          setBackendUnreachable(true);
        }
      });
  }, []);

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

  const renderTopBanners = () => (
    <>
      {isMockMode && (
        <div
          id="mockRibbon"
          className="bg-red-600 text-white text-xs font-bold tracking-widest text-center py-1 uppercase shadow-sm sticky top-0 z-[100] border-b border-red-700 select-none"
        >
          MOCK DATA, NOT A REAL RESULT
        </div>
      )}
      {publicConfig?.banner && (
        <div
          id="configBanner"
          className="bg-slate-900 text-amber-300 text-xs font-mono font-medium px-4 py-1 text-center border-b border-slate-800 sticky top-0 z-[90]"
        >
          ⚠ {publicConfig.banner}
        </div>
      )}
      {backendUnreachable && !isMockMode && (
        <div
          id="backendUnreachableBanner"
          className="bg-amber-600 text-white text-xs font-semibold px-4 py-1.5 flex items-center justify-between border-b border-amber-700 sticky top-0 z-[95]"
        >
          <div className="flex items-center gap-2">
            <span className="font-bold">NOTICE:</span>
            <span>
              Backend not reachable at {API_BASE_URL}. Running in strict mode (no invented data). Start backend server to
              authenticate.
            </span>
          </div>
          <span className="font-mono text-[10px] uppercase tracking-wide bg-amber-800/80 px-2 py-0.5 rounded">
            Backend Not Reachable
          </span>
        </div>
      )}
    </>
  );

  if (!user) {
    return (
      <div className="min-h-screen flex flex-col">
        {renderTopBanners()}
        <div className="flex-1 relative">
          <LoginGate onLoginSuccess={handleLoginSuccess} />
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex flex-col">
      {renderTopBanners()}
      <div className="flex-1 overflow-hidden">
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
              publicConfig={publicConfig}
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
      </div>

      <CapabilitiesModal isOpen={capabilitiesModalOpen} onClose={() => setCapabilitiesModalOpen(false)} />

      {/* Floating Action Toast */}
      {toastMessage && (
        <div className="fixed bottom-5 right-5 z-50 bg-slate-900 text-white border border-slate-700 px-4 py-2.5 rounded shadow-xl font-mono text-xs flex items-center gap-2 animate-in fade-in slide-in-from-bottom-2">
          <span className="w-2 h-2 rounded-full bg-status-emerald"></span>
          <span>{toastMessage}</span>
        </div>
      )}
    </div>
  );
};
