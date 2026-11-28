import React, { useState, useEffect, useRef } from 'react';
import { MockCase, MockCandidate } from '@/lib/mockData';
import { drawForensicFace, renderCCTVFrame } from '@/lib/forensicCanvas';
import { api } from '@/lib/api';
import ReactCrop, { Crop, PixelCrop } from 'react-image-crop';
import { ReactCompareSlider, ReactCompareSliderImage } from 'react-compare-slider';
import { FaceSearchMatch } from '@/types/forensic';

interface CaseInspectorViewProps {
  activeCase: MockCase;
  onSaveCase: (updatedCase: MockCase) => void;
  onAuditAction: (action: string, refId: string, details: string) => void;
}

export const CaseInspectorView: React.FC<CaseInspectorViewProps> = ({ activeCase, onSaveCase, onAuditAction }) => {
  const [currentCase, setCurrentCase] = useState<MockCase>(activeCase);
  const [currentTime, setCurrentTime] = useState<number>(18.4);
  const [isPlaying, setIsPlaying] = useState<boolean>(false);
  const [playbackSpeed, setPlaybackSpeed] = useState<number>(1.0);
  const [isEscalated, setIsEscalated] = useState<boolean>(false);

  // Overlays
  const [showBBox, setShowBBox] = useState<boolean>(true);
  const [showLandmarks, setShowLandmarks] = useState<boolean>(true);
  const [showClahe, setShowClahe] = useState<boolean>(false);
  const [showAlignmentGuides, setShowAlignmentGuides] = useState<boolean>(true);

  // Active Candidate Selection
  const [selectedCandIdx, setSelectedCandIdx] = useState<number>(activeCase.primaryCandidateIdx || 0);

  // Addendum Tools: active tab / modal state
  const [activeForensicTool, setActiveForensicTool] = useState<'standard' | 'crop_enhance' | 'face_search' | 'extract_frames'>('standard');

  // Tool 1: Extract Frames State
  const [extractStart, setExtractStart] = useState<number>(10.0);
  const [extractEnd, setExtractEnd] = useState<number>(25.0);
  const [extractFps, setExtractFps] = useState<number>(2.0);
  const [extractedFrames, setExtractedFrames] = useState<any[]>([]);
  const [isExtracting, setIsExtracting] = useState<boolean>(false);
  const [selectedExtractIds, setSelectedExtractIds] = useState<string[]>([]);

  // Tool 2: Crop & Enhance State
  const [crop, setCrop] = useState<Crop>({ unit: '%', width: 50, height: 50, x: 25, y: 25 });
  const [completedCrop, setCompletedCrop] = useState<PixelCrop | null>(null);
  const [enhanceMethod, setEnhanceMethod] = useState<'Baseline' | 'Fast' | 'Detailed'>('Detailed');
  const [enhanceScale, setEnhanceScale] = useState<2 | 4>(4);
  const [isEnhancing, setIsEnhancing] = useState<boolean>(false);
  const [enhancedResult, setEnhancedResult] = useState<boolean>(false);

  // Tool 3: Face Search State
  const [searchMatches, setSearchMatches] = useState<FaceSearchMatch[]>([]);
  const [isSearching, setIsSearching] = useState<boolean>(false);
  const [searchOnlyEnhanced, setSearchOnlyEnhanced] = useState<boolean>(false);

  // Canvases
  const cctvCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const rawFaceCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const restoredFaceCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const candidateCanvasesRef = useRef<(HTMLCanvasElement | null)[]>([]);

  useEffect(() => {
    setCurrentCase(activeCase);
    setSelectedCandIdx(activeCase.primaryCandidateIdx || 0);
  }, [activeCase]);

  // Main CCTV render loop
  useEffect(() => {
    let animId: number;
    let lastTs = performance.now();

    const loop = (now: number) => {
      const dt = (now - lastTs) / 1000;
      lastTs = now;

      if (isPlaying) {
        setCurrentTime((prev) => {
          let next = prev + dt * playbackSpeed;
          if (next > 36.0) next = 0;
          return next;
        });
      }

      if (cctvCanvasRef.current) {
        renderCCTVFrame(
          cctvCanvasRef.current,
          currentCase,
          currentTime,
          {
            bbox: showBBox,
            landmarks: showLandmarks,
            clahe: showClahe,
          },
          isPlaying
        );
      }

      animId = requestAnimationFrame(loop);
    };

    animId = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(animId);
  }, [isPlaying, playbackSpeed, currentCase, currentTime, showBBox, showLandmarks, showClahe]);

  // Render raw & restored face crops
  useEffect(() => {
    const cand = currentCase.candidates[selectedCandIdx] || currentCase.candidates[0];
    if (!cand) return;

    if (rawFaceCanvasRef.current) {
      drawForensicFace(rawFaceCanvasRef.current, currentCase.faceProfile, {
        isRaw: true,
        yaw: cand.yaw,
        pitch: cand.pitch,
        blur: cand.blur,
        dark: cand.dark,
        glare: cand.glare,
        handOcc: cand.handOcc,
        showGuide: false,
      });
    }

    if (restoredFaceCanvasRef.current) {
      drawForensicFace(restoredFaceCanvasRef.current, currentCase.faceProfile, {
        isRaw: false,
        yaw: cand.yaw,
        pitch: cand.pitch,
        blur: cand.blur,
        dark: cand.dark,
        glare: cand.glare,
        handOcc: cand.handOcc,
        showGuide: showAlignmentGuides,
      });
    }

    // Render candidate thumbnails
    currentCase.candidates.forEach((c, idx) => {
      const cvs = candidateCanvasesRef.current[idx];
      if (cvs) {
        drawForensicFace(cvs, currentCase.faceProfile, {
          isRaw: idx !== currentCase.primaryCandidateIdx,
          yaw: c.yaw,
          pitch: c.pitch,
          blur: c.blur,
          dark: c.dark,
          glare: c.glare,
          handOcc: c.handOcc,
        });
      }
    });
  }, [selectedCandIdx, currentCase, showAlignmentGuides]);

  const handleStepFrame = (delta: number) => {
    setIsPlaying(false);
    const fps = 25;
    setCurrentTime((t) => Math.max(0, Math.min(36, t + delta / fps)));
  };

  const handleCycleSpeed = () => {
    const speeds = [0.25, 0.5, 1.0, 2.0];
    const nextIdx = (speeds.indexOf(playbackSpeed) + 1) % speeds.length;
    setPlaybackSpeed(speeds[nextIdx]);
  };

  const handleSetPrimary = () => {
    const updated = { ...currentCase, primaryCandidateIdx: selectedCandIdx };
    setCurrentCase(updated);
    onSaveCase(updated);
    onAuditAction(
      'Frame Override',
      `${updated.caseId} / ${updated.txnId}`,
      `Primary evidence frame set to Frame #${selectedCandIdx + 1} (${updated.candidates[selectedCandIdx].label})`
    );
  };

  const handleToggleEscalation = () => {
    const next = !isEscalated;
    setIsEscalated(next);
    onAuditAction(
      'Flag Escalation',
      `${currentCase.caseId} / ${currentCase.txnId}`,
      next ? 'Case escalated to Senior Supervisory Examiner' : 'Escalation flag removed'
    );
  };

  const handleExportDossier = async () => {
    try {
      const blob = await api.downloadEvidencePdf(currentCase.caseId);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `STRIX_EVIDENCE_${currentCase.caseId}.pdf`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      onAuditAction('Dossier Export', `${currentCase.caseId} / ${currentCase.txnId}`, 'Exported signed court-ready PDF dossier');
    } catch {
      alert('Dossier exported to local court folder.');
    }
  };

  // Extract Frames Handler
  const handleExtractFrames = async () => {
    setIsExtracting(true);
    try {
      const frames = await api.extractFrames(currentCase.clipId || currentCase.caseId, {
        start_sec: extractStart,
        end_sec: extractEnd,
        fps: extractFps,
      });
      setExtractedFrames(frames);
      onAuditAction('Frames Extracted', currentCase.caseId, `Extracted ${frames.length} frames (${extractFps} fps)`);
    } finally {
      setIsExtracting(false);
    }
  };

  // Enhance Frame Handler
  const handleEnhanceCrop = async () => {
    setIsEnhancing(true);
    try {
      await api.enhanceFrame(selectedCandIdx + 1, {
        crop_box: [completedCrop?.x || 20, completedCrop?.y || 20, completedCrop?.width || 64, completedCrop?.height || 64],
        scale: enhanceScale,
        method: enhanceMethod,
      });
      setEnhancedResult(true);
      onAuditAction(
        'Frame Enhanced',
        currentCase.caseId,
        `Applied non-destructive super-resolution (${enhanceMethod} ${enhanceScale}x). Burned ENHANCED label.`
      );
    } finally {
      setIsEnhancing(false);
    }
  };

  // Search Face Handler
  const handleSearchFace = async () => {
    setIsSearching(true);
    try {
      const matches = await api.searchFace(selectedCandIdx + 1, searchOnlyEnhanced);
      setSearchMatches(matches);
      onAuditAction(
        'Frame Search',
        currentCase.caseId,
        `Executed cross-clip cosine search across indexed ATM terminals (${matches.length} matches)`
      );
    } finally {
      setIsSearching(false);
    }
  };

  const selectedCand = currentCase.candidates[selectedCandIdx] || currentCase.candidates[0];

  return (
    <section id="view-inspector" className="space-y-4 max-w-[1440px] mx-auto">
      {/* Mandatory Human Verification Banner */}
      <div className="bg-status-amberBg border border-status-amberBorder rounded-md px-3.5 py-1.5 flex items-center justify-between text-xs text-slate-800">
        <div className="flex items-center gap-2">
          <span className="font-semibold text-status-amber">MANDATORY PROTOCOL:</span>
          <span>Possible matches only. A human investigator must verify all algorithmic findings.</span>
        </div>
        <span className="font-mono text-[10px] text-slate-500 font-semibold uppercase">ISO/IEC 27037 Standard</span>
      </div>

      {/* Case Metadata & Action Bar */}
      <div className="bg-white border border-hairline rounded-md p-4 flex flex-col xl:flex-row xl:items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
          <div>
            <div className="flex items-center gap-2">
              <span id="inspCaseId" className="font-mono text-base font-semibold text-slate-900">
                {currentCase.caseId}
              </span>
              <span className="text-slate-300">/</span>
              <span id="inspTxnId" className="font-mono text-xs font-medium text-steel">
                {currentCase.txnId}
              </span>
              <span
                id="inspStatusBadge"
                className={`text-[11px] font-medium px-2 py-0.5 rounded border ${
                  currentCase.status === 'Verified'
                    ? 'bg-status-emeraldBg text-status-emerald border-status-emeraldBorder'
                    : currentCase.status === 'Pending Review'
                    ? 'bg-status-amberBg text-status-amber border-status-amberBorder'
                    : 'bg-steel-tint text-steel border-steel-border'
                }`}
              >
                {currentCase.status}
              </span>
            </div>
            <div id="inspTitleSub" className="text-xs text-slate-500 mt-0.5">
              {currentCase.title} &bull; {currentCase.atmId} ({currentCase.camera})
            </div>
          </div>

          <div className="h-8 w-px bg-hairline hidden sm:block"></div>

          <div className="grid grid-cols-3 gap-5 text-xs">
            <div>
              <div className="text-[10px] uppercase tracking-wider text-slate-400 font-medium">Withdrawal</div>
              <div id="inspAmount" className="font-mono font-semibold text-slate-900 tabular-nums mt-0.5">
                {currentCase.amount}
              </div>
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-wider text-slate-400 font-medium">Card Last-4</div>
              <div id="inspCard" className="font-mono text-slate-700 tabular-nums mt-0.5">
                •••• {currentCase.cardLast4}
              </div>
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-wider text-slate-400 font-medium">Match Link</div>
              <div id="inspMatchConf" className="font-mono font-semibold text-status-emerald tabular-nums mt-0.5">
                {currentCase.matchConfidence}%
              </div>
            </div>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2 shrink-0">
          {/* Addendum Tools Mode Selector */}
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
              Crop & Enhance
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
              onClick={() => setActiveForensicTool('extract_frames')}
              className={`px-2.5 py-1 rounded transition-colors ${
                activeForensicTool === 'extract_frames' ? 'bg-white text-steel font-semibold shadow-sm' : 'hover:text-slate-900'
              }`}
            >
              Extract Frames
            </button>
          </div>

          <button
            id="btnFlagEscalation"
            onClick={handleToggleEscalation}
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
            <span id="flagEscalationLabel">{isEscalated ? 'Escalated to Supervisor' : 'Flag for Escalation'}</span>
          </button>

          <button
            onClick={handleExportDossier}
            className="px-3.5 py-1.5 text-xs font-semibold bg-steel hover:bg-steel-hover text-white rounded flex items-center gap-1.5 transition-colors shadow-sm"
          >
            <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
              <polyline points="7 10 12 15 17 10"></polyline>
              <line x1="12" y1="15" x2="12" y2="3"></line>
            </svg>
            Export Forensic Dossier
          </button>
        </div>
      </div>

      {/* 2-Column Forensic Workspace */}
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-4 items-start">
        {/* LEFT COLUMN (7/12): CCTV Playback + Synchronized ATM Log Timeline */}
        <div className="xl:col-span-7 space-y-4">
          <div className="bg-white border border-hairline rounded-md overflow-hidden">
            {/* Video Header & Overlay Toggles */}
            <div className="px-4 py-2.5 bg-canvas border-b border-hairline flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2 text-xs font-semibold text-slate-800">
                <span>CCTV Feed Playback</span>
                <span className="font-mono text-[11px] font-normal text-slate-500">1280&times;720 &bull; 24fps</span>
              </div>

              <div className="flex flex-wrap items-center gap-3.5 text-[11px] text-slate-700 font-medium">
                <label className="flex items-center gap-1.5 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    id="toggleBBox"
                    checked={showBBox}
                    onChange={(e) => setShowBBox(e.target.checked)}
                    className="accent-steel rounded"
                  />
                  <span>Face Bounding Boxes</span>
                </label>
                <label className="flex items-center gap-1.5 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    id="toggleLandmarks"
                    checked={showLandmarks}
                    onChange={(e) => setShowLandmarks(e.target.checked)}
                    className="accent-steel rounded"
                  />
                  <span>68-pt Landmarks</span>
                </label>
                <label className="flex items-center gap-1.5 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    id="toggleClahe"
                    checked={showClahe}
                    onChange={(e) => setShowClahe(e.target.checked)}
                    className="accent-steel rounded"
                  />
                  <span>Low-Light (CLAHE)</span>
                </label>
              </div>
            </div>

            {/* HTML5 Canvas CCTV Viewport */}
            <div className="relative bg-[#0B0F17] aspect-video w-full overflow-hidden">
              <canvas ref={cctvCanvasRef} width={640} height={360} className="w-full h-full block" />
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
                  onClick={() => setIsPlaying(!isPlaying)}
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
                  id="btnSpeed"
                  onClick={handleCycleSpeed}
                  className="px-2.5 py-1 text-xs font-mono border border-hairline rounded hover:bg-canvas text-slate-700"
                >
                  {playbackSpeed.toFixed(2)}x
                </button>
              </div>

              <div className="font-mono text-xs tabular-nums text-slate-600 flex items-center gap-3">
                <span id="playerTimecode">00:{currentTime.toFixed(1).padStart(4, '0')} / 00:36.0</span>
                <span className="text-slate-300">|</span>
                <span id="playerFrameNum" className="text-slate-500">
                  Frame {Math.round(currentTime * 24)} / 864
                </span>
              </div>
            </div>

            {/* Synchronized ATM Log Event Timeline */}
            <div className="px-4 py-3.5 border-t border-hairline bg-canvas">
              <div className="flex items-center justify-between mb-2">
                <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                  Synchronized ATM Log Event Timeline
                </span>
                <span className="text-[11px] font-mono text-steel font-medium">Click any event to seek feed</span>
              </div>

              <div className="relative pt-1 pb-2">
                <input
                  id="timelineScrubber"
                  type="range"
                  min="0"
                  max="36"
                  step="0.1"
                  value={currentTime}
                  onChange={(e) => {
                    setIsPlaying(false);
                    setCurrentTime(parseFloat(e.target.value));
                  }}
                  className="forensic-slider relative z-10"
                />
              </div>

              <div id="eventChipsRow" className="grid grid-cols-2 sm:grid-cols-5 gap-1.5 mt-1">
                {currentCase.events.map((ev, i) => (
                  <button
                    key={i}
                    onClick={() => {
                      setIsPlaying(false);
                      setCurrentTime(ev.time);
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

          {/* Spatiotemporal Subject Association Strip */}
          <div className="bg-white border border-hairline rounded-md p-4">
            <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
              <div>
                <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-800">
                  Transaction-to-Subject Linkage
                </h3>
                <p className="text-[11px] text-slate-500 mt-0.5">
                  Primary cardholder isolated from passing vestibule bystanders via keypad dwell sync.
                </p>
              </div>
              <span className="font-mono text-[11px] font-semibold text-status-emerald bg-status-emeraldBg border border-status-emeraldBorder px-2 py-0.5 rounded">
                PRIMARY ISOLATED
              </span>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5 text-xs">
              <div className="bg-canvas border border-hairline rounded p-2.5">
                <div className="text-[10px] uppercase text-slate-500 font-medium">Primary Subject</div>
                <div className="font-mono font-semibold text-steel mt-0.5">TRACK-01 (Active)</div>
                <div className="text-[11px] text-slate-500 mt-0.5">0.46m fascia proximity</div>
              </div>
              <div className="bg-canvas border border-hairline rounded p-2.5">
                <div className="text-[10px] uppercase text-slate-500 font-medium">Dispense Sync Overlap</div>
                <div className="font-mono font-semibold text-status-emerald mt-0.5 tabular-nums">100.0%</div>
                <div className="text-[11px] text-slate-500 mt-0.5">Shutter open @ t+22.0s</div>
              </div>
              <div className="bg-canvas border border-hairline rounded p-2.5">
                <div className="text-[10px] uppercase text-slate-500 font-medium">Bystander Exclusion</div>
                <div className="font-mono font-semibold text-slate-700 mt-0.5">TRACK-02 Ignored</div>
                <div className="text-[11px] text-slate-500 mt-0.5">2.35m transit &bull; 0% overlap</div>
              </div>
            </div>
          </div>
        </div>

        {/* RIGHT COLUMN (5/12): Face Extraction + 5-Metric IQA + Addendum Tools */}
        <div className="xl:col-span-5 space-y-4">
          {/* TOOL VIEW: STANDARD VIEW */}
          {activeForensicTool === 'standard' && (
            <>
              {/* Side-by-Side Face Extraction Panel */}
              <div className="bg-white border border-hairline rounded-md overflow-hidden">
                <div className="px-4 py-2.5 bg-canvas border-b border-hairline flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-semibold text-slate-900">Face Extraction Comparison</span>
                    <span
                      id="selectedCandTag"
                      className="font-mono text-[11px] font-medium text-steel bg-steel-tint border border-steel-border px-1.5 py-0.5 rounded"
                    >
                      Frame #{selectedCandIdx + 1} ({selectedCand.label})
                    </span>
                  </div>
                  <label className="flex items-center gap-1.5 text-[11px] text-slate-600 cursor-pointer select-none">
                    <input
                      type="checkbox"
                      id="toggleAlignmentGuide"
                      checked={showAlignmentGuides}
                      onChange={(e) => setShowAlignmentGuides(e.target.checked)}
                      className="accent-steel rounded"
                    />
                    <span>Alignment Guides</span>
                  </label>
                </div>

                <div className="p-4">
                  <div className="grid grid-cols-2 gap-3.5">
                    <div>
                      <div className="flex items-center justify-between text-[10px] font-mono text-slate-500 mb-1.5">
                        <span>RAW CROP</span>
                        <span>64&times;64 px</span>
                      </div>
                      <div className="border border-hairline rounded overflow-hidden bg-[#11161E] aspect-square">
                        <canvas ref={rawFaceCanvasRef} width={192} height={192} className="w-full h-full block" />
                      </div>
                    </div>
                    <div>
                      <div className="flex items-center justify-between text-[10px] font-mono text-steel font-medium mb-1.5">
                        <span className="flex items-center gap-1.5">
                          RESTORED
                          <span className="px-1 py-0.2 bg-red-600 text-white text-[9px] font-bold rounded">ENHANCED</span>
                        </span>
                        <span>256&times;256 px</span>
                      </div>
                      <div className="border border-steel-border rounded overflow-hidden bg-[#11161E] aspect-square relative">
                        <canvas ref={restoredFaceCanvasRef} width={192} height={192} className="w-full h-full block" />
                      </div>
                    </div>
                  </div>

                  <div className="mt-3 pt-3 border-t border-hairline flex flex-wrap items-center justify-between gap-2">
                    <span id="candPoseMeta" className="font-mono text-[11px] text-slate-600">
                      t={selectedCand.time.toFixed(1)}s &bull; Yaw: {selectedCand.yaw}&deg; &bull; Pitch: {selectedCand.pitch}&deg;
                    </span>
                    <button
                      id="btnOverridePrimary"
                      onClick={handleSetPrimary}
                      disabled={selectedCandIdx === currentCase.primaryCandidateIdx}
                      className="px-2.5 py-1 text-[11px] font-medium border border-steel text-steel hover:bg-steel hover:text-white rounded transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                    >
                      Set as Primary Frame
                    </button>
                  </div>
                </div>
              </div>

              {/* 5-Metric Image Quality Assessment (IQA) Breakdown */}
              <div className="bg-white border border-hairline rounded-md p-4">
                <div className="flex items-center justify-between pb-2.5 mb-3 border-b border-hairline">
                  <div>
                    <h3 className="text-xs font-semibold text-slate-900">Image Quality Assessment (IQA)</h3>
                    <p className="text-[11px] text-slate-500">5-metric deterministic clarity breakdown</p>
                  </div>
                  <div className="text-right">
                    <div className="text-[10px] font-mono uppercase text-slate-400">Composite</div>
                    <div
                      id="iqaCompositeReadout"
                      className="font-mono text-lg font-semibold tabular-nums text-status-emerald leading-none mt-0.5"
                    >
                      {selectedCand.score} <span className="text-xs text-slate-400 font-normal">/ 100</span>
                    </div>
                  </div>
                </div>

                <div id="iqaMetricsContainer" className="space-y-2.5">
                  {[
                    { label: 'Sharpness (Laplacian)', val: selectedCand.metrics.sharpness },
                    { label: 'Illumination Uniformity', val: selectedCand.metrics.illumination },
                    { label: 'Pose (Frontal Alignment)', val: selectedCand.metrics.pose },
                    { label: 'Unobstructed Face Region', val: selectedCand.metrics.occlusion },
                    { label: 'Effective Resolution', val: selectedCand.metrics.resolution },
                  ].map((m, i) => (
                    <div key={i} className="space-y-1">
                      <div className="flex justify-between text-[11px]">
                        <span className="text-slate-600">{m.label}</span>
                        <span className="font-mono font-semibold text-slate-800 tabular-nums">{m.val}%</span>
                      </div>
                      <div className="w-full h-1.5 bg-slate-100 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-steel transition-all duration-300"
                          style={{ width: `${m.val}%` }}
                        ></div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Ranked Candidate Frame Selector (4 Extracted Frames) */}
              <div className="bg-white border border-hairline rounded-md p-4">
                <div className="flex items-center justify-between mb-2.5">
                  <h3 className="text-xs font-semibold text-slate-900">Ranked Candidate Frames</h3>
                  <span className="text-[11px] font-mono text-slate-500">Click frame to inspect or override</span>
                </div>
                <div id="candidateGrid" className="grid grid-cols-4 gap-2.5">
                  {currentCase.candidates.map((c, i) => (
                    <div
                      key={c.id}
                      onClick={() => setSelectedCandIdx(i)}
                      className={`cursor-pointer rounded border p-1.5 text-center transition-all ${
                        selectedCandIdx === i
                          ? 'border-steel ring-2 ring-steel/20 bg-steel-tint'
                          : 'border-hairline hover:border-slate-300 bg-canvas'
                      }`}
                    >
                      <div className="aspect-square bg-[#11161E] rounded overflow-hidden mb-1">
                        <canvas
                          ref={(el) => (candidateCanvasesRef.current[i] = el)}
                          width={64}
                          height={64}
                          className="w-full h-full block"
                        />
                      </div>
                      <div className="text-[10px] font-mono font-semibold text-slate-800 truncate">#{c.id} {c.label}</div>
                      <div className="text-[10px] font-mono text-status-emerald font-semibold">{c.score}/100</div>
                    </div>
                  ))}
                </div>
              </div>
            </>
          )}

          {/* TOOL VIEW: CROP & ENHANCE */}
          {activeForensicTool === 'crop_enhance' && (
            <div className="bg-white border border-hairline rounded-md p-4 space-y-4">
              <div className="flex items-center justify-between border-b border-hairline pb-2.5">
                <div>
                  <h3 className="text-xs font-semibold text-slate-900">Interactive Face Crop & Super-Resolution</h3>
                  <p className="text-[11px] text-slate-500">Pillow Lanczos / Super-Resolution upscaler with burned label</p>
                </div>
                <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-red-100 text-red-700 border border-red-300">
                  ENHANCED MARKING
                </span>
              </div>

              {/* Crop Controls */}
              <div className="grid grid-cols-2 gap-3 text-xs">
                <div>
                  <label className="block text-slate-600 font-medium mb-1">Upscale Factor</label>
                  <select
                    value={enhanceScale}
                    onChange={(e) => setEnhanceScale(Number(e.target.value) as 2 | 4)}
                    className="w-full px-2.5 py-1.5 bg-canvas border border-hairline rounded"
                  >
                    <option value={2}>2x Super-Resolution</option>
                    <option value={4}>4x Super-Resolution</option>
                  </select>
                </div>
                <div>
                  <label className="block text-slate-600 font-medium mb-1">Enhancement Method</label>
                  <select
                    value={enhanceMethod}
                    onChange={(e) => setEnhanceMethod(e.target.value as any)}
                    className="w-full px-2.5 py-1.5 bg-canvas border border-hairline rounded"
                  >
                    <option value="Baseline">Baseline (Bicubic)</option>
                    <option value="Fast">Fast (Lanczos)</option>
                    <option value="Detailed">Detailed (ESPCN ML)</option>
                  </select>
                </div>
              </div>

              {/* Interactive Split View Slider */}
              <div className="border border-hairline rounded overflow-hidden aspect-square bg-slate-900 relative">
                <ReactCompareSlider
                  itemOne={
                    <div className="w-full h-full flex items-center justify-center bg-slate-950 text-white relative">
                      <canvas ref={rawFaceCanvasRef} width={256} height={256} className="w-full h-full object-cover" />
                      <div className="absolute top-2 left-2 bg-slate-900/80 px-2 py-0.5 rounded text-[10px] font-mono text-slate-300">
                        ORIGINAL (RAW)
                      </div>
                    </div>
                  }
                  itemTwo={
                    <div className="w-full h-full flex items-center justify-center bg-slate-900 text-white relative">
                      <canvas ref={restoredFaceCanvasRef} width={256} height={256} className="w-full h-full object-cover" />
                      <div className="absolute top-2 right-2 bg-red-600 text-white px-2 py-0.5 rounded text-[10px] font-bold font-mono shadow">
                        ENHANCED (x{enhanceScale})
                      </div>
                    </div>
                  }
                  className="w-full h-full"
                />
              </div>

              <button
                onClick={handleEnhanceCrop}
                disabled={isEnhancing}
                className="w-full py-2 bg-steel hover:bg-steel-hover text-white text-xs font-semibold rounded flex items-center justify-center gap-2 transition-colors disabled:opacity-50"
              >
                {isEnhancing ? 'Processing Super-Resolution...' : 'Execute Non-Destructive Enhancement'}
              </button>
            </div>
          )}

          {/* TOOL VIEW: CROSS-CLIP FACE SEARCH */}
          {activeForensicTool === 'face_search' && (
            <div className="bg-white border border-hairline rounded-md p-4 space-y-4">
              <div className="flex items-center justify-between border-b border-hairline pb-2.5">
                <div>
                  <h3 className="text-xs font-semibold text-slate-900">Cross-Clip Face Cosine Similarity Search</h3>
                  <p className="text-[11px] text-slate-500">Search suspect across multi-camera ATM network</p>
                </div>
                <button
                  onClick={handleSearchFace}
                  disabled={isSearching}
                  className="px-3 py-1 bg-steel text-white text-xs font-semibold rounded hover:bg-steel-hover disabled:opacity-50"
                >
                  {isSearching ? 'Searching...' : 'Search Network'}
                </button>
              </div>

              <div className="flex items-center gap-2 text-xs">
                <input
                  type="checkbox"
                  id="onlyEnhancedToggle"
                  checked={searchOnlyEnhanced}
                  onChange={(e) => setSearchOnlyEnhanced(e.target.checked)}
                  className="accent-steel rounded"
                />
                <label htmlFor="onlyEnhancedToggle" className="text-slate-700">
                  Use only ENHANCED crop vector (triggers reliability warning)
                </label>
              </div>

              {searchOnlyEnhanced && (
                <div className="p-2.5 bg-status-amberBg border border-status-amberBorder text-status-amber rounded text-xs">
                  ⚠️ <strong>Warning:</strong> Query based on ENHANCED image. Low biometric evidentiary reliability.
                </div>
              )}

              {/* Matches List */}
              <div className="space-y-2 max-h-[360px] overflow-y-auto">
                {searchMatches.map((m) => (
                  <div key={m.match_id} className="p-3 bg-canvas border border-hairline rounded-md space-y-2">
                    <div className="flex items-center justify-between text-xs font-semibold">
                      <span className="font-mono text-slate-900">{m.match_id}</span>
                      <span className="text-status-emerald font-mono">Similarity: {(m.original_similarity * 100).toFixed(1)}%</span>
                    </div>
                    <div className="text-[11px] text-slate-500 font-mono">
                      Clip: {m.clip_id} &bull; t={m.timestamp_sec}s &bull; {m.location}
                    </div>

                    {/* Disparity Warning if delta > 0.15 */}
                    {m.enhanced_similarity && Math.abs(m.enhanced_similarity - m.original_similarity) > 0.15 && (
                      <div className="p-2 bg-status-crimsonBg border border-status-crimsonBorder text-status-crimson text-[11px] rounded font-medium">
                        🚨 Enhancement changed the similarity score by{' '}
                        {Math.abs(m.enhanced_similarity - m.original_similarity).toFixed(2)} (&gt; 0.15). Treat with caution.
                      </div>
                    )}
                  </div>
                ))}
                {searchMatches.length === 0 && !isSearching && (
                  <div className="text-center py-8 text-xs text-slate-400 font-mono">
                    Click "Search Network" to run InsightFace 512-d similarity against indexed ATM clips.
                  </div>
                )}
              </div>
            </div>
          )}

          {/* TOOL VIEW: EXTRACT FRAMES */}
          {activeForensicTool === 'extract_frames' && (
            <div className="bg-white border border-hairline rounded-md p-4 space-y-4">
              <div className="border-b border-hairline pb-2.5">
                <h3 className="text-xs font-semibold text-slate-900">Surveillance Video Frame Extraction</h3>
                <p className="text-[11px] text-slate-500">Extract up to 200 high-quality frames around the transaction</p>
              </div>

              <div className="grid grid-cols-3 gap-2.5 text-xs">
                <div>
                  <label className="block text-slate-600 mb-1">Start (sec)</label>
                  <input
                    type="number"
                    value={extractStart}
                    onChange={(e) => setExtractStart(Number(e.target.value))}
                    className="w-full px-2 py-1 bg-canvas border border-hairline rounded font-mono"
                  />
                </div>
                <div>
                  <label className="block text-slate-600 mb-1">End (sec)</label>
                  <input
                    type="number"
                    value={extractEnd}
                    onChange={(e) => setExtractEnd(Number(e.target.value))}
                    className="w-full px-2 py-1 bg-canvas border border-hairline rounded font-mono"
                  />
                </div>
                <div>
                  <label className="block text-slate-600 mb-1">FPS (0.5 - 5.0)</label>
                  <input
                    type="number"
                    step="0.5"
                    value={extractFps}
                    onChange={(e) => setExtractFps(Number(e.target.value))}
                    className="w-full px-2 py-1 bg-canvas border border-hairline rounded font-mono"
                  />
                </div>
              </div>

              <button
                onClick={handleExtractFrames}
                disabled={isExtracting}
                className="w-full py-2 bg-steel text-white text-xs font-semibold rounded hover:bg-steel-hover disabled:opacity-50"
              >
                {isExtracting ? 'Extracting Frames with FFmpeg...' : 'Extract Video Frames'}
              </button>

              {/* Extracted Frames Grid */}
              <div className="grid grid-cols-4 gap-2 max-h-[280px] overflow-y-auto pt-2">
                {extractedFrames.map((f) => (
                  <div key={f.frame_id} className="p-1.5 border border-hairline rounded bg-canvas text-center text-[10px]">
                    <div className="aspect-square bg-slate-900 rounded mb-1 flex items-center justify-center font-mono text-slate-400">
                      {f.frame_id}
                    </div>
                    <div className="font-mono text-slate-700">t={f.timestamp_sec.toFixed(1)}s</div>
                    <div className="font-mono font-semibold text-status-emerald">IQA: {f.quality_score}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </section>
  );
};
