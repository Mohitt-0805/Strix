// Direct canvas rendering utilities adapted from docs/strix_prototype.html

export interface FaceOpts {
  isRaw?: boolean;
  yaw?: number;
  pitch?: number;
  blur?: number;
  dark?: number;
  glare?: boolean;
  handOcc?: boolean;
  showGuide?: boolean;
}

export interface CCTVOverlays {
  bbox?: boolean;
  landmarks?: boolean;
  clahe?: boolean;
}

export function computeOSDClock(baseTimestamp: string, offsetSec: number): string {
  try {
    const parts = baseTimestamp.split(' ');
    const timePart = parts[1] || '21:14:24';
    const [hh, mm, ss] = timePart.split(':').map(Number);
    const totalSec = hh * 3600 + mm * 60 + ss + offsetSec;
    const curH = Math.floor(totalSec / 3600) % 24;
    const curM = Math.floor((totalSec % 3600) / 60);
    const curS = Math.floor(totalSec % 60);
    const ms = Math.floor((offsetSec % 1) * 1000);
    return `${parts[0] || '2026-11-26'} ${String(curH).padStart(2, '0')}:${String(curM).padStart(2, '0')}:${String(curS).padStart(2, '0')}.${String(ms).padStart(3, '0')} IST`;
  } catch {
    return '2026-11-26 21:14:24.000 IST';
  }
}

