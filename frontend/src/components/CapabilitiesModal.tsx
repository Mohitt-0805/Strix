import React from 'react';

interface CapabilitiesModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const CapabilitiesModal: React.FC<CapabilitiesModalProps> = ({ isOpen, onClose }) => {
  if (!isOpen) return null;

  return (
    <div
      id="capabilitiesModal"
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="bg-white border border-hairline rounded-md w-full max-w-3xl max-h-[88vh] flex flex-col shadow-xl overflow-hidden">
        <div className="px-5 py-4 bg-canvas border-b border-hairline flex items-center justify-between gap-4 shrink-0">
          <div>
            <h3 className="text-sm font-semibold text-slate-900">Strix — Capabilities Matrix</h3>
            <p className="text-xs text-slate-500 mt-0.5">
              Transparent segregation of live browser-native features vs. ML inference modules
            </p>
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-700 text-xl leading-none px-1"
            aria-label="Close modal"
          >
            &times;
          </button>
        </div>

        <div className="p-5 overflow-y-auto grid grid-cols-1 md:grid-cols-2 gap-5 text-xs">
          {/* Column 1: 10 Working Native Browser Features */}
          <div>
            <div className="flex items-center justify-between mb-3">
              <h4 className="font-semibold text-slate-900">Native Browser Processing</h4>
              <span className="font-mono text-[11px] font-semibold px-2 py-0.5 rounded bg-status-emeraldBg text-status-emerald border border-status-emeraldBorder">
                10 Working
              </span>
            </div>
            <ul className="space-y-2">
              <li className="p-2.5 rounded bg-canvas border border-hairline">
                <div className="font-medium text-slate-800">1. Interactive Canvas CCTV Playback</div>
                <div className="text-[11px] text-slate-500">
                  Frame-stepping (-1f/+1f), variable speed, and timeline scrubbing.
                </div>
              </li>
              <li className="p-2.5 rounded bg-canvas border border-hairline">
                <div className="font-medium text-slate-800">2. CLAHE Low-Light Contrast Filter</div>
                <div className="text-[11px] text-slate-500">
                  Real-time luminance normalization on HTML5 Canvas viewport.
                </div>
              </li>
              <li className="p-2.5 rounded bg-canvas border border-hairline">
                <div className="font-medium text-slate-800">3. Synchronized ATM Log Timeline</div>
                <div className="text-[11px] text-slate-500">
                  Direct event-to-timestamp seeking across terminal events.
                </div>
              </li>
              <li className="p-2.5 rounded bg-canvas border border-hairline">
                <div className="font-medium text-slate-800">4. Live Multi-Facet IQA Filtering</div>
                <div className="text-[11px] text-slate-500">
                  Dynamic threshold slider, condition tags, and instant case search.
                </div>
              </li>
              <li className="p-2.5 rounded bg-canvas border border-hairline">
                <div className="font-medium text-slate-800">5. Primary Frame Override Controls</div>
                <div className="text-[11px] text-slate-500">
                  Human-in-the-loop candidate selection with live state sync.
                </div>
              </li>
              <li className="p-2.5 rounded bg-canvas border border-hairline">
                <div className="font-medium text-slate-800">6. Chain-of-Custody Audit Ledger</div>
                <div className="text-[11px] text-slate-500">
                  Session-persistent action logging with SHA-256 digest references.
                </div>
              </li>
              <li className="p-2.5 rounded bg-canvas border border-hairline">
                <div className="font-medium text-slate-800">7. Forensic Dossier File Export</div>
                <div className="text-[11px] text-slate-500">
                  Generates and downloads structured JSON evidence dossier files.
                </div>
              </li>
              <li className="p-2.5 rounded bg-canvas border border-hairline">
                <div className="font-medium text-slate-800">8. Live Dashboard KPI Synchronization</div>
                <div className="text-[11px] text-slate-500">
                  Real-time counters updated on ingest, status cycle, and export.
                </div>
              </li>
              <li className="p-2.5 rounded bg-canvas border border-hairline">
                <div className="font-medium text-slate-800">9. Interactive Activity Telemetry Chart</div>
                <div className="text-[11px] text-slate-500">
                  Weekly/Monthly SVG chart with point hover inspection tooltips.
                </div>
              </li>
              <li className="p-2.5 rounded bg-canvas border border-hairline">
                <div className="font-medium text-slate-800">10. Facial Alignment Guide Overlays</div>
                <div className="text-[11px] text-slate-500">
                  Inter-ocular axis and midline guides on restored face canvases.
                </div>
              </li>
            </ul>
          </div>

          {/* Column 2: 6 Simulated ML Pipeline Modules */}
          <div>
            <div className="flex items-center justify-between mb-3">
              <h4 className="font-semibold text-slate-900">Demonstration ML Modules</h4>
              <span className="font-mono text-[11px] font-semibold px-2 py-0.5 rounded bg-steel-tint text-steel border border-steel-border">
                6 Configured
              </span>
            </div>
            <ul className="space-y-2">
              <li className="p-2.5 rounded bg-canvas border border-hairline">
                <div className="font-medium text-slate-800">1. MobileNetV3 Faster R-CNN Detection</div>
                <div className="text-[11px] text-slate-500">
                  Strictly non-YOLO person detection and bounding box extraction.
                </div>
              </li>
              <li className="p-2.5 rounded bg-canvas border border-hairline">
                <div className="font-medium text-slate-800">2. ByteTrack / IoU Association</div>
                <div className="text-[11px] text-slate-500">
                  Primary subject tracking and bystander exclusion via ATM spatial zone polygon.
                </div>
              </li>
              <li className="p-2.5 rounded bg-canvas border border-hairline">
                <div className="font-medium text-slate-800">3. 3D Head Pose Estimation</div>
                <div className="text-[11px] text-slate-500">
                  Deterministic yaw/pitch/roll scoring for frontal candidate selection.
                </div>
              </li>
              <li className="p-2.5 rounded bg-canvas border border-hairline">
                <div className="font-medium text-slate-800">4. Occlusion & Blur IQA Scoring</div>
                <div className="text-[11px] text-slate-500">
                  Laplacian sharpness, illumination, and cap/hand occlusion assessment.
                </div>
              </li>
              <li className="p-2.5 rounded bg-canvas border border-hairline">
                <div className="font-medium text-slate-800">5. Non-Destructive Super-Resolution</div>
                <div className="text-[11px] text-slate-500">
                  Lanczos/ESPCN upscale with permanent burned ENHANCED label (original untouched).
                </div>
              </li>
              <li className="p-2.5 rounded bg-canvas border border-hairline">
                <div className="font-medium text-slate-800">6. ISO-8583 ATM Switch Demuxer</div>
                <div className="text-[11px] text-slate-500">
                  Sub-second timestamp correlation between terminal transactions and video feeds.
                </div>
              </li>
            </ul>
          </div>
        </div>

        <div className="px-5 py-3 bg-canvas border-t border-hairline flex items-center justify-between text-[11px] text-slate-500">
          <span>Strix PS04 &bull; Architecture Verification v2.4</span>
          <button
            onClick={onClose}
            className="px-3 py-1 bg-white border border-hairline hover:bg-slate-50 text-slate-700 rounded font-medium transition-colors"
          >
            Close Matrix
          </button>
        </div>
      </div>
    </div>
  );
};
