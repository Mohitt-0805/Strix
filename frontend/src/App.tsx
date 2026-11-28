import React, { useState, useEffect } from 'react';
import { User, PublicConfig, ClipOut, RunResult } from '@/types/forensic';
import { DEMO_CLIPS, DEMO_RUN_RESULTS, DEMO_AUDIT_LOGS } from '@/lib/mockData';
import { api, isMockMode, API_BASE_URL } from '@/lib/api';
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
  const [clips, setClips] = useState<ClipOut[]>(isMockMode ? DEMO_CLIPS : []);
  const [activeClip, setActiveClip] = useState<ClipOut | null>(
    isMockMode ? (DEMO_CLIPS[0] || null) : null
  );
  const [runResults, setRunResults] = useState<RunResult[]>(
    isMockMode ? Object.values(DEMO_RUN_RESULTS) : []
  );
  const [activeRunId, setActiveRunId] = useState<string | number | null>(
    isMockMode ? 'run_2026_014' : null
  );
  const [activeRunResult, setActiveRunResult] = useState<RunResult | null>(
    isMockMode ? (DEMO_RUN_RESULTS['run_2026_014'] || null) : null
  );
  const [auditCount, setAuditCount] = useState<number | undefined>(
    isMockMode ? DEMO_AUDIT_LOGS.length : undefined
  );

  const [capabilitiesModalOpen, setCapabilitiesModalOpen] = useState<boolean>(false);
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [publicConfig, setPublicConfig] = useState<PublicConfig | null>(null);
  const [backendUnreachable, setBackendUnreachable] = useState<boolean>(false);

  // Fetch initial config and real clips
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

    if (user) {
      api
        .listClips()
        .then((serverClips) => {
          if (serverClips && serverClips.length > 0) {
            setClips(serverClips);
            if (!activeClip) setActiveClip(serverClips[0]);
          }
        })
        .catch((err) => {
          console.warn('Could not fetch server clips:', err);
        });

      if (user.role === 'admin' && !isMockMode) {
        api
          .getAuditLogs({ limit: 1, offset: 0 })
          .then((res) => {
            if (res && typeof res.total === 'number') {
              setAuditCount(res.total);
            }
          })
          .catch(() => {
            setAuditCount(undefined);
          });
      }
    }
  }, [user]);

  // Handle auth expired event
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
    console.log(`[AUDIT] Action: ${action} | Ref: ${refId} | Details: ${details}`);
  };

  const handleLoginSuccess = (authenticatedUser: User) => {
    setUser(authenticatedUser);
    showToast(`Signed in as ${authenticatedUser.full_name || authenticatedUser.username}`);
  };

  const handleSignOut = () => {
    api.logout();
    setUser(null);
    setCurrentView('dashboard');
  };

  const handleSelectRun = async (runId: string | number) => {
    setActiveRunId(runId);
    try {
      const result = await api.getRunResult(runId);
      setActiveRunResult(result);
      const matchedClip = clips.find((c) => c.id === result.clip_id);
      if (matchedClip) setActiveClip(matchedClip);
    } catch {
      if (isMockMode && DEMO_RUN_RESULTS[String(runId)]) {
        setActiveRunResult(DEMO_RUN_RESULTS[String(runId)]);
      } else {
        setActiveRunResult(null);
      }
    }
    setCurrentView('inspector');
  };

  const handleSelectClip = (clip: ClipOut) => {
    setActiveClip(clip);
    // Find associated run or default to active
    const matchedRun = runResults.find((r) => r.clip_id === clip.id);
    if (matchedRun) {
      setActiveRunId(matchedRun.run_id);
      setActiveRunResult(matchedRun);
    }
  };

  const handleRunCompleted = (runId: string | number, clip: ClipOut, result?: RunResult) => {
    setClips((prev) => {
      const exists = prev.some((c) => c.id === clip.id);
      return exists ? prev : [clip, ...prev];
    });
    setActiveClip(clip);
    setActiveRunId(runId);
    if (result) {
      setActiveRunResult(result);
      setRunResults((prev) => [result, ...prev.filter((r) => r.run_id !== runId)]);
    }
    showToast(`New evidence dossier indexed: EV-${runId}`);
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

    if (user?.role === 'admin') {
      setCurrentView('audit');
      await new Promise((r) => setTimeout(r, 1200));
    }

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
          DEMO DATA
        </div>
      )}
      {publicConfig?.pipeline_ready === false && (
        <div
          id="modelsLoadingBanner"
          className="bg-blue-600 text-white text-xs font-semibold px-4 py-1.5 flex items-center justify-between border-b border-blue-700 sticky top-0 z-[98] animate-pulse"
        >
          <div className="flex items-center gap-2">
            <span>↻</span>
            <span>Models loading... Inference engines initializing in background.</span>
          </div>
          <span className="font-mono text-[10px] uppercase tracking-wide bg-blue-800/80 px-2 py-0.5 rounded">
            INITIALIZING
          </span>
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
          activeEvidenceId={activeRunId ? `EV-${activeRunId}` : 'EV-NONE'}
          activeRunStatus="DONE"
          isServedFromDemo={Boolean(activeRunResult?.served_from_demo_pack)}
          clipCount={clips.length}
          auditCount={user?.role === 'admin' ? auditCount : undefined}
          onSignOut={handleSignOut}
          onSaveEvidence={() => showToast(`Evidence state saved for EV-${activeRunId}`)}
          onRunFullDemo={handleRunFullDemo}
        >
          {currentView === 'dashboard' && (
            <DashboardView
              clips={clips}
              runResults={runResults}
              publicConfig={publicConfig}
              onNavigate={setCurrentView}
              onSelectRun={handleSelectRun}
              onOpenCapabilities={() => setCapabilitiesModalOpen(true)}
            />
          )}

          {currentView === 'transactions' && (
            <TransactionsView
              clips={clips}
              onSelectClip={handleSelectClip}
              onNavigate={setCurrentView}
            />
          )}

          {currentView === 'inspector' && (
            <CaseInspectorView
              runResult={activeRunResult}
              clip={activeClip}
              publicConfig={publicConfig}
              onAuditAction={addAuditEntry}
              onNavigate={setCurrentView}
            />
          )}

          {currentView === 'ingest' && (
            <IngestFootageView
              onRunCompleted={handleRunCompleted}
              onAuditAction={addAuditEntry}
              onNavigate={setCurrentView}
            />
          )}

          {currentView === 'audit' && <AuditTrailView user={user} />}
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