export function drawForensicFace(canvas: HTMLCanvasElement | null, profile: any, opts: FaceOpts = {}) {
  if (!canvas) return;
  try {
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const w = canvas.width;
    const h = canvas.height;
    const {
      isRaw = false,
      yaw = 0,
      pitch = 0,
      blur = 0,
      dark = 0.12,
      glare = false,
      handOcc = false,
      showGuide = false,
    } = opts;

    ctx.save();
    ctx.clearRect(0, 0, w, h);

    // Monochrome/desaturated surveillance vestibule backdrop
    const bgLuma = Math.max(22, Math.round(74 - dark * 82));
    ctx.fillStyle = `rgb(${bgLuma}, ${bgLuma + 3}, ${bgLuma + 7})`;
    ctx.fillRect(0, 0, w, h);

    ctx.fillStyle = 'rgba(255,255,255,0.04)';
    ctx.fillRect(w * 0.15, 0, 2, h);
    ctx.fillRect(w * 0.85, 0, 2, h);

    const effBlur = isRaw ? Math.max(1.4, blur * 1.15) : Math.max(0, blur * 0.2);
    if (effBlur > 0.2) ctx.filter = `blur(${effBlur.toFixed(1)}px)`;

    const shiftX = (yaw / 45) * (w * 0.16);
    const shiftY = (-pitch / 30) * (h * 0.1);
    const cx = w * 0.5 + shiftX * 0.35;
    const cy = h * 0.52 + shiftY * 0.35;

    const lumaScale = isRaw ? 1 - dark * 0.65 : 1 - dark * 0.16;
    const sv = Math.max(58, Math.min(220, Math.round((profile?.skinTone || 170) * lumaScale)));
    const skinCol = isRaw ? `rgb(${sv},${sv},${sv})` : `rgb(${Math.min(232, sv + 6)},${sv},${Math.max(45, sv - 8)})`;
    const shVal = Math.max(24, sv - 42);
    const shCol = isRaw ? `rgb(${shVal},${shVal},${shVal})` : `rgb(${shVal + 3},${shVal},${Math.max(20, shVal - 5)})`;

    // Shoulders
    ctx.fillStyle = isRaw ? '#20242A' : '#252F3D';
    ctx.beginPath();
    ctx.ellipse(cx, h * 0.98, w * 0.42, h * 0.22, 0, Math.PI, 0);
    ctx.fill();

    // Neck
    ctx.fillStyle = shCol;
    ctx.fillRect(cx - w * 0.11, cy + h * 0.18, w * 0.22, h * 0.18);

    if (profile?.hairStyle === 'long') {
      ctx.fillStyle = '#1B2027';
      ctx.beginPath();
      ctx.ellipse(cx, cy + h * 0.04, w * 0.3, h * 0.35, 0, 0, Math.PI * 2);
      ctx.fill();
    }

    // Ears
    ctx.fillStyle = shCol;
    ctx.beginPath();
    ctx.ellipse(cx - w * 0.23, cy + h * 0.02, w * 0.035, h * 0.065, 0, 0, Math.PI * 2);
    ctx.ellipse(cx + w * 0.23, cy + h * 0.02, w * 0.035, h * 0.065, 0, 0, Math.PI * 2);
    ctx.fill();

    // Head
    const grad = ctx.createRadialGradient(cx - w * 0.05 + shiftX * 0.2, cy - h * 0.08, w * 0.04, cx, cy, w * 0.3);
    grad.addColorStop(0, skinCol);
    grad.addColorStop(1, shCol);
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.ellipse(cx, cy, w * 0.23, h * 0.28, 0, 0, Math.PI * 2);
    ctx.fill();

    const eyeY = cy - h * 0.03 + shiftY * 0.4;
    const lEyeX = cx - w * 0.085 + shiftX * 0.65;
    const rEyeX = cx + w * 0.085 + shiftX * 0.65;
    const noseX = cx + shiftX * 0.85;
    const noseY = cy + h * 0.05 + shiftY * 0.45;
    const mouthY = cy + h * 0.145 + shiftY * 0.45;

    // Brows
    ctx.strokeStyle = '#1E232A';
    ctx.lineWidth = Math.max(1.4, w * 0.017);
    ctx.lineCap = 'round';
    ctx.beginPath();
    ctx.moveTo(lEyeX - w * 0.05, eyeY - h * 0.04);
    ctx.quadraticCurveTo(lEyeX, eyeY - h * 0.06, lEyeX + w * 0.045, eyeY - h * 0.04);
    ctx.moveTo(rEyeX - w * 0.045, eyeY - h * 0.04);
    ctx.quadraticCurveTo(rEyeX, eyeY - h * 0.06, rEyeX + w * 0.05, eyeY - h * 0.04);
    ctx.stroke();

    // Eyes
    ctx.fillStyle = '#11151A';
    ctx.beginPath();
    ctx.ellipse(lEyeX, eyeY, w * 0.032, h * 0.022, 0, 0, Math.PI * 2);
    ctx.ellipse(rEyeX, eyeY, w * 0.032, h * 0.022, 0, 0, Math.PI * 2);
    ctx.fill();

    // Pupils / Catchlight
    if (!isRaw) {
      ctx.fillStyle = '#FFFFFF';
      ctx.beginPath();
      ctx.arc(lEyeX - 1, eyeY - 1, 1.2, 0, Math.PI * 2);
      ctx.arc(rEyeX - 1, eyeY - 1, 1.2, 0, Math.PI * 2);
      ctx.fill();
    }

    // Nose
    ctx.strokeStyle = shCol;
    ctx.lineWidth = Math.max(1.2, w * 0.015);
    ctx.beginPath();
    ctx.moveTo(noseX, eyeY + h * 0.01);
    ctx.lineTo(noseX - w * 0.015, noseY);
    ctx.lineTo(noseX + w * 0.015, noseY);
    ctx.stroke();

    // Mouth
    ctx.strokeStyle = '#3A2727';
    ctx.lineWidth = Math.max(1.4, w * 0.018);
    ctx.beginPath();
    ctx.moveTo(cx - w * 0.06 + shiftX * 0.7, mouthY);
    ctx.quadraticCurveTo(cx + shiftX * 0.7, mouthY + h * 0.01, cx + w * 0.06 + shiftX * 0.7, mouthY);
    ctx.stroke();

    // Beard
    if (profile?.beard) {
      ctx.fillStyle = isRaw ? 'rgba(25, 28, 33, 0.65)' : 'rgba(20, 24, 30, 0.75)';
      ctx.beginPath();
      ctx.ellipse(cx + shiftX * 0.6, cy + h * 0.17, w * 0.15, h * 0.11, 0, 0, Math.PI);
      ctx.fill();
    }

    // Cap / Occlusion
    if (profile?.cap) {
      ctx.fillStyle = '#1E232B';
      ctx.beginPath();
      ctx.ellipse(cx, cy - h * 0.16, w * 0.28, h * 0.14, 0, Math.PI, 0);
      ctx.fill();
      ctx.fillRect(cx - w * 0.32, cy - h * 0.16, w * 0.64, h * 0.04);
    }

    // Hand Occlusion
    if (handOcc) {
      ctx.fillStyle = isRaw ? 'rgba(70, 70, 70, 0.85)' : 'rgba(160, 120, 100, 0.85)';
      ctx.beginPath();
      ctx.ellipse(cx + w * 0.08, cy + h * 0.1, w * 0.12, h * 0.09, -0.3, 0, Math.PI * 2);
      ctx.fill();
    }

    // Glare
    if (glare) {
      const glareGrad = ctx.createRadialGradient(cx + w * 0.1, cy - h * 0.1, 2, cx + w * 0.1, cy - h * 0.1, w * 0.25);
      glareGrad.addColorStop(0, 'rgba(255,255,255,0.7)');
      glareGrad.addColorStop(1, 'rgba(255,255,255,0)');
      ctx.fillStyle = glareGrad;
      ctx.beginPath();
      ctx.arc(cx + w * 0.1, cy - h * 0.1, w * 0.25, 0, Math.PI * 2);
      ctx.fill();
    }

    // Alignment Guides
    if (showGuide && !isRaw) {
      ctx.strokeStyle = 'rgba(37, 99, 235, 0.75)';
      ctx.lineWidth = 1;
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(w * 0.1, eyeY);
      ctx.lineTo(w * 0.9, eyeY);
      ctx.moveTo(noseX, h * 0.1);
      ctx.lineTo(noseX, h * 0.9);
      ctx.stroke();
      ctx.setLineDash([]);

      const pts = [
        [lEyeX, eyeY],
        [rEyeX, eyeY],
        [noseX, noseY],
        [cx - w * 0.055 + shiftX * 0.7, mouthY],
        [cx + w * 0.055 + shiftX * 0.7, mouthY],
      ];
      pts.forEach(([px, py]) => {
        ctx.fillStyle = '#2563EB';
        ctx.beginPath();
        ctx.arc(px, py, 2.6, 0, Math.PI * 2);
        ctx.fill();
        ctx.strokeStyle = '#FFFFFF';
        ctx.lineWidth = 1;
        ctx.stroke();
      });
    }

    ctx.restore();
  } catch (e) {
    // Canvas context guard
  }
}

