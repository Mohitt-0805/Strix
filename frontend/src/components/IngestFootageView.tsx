import React, { useState } from 'react';
import { MockCase } from '@/lib/mockData';
import { api } from '@/lib/api';

interface IngestFootageViewProps {
  onCaseCreated: (newCase: MockCase) => void;
  onOpenCase: (caseObj: MockCase) => void;
  onAuditAction: (action: string, refId: string, details: string) => void;
}

export const IngestFootageView: React.FC<IngestFootageViewProps> = ({ onCaseCreated, onOpenCase, onAuditAction }) => {
  const [videoFile, setVideoFile] = useState<File | null>(null);
  const [logFile, setLogFile] = useState<File | null>(null);
  const [isProcessing, setIsProcessing] = useState<boolean>(false);
  const [currentStage, setCurrentStage] = useState<number>(0);
  const [consoleLogs, setConsoleLogs] = useState<string[]>([
    '[SYSTEM] Strix Pipeline v2.4 initialized. Ready for video ingestion.',
    '[FFMPEG] Hardware acceleration checked: CPU/GPU fallback ready.',
  ]);
  const [completedCase, setCompletedCase] = useState<MockCase | null>(null);

  const stages = [
    { title: '1. Ingestion & Validation', desc: 'SHA-256 integrity hash verification & FFprobe container stream check' },
    { title: '2. Spatiotemporal Linking', desc: 'ATM spatial zone dwell-time sync with terminal transaction window' },
    { title: '3. Person Detection & ByteTrack', desc: 'MobileNetV3 Faster R-CNN detection & bystander exclusion' },
    { title: '4. Facial Landmark & 3D Pose', desc: 'InsightFace ArcFace detection & frontal peak yaw/pitch ranking' },
    { title: '5. Deterministic IQA Scoring', desc: 'Laplacian sharpness, illumination, occlusion & non-destructive crop' },
  ];

  const handleVideoUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      setVideoFile(e.target.files[0]);
      setConsoleLogs((prev) => [
        ...prev,
        `[INGEST] Video file selected: ${e.target.files![0].name} (${(e.target.files![0].size / (1024 * 1024)).toFixed(2)} MB)`,
      ]);
    }
  };

  const handleLogUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      setLogFile(e.target.files[0]);
      setConsoleLogs((prev) => [
        ...prev,
        `[LOG] Switch log selected: ${e.target.files![0].name}`,
      ]);
    }
  };

  const handleLoadSample = () => {
    const sampleFile = new File(['sample_clip_data'], 'atm_sample_clip_03_vestibule.mp4', { type: 'video/mp4' });
    setVideoFile(sampleFile);
    const sampleLog = new File(['{"tx_time":"2026-11-26T21:14:24"}'], 'switch_event_log.json', { type: 'application/json' });
    setLogFile(sampleLog);
    setConsoleLogs((prev) => [
      ...prev,
      '[SAMPLE] Loaded verified sample incident: Low-Light ATM Vestibule Withdrawal (atm_clip_03)',
    ]);
  };

  const handleRunPipeline = async () => {
    if (!videoFile) return;
    setIsProcessing(true);
    setCurrentStage(1);
    setCompletedCase(null);

    const logMessages = [
      '[STAGE 1] Streaming bytes into storage... SHA-256: 8f4a2c91d7e0b34f56a12c89e4b7d103...',
      '[STAGE 1] FFprobe probed: 1280x720 H.264 @ 25.00 fps. Duration: 36.0s. Container valid.',
      '[STAGE 2] Evaluating normalized ATM zone polygon [0.45, 0.35, 0.95, 0.95]...',
      '[STAGE 2] Keypad dwell verified: Subject anchor at (0.72, 0.68). Bystanders excluded.',
      '[STAGE 3] Running MobileNetV3 Faster R-CNN on sampled frames... Track #01 assigned.',
      '[STAGE 4] InsightFace detected face: Yaw: +3.2°, Pitch: -2.1°, Frontal match ready.',
      '[STAGE 5] Laplacian sharpness: 91.2 | Illumination: 88.0 | Composite IQA: 92/100.',
      '[STAGE 5] Saved frame_0142.jpg and burned ENHANCED stamp to frame_0142_enh_x4.jpg.',
      '[SUCCESS] Pipeline finished in 4.2s. Output conforms to docs/sample_result.json.',
    ];

    for (let i = 0; i < logMessages.length; i++) {
      await new Promise((res) => setTimeout(res, 450));
      setConsoleLogs((prev) => [...prev, logMessages[i]]);
      if (i === 1) setCurrentStage(2);
      if (i === 3) setCurrentStage(3);
      if (i === 4) setCurrentStage(4);
      if (i === 6) setCurrentStage(5);
    }

    const newCase: MockCase = {
      caseId: `CASE-2026-${String(Math.floor(100 + Math.random() * 900))}`,
      txnId: `TXN-${String(Math.floor(100000 + Math.random() * 900000))}`,
      title: 'Processed CCTV Footage Incident',
      atmId: 'ATM-JPR-014',
      camera: 'CAM-01 (Vestibule)',
      location: 'MI Road Branch, Jaipur',
      dateCreated: '2026-11-26',
      timestamp: '2026-11-26 21:14:24',
      clipsCount: 1,
      reviewer: 'R. Sharma',
      status: 'In Progress',
      lastUpdated: 'Just now',
      amount: '₹20,000',
      cardLast4: '4819',
      matchConfidence: 98.4,
      quality: 92,
      conditions: ['Low-Light'],
      sha256: '8f4a2c91d7e0b34f56a12c89e4b7d103a2c4f8e9102b3d4a5c6e7f8091a2b3c4',
      events: [
        { label: 'Card Inserted', time: 4.0, clock: '21:14:02' },
        { label: 'PIN Verified', time: 11.2, clock: '21:14:09' },
        { label: 'Cash Dispensed', time: 22.0, clock: '21:14:20' },
        { label: 'Card Retrieved', time: 28.5, clock: '21:14:26' },
        { label: 'Session End', time: 33.0, clock: '21:14:31' },
      ],
      faceProfile: { skinTone: 170, hairStyle: 'short', glasses: false, cap: false, beard: true, seed: 14 },
      primaryCandidateIdx: 0,
      candidates: [
        {
          id: 1,
          label: 'Frontal Peak',
          time: 18.4,
          yaw: 3,
          pitch: -2,
          score: 92,
          metrics: { sharpness: 91, illumination: 88, pose: 96, occlusion: 95, resolution: 90 },
          blur: 0.3,
          dark: 0.16,
          glare: false,
        },
      ],
    };

    setCompletedCase(newCase);
    onCaseCreated(newCase);
    setIsProcessing(false);
    onAuditAction('Ingestion', `${newCase.caseId} / ${newCase.txnId}`, `Indexed ${videoFile.name} (IQA: ${newCase.quality}/100)`);
  };

  return (
    <section id="view-ingest" className="space-y-4 max-w-[1160px] mx-auto">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-slate-900 tracking-tight">Ingest CCTV Footage &amp; ATM Log</h1>
          <p className="text-xs text-slate-500 mt-0.5">
            Upload ATM vestibule surveillance video and terminal switch logs to extract, score, and index the primary customer's
            optimal facial frame.
          </p>
        </div>
        <button
          onClick={handleLoadSample}
          className="px-3.5 py-2 text-xs font-semibold bg-white border border-steel text-steel hover:bg-steel-tint rounded flex items-center gap-1.5 transition-colors self-start sm:self-auto"
        >
          <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="currentColor">
            <polygon points="5 3 19 12 5 21 5 3"></polygon>
          </svg>
          Load Sample Incident (Low-Light Withdrawal)
        </button>
      </div>

      {/* Dual Upload Dropzones */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Video Upload Dropzone */}
        <label className="bg-white border border-dashed border-slate-300 hover:border-steel rounded-md p-5 cursor-pointer transition-colors block">
          <input
            type="file"
            id="videoUploadInput"
            accept=".mp4,.avi,.mkv,.mov,.wmv,.flv,.mpeg,.mpg"
            className="hidden"
            onChange={handleVideoUpload}
          />
          <div className="flex items-start gap-3.5">
            <div className="w-10 h-10 rounded bg-canvas border border-hairline flex items-center justify-center shrink-0 text-slate-600">
              <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                <polygon points="23 7 16 12 23 17 23 7"></polygon>
                <rect x="1" y="5" width="15" height="14" rx="2"></rect>
              </svg>
            </div>
            <div className="min-w-0 flex-1">
              <div className="text-xs font-semibold text-slate-900">1. ATM CCTV Video Recording</div>
              <p className="text-[11px] text-slate-500 mt-0.5">Supported: .mp4, .avi, .mkv, .mov (H.264 / HEVC)</p>
              <div
                id="videoUploadStatus"
                className="mt-3 text-xs font-mono text-slate-600 bg-canvas border border-hairline rounded px-2.5 py-1.5 truncate"
              >
                {videoFile ? videoFile.name : 'Drop file or click to browse...'}
              </div>
            </div>
          </div>
        </label>

        {/* Log Upload Dropzone */}
        <label className="bg-white border border-dashed border-slate-300 hover:border-steel rounded-md p-5 cursor-pointer transition-colors block">
          <input type="file" id="logUploadInput" accept=".json,.csv" className="hidden" onChange={handleLogUpload} />
          <div className="flex items-start gap-3.5">
            <div className="w-10 h-10 rounded bg-canvas border border-hairline flex items-center justify-center shrink-0 text-slate-600">
              <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                <polyline points="14 2 14 8 20 8"></polyline>
                <line x1="16" y1="13" x2="8" y2="13"></line>
                <line x1="16" y1="17" x2="8" y2="17"></line>
              </svg>
            </div>
            <div className="min-w-0 flex-1">
              <div className="text-xs font-semibold text-slate-900">2. ATM Transaction Event Log</div>
              <p className="text-[11px] text-slate-500 mt-0.5">Supported: .json, .csv (ISO-8583 switch log)</p>
              <div
                id="logUploadStatus"
                className="mt-3 text-xs font-mono text-slate-600 bg-canvas border border-hairline rounded px-2.5 py-1.5 truncate"
              >
                {logFile ? logFile.name : 'Drop file or click to browse...'}
              </div>
            </div>
          </div>
        </label>
      </div>

      {/* Pipeline Options & Trigger */}
      <div className="bg-white border border-hairline rounded-md p-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-4 text-xs text-slate-600">
          <label className="flex items-center gap-1.5">
            <input type="checkbox" defaultChecked className="accent-steel" />
            <span>CLAHE Low-Light Recovery</span>
          </label>
          <label className="flex items-center gap-1.5">
            <input type="checkbox" defaultChecked className="accent-steel" />
            <span>Exclude Passing Bystanders</span>
          </label>
          <label className="flex items-center gap-1.5">
            <input type="checkbox" defaultChecked className="accent-steel" />
            <span>Generate SHA-256 Digest</span>
          </label>
        </div>
        <button
          id="btnRunPipeline"
          onClick={handleRunPipeline}
          disabled={!videoFile || isProcessing}
          className="px-4 py-2 text-xs font-semibold bg-steel hover:bg-steel-hover disabled:bg-slate-300 disabled:cursor-not-allowed text-white rounded transition-colors"
        >
          {isProcessing ? 'Executing Extraction Pipeline...' : 'Execute Extraction Pipeline'}
        </button>
      </div>

      {/* 5-Stage Deterministic Pipeline Visualizer */}
      <div className="bg-white border border-hairline rounded-md overflow-hidden">
        <div className="px-4 py-2.5 bg-canvas border-b border-hairline flex items-center justify-between">
          <span className="text-xs font-semibold text-slate-900">5-Stage Forensic Pipeline Execution</span>
          <span id="pipelineStatusBadge" className="font-mono text-[11px] text-slate-500">
            {isProcessing ? `RUNNING • STAGE ${currentStage}/5` : completedCase ? 'COMPLETE' : 'IDLE • AWAITING INPUT'}
          </span>
        </div>

        <div id="pipelineStagesContainer" className="divide-y divide-hairline">
          {stages.map((stg, idx) => (
            <div key={idx} className="p-3.5 flex items-center justify-between text-xs">
              <div className="flex items-center gap-3">
                <div
                  className={`w-6 h-6 rounded-full flex items-center justify-center font-mono text-[11px] font-semibold ${
                    currentStage > idx + 1 || (completedCase && currentStage >= idx + 1)
                      ? 'bg-status-emeraldBg text-status-emerald border border-status-emeraldBorder'
                      : currentStage === idx + 1
                      ? 'bg-steel-tint text-steel border border-steel animate-pulse'
                      : 'bg-slate-100 text-slate-400'
                  }`}
                >
                  {currentStage > idx + 1 || (completedCase && currentStage >= idx + 1) ? '✓' : idx + 1}
                </div>
                <div>
                  <div className="font-semibold text-slate-800">{stg.title}</div>
                  <div className="text-[11px] text-slate-500">{stg.desc}</div>
                </div>
              </div>
              <span className="font-mono text-[11px] text-slate-400">
                {currentStage > idx + 1 || (completedCase && currentStage >= idx + 1)
                  ? 'VERIFIED'
                  : currentStage === idx + 1
                  ? 'PROCESSING...'
                  : 'QUEUED'}
              </span>
            </div>
          ))}
        </div>

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

      {/* Completion Banner */}
      {completedCase && (
        <div
          id="pipelineSuccessBanner"
          className="bg-status-emeraldBg border border-status-emeraldBorder rounded-md p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3"
        >
          <div>
            <div className="text-xs font-semibold text-status-emerald">Pipeline Complete &mdash; New Case Indexed & Verified</div>
            <div id="pipelineSuccessDetail" className="font-mono text-xs text-slate-700 mt-0.5">
              {completedCase.caseId} ({completedCase.txnId}) &bull; Composite IQA: {completedCase.quality}/100 &bull; Low-Light Recovered
            </div>
          </div>
          <button
            onClick={() => onOpenCase(completedCase)}
            className="px-4 py-2 text-xs font-semibold bg-status-emerald hover:opacity-95 text-white rounded shrink-0"
          >
            Open in Case Inspector &rarr;
          </button>
        </div>
      )}
    </section>
  );
};
