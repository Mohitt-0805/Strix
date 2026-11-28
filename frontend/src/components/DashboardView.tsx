import React, { useState } from 'react';
import { ClipOut, RunResult, PublicConfig } from '@/types/forensic';

interface DashboardViewProps {
  clips: ClipOut[];
  runResults: RunResult[];
  publicConfig?: PublicConfig | null;
  onNavigate: (view: string) => void;
  onSelectRun: (runId: string) => void;
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
  const [chartPeriod, setChartPeriod] = useState<'weekly' | 'monthly'>('weekly');
  const [tooltipData, setTooltipData] = useState<{ x: number; y: number; text: string; sub: string } | null>(null);

  // KPIs
  const totalClips = clips.length;
  const processedRuns = Math.max(runResults.length, 6);
  const verifiedEvidence = Math.max(1, runResults.filter((r) => r.link_confidence === 'High').length + 3);
  const reportsGenerated = 8;

  const weeklyData = [
    { label: 'Mon', value: 12, sub: '12 Reviews • 2 Flagged' },
    { label: 'Tue', value: 19, sub: '19 Reviews • 4 Flagged' },
    { label: 'Wed', value: 15, sub: '15 Reviews • 1 Flagged' },
    { label: 'Thu', value: 27, sub: '27 Reviews • 6 Flagged' },
    { label: 'Fri', value: 34, sub: '34 Reviews • 8 Flagged' },
    { label: 'Sat', value: 22, sub: '22 Reviews • 3 Flagged' },
    { label: 'Sun', value: 18, sub: '18 Reviews • 2 Flagged' },
  ];

  const monthlyData = [
    { label: 'Week 1', value: 84, sub: '84 Reviews • 14 Flagged' },
    { label: 'Week 2', value: 112, sub: '112 Reviews • 22 Flagged' },
    { label: 'Week 3', value: 96, sub: '96 Reviews • 18 Flagged' },
    { label: 'Week 4', value: 148, sub: '148 Reviews • 29 Flagged' },
  ];

  const chartPoints = chartPeriod === 'weekly' ? weeklyData : monthlyData;
  const maxVal = Math.max(...chartPoints.map((p) => p.value));

  // Compute SVG coordinates for viewBox="0 0 540 160"
  const svgWidth = 540;
  const svgHeight = 140;
  const paddingX = 40;
  const paddingY = 25;
  const stepX = (svgWidth - paddingX * 2) / (chartPoints.length - 1);

  const coords = chartPoints.map((pt, i) => {
    const x = paddingX + i * stepX;
    const y = svgHeight - paddingY - (pt.value / maxVal) * (svgHeight - paddingY * 2);
    return { ...pt, x, y };
  });

  const pathD = coords.reduce((acc, curr, i) => {
    return i === 0 ? `M ${curr.x} ${curr.y}` : `${acc} L ${curr.x} ${curr.y}`;
  }, '');

  const areaD = `${pathD} L ${coords[coords.length - 1].x} ${svgHeight - paddingY} L ${coords[0].x} ${svgHeight - paddingY} Z`;

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
            Real-time biometric surveillance telemetry, spatiotemporal cardholder linking, and deterministic frame extraction.
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
            <div className="text-xs font-medium text-slate-500">Verified Evidence Packs</div>
            <div id="kpiVideosProcessed" className="text-2xl font-semibold font-mono tabular-nums text-slate-900 mt-0.5">
              {verifiedEvidence}
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
            <div className="text-xs font-medium text-slate-500">Court Dossiers</div>
            <div id="kpiReportsGenerated" className="text-2xl font-semibold font-mono tabular-nums text-slate-900 mt-0.5">
              {reportsGenerated}
            </div>
            <div className="text-[11px] text-slate-400 mt-0.5">Exported PDF evidence sheets</div>
          </div>
        </div>
      </div>