export function drawPersonSilhouette(
  ctx: CanvasRenderingContext2D,
  cx: number,
  topY: number,
  w: number,
  h: number,
  tone: number,
  reaching: boolean,
  hasCap: boolean
) {
  ctx.fillStyle = `rgb(${Math.max(24, tone - 28)}, ${Math.max(26, tone - 26)}, ${Math.max(30, tone - 22)})`;
  ctx.beginPath();
  ctx.ellipse(cx, topY + h * 0.5, w * 0.42, h * 0.38, 0, 0, Math.PI * 2);
  ctx.fill();

  ctx.fillStyle = `rgb(${Math.max(18, tone - 42)}, ${Math.max(20, tone - 40)}, ${Math.max(24, tone - 38)})`;
  ctx.fillRect(cx - w * 0.34, topY + h * 0.72, w * 0.68, h * 0.28);

  const headY = topY + h * 0.12;
  const headR = w * 0.24;
  ctx.fillStyle = `rgb(${tone}, ${tone - 2}, ${tone - 4})`;
  ctx.beginPath();
  ctx.arc(cx, headY, headR, 0, Math.PI * 2);
  ctx.fill();

  if (hasCap) {
    ctx.fillStyle = '#1E232B';
    ctx.beginPath();
    ctx.arc(cx, headY - headR * 0.2, headR * 1.05, Math.PI, 0);
    ctx.fill();
    ctx.fillRect(cx - headR * 1.2, headY - headR * 0.2, headR * 2.4, headR * 0.3);
  }

  if (reaching) {
    ctx.strokeStyle = `rgb(${Math.max(24, tone - 28)}, ${Math.max(26, tone - 26)}, ${Math.max(30, tone - 22)})`;
    ctx.lineWidth = w * 0.18;
    ctx.lineCap = 'round';
    ctx.beginPath();
    ctx.moveTo(cx - w * 0.22, topY + h * 0.36);
    ctx.lineTo(cx - w * 0.75, topY + h * 0.52);
    ctx.stroke();
  }
}

