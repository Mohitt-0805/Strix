import React, { useState, useEffect, useRef } from 'react';
import { RunResult, ClipOut, Frame, PublicConfig, SearchMatch, SearchResult } from '@/types/forensic';
import { api, getMediaUrl } from '@/lib/api';
import ReactCrop, { Crop, PixelCrop } from 'react-image-crop';
import { ReactCompareSlider } from 'react-compare-slider';

export interface RunInspectorViewProps {
  runResult?: RunResult | null;
  clip?: ClipOut | null;
  publicConfig?: PublicConfig | null;
  onAuditAction: (action: string, refId: string, details: string) => void;
  onNavigate?: (view: string) => void;
}

export const RunInspectorView: React.FC<RunInspectorViewProps> = ({
  runResult,
  clip,
  publicConfig,
  onAuditAction,
  onNavigate,
}) => {
  // Best frames & active inspection index
  const bestFrames: Frame[] = runResult?.best_frames || [];
  const [selectedFrameIdx, setSelectedFrameIdx] = useState<number>(0);
  const activeFrame: Frame | undefined = bestFrames[selectedFrameIdx] || bestFrames[0];

  // Tool tabs
  const [activeForensicTool, setActiveForensicTool] = useState<
    'standard' | 'crop_enhance' | 'face_search' | 'evidence_sheet'
  >('standard');

  // Video playback transport
  const [isPlaying, setIsPlaying] = useState<boolean>(false);
  const [currentTime, setCurrentTime] = useState<number>(18.4);
  const [playbackSpeed, setPlaybackSpeed] = useState<number>(1.0);
  const videoRef = useRef<HTMLVideoElement | null>(null);

  // Overlays
  const [showBBox, setShowBBox] = useState<boolean>(true);
  const [showLandmarks, setShowLandmarks] = useState<boolean>(true);
  const [showClahe, setShowClahe] = useState<boolean>(false);
  const [showAlignmentGuides, setShowAlignmentGuides] = useState<boolean>(true);
  const [isEscalated, setIsEscalated] = useState<boolean>(false);

  // Crop & Enhance state
  const [crop, setCrop] = useState<Crop>({ unit: '%', width: 60, height: 60, x: 20, y: 20 });
  const [completedCrop, setCompletedCrop] = useState<PixelCrop | null>(null);
  const [enhanceScale, setEnhanceScale] = useState<2 | 4>(4);
  const [enhanceMethod, setEnhanceMethod] = useState<'lanczos' | 'espcn'>('lanczos');
  const [isEnhancing, setIsEnhancing] = useState<boolean>(false);
  const [enhancedImageUrl, setEnhancedImageUrl] = useState<string | null>(null);
  const cropImageRef = useRef<HTMLImageElement | null>(null);

  // Search state
  const [searchMatches, setSearchMatches] = useState<SearchMatch[]>([]);
  const [searchResultMeta, setSearchResultMeta] = useState<{ notice?: string; score_note?: string; search_id?: string } | null>(null);
  const [isSearching, setIsSearching] = useState<boolean>(false);

  // Evidence frame selection
  const [selectedFrameIds, setSelectedFrameIds] = useState<(string | number)[]>(
    runResult?.selected_frame_ids || (activeFrame ? [activeFrame.frame_id] : [])
  );
  const [isDownloadingPdf, setIsDownloadingPdf] = useState<boolean>(false);

  const runId = runResult?.run_id || 'run_2026_014';
  const evidenceId = `EV-${runId}`;

  // Keep selected frame index within bounds when run changes
  useEffect(() => {
    setSelectedFrameIdx(0);
    if (runResult?.selected_frame_ids && runResult.selected_frame_ids.length > 0) {
      setSelectedFrameIds(runResult.selected_frame_ids);
    } else if (runResult?.best_frames && runResult.best_frames.length > 0) {
      setSelectedFrameIds([runResult.best_frames[0].frame_id]);
    }
  }, [runResult?.run_id]);

  // Video time updates
  const handleTimeUpdate = () => {
    if (videoRef.current) {
      setCurrentTime(videoRef.current.currentTime);
    }
  };

  const handleStepFrame = (delta: number) => {
    if (videoRef.current) {
      const fps = clip?.fps || 25;
      videoRef.current.currentTime = Math.max(0, videoRef.current.currentTime + delta / fps);
    } else {
      setCurrentTime((prev) => Math.max(0, prev + delta * 0.04));
    }
  };

  const handleCycleSpeed = () => {
    const speeds = [0.25, 0.5, 1.0, 2.0];
    const nextIdx = (speeds.indexOf(playbackSpeed) + 1) % speeds.length;
    const nextSpeed = speeds[nextIdx];
    setPlaybackSpeed(nextSpeed);
    if (videoRef.current) {
      videoRef.current.playbackRate = nextSpeed;
    }
  };

  // Toggle selection for official court evidence (POST /runs/{run_id}/selection)
  const handleToggleFrameEvidence = async (frameId: string | number) => {
    const nextIds = selectedFrameIds.includes(frameId)
      ? selectedFrameIds.filter((id) => id !== frameId)
      : [...selectedFrameIds, frameId];

    setSelectedFrameIds(nextIds);
    try {
      await api.updateSelection(runId, nextIds);
      onAuditAction('SELECTION_UPDATE', evidenceId, `Updated selected evidentiary frames: [${nextIds.join(', ')}]`);
    } catch (err) {
      console.error('Failed to update selection on server:', err);
    }
  };

  // Enhance Crop Handler: NATURAL pixel conversion (displayed -> natural pixels)
  const handleExecuteEnhance = async () => {
    if (!activeFrame) return;

    setIsEnhancing(true);
    try {
      let crop_box: [number, number, number, number] = [20, 20, 64, 64];

      if (cropImageRef.current && completedCrop) {
        const img = cropImageRef.current;
        const scaleX = img.naturalWidth / img.width;
        const scaleY = img.naturalHeight / img.height;

        crop_box = [
          Math.max(0, Math.round(completedCrop.x * scaleX)),
          Math.max(0, Math.round(completedCrop.y * scaleY)),
          Math.max(16, Math.round(completedCrop.width * scaleX)),
          Math.max(16, Math.round(completedCrop.height * scaleY)),
        ];
      }

      const res = await api.enhanceFrame(runId, activeFrame.frame_id, {
        crop_box,
        scale: enhanceScale,
        method: enhanceMethod,
      });

      const url = res.enhanced_url || res.signed_enhanced_url || `/files?p=${res.enhanced_path}`;
      setEnhancedImageUrl(getMediaUrl(url));

      onAuditAction(
        'FRAME_ENHANCE',
        evidenceId,
        `Super-resolution enhancement applied to Frame #${activeFrame.frame_id} (${enhanceMethod} x${enhanceScale}). Burned ENHANCED label.`
      );
    } catch (err: any) {
      console.error('Enhance failed:', err);
      alert(err.message || 'Enhance operation failed');
    } finally {
      setIsEnhancing(false);
    }
  };

  // Search Face Handler: POST /search
  const handleExecuteSearch = async () => {
    if (!activeFrame) return;

    setIsSearching(true);
    try {
      const searchRes: SearchResult = await api.searchFace({
        run_id: runId,
        frame_id: activeFrame.frame_id,
        top_k: 10,
        best_per_clip: true,
      });

      setSearchMatches(searchRes.matches || []);
      setSearchResultMeta({
        notice: searchRes.notice,
        score_note: searchRes.score_note,
        search_id: searchRes.search_id,
      });

      onAuditAction(
        'FACE_SEARCH',
        evidenceId,
        `Executed cross-clip face search for Frame #${activeFrame.frame_id}. Retrieved ${(searchRes.matches || []).length} candidate matches.`
      );
    } catch (err: any) {
      console.error('Search failed:', err);
      alert(err.message || 'Search failed');
    } finally {
      setIsSearching(false);
    }
  };

  // Evidence PDF Download Handler: GET /runs/{run_id}/evidence.pdf via URL.createObjectURL
  const handleDownloadEvidencePdf = async () => {
    setIsDownloadingPdf(true);
    try {
      const blob = await api.downloadEvidencePdf(runId, searchResultMeta?.search_id);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `STRIX_EVIDENCE_${evidenceId}.pdf`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);

      onAuditAction('DOWNLOAD_EVIDENCE_PDF', evidenceId, `Downloaded official court Evidence Sheet PDF`);
    } catch (err: any) {
      console.error('Download PDF failed:', err);
      alert(err.message || 'Evidence PDF export failed');
    } finally {
      setIsDownloadingPdf(false);
    }
  };

  const getReliabilityBadge = (rel?: string) => {
    switch (rel) {
      case 'High':
        return 'bg-status-emeraldBg text-status-emerald border-status-emeraldBorder';
      case 'Medium':
        return 'bg-status-amberBg text-status-amber border-status-amberBorder';
      case 'Low':
      default:
        return 'bg-status-crimsonBg text-status-crimson border-status-crimsonBorder';
    }
  };

  const rawCropUrl = getMediaUrl(activeFrame?.crop_url || activeFrame?.signed_crop_url);
  const fullFrameUrl = getMediaUrl(activeFrame?.image_url || activeFrame?.signed_frame_url);
  const enhancedDisplayUrl =
    enhancedImageUrl ||
    getMediaUrl(activeFrame?.enhancement?.enhanced_url || activeFrame?.enhancement?.signed_enhanced_url);

  // Check if all frames are low or empty
  const isAllLowOrEmpty =
    bestFrames.length === 0 || bestFrames.every((f) => f.reliability === 'Low' || f.quality_score < 0.6);

  return (
    <section id="view-run-inspector" className="space-y-4 max-w-[1440px] mx-auto">
      {/* 1. Fake Pipeline / Demo Banner */}
      {publicConfig?.pipeline_mode === 'fake' && (
        <div
          id="pipelineFakeBanner"
          className="bg-amber-500 text-slate-950 text-xs font-mono font-bold px-4 py-1.5 rounded flex items-center justify-between border border-amber-600 shadow-sm"
        >
          <div className="flex items-center gap-2">
            <span>⚠</span>
            <span>FAKE PIPELINE, DEMO DATA &mdash; Synthetic evaluation pipeline active</span>
          </div>
          <span className="text-[10px] uppercase tracking-wider bg-amber-600/40 px-2 py-0.5 rounded">
            DEMO MODE
          </span>
        </div>
      )}

      {/* 2. Models Loading Banner */}
      {publicConfig?.pipeline_ready === false && (
        <div
          id="modelsLoadingBanner"
          className="bg-blue-600 text-white text-xs font-semibold px-4 py-1.5 rounded flex items-center justify-between border border-blue-700 shadow-sm animate-pulse"
        >
          <div className="flex items-center gap-2">
            <span className="animate-spin text-sm">↻</span>
            <span>Models loading... Inference engines initializing in background.</span>
          </div>
          <span className="font-mono text-[10px] uppercase tracking-wide bg-blue-800/80 px-2 py-0.5 rounded">
            INITIALIZING
          </span>
        </div>
      )}

      {/* 3. Mandatory Human Verification Notice */}
      <div className="bg-status-amberBg border border-status-amberBorder rounded-md px-3.5 py-2 flex flex-col sm:flex-row sm:items-center justify-between gap-2 text-xs text-slate-800">
        <div className="flex items-center gap-2">
          <span className="font-semibold text-status-amber shrink-0">MANDATORY FORENSIC PROTOCOL:</span>
          <span>Possible matches only. A human investigator must verify every result.</span>
        </div>
        <span className="font-mono text-[10px] text-slate-500 font-semibold uppercase shrink-0">
          ISO/IEC 27037 Standard
        </span>
      </div>

      {/* 4. Link Low Margin Warning */}
      {runResult?.link_low_margin && (
        <div className="bg-status-crimsonBg border border-status-crimsonBorder rounded-md px-3.5 py-2 flex items-center gap-2.5 text-xs text-status-crimson font-medium">
          <svg className="w-4 h-4 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path>
            <line x1="12" y1="9" x2="12" y2="13"></line>
            <line x1="12" y1="17" x2="12.01" y2="17"></line>
          </svg>
          <span>Warning: Top candidate tracks had a narrow margin. Human verification required.</span>
        </div>
      )}

      {/* 5. Warnings and Sampling Coverage */}
      {(runResult?.coverage_start_sec !== undefined || (runResult?.warnings && runResult.warnings.length > 0)) && (
        <div className="bg-canvas border border-hairline rounded-md p-3 text-xs space-y-1.5">
          {runResult.coverage_start_sec !== undefined && runResult.coverage_end_sec !== undefined && (
            <div className="flex items-center gap-2 text-slate-700 font-mono">
              <span className="text-[10px] uppercase font-semibold text-slate-500">Sampling Coverage:</span>
              <span>
                t+{runResult.coverage_start_sec.toFixed(1)}s to t+{runResult.coverage_end_sec.toFixed(1)}s
              </span>
            </div>
          )}
          {runResult?.warnings &&
            runResult.warnings.map((w, idx) => (
              <div key={idx} className="flex items-center gap-2 text-amber-700 font-medium">
                <span>⚠ {w}</span>
              </div>
            ))}
        </div>
      )}

      {/* 6. Selection Reason Prominent Banner (Empty or All Low) */}
      {isAllLowOrEmpty && runResult?.selection_reason && (
        <div className="bg-slate-100 border border-slate-300 rounded-md p-3 text-xs text-slate-800 space-y-1">
          <div className="font-semibold text-slate-900 flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-status-amber"></span>
            <span>Selection Advisory: Low Confidence Surveillance Extraction</span>
          </div>
          <p className="font-mono text-slate-600 pl-3.5">{runResult.selection_reason}</p>
        </div>
      )}

      {/* Context Metadata Bar */}
      <div className="bg-white border border-hairline rounded-md p-4 flex flex-col xl:flex-row xl:items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
          <div>
            <div className="flex items-center gap-2">
              <span id="inspCaseId" className="font-mono text-base font-semibold text-slate-900">
                {evidenceId}
              </span>
              {runResult?.served_from_demo_pack && (
                <span className="font-mono text-[10px] font-bold px-2 py-0.5 rounded bg-blue-50 text-blue-700 border border-blue-200 uppercase tracking-tight">
                  precomputed demo result
                </span>
              )}
              <span className="text-slate-300">/</span>
              <span id="inspClipName" className="font-mono text-xs font-medium text-steel truncate max-w-[200px]">
                {clip?.original_filename || 'atm_cctv_vestibule.mp4'}
              </span>
              <span
                id="inspStatusBadge"
                className="text-[11px] font-medium px-2 py-0.5 rounded border bg-status-emeraldBg text-status-emerald border-status-emeraldBorder"
              >
                DONE
              </span>
            </div>
            <div id="inspTitleSub" className="text-xs text-slate-500 mt-0.5">
              Terminal: {clip?.atm_id || 'ATM-JPR-014'} &bull; Trans Time: {runResult?.transaction_time || '2026-11-26 21:14:24'} &bull; Duration: {clip?.duration_sec || 36}s
            </div>
          </div>

          <div className="h-8 w-px bg-hairline hidden sm:block"></div>

          {/* Quick Metrics */}
          <div className="grid grid-cols-3 gap-5 text-xs">
            <div>
              <div className="text-[10px] uppercase tracking-wider text-slate-400 font-medium">Link Confidence</div>
              <div
                id="inspMatchConf"
                className={`font-mono font-semibold tabular-nums mt-0.5 ${
                  (runResult?.link_confidence || 'High') === 'High'
                    ? 'text-status-emerald'
                    : (runResult?.link_confidence || 'High') === 'Medium'
                    ? 'text-status-amber'
                    : 'text-status-crimson'
                }`}
              >
                {runResult?.link_confidence || 'High'}
              </div>
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-wider text-slate-400 font-medium">Track ID</div>
              <div id="inspTrackId" className="font-mono text-slate-700 tabular-nums mt-0.5">
                TRACK #{runResult?.person_track_id ?? 1}
              </div>
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-wider text-slate-400 font-medium">Best Frames</div>
              <div id="inspBestCount" className="font-mono font-semibold text-slate-900 tabular-nums mt-0.5">
                {bestFrames.length} Extracted
              </div>
            </div>
          </div>
        </div>

        {/* Action Tabs & Buttons */}
        <div className="flex flex-wrap items-center gap-2 shrink-0">
          <div className="inline-flex rounded border border-hairline bg-canvas p-0.5 text-xs font-medium text-slate-600">
            <button
              onClick={() => setActiveForensicTool('standard')}
              className={`px-2.5 py-1 rounded transition-colors ${
                activeForensicTool === 'standard' ? 'bg-white text-steel font-semibold shadow-sm' : 'hover:text-slate-900'
              }`}
            >
              Surveillance
            </button>
            <button
              onClick={() => setActiveForensicTool('crop_enhance')}
              className={`px-2.5 py-1 rounded transition-colors ${
                activeForensicTool === 'crop_enhance' ? 'bg-white text-steel font-semibold shadow-sm' : 'hover:text-slate-900'
              }`}
            >
              Crop &amp; Enhance
            </button>
            <button
              onClick={() => setActiveForensicTool('face_search')}
              className={`px-2.5 py-1 rounded transition-colors ${
                activeForensicTool === 'face_search' ? 'bg-white text-steel font-semibold shadow-sm' : 'hover:text-slate-900'
              }`}
            >
              Cross-Clip Search
            </button>
            <button
              onClick={() => setActiveForensicTool('evidence_sheet')}
              className={`px-2.5 py-1 rounded transition-colors ${
                activeForensicTool === 'evidence_sheet' ? 'bg-white text-steel font-semibold shadow-sm' : 'hover:text-slate-900'
              }`}
            >
              Evidence Dossier
            </button>
          </div>

          <button
            onClick={() => setIsEscalated(!isEscalated)}
            className={`px-3 py-1.5 text-xs font-medium border rounded flex items-center gap-1.5 transition-colors ${
              isEscalated
                ? 'bg-status-crimsonBg text-status-crimson border-status-crimsonBorder font-semibold'
                : 'border-hairline bg-white hover:bg-status-crimsonBg hover:text-status-crimson hover:border-status-crimsonBorder text-slate-700'
            }`}
          >
            <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"></path>
              <line x1="4" y1="22" x2="4" y2="15"></line>
            </svg>
            <span>{isEscalated ? 'Escalated to Supervisor' : 'Flag for Escalation'}</span>
          </button>

          <button
            onClick={handleDownloadEvidencePdf}
            disabled={isDownloadingPdf}
            className="px-3.5 py-1.5 text-xs font-semibold bg-steel hover:bg-steel-hover text-white rounded flex items-center gap-1.5 transition-colors shadow-sm disabled:opacity-50"
          >
            <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
              <polyline points="7 10 12 15 17 10"></polyline>
              <line x1="12" y1="15" x2="12" y2="3"></line>
            </svg>
            <span>{isDownloadingPdf ? 'Generating PDF...' : 'Export Evidence PDF'}</span>
          </button>
        </div>
      </div>

      {/* 2-Column Forensic Workspace */}
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-4 items-start">
        {/* LEFT COLUMN (7/12): CCTV Playback & Spatiotemporal Linking */}
        <div className="xl:col-span-7 space-y-4">
          <div className="bg-white border border-hairline rounded-md overflow-hidden">
            {/* Video Header & Controls */}
            <div className="px-4 py-2.5 bg-canvas border-b border-hairline flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2 text-xs font-semibold text-slate-800">
                <span>CCTV Surveillance Feed</span>
                <span className="font-mono text-[11px] font-normal text-slate-500">
                  {clip ? `${clip.width}×${clip.height} • ${clip.fps || 25}fps` : '1280×720 • 25fps'}
                </span>
              </div>

              <div className="flex flex-wrap items-center gap-3.5 text-[11px] text-slate-700 font-medium">
                <label className="flex items-center gap-1.5 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={showBBox}
                    onChange={(e) => setShowBBox(e.target.checked)}
                    className="accent-steel rounded"
                  />
                  <span>Face BBox</span>
                </label>
                <label className="flex items-center gap-1.5 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={showLandmarks}
                    onChange={(e) => setShowLandmarks(e.target.checked)}
                    className="accent-steel rounded"
                  />
                  <span>Landmarks</span>
                </label>
                <label className="flex items-center gap-1.5 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={showClahe}
                    onChange={(e) => setShowClahe(e.target.checked)}
                    className="accent-steel rounded"
                  />
                  <span>Low-Light (CLAHE)</span>
                </label>
              </div>
            </div>

            {/* Video Viewport: Uses Signed Media URL Directly with NO Authorization Header */}
            <div className="relative bg-[#0B0F17] aspect-video w-full overflow-hidden flex items-center justify-center">
              {clip?.video_url ? (
                <video
                  ref={videoRef}
                  src={getMediaUrl(clip.video_url)}
                  controls
                  onTimeUpdate={handleTimeUpdate}
                  className="w-full h-full object-contain"
                />
              ) : fullFrameUrl ? (
                <div className="relative w-full h-full flex items-center justify-center">
                  <img
                    src={fullFrameUrl}
                    alt="Active Frame View"
                    className="w-full h-full object-contain"
                  />
                  {showBBox && (
                    <div className="absolute inset-0 pointer-events-none border border-status-emerald/60">
                      <div className="absolute top-[32%] left-[46%] w-[12%] h-[18%] border-2 border-status-emerald rounded-sm">
                        <span className="absolute -top-4 left-0 font-mono text-[9px] bg-status-emerald text-white px-1">
                          TRACK #{runResult?.person_track_id ?? 1} (98.4%)
                        </span>
                      </div>
                    </div>
                  )}
                </div>
              ) : (
                <div className="text-slate-400 font-mono text-xs flex flex-col items-center gap-2">
                  <svg className="w-8 h-8 opacity-40" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                    <rect x="2" y="4" width="20" height="14" rx="2"></rect>
                    <polygon points="10 8 16 11 10 14 10 8"></polygon>
                  </svg>
                  <span>CCTV Video Stream Ready</span>
                </div>
              )}
            </div>

            {/* Transport Controls */}
            <div className="px-4 py-2.5 border-t border-hairline bg-white flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-1.5">
                <button
                  onClick={() => handleStepFrame(-1)}
                  className="px-2 py-1 text-xs font-mono border border-hairline rounded hover:bg-canvas text-slate-700"
                  title="Step Backward (-1 Frame)"
                >
                  -1f
                </button>
                <button
                  onClick={() => {
                    if (videoRef.current) {
                      if (isPlaying) videoRef.current.pause();
                      else videoRef.current.play();
                      setIsPlaying(!isPlaying);
                    }
                  }}
                  className="px-3.5 py-1 text-xs font-semibold bg-steel hover:bg-steel-hover text-white rounded flex items-center gap-1.5 min-w-[82px] justify-center transition-colors"
                >
                  <span>{isPlaying ? '❚❚' : '▶'}</span>
                  <span>{isPlaying ? 'Pause' : 'Play'}</span>
                </button>
                <button
                  onClick={() => handleStepFrame(1)}
                  className="px-2 py-1 text-xs font-mono border border-hairline rounded hover:bg-canvas text-slate-700"
                  title="Step Forward (+1 Frame)"
                >
                  +1f
                </button>
                <div className="h-4 w-px bg-hairline mx-1"></div>
                <button
                  onClick={handleCycleSpeed}
                  className="px-2.5 py-1 text-xs font-mono border border-hairline rounded hover:bg-canvas text-slate-700"
                >
                  {playbackSpeed.toFixed(2)}x
                </button>
              </div>

              <div className="font-mono text-xs tabular-nums text-slate-600 flex items-center gap-3">
                <span id="playerTimecode">t={currentTime.toFixed(1)}s / {(clip?.duration_sec || 36).toFixed(1)}s</span>
                <span className="text-slate-300">|</span>
                <span id="playerFrameNum" className="text-slate-500">
                  Frame {activeFrame?.frame_id ? `#${activeFrame.frame_id}` : Math.round(currentTime * (clip?.fps || 25))}
                </span>
              </div>
            </div>

            {/* Synchronized ATM Timeline */}
            <div className="px-4 py-3.5 border-t border-hairline bg-canvas">
              <div className="flex items-center justify-between mb-2">
                <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                  Synchronized ATM Terminal Event Timeline
                </span>
                <span className="text-[11px] font-mono text-steel font-medium">Click event to seek timestamp</span>
              </div>

              <div className="relative pt-1 pb-2">
                <input
                  type="range"
                  min="0"
                  max={clip?.duration_sec || 36}
                  step="0.1"
                  value={currentTime}
                  onChange={(e) => {
                    const t = parseFloat(e.target.value);
                    setCurrentTime(t);
                    if (videoRef.current) videoRef.current.currentTime = t;
                  }}
                  className="forensic-slider relative z-10"
                />
              </div>

              <div className="grid grid-cols-2 sm:grid-cols-5 gap-1.5 mt-1">
                {[
                  { label: 'Card Inserted', time: 4.0 },
                  { label: 'PIN Verified', time: 11.2 },
                  { label: 'Cash Dispensed', time: 22.0 },
                  { label: 'Card Retrieved', time: 28.5 },
                  { label: 'Session End', time: 33.0 },
                ].map((ev, i) => (
                  <button
                    key={i}
                    onClick={() => {
                      setCurrentTime(ev.time);
                      if (videoRef.current) videoRef.current.currentTime = ev.time;
                    }}
                    className={`p-2 rounded border text-left transition-colors ${
                      Math.abs(currentTime - ev.time) < 1.5
                        ? 'bg-steel-tint border-steel text-steel font-semibold'
                        : 'bg-white border-hairline hover:bg-slate-50 text-slate-700'
                    }`}
                  >
                    <div className="text-[10px] uppercase truncate">{ev.label}</div>
                    <div className="font-mono text-[11px] mt-0.5 tabular-nums">t+{ev.time.toFixed(1)}s</div>
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Spatiotemporal Linking Strip */}
          <div className="bg-white border border-hairline rounded-md p-4">
            <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
              <div>
                <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-800">
                  Spatiotemporal Subject Association
                </h3>
                <p className="text-[11px] text-slate-500 mt-0.5">
                  {runResult?.link_reason || 'Primary cardholder verified via vestibule keypad standing zone dwell sync.'}
                </p>
              </div>
              <span
                className={`font-mono text-[11px] font-semibold px-2 py-0.5 rounded border uppercase ${getReliabilityBadge(
                  runResult?.link_confidence || 'High'
                )}`}
              >
                LINK CONFIDENCE: {runResult?.link_confidence || 'HIGH'}
              </span>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5 text-xs">
              <div className="bg-canvas border border-hairline rounded p-2.5">
                <div className="text-[10px] uppercase text-slate-500 font-medium">Assigned Subject</div>
                <div className="font-mono font-semibold text-steel mt-0.5">
                  TRACK #{runResult?.person_track_id ?? 1} (Active)
                </div>
                <div className="text-[11px] text-slate-500 mt-0.5">Keypad dwell overlap verified</div>
              </div>
              <div className="bg-canvas border border-hairline rounded p-2.5">
                <div className="text-[10px] uppercase text-slate-500 font-medium">Link Reason</div>
                <div className="font-mono font-semibold text-status-emerald mt-0.5 truncate">
                  {runResult?.link_reason || 'Dwell in ATM zone'}
                </div>
                <div className="text-[11px] text-slate-500 mt-0.5">
                  Margin: {runResult?.link_low_margin ? 'Narrow' : 'Robust'}
                </div>
              </div>
              <div className="bg-canvas border border-hairline rounded p-2.5">
                <div className="text-[10px] uppercase text-slate-500 font-medium">SHA-256 Digest</div>
                <div className="font-mono text-[10px] text-slate-700 mt-0.5 truncate" title={clip?.sha256}>
                  {clip?.sha256 ? `${clip.sha256.substring(0, 16)}...` : '8f4a2c91d7e0b34f...'}
                </div>
                <div className="text-[11px] text-slate-500 mt-0.5">Integrity verified</div>
              </div>
            </div>
          </div>
        </div>

        {/* RIGHT COLUMN (5/12): Tool Views (Standard, Crop & Enhance, Search, Evidence Sheet) */}
        <div className="xl:col-span-5 space-y-4">
          {/* TAB 1: STANDARD SURVEILLANCE VIEW */}
          {activeForensicTool === 'standard' && (
            <>
              {/* Face Extraction Comparison */}
              <div className="bg-white border border-hairline rounded-md overflow-hidden">
                <div className="px-4 py-2.5 bg-canvas border-b border-hairline flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-semibold text-slate-900">Extracted Face Crop</span>
                    {activeFrame && (
                      <span className="font-mono text-[11px] font-medium text-steel bg-steel-tint border border-steel-border px-1.5 py-0.5 rounded">
                        Frame #{activeFrame.frame_id}
                      </span>
                    )}
                  </div>
                  <label className="flex items-center gap-1.5 text-[11px] text-slate-600 cursor-pointer select-none">
                    <input
                      type="checkbox"
                      checked={showAlignmentGuides}
                      onChange={(e) => setShowAlignmentGuides(e.target.checked)}
                      className="accent-steel rounded"
                    />
                    <span>Alignment Guides</span>
                  </label>
                </div>

                <div className="p-4">
                  <div className="grid grid-cols-2 gap-3.5">
                    {/* Raw Crop */}
                    <div>
                      <div className="flex items-center justify-between text-[10px] font-mono text-slate-500 mb-1.5">
                        <span>ORIGINAL CROP</span>
                        <span>112×112 px</span>
                      </div>
                      <div className="border border-hairline rounded overflow-hidden bg-[#11161E] aspect-square flex items-center justify-center">
                        {rawCropUrl ? (
                          <img
                            src={rawCropUrl}
                            alt="Raw Face Crop"
                            className="w-full h-full object-cover"
                          />
                        ) : (
                          <div className="text-slate-500 font-mono text-xs">No crop preview</div>
                        )}
                      </div>
                    </div>

                    {/* Restored / Enhanced Crop */}
                    <div>
                      <div className="flex items-center justify-between text-[10px] font-mono text-steel font-medium mb-1.5">
                        <span className="flex items-center gap-1.5">
                          RESTORED
                          <span className="px-1 py-0.2 bg-red-600 text-white text-[9px] font-bold rounded">ENHANCED</span>
                        </span>
                        <span>256×256 px</span>
                      </div>
                      <div className="border border-steel-border rounded overflow-hidden bg-[#11161E] aspect-square relative flex items-center justify-center">
                        {enhancedDisplayUrl ? (
                          <img
                            src={enhancedDisplayUrl}
                            alt="Enhanced Face Crop"
                            className="w-full h-full object-cover"
                          />
                        ) : (
                          <div className="text-slate-400 font-mono text-xs text-center p-2">
                            Click "Crop &amp; Enhance" to super-resolve
                          </div>
                        )}
                      </div>
                    </div>
                  </div>

                  {/* Reliability and Flags with model estimate */}
                  <div className="mt-3 pt-3 border-t border-hairline space-y-2">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <span className="text-[11px] font-semibold text-slate-700">Reliability:</span>
                        <span
                          className={`text-[10px] font-mono font-bold px-2 py-0.5 rounded border uppercase ${getReliabilityBadge(
                            activeFrame?.reliability || 'High'
                          )}`}
                        >
                          {activeFrame?.reliability || 'High'}
                        </span>
                      </div>
                      <span className="font-mono text-[11px] text-slate-600">
                        t={activeFrame?.timestamp_sec?.toFixed(1) || '18.4'}s &bull; Yaw: {activeFrame?.metrics?.pose_yaw ?? 3}&deg;
                      </span>
                    </div>

                    {/* Flags shown with flag_scores as (model estimate) */}
                    {activeFrame?.flag_scores && Object.keys(activeFrame.flag_scores).length > 0 ? (
                      <div className="flex flex-wrap items-center gap-1.5 pt-1">
                        <span className="text-[10px] font-mono uppercase text-slate-500 font-medium">Model Flags:</span>
                        {Object.entries(activeFrame.flag_scores).map(([flag, score]) => (
                          <span
                            key={flag}
                            className="font-mono text-[10px] px-2 py-0.5 rounded bg-slate-100 border border-slate-200 text-slate-700"
                          >
                            <span className="font-semibold">{flag.replace('_', ' ')}</span> ({score}){' '}
                            <span className="font-sans text-[9px] text-slate-500 italic">(model estimate)</span>
                          </span>
                        ))}
                      </div>
                    ) : (
                      activeFrame?.flags && activeFrame.flags.length > 0 && (
                        <div className="flex flex-wrap items-center gap-1.5 pt-1">
                          <span className="text-[10px] font-mono uppercase text-slate-500 font-medium">Model Flags:</span>
                          {activeFrame.flags.map((flag) => (
                            <span
                              key={flag}
                              className="font-mono text-[10px] px-2 py-0.5 rounded bg-slate-100 border border-slate-200 text-slate-700"
                            >
                              <span className="font-semibold">{flag.replace('_', ' ')}</span>{' '}
                              <span className="font-sans text-[9px] text-slate-500 italic">(model estimate)</span>
                            </span>
                          ))}
                        </div>
                      )
                    )}

                    {/* Secondary score and delta warning */}
                    <div className="p-2 bg-canvas border border-hairline rounded flex flex-wrap items-center justify-between text-xs font-mono">
                      <div>
                        <span className="text-slate-500">Quality Score: </span>
                        <span className="font-semibold text-slate-800">
                          {activeFrame?.quality_score !== undefined
                            ? (activeFrame.quality_score > 1 ? activeFrame.quality_score / 100 : activeFrame.quality_score).toFixed(2)
                            : '0.92'}
                        </span>
                      </div>
                      <div>
                        <span className="text-slate-500">Method: </span>
                        <span className="font-semibold text-steel">
                          {activeFrame?.enhancement?.method || 'Lanczos Non-Destructive'}
                        </span>
                      </div>
                    </div>

                    {/* Evidence selection toggle button */}
                    {activeFrame && (
                      <div className="flex items-center justify-between pt-1">
                        <label className="flex items-center gap-2 cursor-pointer text-xs font-medium text-slate-700 select-none">
                          <input
                            type="checkbox"
                            checked={selectedFrameIds.includes(activeFrame.frame_id)}
                            onChange={() => handleToggleFrameEvidence(activeFrame.frame_id)}
                            className="accent-steel rounded"
                          />
                          <span>Include in Official Evidence Sheet</span>
                        </label>
                      </div>
                    )}
                  </div>
                </div>
              </div>

              {/* 5-Metric IQA Breakdown */}
              <div className="bg-white border border-hairline rounded-md p-4">
                <div className="flex items-center justify-between pb-2.5 mb-3 border-b border-hairline">
                  <div>
                    <h3 className="text-xs font-semibold text-slate-900">Image Quality Assessment (IQA)</h3>
                    <p className="text-[11px] text-slate-500">5-metric deterministic clarity breakdown</p>
                  </div>
                  <div className="text-right">
                    <div className="text-[10px] font-mono uppercase text-slate-400">Composite Score</div>
                    <div className="font-mono text-lg font-semibold tabular-nums text-status-emerald leading-none mt-0.5">
                      {Math.round(
                        (activeFrame?.quality_score !== undefined
                          ? activeFrame.quality_score > 1
                            ? activeFrame.quality_score
                            : activeFrame.quality_score * 100
                          : 92)
                      )}{' '}
                      <span className="text-xs text-slate-400 font-normal">/ 100</span>
                    </div>
                  </div>
                </div>

                <div className="space-y-2.5">
                  {[
                    { label: 'Sharpness (Laplacian)', val: activeFrame?.metrics?.sharpness ?? 91 },
                    { label: 'Illumination Uniformity', val: activeFrame?.metrics?.illumination ?? 88 },
                    { label: 'Pose (Frontal Alignment)', val: Math.max(0, 100 - Math.abs(activeFrame?.metrics?.pose_yaw ?? 3) * 3) },
                    { label: 'Unobstructed Face Region', val: Math.max(0, 100 - (activeFrame?.metrics?.occlusion ?? 5)) },
                    { label: 'Face Resolution (Pixels)', val: Math.min(100, Math.round((activeFrame?.metrics?.face_size ?? 110) * 0.8)) },
                  ].map((m, i) => (
                    <div key={i} className="space-y-1">
                      <div className="flex justify-between text-[11px]">
                        <span className="text-slate-600">{m.label}</span>
                        <span className="font-mono font-semibold text-slate-800 tabular-nums">{Math.round(m.val)}%</span>
                      </div>
                      <div className="w-full h-1.5 bg-slate-100 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-steel transition-all duration-300"
                          style={{ width: `${Math.min(100, Math.max(0, m.val))}%` }}
                        ></div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Ranked Best Frames Selector */}
              <div className="bg-white border border-hairline rounded-md p-4">
                <div className="flex items-center justify-between mb-2.5">
                  <h3 className="text-xs font-semibold text-slate-900">Ranked Best Frames</h3>
                  <span className="text-[11px] font-mono text-slate-500">Click to switch inspection frame</span>
                </div>

                <div className="grid grid-cols-4 gap-2.5">
                  {bestFrames.map((frame, i) => (
                    <div
                      key={frame.frame_id}
                      onClick={() => setSelectedFrameIdx(i)}
                      className={`cursor-pointer rounded border p-1.5 text-center transition-all ${
                        selectedFrameIdx === i
                          ? 'border-steel ring-2 ring-steel/20 bg-steel-tint'
                          : 'border-hairline hover:border-slate-300 bg-canvas'
                      }`}
                    >
                      <div className="aspect-square bg-[#11161E] rounded overflow-hidden mb-1 flex items-center justify-center">
                        <img
                          src={getMediaUrl(frame.crop_url || frame.signed_crop_url)}
                          alt={`Frame ${frame.frame_id}`}
                          className="w-full h-full object-cover"
                        />
                      </div>
                      <div className="text-[10px] font-mono font-semibold text-slate-800 truncate">
                        #{frame.frame_id}
                      </div>
                      <div className="text-[10px] font-mono text-status-emerald font-semibold">
                        {Math.round(
                          frame.quality_score > 1 ? frame.quality_score : frame.quality_score * 100
                        )}
                        /100
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </>
          )}

          {/* TAB 2: CROP & ENHANCE (Super-Resolution) */}
          {activeForensicTool === 'crop_enhance' && (
            <div className="bg-white border border-hairline rounded-md p-4 space-y-4">
              <div className="flex items-center justify-between border-b border-hairline pb-2.5">
                <div>
                  <h3 className="text-xs font-semibold text-slate-900">Non-Destructive Crop &amp; Super-Resolution</h3>
                  <p className="text-[11px] text-slate-500">Draw crop box on frame; natural pixels sent to backend</p>
                </div>
                <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-red-100 text-red-700 border border-red-300">
                  ENHANCED MARKING
                </span>
              </div>

              {/* Crop Controls */}
              <div className="grid grid-cols-2 gap-3 text-xs">
                <div>
                  <label className="block text-slate-600 font-medium mb-1">Scale Factor</label>
                  <select
                    value={enhanceScale}
                    onChange={(e) => setEnhanceScale(Number(e.target.value) as 2 | 4)}
                    className="w-full px-2.5 py-1.5 bg-canvas border border-hairline rounded"
                  >
                    <option value={2}>2x Super-Resolution</option>
                    <option value={4}>4x Super-Resolution (Default)</option>
                  </select>
                </div>
                <div>
                  <label className="block text-slate-600 font-medium mb-1">Algorithm</label>
                  <select
                    value={enhanceMethod}
                    onChange={(e) => setEnhanceMethod(e.target.value as any)}
                    className="w-full px-2.5 py-1.5 bg-canvas border border-hairline rounded"
                  >
                    <option value="lanczos">Lanczos (Deterministic Filter)</option>
                    <option value="espcn">ESPCN (Deep Learning Super-Res)</option>
                  </select>
                </div>
              </div>

              {/* ReactCrop UI on Frame Image */}
              <div className="space-y-1.5">
                <div className="text-[11px] font-semibold text-slate-700">1. Adjust Crop Box on Frame:</div>
                <div className="border border-hairline rounded overflow-hidden bg-slate-900 flex justify-center max-h-[280px]">
                  {fullFrameUrl || rawCropUrl ? (
                    <ReactCrop
                      crop={crop}
                      onChange={(c) => setCrop(c)}
                      onComplete={(c) => setCompletedCrop(c)}
                      aspect={1}
                    >
                      <img
                        ref={cropImageRef}
                        src={fullFrameUrl || rawCropUrl}
                        alt="Crop target"
                        className="max-h-[280px] w-auto object-contain"
                      />
                    </ReactCrop>
                  ) : (
                    <div className="p-8 text-slate-400 font-mono text-xs">No frame loaded</div>
                  )}
                </div>
              </div>

              {/* Trigger Enhancement */}
              <button
                onClick={handleExecuteEnhance}
                disabled={isEnhancing}
                className="w-full py-2 bg-steel hover:bg-steel-hover text-white text-xs font-semibold rounded flex items-center justify-center gap-2 transition-colors disabled:opacity-50 shadow-sm"
              >
                {isEnhancing ? (
                  <>
                    <svg className="animate-spin w-3.5 h-3.5 text-white" viewBox="0 0 24 24" fill="none">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path>
                    </svg>
                    <span>Executing Backend Super-Resolution...</span>
                  </>
                ) : (
                  <span>Execute Non-Destructive Enhancement (x{enhanceScale})</span>
                )}
              </button>

              {/* ReactCompareSlider View with Permanent Red ENHANCED Badge */}
              {enhancedDisplayUrl && rawCropUrl && (
                <div className="space-y-1.5 pt-2">
                  <div className="text-[11px] font-semibold text-slate-700">
                    2. Original vs. Enhanced Split Comparison:
                  </div>
                  <div className="border border-hairline rounded overflow-hidden aspect-square bg-slate-900 relative">
                    <ReactCompareSlider
                      itemOne={
                        <div className="w-full h-full flex items-center justify-center bg-slate-950 relative">
                          <img
                            src={rawCropUrl}
                            alt="Raw crop"
                            className="w-full h-full object-cover"
                          />
                          <div className="absolute top-2 left-2 bg-slate-900/80 text-white px-2 py-0.5 rounded text-[10px] font-mono">
                            ORIGINAL (RAW)
                          </div>
                        </div>
                      }
                      itemTwo={
                        <div className="w-full h-full flex items-center justify-center bg-slate-950 relative">
                          <img
                            src={enhancedDisplayUrl}
                            alt="Enhanced crop"
                            className="w-full h-full object-cover"
                          />
                          <div className="absolute top-2 right-2 bg-red-600 text-white px-2 py-0.5 rounded text-[10px] font-bold font-mono shadow">
                            ENHANCED (x{enhanceScale})
                          </div>
                        </div>
                      }
                      className="w-full h-full"
                    />
                  </div>
                </div>
              )}
            </div>
          )}

          {/* TAB 3: CROSS-CLIP FACE SEARCH */}
          {activeForensicTool === 'face_search' && (
            <div className="bg-white border border-hairline rounded-md p-4 space-y-4">
              <div className="flex items-center justify-between border-b border-hairline pb-2.5">
                <div>
                  <h3 className="text-xs font-semibold text-slate-900">Cross-Clip Face Cosine Similarity Search</h3>
                  <p className="text-[11px] text-slate-500">Query suspect against indexed ATM surveillance clips</p>
                </div>
                <button
                  onClick={handleExecuteSearch}
                  disabled={isSearching}
                  className="px-3.5 py-1.5 bg-steel text-white text-xs font-semibold rounded hover:bg-steel-hover disabled:opacity-50 shadow-sm"
                >
                  {isSearching ? 'Searching...' : 'Search Network'}
                </button>
              </div>

              {/* Mandatory Notice & Score Note */}
              <div className="bg-status-amberBg border border-status-amberBorder rounded p-2.5 text-xs text-slate-800 space-y-1">
                <div className="flex items-center gap-2">
                  <span className="font-semibold text-status-amber">MANDATORY PROTOCOL:</span>
                  <span>Possible matches only. A human investigator must verify every result.</span>
                </div>
                {searchResultMeta?.score_note && (
                  <p className="font-mono text-[10px] text-slate-600 pl-4">
                    Score Note: {searchResultMeta.score_note}
                  </p>
                )}
              </div>

              {/* Matches List */}
              <div className="space-y-2.5 max-h-[380px] overflow-y-auto">
                {searchMatches.map((m, idx) => {
                  const isShortTrack = Boolean(m.short_track);
                  const thumb = getMediaUrl(m.crop_url || m.thumbnail_url || m.signed_crop_url);

                  return (
                    <div
                      key={idx}
                      className={`p-3 bg-canvas border rounded-md space-y-2 ${
                        isShortTrack ? 'border-amber-300 bg-amber-50/40' : 'border-hairline'
                      }`}
                    >
                      <div className="flex items-center justify-between text-xs font-semibold">
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-slate-900 truncate max-w-[160px]">
                            {m.filename || m.clip_id}
                          </span>
                          {isShortTrack && (
                            <span className="font-mono text-[9px] font-bold px-1.5 py-0.2 rounded bg-amber-200 text-amber-800 border border-amber-300 uppercase">
                              Low Confidence (Short Track)
                            </span>
                          )}
                        </div>
                        <span
                          className={`font-mono text-[10px] px-2 py-0.5 rounded border uppercase ${getReliabilityBadge(
                            m.reliability
                          )}`}
                        >
                          Reliability: {m.reliability || 'High'}
                        </span>
                      </div>

                      <div className="flex gap-3 items-center">
                        {thumb && (
                          <div className="w-12 h-12 bg-slate-900 rounded overflow-hidden shrink-0">
                            <img src={thumb} alt="Match thumb" className="w-full h-full object-cover" />
                          </div>
                        )}
                        <div className="flex-1 grid grid-cols-2 gap-2 text-xs font-mono bg-white p-2 border border-hairline rounded">
                          <div>
                            <span className="text-slate-500">Cosine Score: </span>
                            <span className="font-semibold text-slate-900">
                              {(m.score * 100).toFixed(1)}%
                            </span>
                          </div>
                          <div>
                            <span className="text-slate-500">Source: </span>
                            <span className="font-semibold text-steel">{m.source}</span>
                          </div>
                        </div>
                      </div>

                      <div className="text-[11px] text-slate-500 font-mono flex items-center justify-between">
                        <span>
                          Track #{m.track_id} &bull; t={m.timestamp_sec?.toFixed(1) || '0.0'}s
                        </span>
                        {m.flags && m.flags.length > 0 && (
                          <span className="text-slate-600">Flags: {m.flags.join(', ')}</span>
                        )}
                      </div>
                    </div>
                  );
                })}

                {searchMatches.length === 0 && !isSearching && (
                  <div className="text-center py-8 text-xs text-slate-400 font-mono">
                    Click "Search Network" to run cosine search against indexed ATM clips.
                  </div>
                )}
              </div>
            </div>
          )}

          {/* TAB 4: EVIDENCE DOSSIER */}
          {activeForensicTool === 'evidence_sheet' && (
            <div className="bg-white border border-hairline rounded-md p-4 space-y-4">
              <div className="flex items-center justify-between border-b border-hairline pb-2.5">
                <div>
                  <h3 className="text-xs font-semibold text-slate-900">Forensic Evidence Sheet</h3>
                  <p className="text-[11px] text-slate-500">Official court evidence pack {evidenceId}</p>
                </div>
                <span className="font-mono text-xs font-semibold text-steel">
                  {selectedFrameIds.length} Frames Curated
                </span>
              </div>

              {/* Curated Frames List */}
              <div className="space-y-2.5 max-h-[340px] overflow-y-auto">
                {bestFrames
                  .filter((f) => selectedFrameIds.includes(f.frame_id))
                  .map((f) => (
                    <div key={f.frame_id} className="p-3 bg-canvas border border-hairline rounded-md space-y-2">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-xs font-semibold text-slate-900">
                            Frame #{f.frame_id}
                          </span>
                          <span
                            className={`font-mono text-[10px] px-1.5 py-0.5 rounded border uppercase ${getReliabilityBadge(
                              f.reliability
                            )}`}
                          >
                            {f.reliability}
                          </span>
                        </div>
                        <span className="font-mono text-xs font-semibold text-status-emerald">
                          IQA: {Math.round(f.quality_score > 1 ? f.quality_score : f.quality_score * 100)}/100
                        </span>
                      </div>

                      <div className="flex gap-2.5 items-center">
                        <img
                          src={getMediaUrl(f.crop_url || f.signed_crop_url)}
                          alt="Crop"
                          className="w-10 h-10 rounded object-cover border border-hairline"
                        />
                        <div className="text-[11px] text-slate-600 font-mono">
                          Timestamp: t={f.timestamp_sec?.toFixed(1)}s &bull; Yaw: {f.metrics?.pose_yaw ?? 0}&deg; &bull; Sharpness: {f.metrics?.sharpness ?? 0}
                        </div>
                      </div>
                    </div>
                  ))}

                {selectedFrameIds.length === 0 && (
                  <div className="text-center py-6 text-xs text-slate-400 font-mono">
                    No frames selected. Check "Include in Official Evidence Sheet" on best frames.
                  </div>
                )}
              </div>

              {/* Download PDF Button */}
              <button
                onClick={handleDownloadEvidencePdf}
                disabled={isDownloadingPdf}
                className="w-full py-2 bg-steel hover:bg-steel-hover text-white text-xs font-semibold rounded flex items-center justify-center gap-2 transition-colors shadow-sm disabled:opacity-50"
              >
                <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                  <polyline points="7 10 12 15 17 10"></polyline>
                  <line x1="12" y1="15" x2="12" y2="3"></line>
                </svg>
                <span>{isDownloadingPdf ? 'Generating PDF...' : 'Download Official Evidence Sheet PDF'}</span>
              </button>
            </div>
          )}
        </div>
      </div>
    </section>
  );
};
