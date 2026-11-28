import React from 'react';
import { ClipOut, RunResult, PublicConfig } from '@/types/forensic';

interface DashboardViewProps {
  clips: ClipOut[];
  runResults: RunResult[];
  publicConfig?: PublicConfig | null;
  onNavigate: (view: string) => void;
  onSelectRun: (runId: string | number) => void;
  onOpenCapabilities: () => void;
}

export const DashboardView: React.FC<DashboardViewProps> = ({
  clips,
  runResults,
  publicConfig,
  onNavigate,
  onSelectRun,
  onOpenCapabilities,
}) => {
  // KPIs computed from real clips and runs only
  const totalClips = clips.length;
  const processedRuns = runResults.length;
  const highReliabilityRuns = runResults.filter((r) => r.link_confidence === 'High').length;
  const candidateFrames = runResults.reduce((acc, r) => acc + (r.best_frames?.length || 0), 0);

  return (
    <section id="view-dashboard" className="space-y-5 max-w-[1440px] mx-auto">
      {/* Forensic Notice Banner */}
      <div className="bg-status-amberBg border border-status-amberBorder rounded-md px-4 py-2.5 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-start sm:items-center gap-2.5 text-xs text-slate-800">
          <svg
            className="w-4 h-4 text-status-amber shrink-0 mt-0.5 sm:mt-0"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
          >
            <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path>
            <line x1="12" y1="9" x2="12" y2="13"></line>
            <line x1="12" y1="17" x2="12.01" y2="17"></line>
          </svg>
          <p className="leading-relaxed">
            <span className="font-semibold text-status-amber">FORENSIC NOTICE:</span> Possible matches only. A human investigator must verify every result. Image quality scores reflect camera focus and illumination only.
          </p>
        </div>
        <button
          onClick={onOpenCapabilities}
          className="px-3 py-1.5 text-xs font-medium bg-white border border-status-amberBorder hover:bg-amber-50 text-slate-800 rounded flex items-center gap-1.5 shrink-0 transition-colors self-start sm:self-center shadow-sm"
        >
          <svg className="w-3.5 h-3.5 text-slate-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="10"></circle>
            <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"></path>
            <line x1="12" y1="17" x2="12.01" y2="17"></line>
          </svg>
          Platform Capabilities
        </button>
      </div>

      {/* Dashboard Header Row */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-slate-900 tracking-tight">Surveillance &amp; ATM Ingestion Overview</h1>
          <p className="text-xs text-slate-500 mt-0.5">
            Review ATM footage and candidate face frames.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => onNavigate('ingest')}
            className="px-3.5 py-1.5 text-xs font-semibold bg-steel hover:bg-steel-hover text-white rounded flex items-center gap-1.5 transition-colors shadow-sm"
          >
            <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="12" y1="5" x2="12" y2="19"></line>
              <line x1="5" y1="12" x2="19" y2="12"></line>
            </svg>
            Ingest Footage
          </button>
        </div>
      </div>

      {/* 4 Live Forensic Metric KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* KPI 1 */}
        <div className="bg-white border border-hairline rounded-md p-4 flex items-center gap-3.5">
          <div className="w-10 h-10 rounded bg-canvas border border-hairline flex items-center justify-center shrink-0 text-steel">
            <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
              <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
            </svg>
          </div>
          <div className="min-w-0">
            <div className="text-xs font-medium text-slate-500">Total Footage Clips</div>
            <div id="kpiTotalInvestigations" className="text-2xl font-semibold font-mono tabular-nums text-slate-900 mt-0.5">
              {totalClips}
            </div>
            <div className="text-[11px] text-slate-400 mt-0.5">Indexed ATM recordings</div>
          </div>
        </div>

        {/* KPI 2 */}
        <div className="bg-white border border-hairline rounded-md p-4 flex items-center gap-3.5">
          <div className="w-10 h-10 rounded bg-canvas border border-hairline flex items-center justify-center shrink-0 text-status-amber">
            <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
              <circle cx="12" cy="12" r="10"></circle>
              <polyline points="12 6 12 12 16 14"></polyline>
            </svg>
          </div>
          <div className="min-w-0">
            <div className="text-xs font-medium text-slate-500">Pipeline Runs</div>
            <div id="kpiPendingReviews" className="text-2xl font-semibold font-mono tabular-nums text-slate-900 mt-0.5">
              {processedRuns}
            </div>
            <div className="text-[11px] text-slate-400 mt-0.5">Spatiotemporal extractions</div>
          </div>
        </div>

        {/* KPI 3 */}
        <div className="bg-white border border-hairline rounded-md p-4 flex items-center gap-3.5">
          <div className="w-10 h-10 rounded bg-canvas border border-hairline flex items-center justify-center shrink-0 text-status-emerald">
            <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
              <polygon points="23 7 16 12 23 17 23 7"></polygon>
              <rect x="1" y="5" width="15" height="14" rx="2"></rect>
            </svg>
          </div>
          <div className="min-w-0">
            <div className="text-xs font-medium text-slate-500">High-reliability runs</div>
            <div id="kpiVideosProcessed" className="text-2xl font-semibold font-mono tabular-nums text-slate-900 mt-0.5">
              {highReliabilityRuns}
            </div>
            <div className="text-[11px] text-slate-400 mt-0.5">High confidence associations</div>
          </div>
        </div>

        {/* KPI 4 */}
        <div className="bg-white border border-hairline rounded-md p-4 flex items-center gap-3.5">
          <div className="w-10 h-10 rounded bg-canvas border border-hairline flex items-center justify-center shrink-0 text-purple-600">
            <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
              <polyline points="14 2 14 8 20 8"></polyline>
              <line x1="16" y1="13" x2="8" y2="13"></line>
              <line x1="16" y1="17" x2="8" y2="17"></line>
            </svg>
          </div>
          <div className="min-w-0">
            <div className="text-xs font-medium text-slate-500">Candidate Face Frames</div>
            <div id="kpiReportsGenerated" className="text-2xl font-semibold font-mono tabular-nums text-slate-900 mt-0.5">
              {candidateFrames}
            </div>
            <div className="text-[11px] text-slate-400 mt-0.5">Ranked face crops extracted</div>
          </div>
        </div>
      </div>

      {/* Forensic Capabilities Architecture Strip */}
      <div className="bg-white border border-hairline rounded-md p-4">
        <div className="flex items-center justify-between pb-2 mb-3 border-b border-hairline">
          <div>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-800">
              Pipeline Architecture &amp; Guarantees
            </h3>
            <p className="text-[11px] text-slate-500">Deterministic face candidate extraction parameters and integrity standards</p>
          </div>
          <span className="font-mono text-[10px] text-steel font-semibold px-2 py-0.5 rounded bg-steel-tint border border-steel-border">
            ISO/IEC 27037
          </span>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 text-xs">
          <div className="p-2.5 rounded bg-canvas border border-hairline">
            <div className="font-semibold text-slate-800 flex items-center gap-1.5">
              <span className="text-status-emerald font-bold">✓</span>
              Person Detection &amp; Tracking
            </div>
            <p className="text-[11px] text-slate-500 mt-1">MobileNetV3 Faster R-CNN + ByteTrack spatial ATM zone anchoring.</p>
          </div>
          <div className="p-2.5 rounded bg-canvas border border-hairline">
            <div className="font-semibold text-slate-800 flex items-center gap-1.5">
              <span className="text-status-emerald font-bold">✓</span>
              Face Detection &amp; Embeddings
            </div>
            <p className="text-[11px] text-slate-500 mt-1">InsightFace ArcFace 512-d normalized cosine embeddings.</p>
          </div>
          <div className="p-2.5 rounded bg-canvas border border-hairline">
            <div className="font-semibold text-slate-800 flex items-center gap-1.5">
              <span className="text-status-emerald font-bold">✓</span>
              Non-Destructive Enhancement
            </div>
            <p className="text-[11px] text-slate-500 mt-1">Original files untouched. Restored crops have permanent burned ENHANCED stamp.</p>
          </div>
          <div className="p-2.5 rounded bg-canvas border border-hairline">
            <div className="font-semibold text-slate-800 flex items-center gap-1.5">
              <span className="text-status-emerald font-bold">✓</span>
              No Ultralytics / YOLOv8
            </div>
            <p className="text-[11px] text-slate-500 mt-1">Strict repository hard rules compliance.</p>
          </div>
        </div>

        {publicConfig?.model_labels && (
          <div className="mt-3 pt-2.5 border-t border-hairline flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-[10px] font-mono uppercase text-slate-500 font-semibold mr-1">
                Active Pipeline Model Labels:
              </span>
              {publicConfig.model_labels.map((lbl, idx) => (
                <span
                  key={idx}
                  className={`font-mono text-[10px] px-2 py-0.5 rounded border font-semibold ${
                    lbl === 'MOCK'
                      ? 'bg-red-50 text-red-700 border-red-300'
                      : 'bg-steel-tint text-steel border-steel-border'
                  }`}
                >
                  {lbl}
                </span>
              ))}
            </div>
            <button
              onClick={onOpenCapabilities}
              className="text-xs font-medium text-steel hover:underline"
            >
              Full Forensic Matrix →
            </button>
          </div>
        )}
      </div>

      {/* Recent Investigations Table */}
      <div className="bg-white border border-hairline rounded-md overflow-hidden">
        <div className="px-4 py-3 bg-canvas border-b border-hairline flex items-center justify-between">
          <div>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-900">Recent Investigations &amp; Runs</h3>
            <p className="text-[11px] text-slate-500">Showing synchronized ATM CCTV cases logged in system</p>
          </div>
          <button
            onClick={() => onNavigate('transactions')}
            className="text-xs font-medium text-steel hover:underline"
          >
            View All ({clips.length}) →
          </button>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-canvas border-b border-hairline text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
                <th className="py-2.5 px-4">Evidence / Run ID</th>
                <th className="py-2.5 px-4">ATM Terminal</th>
                <th className="py-2.5 px-4">Transaction Time</th>
                <th className="py-2.5 px-4">Link Confidence</th>
                <th className="py-2.5 px-4">Best Frame IQA</th>
                <th className="py-2.5 px-4">Status</th>
                <th className="py-2.5 px-4 text-right">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-hairline text-xs font-mono">
              {runResults.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-8 text-center text-xs text-slate-400 font-mono">
                    No data yet
                  </td>
                </tr>
              ) : (
                runResults.map((r) => {
                  const bestF = r.best_frames?.[0];
                  const qualityScore = bestF
                    ? Math.round(bestF.quality_score > 1 ? bestF.quality_score : bestF.quality_score * 100)
                    : null;
                  const matchedClip = clips.find((c) => c.id === r.clip_id);
                  const atmLabel = matchedClip?.atm_id || (typeof r.clip_id === 'string' ? r.clip_id : `Clip ${r.clip_id}`);

                  return (
                    <tr key={r.run_id} className="hover:bg-slate-50/80 transition-colors">
                      <td className="py-3 px-4">
                        <div className="font-semibold text-slate-900">EV-{r.run_id}</div>
                        <div className="text-[10px] text-slate-500 font-sans truncate max-w-[180px]">
                          Clip: {r.clip_id}
                        </div>
                      </td>
                      <td className="py-3 px-4 text-slate-700">
                        <div>{atmLabel}</div>
                        <div className="text-[10px] text-slate-400 font-sans">
                          {matchedClip?.notes || 'Vestibule Cam'}
                        </div>
                      </td>
                      <td className="py-3 px-4 text-slate-600 whitespace-nowrap">
                        {r.transaction_time ? r.transaction_time.replace('T', ' ').substring(0, 19) : '—'}
                      </td>
                      <td className="py-3 px-4">
                        <span
                          className={`text-[10px] font-semibold px-2 py-0.5 rounded border uppercase ${
                            r.link_confidence === 'High'
                              ? 'bg-status-emeraldBg text-status-emerald border-status-emeraldBorder'
                              : r.link_confidence === 'Medium'
                              ? 'bg-status-amberBg text-status-amber border-status-amberBorder'
                              : 'bg-status-crimsonBg text-status-crimson border-status-crimsonBorder'
                          }`}
                        >
                          {r.link_confidence || '—'}
                        </span>
                      </td>
                      <td className="py-3 px-4">
                        {qualityScore !== null ? (
                          <>
                            <span className="font-semibold text-status-emerald tabular-nums">
                              {qualityScore}
                            </span>
                            <span className="text-slate-400 text-[10px]"> / 100</span>
                          </>
                        ) : (
                          <span className="text-slate-400">—</span>
                        )}
                      </td>
                      <td className="py-3 px-4">
                        <span className="text-[10px] uppercase px-2 py-0.5 rounded border bg-status-emeraldBg text-status-emerald border-status-emeraldBorder font-semibold">
                          DONE
                        </span>
                      </td>
                      <td className="py-3 px-4 text-right">
                        <button
                          onClick={() => {
                            onSelectRun(r.run_id);
                            onNavigate('inspector');
                          }}
                          className="px-2.5 py-1 text-xs font-medium text-steel bg-steel-tint hover:bg-steel hover:text-white border border-steel-border rounded transition-colors"
                        >
                          Inspect
                        </button>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
};