export function renderCCTVFrame(
  canvas: HTMLCanvasElement | null,
  activeCase: any,
  playbackTime: number,
  overlays: CCTVOverlays = {},
  isPlaying: boolean = false
) {
  if (!canvas || canvas.width === 0) return;
  try {
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const w = canvas.width;
    const h = canvas.height;

    const showBBox = overlays.bbox !== false;
    const showLandmarks = overlays.landmarks !== false;
    const claheOn = !!overlays.clahe;

    const isLowLight = activeCase?.conditions?.includes('Low-Light');
    const boost = claheOn ? 38 : isLowLight ? -16 : 12;

    ctx.save();
    ctx.clearRect(0, 0, w, h);

    // Vestibule walls & floor perspective
    const wallV = Math.max(18, Math.min(96, 44 + boost));
    ctx.fillStyle = `rgb(${wallV}, ${wallV + 3}, ${wallV + 7})`;
    ctx.fillRect(0, 0, w, h);

    const floorV = Math.max(14, wallV - 12);
    ctx.fillStyle = `rgb(${floorV}, ${floorV + 2}, ${floorV + 4})`;
    ctx.beginPath();
    ctx.moveTo(0, h);
    ctx.lineTo(w * 0.18, h * 0.68);
    ctx.lineTo(w * 0.85, h * 0.68);
    ctx.lineTo(w, h);
    ctx.closePath();
    ctx.fill();

    ctx.strokeStyle = `rgba(255,255,255,${claheOn ? 0.14 : 0.08})`;
    ctx.lineWidth = Math.max(1, w * 0.0014);
    ctx.beginPath();
    ctx.moveTo(w * 0.18, 0);
    ctx.lineTo(w * 0.18, h * 0.68);
    ctx.lineTo(0, h);
    ctx.moveTo(w * 0.85, 0);
    ctx.lineTo(w * 0.85, h * 0.68);
    ctx.lineTo(w, h);
    ctx.moveTo(w * 0.18, h * 0.68);
    ctx.lineTo(w * 0.85, h * 0.68);
    ctx.stroke();

    // ATM Terminal Fascia
    const atmX = w * 0.14;
    const atmY = h * 0.22;
    const atmW = w * 0.22;
    const atmH = h * 0.62;
    const atmV = Math.min(125, wallV + 22);
    ctx.fillStyle = `rgb(${atmV}, ${atmV + 3}, ${atmV + 6})`;
    ctx.fillRect(atmX, atmY, atmW, atmH);
    ctx.strokeStyle = 'rgba(0,0,0,0.4)';
    ctx.strokeRect(atmX, atmY, atmW, atmH);

    // ATM Screen Glow
    ctx.fillStyle = `rgba(191, 219, 254, ${claheOn ? 0.55 : 0.34})`;
    ctx.fillRect(atmX + atmW * 0.16, atmY + atmH * 0.14, atmW * 0.68, atmH * 0.24);

    // Keypad & Cash Slot
    ctx.fillStyle = `rgb(${atmV - 18}, ${atmV - 18}, ${atmV - 16})`;
    ctx.fillRect(atmX + atmW * 0.1, atmY + atmH * 0.45, atmW * 0.8, atmH * 0.08);
    ctx.fillStyle = '#090D12';
    ctx.fillRect(atmX + atmW * 0.22, atmY + atmH * 0.6, atmW * 0.56, atmH * 0.035);

    // Passing Bystander
    const bysProgress = (playbackTime * 0.04) % 1;
    const bx = w * (0.64 + bysProgress * 0.22);
    const by = h * 0.35;
    const bw = w * 0.1;
    const bh = h * 0.37;
    drawPersonSilhouette(ctx, bx, by, bw, bh, wallV + 14, false, false);

    if (showBBox) {
      ctx.strokeStyle = '#94A3B8';
      ctx.lineWidth = Math.max(1.3, w * 0.0018);
      ctx.setLineDash([4, 3]);
      ctx.strokeRect(bx - bw * 0.52, by - bh * 0.06, bw * 1.04, bh * 1.06);
      ctx.setLineDash([]);

      const fs = Math.max(10, Math.round(w * 0.013));
      ctx.font = `500 ${fs}px "IBM Plex Mono", monospace`;
      const bTag = 'TRACK-02 BYSTANDER';
      const tw = ctx.measureText(bTag).width + 10;
      ctx.fillStyle = 'rgba(15, 23, 42, 0.82)';
      ctx.fillRect(bx - bw * 0.52, by - bh * 0.06 - fs - 6, tw, fs + 6);
      ctx.fillStyle = '#CBD5E1';
      ctx.fillText(bTag, bx - bw * 0.52 + 5, by - bh * 0.06 - 4);
    }

    // Primary Customer at ATM Terminal
    let px = w * 0.43;
    const py = h * 0.25;
    let reaching = false;
    if (playbackTime < 3.5) {
      px = w * (0.6 - 0.17 * (playbackTime / 3.5));
    } else if (playbackTime > 32.0) {
      px = w * (0.43 + 0.22 * ((playbackTime - 32.0) / 4.0));
    } else {
      px = w * 0.43 + Math.sin(playbackTime * 0.75) * (w * 0.007);
      reaching = playbackTime >= 4.0 && playbackTime <= 28.0;
    }

    const pw = w * 0.17;
    const ph = h * 0.58;
    const subjV = Math.min(185, wallV + 48);
    drawPersonSilhouette(ctx, px, py, pw, ph, subjV, reaching, activeCase?.faceProfile?.cap || false);

    if (showBBox) {
      const boxX = px - pw * 0.56;
      const boxY = py - ph * 0.06;
      const boxW = pw * 1.12;
      const boxH = ph * 1.06;
      ctx.strokeStyle = '#2563EB';
      ctx.lineWidth = Math.max(1.8, w * 0.0022);
      ctx.strokeRect(boxX, boxY, boxW, boxH);

      // Face crop box
      const fx = px - pw * 0.23;
      const fy = py + ph * 0.01;
      const fw = pw * 0.46;
      const fh = ph * 0.22;
      ctx.strokeStyle = '#60A5FA';
      ctx.lineWidth = Math.max(1.5, w * 0.0018);
      ctx.strokeRect(fx, fy, fw, fh);

      const fs = Math.max(10, Math.round(w * 0.0135));
      ctx.font = `600 ${fs}px "IBM Plex Mono", monospace`;
      const pTag = `TRACK-01 PRIMARY • ${(activeCase?.matchConfidence || 98.4).toFixed(1)}%`;
      const tw = ctx.measureText(pTag).width + 12;
      ctx.fillStyle = '#1D4ED8';
      ctx.fillRect(boxX, boxY - fs - 7, tw, fs + 7);
      ctx.fillStyle = '#FFFFFF';
      ctx.fillText(pTag, boxX + 6, boxY - 5);

      if (showLandmarks) {
        ctx.fillStyle = '#93C5FD';
        const r = Math.max(1.4, w * 0.0018);
        for (let i = 0; i < 17; i++) {
          const ang = Math.PI * (0.12 + (i / 16) * 0.76);
          const lx = fx + fw * 0.5 + Math.cos(ang) * fw * 0.36;
          const ly = fy + fh * 0.46 + Math.sin(ang) * fh * 0.44;
          ctx.beginPath();
          ctx.arc(lx, ly, r, 0, Math.PI * 2);
          ctx.fill();
        }
      }
    }

    // Subtle scanlines
    ctx.fillStyle = 'rgba(0,0,0,0.08)';
    for (let y = 0; y < h; y += 4) ctx.fillRect(0, y, w, 1);

    // HUD Overlay
    const osdSize = Math.max(11, Math.round(w * 0.0155));
    ctx.font = `500 ${osdSize}px "IBM Plex Mono", monospace`;
    ctx.fillStyle = 'rgba(15, 23, 42, 0.68)';
    ctx.fillRect(10, 10, w - 20, osdSize + 12);

    const clockStr = computeOSDClock(activeCase?.timestamp || '2026-11-26 21:14:24', playbackTime);
    ctx.fillStyle = '#F1F5F9';
    ctx.fillText(`${activeCase?.atmId || 'ATM-JPR-014'}  ${(activeCase?.camera || 'CAM-01').split(' ')[0]}   ${clockStr}`, 18, 10 + osdSize + 2);

    const rightText = `${claheOn ? 'CLAHE-ON  ' : ''}24.0 FPS   REC`;
    const rw = ctx.measureText(rightText).width;
    ctx.fillText(rightText, w - rw - 28, 10 + osdSize + 2);

    // REC indicator dot
    ctx.fillStyle = Math.floor(playbackTime * 2) % 2 === 0 || !isPlaying ? '#EF4444' : '#7F1D1D';
    ctx.beginPath();
    ctx.arc(w - 18, 10 + (osdSize + 12) / 2, Math.max(3, w * 0.004), 0, Math.PI * 2);
    ctx.fill();

    ctx.restore();
  } catch (e) {
    // Prevent uncaught rendering errors
  }
}