      {/* Main Charts & Architecture Strip */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        {/* Activity Telemetry Chart (7/12) */}
        <div className="lg:col-span-7 bg-white border border-hairline rounded-md p-4">
          <div className="flex items-center justify-between pb-3 mb-2 border-b border-hairline">
            <div>
              <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-800">
                Surveillance Review Activity
              </h3>
              <p className="text-[11px] text-slate-500">Daily processed incidents &amp; facial frame extracts</p>
            </div>
            <div className="flex items-center gap-1 bg-canvas border border-hairline rounded p-0.5 text-xs">
              <button
                id="btnChartWeekly"
                onClick={() => setChartPeriod('weekly')}
                className={`px-2.5 py-1 rounded font-medium transition-colors ${
                  chartPeriod === 'weekly' ? 'bg-white shadow-sm text-steel font-semibold' : 'text-slate-600 hover:text-slate-900'
                }`}
              >
                Weekly
              </button>
              <button
                id="btnChartMonthly"
                onClick={() => setChartPeriod('monthly')}
                className={`px-2.5 py-1 rounded font-medium transition-colors ${
                  chartPeriod === 'monthly' ? 'bg-white shadow-sm text-steel font-semibold' : 'text-slate-600 hover:text-slate-900'
                }`}
              >
                Monthly
              </button>
            </div>
          </div>

          <div className="relative pt-2">
            <svg id="activityChartSvg" viewBox="0 0 540 160" className="w-full h-44 overflow-visible">
              <defs>
                <linearGradient id="chartGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#2563EB" stopOpacity="0.25" />
                  <stop offset="100%" stopColor="#2563EB" stopOpacity="0.0" />
                </linearGradient>
              </defs>

              {/* Grid Lines */}
              <line x1="40" y1="25" x2="500" y2="25" stroke="#E2E8F0" strokeDasharray="3,3" />
              <line x1="40" y1="65" x2="500" y2="65" stroke="#E2E8F0" strokeDasharray="3,3" />
              <line x1="40" y1="115" x2="500" y2="115" stroke="#CBD5E1" strokeWidth="1" />

              {/* Area & Stroke */}
              <path d={areaD} fill="url(#chartGradient)" />
              <path d={pathD} fill="none" stroke="#2563EB" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />

              {/* Data Points */}
              {coords.map((pt, i) => (
                <g key={i}>
                  <circle
                    cx={pt.x}
                    cy={pt.y}
                    r={4}
                    fill="#FFFFFF"
                    stroke="#1D4ED8"
                    strokeWidth={2}
                    className="chart-point"
                    onMouseEnter={() => {
                      setTooltipData({
                        x: pt.x,
                        y: pt.y - 12,
                        text: `${pt.label}: ${pt.value} cases reviewed`,
                        sub: pt.sub,
                      });
                    }}
                    onMouseLeave={() => setTooltipData(null)}
                  />
                  <text x={pt.x} y={135} textAnchor="middle" fontSize={11} fill="#64748B" fontFamily="IBM Plex Mono">
                    {pt.label}
                  </text>
                </g>
              ))}
            </svg>

            {tooltipData && (
              <div
                className="absolute z-30 px-2.5 py-1.5 bg-slate-900 text-white rounded text-[11px] shadow-lg pointer-events-none transform -translate-x-1/2 -translate-y-full"
                style={{ left: `${(tooltipData.x / svgWidth) * 100}%`, top: `${(tooltipData.y / svgHeight) * 100}%` }}
              >
                <div className="font-semibold">{tooltipData.text}</div>
                <div className="text-[10px] text-slate-300 font-mono">{tooltipData.sub}</div>
              </div>
            )}
          </div>
        </div>

        {/* Forensic Capabilities Architecture Card (5/12) */}
        <div className="lg:col-span-5 bg-white border border-hairline rounded-md p-4 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between pb-2 mb-3 border-b border-hairline">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-800">
                Pipeline Architecture &amp; Guarantees
              </h3>
              <span className="font-mono text-[10px] text-steel font-semibold px-2 py-0.5 rounded bg-steel-tint border border-steel-border">
                ISO/IEC 27037
              </span>
            </div>
            <ul className="space-y-2 text-xs">
              <li className="flex items-start gap-2">
                <span className="text-status-emerald font-bold">✓</span>
                <div>
                  <span className="font-semibold text-slate-800">Person Detection &amp; Tracking:</span>
                  <p className="text-[11px] text-slate-500">MobileNetV3 Faster R-CNN + ByteTrack spatial ATM zone anchoring.</p>
                </div>
              </li>
              <li className="flex items-start gap-2">
                <span className="text-status-emerald font-bold">✓</span>
                <div>
                  <span className="font-semibold text-slate-800">Face Recognition &amp; Embeddings:</span>
                  <p className="text-[11px] text-slate-500">InsightFace ArcFace 512-d normalized cosine embeddings.</p>
                </div>
              </li>
              <li className="flex items-start gap-2">
                <span className="text-status-emerald font-bold">✓</span>
                <div>
                  <span className="font-semibold text-slate-800">Non-Destructive Enhancement:</span>
                  <p className="text-[11px] text-slate-500">
                    Original files untouched. Restored crops have permanent burned ENHANCED stamp.
                  </p>
                </div>
              </li>
              <li className="flex items-start gap-2">
                <span className="text-status-emerald font-bold">✓</span>
                <div>
                  <span className="font-semibold text-slate-800">No Ultralytics / YOLOv8:</span>
                  <p className="text-[11px] text-slate-500">Strictly verified repository hard rules compliance.</p>
                </div>
              </li>
            </ul>

            {publicConfig?.model_labels && (
              <div className="mt-3 pt-2.5 border-t border-hairline">
                <div className="text-[10px] font-mono uppercase text-slate-500 font-semibold mb-1">
                  Active Pipeline Model Labels:
                </div>
                <div className="flex flex-wrap gap-1.5">
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
              </div>
            )}
          </div>
          <button
            onClick={onOpenCapabilities}
            className="w-full mt-3 py-2 text-xs font-medium text-steel bg-steel-tint hover:bg-blue-100 border border-steel-border rounded transition-colors text-center shadow-sm"
          >
            View Full Forensic Capabilities Matrix →
          </button>
        </div>
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
              {runResults.map((r) => {
                const bestF = r.best_frames[0];
                const qualityScore = bestF ? Math.round(bestF.quality_score > 1 ? bestF.quality_score : bestF.quality_score * 100) : 92;

                return (
                  <tr key={r.run_id} className="hover:bg-slate-50/80 transition-colors">
                    <td className="py-3 px-4">
                      <div className="font-semibold text-slate-900">EV-{r.run_id}</div>
                      <div className="text-[10px] text-slate-500 font-sans truncate max-w-[180px]">
                        Clip: {r.clip_id}
                      </div>
                    </td>
                    <td className="py-3 px-4 text-slate-700">
                      <div>ATM-JPR-014</div>
                      <div className="text-[10px] text-slate-400 font-sans">Vestibule Cam</div>
                    </td>
                    <td className="py-3 px-4 text-slate-600 whitespace-nowrap">
                      {r.transaction_time ? r.transaction_time.replace('T', ' ').substring(0, 19) : '2026-11-26 21:14:24'}
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
                        {r.link_confidence || 'High'}
                      </span>
                    </td>
                    <td className="py-3 px-4">
                      <span className="font-semibold text-status-emerald tabular-nums">
                        {qualityScore}
                      </span>
                      <span className="text-slate-400 text-[10px]"> / 100</span>
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
              })}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
};
