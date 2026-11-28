import React, { useState, useEffect, useRef, useMemo } from 'react';
import { RunResult, ClipOut, Frame, PublicConfig } from '@/types/forensic';
import { api, getMediaUrl } from '@/lib/api';

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
  // Best frames in exact API order
  const bestFrames: Frame[] = runResult?.best_frames || [];
  const [selectedFrameIdx, setSelectedFrameIdx] = useState<number>(0);
  const activeFrame: Frame | undefined = bestFrames[selectedFrameIdx] || bestFrames[0];

  // Video playback transport
  const [isPlaying, setIsPlaying] = useState<boolean>(false);
  const [currentTime, setCurrentTime] = useState<number>(0);
  const [playbackSpeed, setPlaybackSpeed] = useState<number>(1.0);
  const videoRef = useRef<HTMLVideoElement | null>(null);

  // ATM Zone overlay state
  const [showZoneOverlay, setShowZoneOverlay] = useState<boolean>(true);
  const [zonePolygon, setZonePolygon] = useState<[number, number][] | null>(
    clip?.zone_polygon_norm || null
  );

  // Evidence frame selection
  const [selectedFrameIds, setSelectedFrameIds] = useState<(string | number)[]>(
    runResult?.selected_frame_ids || (bestFrames.length > 0 ? [bestFrames[0].frame_id] : [])
  );
  const [isUpdatingSelection, setIsUpdatingSelection] = useState<boolean>(false);

  const runId = runResult?.run_id || 'run_pending';
  const evidenceId = `EV-${runId}`;

  // Fetch ATM zone polygon if not provided directly on the clip
  useEffect(() => {
    if (clip?.zone_polygon_norm && clip.zone_polygon_norm.length >= 3) {
      setZonePolygon(clip.zone_polygon_norm);
    } else {
      api
        .getZones()
        .then((zones) => {
          if (zones && zones.length > 0) {
            const matched = zones.find((z) => z.id === clip?.atm_id) || zones[0];
            if (matched && matched.polygon && matched.polygon.length >= 3) {
              setZonePolygon(matched.polygon);
            }
          }
        })
        .catch((err) => {
          console.warn('Could not fetch ATM zone polygon:', err);
        });
    }
  }, [clip?.id, clip?.zone_polygon_norm, clip?.atm_id]);

  // Keep selected frame index and selected IDs in sync when run changes
  useEffect(() => {
    setSelectedFrameIdx(0);
    if (runResult?.selected_frame_ids && runResult.selected_frame_ids.length > 0) {
      setSelectedFrameIds(runResult.selected_frame_ids);
    } else if (runResult?.best_frames && runResult.best_frames.length > 0) {
      setSelectedFrameIds([runResult.best_frames[0].frame_id]);
    } else {
      setSelectedFrameIds([]);
    }
    // Seek to first best frame timestamp if available
    if (runResult?.best_frames && runResult.best_frames.length > 0) {
      const firstTs = runResult.best_frames[0].timestamp_sec;
      setCurrentTime(firstTs);
      if (videoRef.current) {
        videoRef.current.currentTime = firstTs;
      }
    }
  }, [runResult?.run_id]);

  // Handle video time updates
  const handleTimeUpdate = () => {
    if (videoRef.current) {
      setCurrentTime(videoRef.current.currentTime);
    }
  };

  const handleStepFrame = (delta: number) => {
    const fps = clip?.fps || 25;
    if (videoRef.current) {
      const newTime = Math.max(0, videoRef.current.currentTime + delta / fps);
      videoRef.current.currentTime = newTime;
      setCurrentTime(newTime);
    } else {
      setCurrentTime((prev) => Math.max(0, prev + delta / fps));
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

  // Seek video when clicking any frame card
  const handleSeekToFrame = (timestampSec: number, frameIdx: number) => {
    setSelectedFrameIdx(frameIdx);
    setCurrentTime(timestampSec);
    if (videoRef.current) {
      videoRef.current.currentTime = timestampSec;
    }
  };

  // Toggle selection for official court evidence (POST /runs/{run_id}/selection)
  const handleToggleFrameEvidence = async (frameId: string | number) => {
    const nextIds = selectedFrameIds.includes(frameId)
      ? selectedFrameIds.filter((id) => id !== frameId)
      : [...selectedFrameIds, frameId];

    setSelectedFrameIds(nextIds);
    setIsUpdatingSelection(true);
    try {
      await api.updateSelection(runId, nextIds);
      onAuditAction(
        'SELECTION_UPDATE',
        evidenceId,
        `Updated selected candidate frames: [${nextIds.join(', ')}]`
      );
    } catch (err) {
      console.error('Failed to update evidence selection on server:', err);
    } finally {
      setIsUpdatingSelection(false);
    }
  };

  // Convert ATM zone polygon to SVG polygon points (supports 0..1 normalized or 0..100)
  const svgPoints = useMemo(() => {
    if (!zonePolygon || zonePolygon.length < 3) return '';
    const maxVal = Math.max(...zonePolygon.flat());
    const factor = maxVal <= 1.0 ? 100 : 1;
    return zonePolygon
      .map(([x, y]) => `${(x * factor).toFixed(2)},${(y * factor).toFixed(2)}`)
      .join(' ');
  }, [zonePolygon]);

  // Timeline & Transaction Window Calculations
  const timelineData = useMemo(() => {
    const duration = clip?.duration_sec && clip.duration_sec > 0 ? clip.duration_sec : 30;
    let txOffset: number | null = null;

    if (runResult?.coverage_start_sec != null && runResult?.coverage_end_sec != null) {
      txOffset = (runResult.coverage_start_sec + runResult.coverage_end_sec) / 2;
    } else if (runResult?.transaction_time && clip?.clip_start_time) {
      try {
        const txMs = new Date(runResult.transaction_time).getTime();
        const clipStartMs = new Date(clip.clip_start_time).getTime();
        if (!isNaN(txMs) && !isNaN(clipStartMs)) {
          const diff = (txMs - clipStartMs) / 1000;
          if (diff >= 0 && diff <= duration + 60) {
            txOffset = diff;
          }
        }
      } catch {
        // Ignore date parse issues
      }
    }

    const windowHalf = 10; // Default ±10s window if exact bounds absent
    let winStart = runResult?.coverage_start_sec ?? null;
    let winEnd = runResult?.coverage_end_sec ?? null;

    if (winStart == null && txOffset != null) {
      winStart = Math.max(0, txOffset - windowHalf);
    }
    if (winEnd == null && txOffset != null) {
      winEnd = Math.min(duration, txOffset + windowHalf);
    }

    const winLeftPct =
      winStart != null ? Math.max(0, Math.min(100, (winStart / duration) * 100)) : null;
    const winWidthPct =
      winStart != null && winEnd != null
        ? Math.max(0, Math.min(100 - (winLeftPct || 0), ((winEnd - winStart) / duration) * 100))
        : null;
    const txPinPct =
      txOffset != null ? Math.max(0, Math.min(100, (txOffset / duration) * 100)) : null;

    return {
      duration,
      txOffset,
      winStart,
      winEnd,
      winLeftPct,
      winWidthPct,
      txPinPct,
    };
  }, [
    clip?.duration_sec,
    clip?.clip_start_time,
    runResult?.transaction_time,
    runResult?.coverage_start_sec,
    runResult?.coverage_end_sec,
  ]);

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

  return (
    <section id="view-case-inspector" className="space-y-4 max-w-[1440px] mx-auto pb-12">
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
      <div className="bg-status-amberBg border border-status-amberBorder rounded-md px-3.5 py-2.5 flex flex-col sm:flex-row sm:items-center justify-between gap-2 text-xs text-slate-800">
        <div className="flex items-center gap-2">
          <span className="font-semibold text-status-amber shrink-0">MANDATORY PROTOCOL:</span>
          <span className="font-medium">
            Possible matches only. A human investigator must verify every result.
          </span>
        </div>
        <span className="font-mono text-[10px] text-slate-500 font-semibold uppercase shrink-0">
          ISO/IEC 27037 Standard
        </span>
      </div>

      {/* 4. Link Low Margin Warning */}
      {runResult?.link_low_margin && (
        <div className="bg-status-crimsonBg border border-status-crimsonBorder rounded-md px-3.5 py-2.5 flex items-center gap-2.5 text-xs text-status-crimson font-medium">
          <svg className="w-4 h-4 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path>
            <line x1="12" y1="9" x2="12" y2="13"></line>
            <line x1="12" y1="17" x2="12.01" y2="17"></line>
          </svg>
          <span>
            Warning: Narrow margin between candidate tracks. Human verification required.
          </span>
        </div>
      )}

      {/* 5. Warnings and Coverage Notice */}
      {runResult?.warnings && runResult.warnings.length > 0 && (
        <div className="bg-canvas border border-hairline rounded-md p-3 text-xs space-y-1">
          {runResult.warnings.map((w, idx) => (
            <div key={idx} className="flex items-center gap-2 text-amber-700 font-medium">
              <span>⚠ {w}</span>
            </div>
          ))}
        </div>
      )}

      {/* Dossier Header */}
      <div className="bg-white border border-hairline rounded-md p-4 flex flex-col md:flex-row md:items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
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
            <span className="font-mono text-xs font-medium text-steel truncate max-w-[220px]">
              {clip?.original_filename || 'Surveillance Clip'}
            </span>
          </div>
          <div className="text-xs text-slate-500">
            ATM: <span className="font-mono text-slate-700 font-semibold">{clip?.atm_id || 'N/A'}</span> &bull;{' '}
            Tx Time: <span className="font-mono text-slate-700">{runResult?.transaction_time || 'N/A'}</span> &bull;{' '}
            Duration: <span className="font-mono text-slate-700">{timelineData.duration.toFixed(1)}s</span>
          </div>
        </div>

        <div className="flex items-center gap-3 shrink-0">
          <span className="text-xs text-slate-500 font-mono">
            {bestFrames.length} candidate frame{bestFrames.length !== 1 ? 's' : ''}
          </span>
          {isUpdatingSelection && (
            <span className="text-[11px] text-steel font-mono animate-pulse">
              Saving selection...
            </span>
          )}
        </div>
      </div>

      {/* Link Panel: Spatiotemporal Subject Association */}
      <div className="bg-white border border-hairline rounded-md p-4">
        <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
          <div>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-800">
              Spatiotemporal Subject Association
            </h3>
            <p className="text-[11px] text-slate-500 mt-0.5">
              Correlation between surveillance camera tracking and ATM transaction window
            </p>
          </div>
          <span
            className={`font-mono text-[11px] font-semibold px-2.5 py-0.5 rounded border uppercase ${getReliabilityBadge(
              runResult?.link_confidence || 'Medium'
            )}`}
          >
            LINK CONFIDENCE: {runResult?.link_confidence || 'NOT ASSESSED'}
          </span>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-4 gap-3 text-xs">
          <div className="bg-canvas border border-hairline rounded p-3">
            <div className="text-[10px] uppercase text-slate-500 font-medium">Assigned Subject</div>
            <div className="font-mono font-semibold text-steel text-sm mt-0.5">
              {runResult?.person_track_id !== null && runResult?.person_track_id !== undefined
                ? `TRACK #${runResult.person_track_id}`
                : 'Unassigned'}
            </div>
            <div className="text-[11px] text-slate-500 mt-0.5">
              {runResult?.person_track_id !== null ? 'ATM standing zone correlation' : 'No track linked'}
            </div>
          </div>

          <div className="bg-canvas border border-hairline rounded p-3">
            <div className="text-[10px] uppercase text-slate-500 font-medium">Link Reason</div>
            <div className="font-mono font-semibold text-slate-800 mt-0.5 truncate" title={runResult?.link_reason || 'N/A'}>
              {runResult?.link_reason || 'No linking reason provided'}
            </div>
            <div className="text-[11px] text-slate-500 mt-0.5">
              Margin: {runResult?.link_low_margin ? 'Narrow margin ⚠' : 'Robust separation'}
            </div>
          </div>

          <div className="bg-canvas border border-hairline rounded p-3">
            <div className="text-[10px] uppercase text-slate-500 font-medium">Coverage Window</div>
            <div className="font-mono font-semibold text-slate-800 mt-0.5">
              {timelineData.winStart != null && timelineData.winEnd != null
                ? `t+${timelineData.winStart.toFixed(1)}s to t+${timelineData.winEnd.toFixed(1)}s`
                : 'Full recording'}
            </div>
            <div className="text-[11px] text-slate-500 mt-0.5">
              Sampling interval
            </div>
          </div>

          <div className="bg-canvas border border-hairline rounded p-3">
            <div className="text-[10px] uppercase text-slate-500 font-medium">Footage Integrity</div>
            <div className="font-mono text-[10px] text-slate-700 mt-0.5 truncate" title={clip?.sha256}>
              {clip?.sha256 ? `${clip.sha256.substring(0, 16)}...` : 'SHA-256 pending'}
            </div>
            <div className="text-[11px] text-slate-500 mt-0.5">
              Cryptographically verified
            </div>
          </div>
        </div>
      </div>

      {/* Video Surveillance Player & Synchronized Timeline */}
      <div className="bg-white border border-hairline rounded-md overflow-hidden">
        {/* Video Header & Controls */}
        <div className="px-4 py-2.5 bg-canvas border-b border-hairline flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2 text-xs font-semibold text-slate-800">
            <span>CCTV Surveillance Feed</span>
            <span className="font-mono text-[11px] font-normal text-slate-500">
              {clip ? `${clip.width}×${clip.height} • ${clip.fps || 25}fps` : 'Stream ready'}
            </span>
          </div>

          <div className="flex items-center gap-3 text-[11px] text-slate-700 font-medium">
            <label className="flex items-center gap-1.5 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={showZoneOverlay}
                onChange={(e) => setShowZoneOverlay(e.target.checked)}
                className="accent-steel rounded"
              />
              <span>ATM Zone Overlay</span>
            </label>
          </div>
        </div>

        {/* Video Viewport with SVG ATM Zone Overlay */}
        <div className="relative bg-[#0B0F17] aspect-video w-full overflow-hidden flex items-center justify-center">
          {clip?.video_url ? (
            <video
              ref={videoRef}
              src={getMediaUrl(clip.video_url)}
              controls
              onTimeUpdate={handleTimeUpdate}
              className="w-full h-full object-contain"
            />
          ) : activeFrame?.frame_path || activeFrame?.image_url ? (
            <img
              src={getMediaUrl(activeFrame.frame_path || activeFrame.image_url || activeFrame.signed_frame_url)}
              alt="Active Frame View"
              className="w-full h-full object-contain"
            />
          ) : (
            <div className="text-slate-400 font-mono text-xs flex flex-col items-center gap-2">
              <svg className="w-8 h-8 opacity-40" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <rect x="2" y="4" width="20" height="14" rx="2"></rect>
                <polygon points="10 8 16 11 10 14 10 8"></polygon>
              </svg>
              <span>No CCTV video stream attached</span>
            </div>
          )}

          {/* SVG ATM Zone Polygon Overlay (Normalized Coordinates) */}
          {showZoneOverlay && svgPoints && (
            <svg
              className="absolute inset-0 w-full h-full pointer-events-none z-10"
              viewBox="0 0 100 100"
              preserveAspectRatio="none"
            >
              <polygon
                points={svgPoints}
                fill="rgba(2, 132, 199, 0.22)"
                stroke="#0284c7"
                strokeWidth="1.2"
                strokeDasharray="3 2"
              />
              {zonePolygon && zonePolygon.length > 0 && (
                <text
                  x={(zonePolygon[0][0] <= 1 ? zonePolygon[0][0] * 100 : zonePolygon[0][0]).toFixed(1)}
                  y={Math.max(
                    4,
                    (zonePolygon[0][1] <= 1 ? zonePolygon[0][1] * 100 : zonePolygon[0][1]) - 2
                  ).toFixed(1)}
                  fill="#0284c7"
                  fontSize="3.2"
                  fontWeight="bold"
                  fontFamily="monospace"
                >
                  ATM ZONE {clip?.atm_id ? `(${clip.atm_id})` : ''}
                </text>
              )}
            </svg>
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
              title="Playback Speed"
            >
              {playbackSpeed.toFixed(2)}x
            </button>
          </div>

          <div className="font-mono text-xs tabular-nums text-slate-600 flex items-center gap-3">
            <span id="playerTimecode">
              t={currentTime.toFixed(2)}s / {timelineData.duration.toFixed(2)}s
            </span>
            <span className="text-slate-300">|</span>
            <span id="playerFrameNum" className="text-slate-500">
              Frame #{activeFrame?.frame_id || Math.round(currentTime * (clip?.fps || 25))}
            </span>
          </div>
        </div>

        {/* Synchronized Timeline & Transaction Window Marker */}
        <div className="px-4 py-3 border-t border-hairline bg-canvas space-y-2">
          <div className="flex items-center justify-between text-[11px]">
            <span className="font-semibold uppercase tracking-wider text-slate-600">
              Surveillance Timeline &bull; Transaction Window
            </span>
            <span className="font-mono text-slate-500">
              Click frame marker or card below to seek
            </span>
          </div>

          {/* Interactive Timeline Track with Window & Markers */}
          <div className="relative pt-2 pb-2">
            {/* Base timeline bar */}
            <div className="relative h-6 bg-slate-200 rounded overflow-hidden border border-slate-300">
              {/* Highlighted Transaction Window (±window) */}
              {timelineData.winLeftPct !== null && timelineData.winWidthPct !== null && (
                <div
                  className="absolute top-0 bottom-0 bg-amber-300/60 border-x-2 border-amber-500 flex items-center justify-center text-[9px] font-mono font-bold text-amber-900 pointer-events-none"
                  style={{
                    left: `${timelineData.winLeftPct}%`,
                    width: `${timelineData.winWidthPct}%`,
                  }}
                  title={`Transaction Window: t+${timelineData.winStart?.toFixed(1)}s to t+${timelineData.winEnd?.toFixed(1)}s`}
                >
                  <span className="truncate px-1">
                    TX WINDOW ({timelineData.winStart?.toFixed(0)}s–{timelineData.winEnd?.toFixed(0)}s)
                  </span>
                </div>
              )}

              {/* Exact Transaction Center Pin */}
              {timelineData.txPinPct !== null && (
                <div
                  className="absolute top-0 bottom-0 w-0.5 bg-red-600 z-10 pointer-events-none"
                  style={{ left: `${timelineData.txPinPct}%` }}
                  title={`Transaction Event: t+${timelineData.txOffset?.toFixed(1)}s`}
                >
                  <span className="absolute -top-3.5 -translate-x-1/2 text-[9px] font-mono font-bold bg-red-600 text-white px-1 rounded-sm">
                    TX
                  </span>
                </div>
              )}

              {/* Best Frames Markers on Timeline */}
              {bestFrames.map((frame, i) => {
                const pct = Math.max(
                  0,
                  Math.min(100, (frame.timestamp_sec / timelineData.duration) * 100)
                );
                const isSelected = selectedFrameIdx === i;
                return (
                  <button
                    key={frame.frame_id}
                    onClick={() => handleSeekToFrame(frame.timestamp_sec, i)}
                    style={{ left: `${pct}%` }}
                    className={`absolute top-0 bottom-0 w-1.5 -translate-x-1/2 z-20 transition-all ${
                      isSelected
                        ? 'bg-steel ring-2 ring-steel/50'
                        : 'bg-emerald-600 hover:bg-emerald-700'
                    }`}
                    title={`Seek to Frame #${frame.frame_id} (t=${frame.timestamp_sec.toFixed(2)}s)`}
                  />
                );
              })}

              {/* Current Playhead */}
              <div
                className="absolute top-0 bottom-0 w-1 bg-slate-900 -translate-x-1/2 z-30 pointer-events-none shadow"
                style={{
                  left: `${Math.max(
                    0,
                    Math.min(100, (currentTime / timelineData.duration) * 100)
                  )}%`,
                }}
              />
            </div>

            {/* Range Scrubber */}
            <input
              type="range"
              min="0"
              max={timelineData.duration}
              step="0.04"
              value={currentTime}
              onChange={(e) => {
                const t = parseFloat(e.target.value);
                setCurrentTime(t);
                if (videoRef.current) videoRef.current.currentTime = t;
              }}
              className="forensic-slider w-full mt-1.5"
            />
          </div>

          <div className="flex items-center justify-between text-[10px] font-mono text-slate-500">
            <span>0.0s</span>
            {timelineData.txOffset !== null && (
              <span className="text-red-700 font-semibold">
                Transaction Event: t+{timelineData.txOffset.toFixed(1)}s
              </span>
            )}
            <span>{timelineData.duration.toFixed(1)}s</span>
          </div>
        </div>
      </div>

      {/* Best Frames Section (in exact API order) */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-sm font-semibold text-slate-900">
              Ranked Candidate Face Frames
            </h3>
            <p className="text-xs text-slate-500">
              Extracted surveillance frames in deterministic quality ranking order. Click any card to seek video.
            </p>
          </div>
          <span className="text-xs font-mono text-slate-500">
            {bestFrames.length} candidate frame{bestFrames.length !== 1 ? 's' : ''} extracted
          </span>
        </div>

        {/* Empty State: If best_frames is empty, display selection_reason or link_reason in plain words */}
        {bestFrames.length === 0 ? (
          <div className="bg-canvas border border-hairline rounded-md p-6 text-center space-y-2.5">
            <div className="w-12 h-12 rounded-full bg-slate-100 border border-slate-200 flex items-center justify-center mx-auto text-slate-400">
              <svg className="w-6 h-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                <circle cx="12" cy="12" r="10" />
                <line x1="12" y1="8" x2="12" y2="12" />
                <line x1="12" y1="16" x2="12.01" y2="16" />
              </svg>
            </div>
            <div className="space-y-1 max-w-lg mx-auto">
              <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-800">
                Surveillance Extraction Advisory
              </h4>
              <p className="text-xs text-slate-700 font-mono bg-white p-3 rounded border border-hairline">
                {runResult?.selection_reason ||
                  runResult?.link_reason ||
                  'No candidate face frames met the clarity and frontal orientation threshold in this surveillance window.'}
              </p>
              <p className="text-[11px] text-slate-500 pt-1">
                This is a normal forensic result when lighting, obstruction, or camera angle prevents isolated facial extraction.
              </p>
            </div>
          </div>
        ) : (
          /* Cards Grid in API Order */
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {bestFrames.map((frame, index) => {
              const isSelected = selectedFrameIdx === index;
              const isIncludedInEvidence = selectedFrameIds.includes(frame.frame_id);
              const cropImgUrl = getMediaUrl(
                frame.crop_url ||
                  frame.signed_crop_url ||
                  frame.frame_url ||
                  frame.signed_frame_url ||
                  frame.image_url
              );

              return (
                <div
                  key={frame.frame_id}
                  onClick={() => handleSeekToFrame(frame.timestamp_sec, index)}
                  className={`bg-white rounded-md border p-3.5 space-y-3 cursor-pointer transition-all ${
                    isSelected
                      ? 'border-steel ring-2 ring-steel/20 shadow-md'
                      : 'border-hairline hover:border-slate-300 shadow-sm'
                  }`}
                >
                  {/* Card Header: Rank, Frame ID & Reliability Badge */}
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-xs font-bold text-steel bg-steel-tint border border-steel-border px-1.5 py-0.5 rounded">
                        Rank #{index + 1}
                      </span>
                      <span className="font-mono text-xs text-slate-600">
                        Frame #{frame.frame_id}
                      </span>
                    </div>

                    <span
                      className={`text-[10px] font-mono font-bold px-2 py-0.5 rounded border uppercase ${getReliabilityBadge(
                        frame.reliability
                      )}`}
                    >
                      {frame.reliability || 'Unrated'}
                    </span>
                  </div>

                  {/* Image Preview & Timestamp */}
                  <div className="flex gap-3 items-center">
                    <div className="w-24 h-24 bg-[#11161E] rounded overflow-hidden border border-hairline shrink-0 flex items-center justify-center">
                      {cropImgUrl ? (
                        <img
                          src={cropImgUrl}
                          alt={`Candidate Frame ${frame.frame_id}`}
                          className="w-full h-full object-cover"
                        />
                      ) : (
                        <div className="text-slate-500 font-mono text-[10px] text-center p-1">
                          No preview
                        </div>
                      )}
                    </div>

                    <div className="space-y-1.5 flex-1 min-w-0">
                      <div>
                        <div className="text-[10px] uppercase text-slate-400 font-medium">Quality Score</div>
                        <div className="font-mono text-base font-semibold text-status-emerald tabular-nums">
                          {frame.quality_score !== undefined
                            ? (frame.quality_score > 1
                                ? frame.quality_score / 100
                                : frame.quality_score
                              ).toFixed(2)
                            : 'N/A'}{' '}
                          <span className="text-[10px] text-slate-400 font-normal">
                            ({Math.round(
                              frame.quality_score > 1
                                ? frame.quality_score
                                : frame.quality_score * 100
                            )}/100)
                          </span>
                        </div>
                      </div>

                      <div className="text-xs font-mono text-slate-600">
                        t={frame.timestamp_sec.toFixed(2)}s
                      </div>

                      <div className="text-[10px] text-steel font-medium flex items-center gap-1">
                        <span>▶</span>
                        <span>Click to seek video</span>
                      </div>
                    </div>
                  </div>

                  {/* Dynamic Open Flags Tags (Never hard-coded list) */}
                  <div>
                    <div className="text-[10px] uppercase font-semibold text-slate-400 mb-1">
                      Reliability Flags
                    </div>
                    {frame.flags && frame.flags.length > 0 ? (
                      <div className="flex flex-wrap gap-1">
                        {frame.flags.map((flag, flagIdx) => (
                          <span
                            key={flagIdx}
                            className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-700 border border-slate-200"
                          >
                            {flag}
                          </span>
                        ))}
                      </div>
                    ) : (
                      <span className="text-[10px] text-slate-400 italic">No flags reported</span>
                    )}
                  </div>

                  {/* 5-Metric IQA Breakdown */}
                  {frame.metrics && (
                    <div className="bg-canvas border border-hairline rounded p-2 text-[10px] font-mono space-y-1">
                      <div className="grid grid-cols-5 gap-1 text-center">
                        <div>
                          <span className="text-slate-400 block text-[9px] uppercase">Sharp</span>
                          <span className="font-semibold text-slate-700">
                            {frame.metrics.sharpness?.toFixed(0) ?? 'N/A'}
                          </span>
                        </div>
                        <div>
                          <span className="text-slate-400 block text-[9px] uppercase">Size</span>
                          <span className="font-semibold text-slate-700">
                            {frame.metrics.face_size ? `${frame.metrics.face_size}px` : 'N/A'}
                          </span>
                        </div>
                        <div>
                          <span className="text-slate-400 block text-[9px] uppercase">Yaw</span>
                          <span className="font-semibold text-slate-700">
                            {frame.metrics.pose_yaw !== undefined
                              ? `${frame.metrics.pose_yaw.toFixed(0)}°`
                              : 'N/A'}
                          </span>
                        </div>
                        <div>
                          <span className="text-slate-400 block text-[9px] uppercase">Illum</span>
                          <span className="font-semibold text-slate-700">
                            {frame.metrics.illumination?.toFixed(0) ?? 'N/A'}
                          </span>
                        </div>
                        <div>
                          <span className="text-slate-400 block text-[9px] uppercase">Occl</span>
                          <span className="font-semibold text-slate-700">
                            {frame.metrics.occlusion?.toFixed(0) ?? 'N/A'}
                          </span>
                        </div>
                      </div>
                    </div>
                  )}

                  {/* "Select for Evidence" Checkbox per Frame */}
                  <div
                    className="pt-2 border-t border-hairline flex items-center justify-between"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <label className="flex items-center gap-2 cursor-pointer text-xs font-medium text-slate-700 select-none">
                      <input
                        type="checkbox"
                        checked={isIncludedInEvidence}
                        onChange={() => handleToggleFrameEvidence(frame.frame_id)}
                        className="accent-steel rounded"
                      />
                      <span>Select for evidence</span>
                    </label>

                    {isIncludedInEvidence && (
                      <span className="text-[10px] font-mono font-bold text-steel bg-steel-tint px-1.5 py-0.5 rounded">
                        EVIDENTIARY
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
};
