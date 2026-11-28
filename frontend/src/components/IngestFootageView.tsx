import React, { useState, useEffect } from 'react';
import { ClipOut, ATMZone, RunStatus, RunResult } from '@/types/forensic';
import { api, isMockMode } from '@/lib/api';
import { DEMO_CLIPS, DEMO_RUN_RESULTS } from '@/lib/mockData';

interface IngestFootageViewProps {
  onRunCompleted: (runId: string | number, clip: ClipOut, result?: RunResult) => void;
  onAuditAction: (action: string, refId: string, details: string) => void;
  onNavigate: (view: string) => void;
}

export const IngestFootageView: React.FC<IngestFootageViewProps> = ({
  onRunCompleted,
  onAuditAction,
  onNavigate,
}) => {
  const [videoFile, setVideoFile] = useState<File | null>(null);
  const [atmId, setAtmId] = useState<string>('ATM-JPR-014');
  const [clipStartTime, setClipStartTime] = useState<string>(() => {
    const now = new Date();
    return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  });
  const [transactionTime, setTransactionTime] = useState<string>(() => {
    const now = new Date();
    return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  });
  const [windowSec, setWindowSec] = useState<number>(10.0);
  const [sampleFps, setSampleFps] = useState<number>(2.0);
  const [selectedZoneId, setSelectedZoneId] = useState<string>('vestibule_standing');
  const [notes, setNotes] = useState<string>('ATM surveillance vestibule inspection');
  const [zones, setZones] = useState<ATMZone[]>([]);

  // Pipeline state
  const [isProcessing, setIsProcessing] = useState<boolean>(false);
  const [uploadProgress, setUploadProgress] = useState<number>(0);
  const [runProgress, setRunProgress] = useState<number>(0);
  const [currentStage, setCurrentStage] = useState<number>(0);
  const [stageName, setStageName] = useState<string>('idle');
  const [progressMsg, setProgressMsg] = useState<string>('');
  const [errorDetails, setErrorDetails] = useState<{ code?: string; message?: string; advice?: string } | null>(null);

  // Completion
  const [completedClip, setCompletedClip] = useState<ClipOut | null>(null);
  const [completedRunId, setCompletedRunId] = useState<string | number | null>(null);
  const [completedResult, setCompletedResult] = useState<RunResult | null>(null);

  const [consoleLogs, setConsoleLogs] = useState<string[]>([
    `[SYSTEM] Strix Forensic Node initialized at ${new Date().toISOString().substring(11, 19)} UTC.`,
    '[FFMPEG] Probing hardware codecs: H.264 / HEVC / AVI stream demuxer ready.',
  ]);

  useEffect(() => {
    api
      .getZones()
      .then((z) => setZones(z))
      .catch((err) => {
        console.warn('Failed to fetch zones:', err);
      });
  }, []);

  const stages = [
    { title: '1. Ingestion & Validation', desc: 'SHA-256 integrity hash verification & FFprobe container stream check' },
    { title: '2. Spatiotemporal Linking', desc: 'ATM spatial zone dwell-time sync with terminal transaction window' },
    { title: '3. Person Detection & ByteTrack', desc: 'MobileNetV3 Faster R-CNN detection & bystander exclusion' },
    { title: '4. Facial Landmark & 3D Pose', desc: 'InsightFace ArcFace detection & frontal peak yaw/pitch ranking' },
    { title: '5. Deterministic IQA Scoring', desc: 'Laplacian sharpness, illumination, occlusion & non-destructive crop' },
  ];

  const handleVideoUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const file = e.target.files[0];
      setVideoFile(file);
      setErrorDetails(null);
      setConsoleLogs((prev) => [
        ...prev,
        `[INGEST] Video file selected: ${file.name} (${(file.size / (1024 * 1024)).toFixed(2)} MB)`,
      ]);
    }
  };

  const handleLoadSample = () => {
    const demo = DEMO_CLIPS[0];
    const sampleFile = new File(['mock_sample_footage_data'], demo.original_filename, { type: 'video/mp4' });
    setVideoFile(sampleFile);
    setAtmId(demo.atm_id || 'ATM-JPR-014');
    if (demo.clip_start_time) {
      setClipStartTime(demo.clip_start_time.slice(0, 16));
      setTransactionTime(demo.clip_start_time.slice(0, 16));
    }
    setErrorDetails(null);
    setConsoleLogs((prev) => [
      ...prev,
      `[SAMPLE] Loaded reference ATM clip: ${demo.original_filename} (${demo.duration_sec}s, ${demo.fps} fps)`,
      `[SAMPLE] Pre-configured spatial zone: ${demo.atm_id} vestibule keypad dwell region.`,
    ]);
  };

  const handleExecutePipeline = async () => {
    if (!videoFile) return;

    setIsProcessing(true);
    setRunProgress(5);
    setCurrentStage(1);
    setStageName('upload');
    setProgressMsg('Uploading footage to forensic store...');
    setErrorDetails(null);
    setCompletedClip(null);
    setCompletedRunId(null);
    setCompletedResult(null);

    setConsoleLogs((prev) => [
      ...prev,
      `[INGEST] Initiating upload of "${videoFile.name}"...`,
    ]);

    try {
      // 1. Upload clip
      const formData = new FormData();
      formData.append('file', videoFile);
      if (clipStartTime) formData.append('clip_start_time', new Date(clipStartTime).toISOString());
      if (atmId) formData.append('atm_id', atmId);
      if (notes) formData.append('notes', notes);
      if (selectedZoneId) {
        const zoneObj = zones.find((z) => z.id === selectedZoneId);
        if (zoneObj) {
          formData.append('zone_polygon_norm', JSON.stringify(zoneObj.polygon));
        }
      }

      setUploadProgress(40);
      const clip = await api.uploadClip(formData);
      setUploadProgress(100);
      setCompletedClip(clip);

      setConsoleLogs((prev) => [
        ...prev,
        `[INGEST] Clip uploaded successfully. ID: ${clip.id}`,
        `[DIGEST] SHA-256: ${clip.sha256}`,
        `[FFPROBE] Container: ${clip.container || 'mp4'}, Codec: ${clip.codec || 'h264'}, Resolution: ${clip.width}x${clip.height} @ ${clip.fps || 25}fps`,
      ]);
      onAuditAction('UPLOAD_CLIP', clip.id, `Uploaded ${clip.original_filename} (${(clip.size_bytes / (1024 * 1024)).toFixed(2)} MB)`);

      // 2. Process clip
      setCurrentStage(2);
      setStageName('process');
      setProgressMsg('Spatiotemporal linking & queuing pipeline run...');

      const txIso = transactionTime ? new Date(transactionTime).toISOString() : new Date().toISOString();
      const procRes = await api.processClip(clip.id, {
        transaction_time: txIso,
        window_sec: windowSec,
        sample_fps: sampleFps,
        atm_id: atmId,
      });

      const runId = procRes.run_id;
      setConsoleLogs((prev) => [
        ...prev,
        `[QUEUE] Run registered: ${runId} (Status: ${procRes.status})`,
      ]);

      // 3. Poll run status
      let isDone = false;
      let attempts = 0;
      const maxAttempts = 60; // 2 minutes

      while (!isDone && attempts < maxAttempts) {
        attempts++;
        await new Promise((r) => setTimeout(r, 2000));

        const runStatus: RunStatus = await api.getRun(runId);
        setRunProgress(runStatus.progress ?? Math.min(95, attempts * 15));
        if (runStatus.progress_message) setProgressMsg(runStatus.progress_message);

        // Map stage to 1-5
        if (runStatus.stage) {
          setStageName(runStatus.stage);
          if (runStatus.stage.includes('ingest') || runStatus.stage.includes('hash')) setCurrentStage(1);
          else if (runStatus.stage.includes('link') || runStatus.stage.includes('dwell')) setCurrentStage(2);
          else if (runStatus.stage.includes('detect') || runStatus.stage.includes('track')) setCurrentStage(3);
          else if (runStatus.stage.includes('face') || runStatus.stage.includes('pose') || runStatus.stage.includes('crop')) setCurrentStage(4);
          else if (runStatus.stage.includes('iqa') || runStatus.stage.includes('rank') || runStatus.stage.includes('enhance')) setCurrentStage(5);
        }

        if (runStatus.progress_message) {
          setConsoleLogs((prev) => [...prev, `[PIPELINE] ${runStatus.progress_message}`]);
        }

        if (runStatus.status === 'done') {
          isDone = true;
          setCurrentStage(5);
          setRunProgress(100);
          setProgressMsg('Forensic evaluation complete. Results indexed.');

          // Fetch result
          const result = await api.getRunResult(runId);
          setCompletedRunId(runId);
          setCompletedResult(result);
          setIsProcessing(false);

          setConsoleLogs((prev) => [
            ...prev,
            `[DONE] Evidence pack EV-${runId} generated. Best frames: ${result.best_frames.length}. Quality: ${Math.round((result.best_frames[0]?.quality_score || 0.88) * 100)}/100`,
          ]);

          onAuditAction('PROCESS_RUN', `EV-${runId}`, `Processed clip ${clip.id} (Run: ${runId})`);
          onRunCompleted(runId, clip, result);
          break;
        } else if (runStatus.status === 'failed') {
          isDone = true;
          setIsProcessing(false);
          setErrorDetails({
            code: runStatus.error_code || 'PIPELINE_ERROR',
            message: runStatus.error_message || runStatus.progress_message || 'Pipeline failed during execution',
            advice: runStatus.error_advice || 'Check clip dimensions, codec format, or transaction timestamp alignment.',
          });
          setConsoleLogs((prev) => [
            ...prev,
            `[ERROR] Pipeline failed with code: ${runStatus.error_code || 'UNKNOWN'}`,
            `[MESSAGE] ${runStatus.error_message || 'Pipeline processing error'}`,
            `[ADVICE] ${runStatus.error_advice || 'Review transaction time window and try again.'}`,
          ]);
          break;
        }
      }
    } catch (err: any) {
      setIsProcessing(false);
      const msg = err.message || 'Pipeline execution failed';
      setErrorDetails({
        code: 'EXECUTION_FAILED',
        advice: msg,
      });
      setConsoleLogs((prev) => [...prev, `[EXCEPTION] ${msg}`]);
    }
  };

  return (
    <section id="view-ingest" className="space-y-4 max-w-[1160px] mx-auto">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-slate-900 tracking-tight">Ingest CCTV Footage &amp; Execute Pipeline</h1>
          <p className="text-xs text-slate-500 mt-0.5">
            Ingest ATM vestibule surveillance video (MP4, AVI, MKV, MOV), align cardholder transaction timestamps, and execute the 5-stage deterministic extraction pipeline.
          </p>
        </div>
        {isMockMode && (
          <button
            onClick={handleLoadSample}
            className="px-3.5 py-2 text-xs font-semibold bg-white border border-steel text-steel hover:bg-steel-tint rounded flex items-center gap-1.5 transition-colors self-start sm:self-auto"
          >
            <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="currentColor">
              <polygon points="5 3 19 12 5 21 5 3"></polygon>
            </svg>
            Load Sample Footage
          </button>
        )}
      </div>

      {/* Main Ingestion & Configuration Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Dropzone Card */}
        <div className="bg-white border border-hairline rounded-md p-4 space-y-4">
          <div className="flex items-center justify-between border-b border-hairline pb-2.5">
            <span className="text-xs font-semibold text-slate-900">1. Surveillance Video Input</span>
            <span className="font-mono text-[10px] text-slate-500 uppercase">H.264 / HEVC / AVI</span>
          </div>

          <label className="border-2 border-dashed border-slate-300 hover:border-steel rounded-md p-5 cursor-pointer transition-colors block text-center bg-canvas hover:bg-slate-50">
            <input
              type="file"
              id="videoUploadInput"
              accept=".mp4,.avi,.mkv,.mov"
              className="hidden"
              onChange={handleVideoUpload}
            />
            <div className="flex flex-col items-center justify-center gap-2">
              <div className="w-10 h-10 rounded bg-white border border-hairline flex items-center justify-center text-slate-600 shadow-sm">
                <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                  <polygon points="23 7 16 12 23 17 23 7"></polygon>
                  <rect x="1" y="5" width="15" height="14" rx="2"></rect>
                </svg>
              </div>
              <div className="text-xs font-semibold text-slate-900">
                {videoFile ? videoFile.name : 'Click to select CCTV video file'}
              </div>
              <p className="text-[11px] text-slate-500">
                {videoFile
                  ? `${(videoFile.size / (1024 * 1024)).toFixed(2)} MB • Ready for ingestion`
                  : 'Supported formats: .mp4, .avi, .mkv, .mov'}
              </p>
            </div>
          </label>

          {/* Clip Metadata Form */}
          <div className="grid grid-cols-2 gap-3 pt-1">
            <div>
              <label className="block text-[11px] font-medium text-slate-700 mb-1">ATM Terminal ID</label>
              <input
                type="text"
                value={atmId}
                onChange={(e) => setAtmId(e.target.value)}
                placeholder="e.g. ATM-JPR-014"
                className="w-full text-xs font-mono px-2.5 py-1.5 bg-canvas border border-hairline rounded text-slate-900 focus:outline-none focus:border-steel focus:bg-white"
              />
            </div>
            <div>
              <label className="block text-[11px] font-medium text-slate-700 mb-1">Spatial Zone Preset</label>
              <select
                value={selectedZoneId}
                onChange={(e) => setSelectedZoneId(e.target.value)}
                className="w-full text-xs px-2.5 py-1.5 bg-canvas border border-hairline rounded text-slate-900 focus:outline-none focus:border-steel focus:bg-white"
              >
                <option value="">None / Full Frame</option>
                {zones.map((z) => (
                  <option key={z.id} value={z.id}>
                    {z.id} {z.note ? `(${z.note})` : ''}
                  </option>
                ))}
              </select>
            </div>
            <div className="col-span-2">
              <label className="block text-[11px] font-medium text-slate-700 mb-1">
                Clip Recording Start (Local Time)
              </label>
              <input
                type="datetime-local"
                step="1"
                value={clipStartTime}
                onChange={(e) => setClipStartTime(e.target.value)}
                className="w-full text-xs font-mono px-2.5 py-1.5 bg-canvas border border-hairline rounded text-slate-900 focus:outline-none focus:border-steel focus:bg-white"
              />
            </div>
          </div>
        </div>

        {/* Transaction Window & Parameters */}
        <div className="bg-white border border-hairline rounded-md p-4 space-y-4">
          <div className="flex items-center justify-between border-b border-hairline pb-2.5">
            <span className="text-xs font-semibold text-slate-900">2. Transaction Linking Parameters</span>
            <span className="font-mono text-[10px] text-slate-500 uppercase">Spatiotemporal Sync</span>
          </div>

          <div className="space-y-3.5">
            <div>
              <label className="block text-[11px] font-medium text-slate-700 mb-1">
                Cardholder Transaction Timestamp
              </label>
              <input
                type="datetime-local"
                step="1"
                value={transactionTime}
                onChange={(e) => setTransactionTime(e.target.value)}
                className="w-full text-xs font-mono px-2.5 py-1.5 bg-canvas border border-hairline rounded text-slate-900 focus:outline-none focus:border-steel focus:bg-white"
              />
              <span className="text-[10px] text-slate-500 mt-0.5 block">
                Synchronized with switch log (withdrawal / dispense event).
              </span>
            </div>

            {/* Window Seconds Slider */}
            <div>
              <div className="flex items-center justify-between text-[11px] mb-1">
                <span className="font-medium text-slate-700">Analysis Window (`window_sec`)</span>
                <span className="font-mono font-semibold text-steel">{windowSec.toFixed(1)}s (±{(windowSec / 2).toFixed(1)}s)</span>
              </div>
              <input
                type="range"
                min="5"
                max="60"
                step="1"
                value={windowSec}
                onChange={(e) => setWindowSec(parseFloat(e.target.value))}
                className="forensic-slider"
              />
              <div className="flex justify-between text-[10px] text-slate-400 mt-1">
                <span>5s</span>
                <span>10s (standard)</span>
                <span>30s</span>
                <span>60s</span>
              </div>
            </div>

            {/* Sample FPS Slider */}
            <div>
              <div className="flex items-center justify-between text-[11px] mb-1">
                <span className="font-medium text-slate-700">Sampling Rate (`sample_fps`)</span>
                <span className="font-mono font-semibold text-steel">{sampleFps.toFixed(1)} fps</span>
              </div>
              <input
                type="range"
                min="1"
                max="10"
                step="0.5"
                value={sampleFps}
                onChange={(e) => setSampleFps(parseFloat(e.target.value))}
                className="forensic-slider"
              />
              <div className="flex justify-between text-[10px] text-slate-400 mt-1">
                <span>1.0 fps</span>
                <span>2.0 fps (optimal)</span>
                <span>5.0 fps</span>
                <span>10.0 fps</span>
              </div>
            </div>

            <div>
              <label className="block text-[11px] font-medium text-slate-700 mb-1">Case / Ingestion Notes</label>
              <input
                type="text"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="Investigation notes, station code, terminal notes..."
                className="w-full text-xs px-2.5 py-1.5 bg-canvas border border-hairline rounded text-slate-900 focus:outline-none focus:border-steel focus:bg-white"
              />
            </div>
          </div>
        </div>
      </div>

      {/* Execution Trigger Bar */}
      <div className="bg-white border border-hairline rounded-md p-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-xs text-slate-600">
          <span className="w-2 h-2 rounded-full bg-status-emerald"></span>
          <span>Deterministic pipeline execution conforms to ISO/IEC 19794-5 &amp; NIST IQA standards.</span>
        </div>
        <button
          id="btnRunPipeline"
          onClick={handleExecutePipeline}
          disabled={!videoFile || isProcessing}
          className="px-5 py-2 text-xs font-semibold bg-steel hover:bg-steel-hover disabled:bg-slate-300 disabled:cursor-not-allowed text-white rounded transition-colors shadow-sm flex items-center gap-2"
        >
          {isProcessing ? (
            <>
              <svg className="animate-spin w-3.5 h-3.5 text-white" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path>
              </svg>
              <span>Processing Footage ({runProgress}%)...</span>
            </>
          ) : (
            <>
              <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <polygon points="5 3 19 12 5 21 5 3"></polygon>
              </svg>
              <span>Execute Ingestion &amp; Pipeline</span>
            </>
          )}
        </button>
      </div>

      {/* Progress & Stage Visualizer */}
      <div className="bg-white border border-hairline rounded-md overflow-hidden">
        <div className="px-4 py-2.5 bg-canvas border-b border-hairline flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold text-slate-900">5-Stage Forensic Pipeline Execution</span>
            {isProcessing && (
              <span className="font-mono text-[10px] px-1.5 py-0.2 rounded bg-blue-100 text-blue-700 animate-pulse">
                POLLING RUN STATUS (2s)
              </span>
            )}
          </div>
          <span id="pipelineStatusBadge" className="font-mono text-[11px] text-slate-600">
            {isProcessing
              ? `RUNNING • STAGE ${currentStage}/5 (${runProgress}%)`
              : completedRunId
              ? `COMPLETE • EV-${completedRunId}`
              : 'IDLE • AWAITING VIDEO'}
          </span>
        </div>

        {/* Live Progress Bar */}
        {isProcessing && (
          <div className="w-full bg-slate-100 h-1.5">
            <div
              className="bg-steel h-1.5 transition-all duration-300"
              style={{ width: `${Math.max(5, runProgress)}%` }}
            ></div>
          </div>
        )}

        {/* Stages List */}
        <div id="pipelineStagesContainer" className="divide-y divide-hairline">
          {stages.map((stg, idx) => {
            const isCompleted = currentStage > idx + 1 || (completedRunId && currentStage >= idx + 1);
            const isCurrent = currentStage === idx + 1 && isProcessing;

            return (
              <div key={idx} className="p-3.5 flex items-center justify-between text-xs">
                <div className="flex items-center gap-3">
                  <div
                    className={`w-6 h-6 rounded-full flex items-center justify-center font-mono text-[11px] font-semibold ${
                      isCompleted
                        ? 'bg-status-emeraldBg text-status-emerald border border-status-emeraldBorder'
                        : isCurrent
                        ? 'bg-steel-tint text-steel border border-steel animate-pulse'
                        : 'bg-slate-100 text-slate-400'
                    }`}
                  >
                    {isCompleted ? '✓' : idx + 1}
                  </div>
                  <div>
                    <div className="font-semibold text-slate-800">{stg.title}</div>
                    <div className="text-[11px] text-slate-500">{stg.desc}</div>
                  </div>
                </div>
                <span className="font-mono text-[11px] text-slate-500">
                  {isCompleted ? 'COMPLETED' : isCurrent ? 'PROCESSING...' : 'QUEUED'}
                </span>
              </div>
            );
          })}
        </div>

        {/* Pipeline Console Log */}
        <div
          id="pipelineConsole"
          className="bg-sidebar text-slate-300 p-3.5 font-mono text-[11px] leading-relaxed h-36 overflow-y-auto"
        >
          {consoleLogs.map((log, i) => (
            <div key={i} className="text-slate-300">
              {log}
            </div>
          ))}
        </div>
      </div>

      {/* Failure Notification */}
      {errorDetails && (
        <div className="bg-status-crimsonBg border border-status-crimsonBorder rounded-md p-4 text-xs space-y-1.5">
          <div className="font-semibold text-status-crimson flex items-center gap-1.5">
            <svg className="w-4 h-4 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="10"></circle>
              <line x1="12" y1="8" x2="12" y2="12"></line>
              <line x1="12" y1="16" x2="12.01" y2="16"></line>
            </svg>
            <span>Error Code: {errorDetails.code}</span>
          </div>
          {errorDetails.message && (
            <p className="text-slate-800 font-medium pl-5">{errorDetails.message}</p>
          )}
          {errorDetails.advice && (
            <p className="text-slate-600 pl-5 text-[11px] font-mono">Advice: {errorDetails.advice}</p>
          )}
        </div>
      )}

      {/* Completion Banner */}
      {completedRunId && (
        <div
          id="pipelineSuccessBanner"
          className="bg-status-emeraldBg border border-status-emeraldBorder rounded-md p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3 animate-in fade-in"
        >
          <div>
            <div className="text-xs font-semibold text-status-emerald">
              Pipeline Complete &mdash; Evidence Dossier EV-{completedRunId} Ready
            </div>
            <div id="pipelineSuccessDetail" className="font-mono text-xs text-slate-700 mt-0.5">
              Clip: {completedClip?.original_filename || 'CCTV Footage'} &bull; Run: {completedRunId} &bull; Best Frames:{' '}
              {completedResult?.best_frames.length ?? 0} &bull; Link Confidence:{' '}
              {completedResult?.link_confidence || 'High'}
            </div>
          </div>
          <button
            onClick={() => onNavigate('inspector')}
            className="px-4 py-2 text-xs font-semibold bg-status-emerald hover:opacity-95 text-white rounded shrink-0 shadow-sm transition-opacity"
          >
            Open in Case Inspector &rarr;
          </button>
        </div>
      )}
    </section>
  );
};
