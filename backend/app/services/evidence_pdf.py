"""ReportLab Platypus evidence sheet PDF generator."""

import hashlib
import io
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

import reportlab
from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    Image as RLImage,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from backend.app.config import FAKE_BANNER_TEXT, HUMAN_VERIFICATION_NOTICE, Settings
from backend.app.models import Clip, FrameRecord, Run, Search, User
from backend.app.services.storage import from_rel

_UNICODE_FONT_NAME: str | None = None
_FONT_CHECKED = False


def _ensure_unicode_font() -> str | None:
    """Register a UTF-8 TTF font once for non-ASCII names without crashing."""
    global _UNICODE_FONT_NAME, _FONT_CHECKED
    if _FONT_CHECKED:
        return _UNICODE_FONT_NAME
    _FONT_CHECKED = True

    rl_fonts = Path(reportlab.__file__).resolve().parent / "fonts"
    candidates = [
        Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
        Path("/Library/Fonts/Arial Unicode.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        rl_fonts / "Vera.ttf",
    ]
    for path in candidates:
        if path.is_file():
            try:
                pdfmetrics.registerFont(TTFont("StrixUnicode", str(path)))
                _UNICODE_FONT_NAME = "StrixUnicode"
                break
            except Exception:
                continue
    return _UNICODE_FONT_NAME


def _fmt_num(value: float) -> str:
    """Format a float cleanly without trailing zeros or scientific notation."""
    text = f"{float(value):.3f}".rstrip("0").rstrip(".")
    return text or "0"


def _para(text: object, style: ParagraphStyle, unicode_style: ParagraphStyle) -> Paragraph:
    """Render XML-escaped text safely, switching to Unicode TTF if non-ASCII."""
    raw = "" if text is None else str(text)
    escaped = escape(raw).replace("\n", "<br/>")
    chosen = style if raw.isascii() else unicode_style
    return Paragraph(escaped, chosen)


def _safe_rl_image(
    rel_path: str | None,
    data_dir: Path,
    max_w: float,
    max_h: float,
    fallback_style: ParagraphStyle,
) -> RLImage | Paragraph:
    """Load an image safely within DATA_DIR; return 'image unavailable' if missing/corrupt."""
    if not rel_path:
        return Paragraph("image unavailable", fallback_style)
    try:
        abs_path = from_rel(rel_path, data_dir, allowed_roots=("outputs", "uploads"))
    except Exception:
        return Paragraph("image unavailable", fallback_style)
    if not abs_path.is_file():
        return Paragraph("image unavailable", fallback_style)

    try:
        with PILImage.open(abs_path) as im:
            w, h = im.size
        if w <= 0 or h <= 0:
            return Paragraph("image unavailable", fallback_style)
        scale = min(max_w / float(w), max_h / float(h), 1.0)
        return RLImage(str(abs_path), width=w * scale, height=h * scale)
    except Exception:
        return Paragraph("image unavailable", fallback_style)


class _NumberedCanvas(canvas.Canvas):
    """Two-pass ReportLab canvas drawing the mandatory notice and Page X of Y footer."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._saved_page_states: list[dict] = []

    def showPage(self) -> None:
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        total_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_footer(total_pages)
            super().showPage()
        super().save()

    def _draw_footer(self, page_count: int) -> None:
        width, _height = A4
        self.saveState()
        self.setStrokeColor(colors.HexColor("#CBD5E1"))
        self.setLineWidth(0.5)
        self.line(15 * mm, 14 * mm, width - 15 * mm, 14 * mm)
        self.setFont("Helvetica", 7.5)
        self.setFillColor(colors.HexColor("#334155"))
        self.drawString(15 * mm, 9 * mm, HUMAN_VERIFICATION_NOTICE)
        self.drawRightString(
            width - 15 * mm, 9 * mm, f"Page {self._pageNumber} of {page_count}"
        )
        self.restoreState()


def build_evidence_pdf(
    *,
    run: Run,
    clip: Clip,
    frames: list[FrameRecord],
    investigator: User,
    settings: Settings,
    search: Search | None = None,
) -> tuple[bytes, str, int]:
    """Generate an Evidence Sheet PDF and return (pdf_bytes, sha256_hex, frame_count)."""
    unicode_font = _ensure_unicode_font() or "Helvetica"
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "StrixTitle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=16,
        spaceAfter=4,
        textColor=colors.HexColor("#0F172A"),
    )
    h2_style = ParagraphStyle(
        "StrixH2",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=11.5,
        spaceBefore=10,
        spaceAfter=4,
        textColor=colors.HexColor("#1E293B"),
    )
    body_style = ParagraphStyle(
        "StrixBody",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=11,
        wordWrap="CJK",
    )
    body_unicode = ParagraphStyle(
        "StrixBodyUnicode",
        parent=body_style,
        fontName=unicode_font,
    )
    bold_style = ParagraphStyle(
        "StrixBold",
        parent=body_style,
        fontName="Helvetica-Bold",
    )
    caption_style = ParagraphStyle(
        "StrixCaption",
        parent=body_style,
        fontSize=7.5,
        leading=9.5,
        textColor=colors.HexColor("#334155"),
    )
    warn_style = ParagraphStyle(
        "StrixWarn",
        parent=bold_style,
        fontSize=10,
        leading=13,
        textColor=colors.HexColor("#991B1B"),
    )

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=20 * mm,
        pageCompression=0,
        title=f"Evidence Sheet EV-{run.id}",
    )

    story: list = []
    story.append(Paragraph(f"Evidence Sheet — EV-{run.id}", title_style))
    story.append(
        Paragraph(
            escape(HUMAN_VERIFICATION_NOTICE),
            caption_style,
        )
    )
    story.append(Spacer(1, 4 * mm))

    if run.pipeline_mode == "fake":
        warn_tbl = Table(
            [[Paragraph(f"WARNING: {FAKE_BANNER_TEXT} — NOT FOR REAL INVESTIGATIVE USE", warn_style)]],
            colWidths=[180 * mm],
        )
        warn_tbl.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FEE2E2")),
                    ("BOX", (0, 0), (-1, -1), 1.0, colors.HexColor("#DC2626")),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ]
            )
        )
        story.append(warn_tbl)
        story.append(Spacer(1, 4 * mm))

    if run.served_from_demo_pack:
        demo_tbl = Table(
            [
                [
                    Paragraph(
                        "RESULT SERVED FROM A PRE-COMPUTED DEMO PACK "
                        "(not computed live for this upload)",
                        warn_style,
                    )
                ]
            ],
            colWidths=[180 * mm],
        )
        demo_tbl.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FEF3C7")),
                    ("BOX", (0, 0), (-1, -1), 1.0, colors.HexColor("#D97706")),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ]
            )
        )
        story.append(demo_tbl)
        story.append(Spacer(1, 3 * mm))

    if run.link_low_margin:
        margin_tbl = Table(
            [
                [
                    Paragraph(
                        "WARNING: link_low_margin=True — narrow margin between candidate tracks; "
                        "verify person identity carefully.",
                        warn_style,
                    )
                ]
            ],
            colWidths=[180 * mm],
        )
        margin_tbl.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FEF3C7")),
                    ("BOX", (0, 0), (-1, -1), 1.0, colors.HexColor("#D97706")),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ]
            )
        )
        story.append(margin_tbl)
        story.append(Spacer(1, 3 * mm))

    raw_res = run.result_json or {}
    generated_local = datetime.now(ZoneInfo(settings.display_tz)).strftime(
        "%Y-%m-%d %H:%M:%S %Z"
    )
    model_labels = (
        ["FAKE PIPELINE"] if run.pipeline_mode == "fake" else settings.model_labels_list
    )

    meta_rows = [
        ("Evidence ID", f"EV-{run.id}"),
        ("Generated At", generated_local),
        ("Investigator", f"{investigator.full_name} ({investigator.username})"),
        ("Clip Filename", clip.original_filename),
        ("Clip SHA-256", clip.sha256),
        ("Transaction Time", run.transaction_time.isoformat()),
        (
            "Clip Start Time",
            f"{clip.clip_start_time.isoformat() if clip.clip_start_time else 'N/A'} "
            f"(source: {clip.clip_start_source})",
        ),
        (
            "Offset / Window",
            f"offset={run.tx_offset_sec:.2f}s, window=+/-{run.window_sec:g}s, "
            f"fps={run.sample_fps:g}, tracker={run.tracker}",
        ),
        (
            "Link Confidence",
            f"{raw_res.get('link_confidence') or 'N/A'} — {raw_res.get('link_reason') or 'N/A'}",
        ),
        ("Link Low Margin", str(bool(run.link_low_margin))),
        ("Selection Reason", raw_res.get("selection_reason") or "N/A"),
        ("Pipeline Mode", run.pipeline_mode),
        ("Served From Demo Pack", str(bool(run.served_from_demo_pack))),
        ("Model Labels", " | ".join(model_labels)),
    ]
    meta_table = Table(
        [
            [
                _para(label, bold_style, body_unicode),
                _para(val, body_style, body_unicode),
            ]
            for label, val in meta_rows
        ],
        colWidths=[42 * mm, 138 * mm],
    )
    meta_table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F8FAFC")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(meta_table)
    story.append(Spacer(1, 5 * mm))

    req_fps = (
        run.requested_sample_fps
        if run.requested_sample_fps is not None
        else raw_res.get("requested_sample_fps")
    )
    eff_fps = (
        run.effective_sample_fps
        if run.effective_sample_fps is not None
        else raw_res.get("effective_sample_fps")
    )
    cov_start = (
        run.coverage_start_sec
        if run.coverage_start_sec is not None
        else raw_res.get("coverage_start_sec")
    )
    cov_end = (
        run.coverage_end_sec
        if run.coverage_end_sec is not None
        else raw_res.get("coverage_end_sec")
    )
    run_warnings = (
        list(run.warnings)
        if run.warnings is not None
        else list(raw_res.get("warnings") or [])
    )

    sampling_line: str | None = None
    if req_fps is not None and eff_fps is not None and cov_start is not None and cov_end is not None:
        sampling_line = (
            f"Sampling: requested {_fmt_num(req_fps)} fps, used {_fmt_num(eff_fps)} fps; "
            f"coverage {_fmt_num(cov_start)} s to {_fmt_num(cov_end)} s of the clip"
        )
    elif req_fps is not None and eff_fps is not None:
        sampling_line = f"Sampling: requested {_fmt_num(req_fps)} fps, used {_fmt_num(eff_fps)} fps"
    elif cov_start is not None and cov_end is not None:
        sampling_line = f"Coverage: {_fmt_num(cov_start)} s to {_fmt_num(cov_end)} s of the clip"

    reduced_line = (
        "Sampling was reduced; some brief appearances may be missed."
        if req_fps is not None and eff_fps is not None and (float(eff_fps) + 1e-9 < float(req_fps))
        else None
    )

    if sampling_line or reduced_line or run_warnings:
        story.append(Paragraph("Sampling &amp; Pipeline Warnings", h2_style))
        if sampling_line:
            story.append(_para(sampling_line, body_style, body_unicode))
        if reduced_line:
            story.append(_para(reduced_line, warn_style, body_unicode))
        for warning_text in run_warnings:
            story.append(_para(f"Warning: {warning_text}", body_style, body_unicode))
        story.append(Spacer(1, 4 * mm))

    selected_frames = [f for f in frames if f.selected]
    chosen_frames = selected_frames if selected_frames else frames
    selection_label = "Selected Frames" if selected_frames else "Candidate Best Frames"
    story.append(Paragraph(f"{selection_label} ({len(chosen_frames)})", h2_style))
    story.append(
        Paragraph(
            "Flags are model estimates and can be wrong in both directions. A human must verify.",
            caption_style,
        )
    )
    story.append(Spacer(1, 2 * mm))

    data_root = settings.resolved_data_dir
    if not chosen_frames:
        reason_text = raw_res.get("selection_reason") or raw_res.get("link_reason") or "No candidate frames found."
        story.append(
            _para(
                f"No frames available. Reason: {reason_text}",
                body_style,
                body_unicode,
            )
        )
    else:
        frame_table_data: list[list] = [
            [
                Paragraph("Visual Evidence", bold_style),
                Paragraph("Frame Details", bold_style),
            ]
        ]
        for fr in chosen_frames:
            primary_rel = fr.crop_path_rel or fr.frame_path_rel
            if fr.enhanced and fr.enhancement and fr.enhancement.get("enhanced_path"):
                orig_img = _safe_rl_image(
                    primary_rel, data_root, 34 * mm, 32 * mm, caption_style
                )
                enh_meta = fr.enhancement
                enh_img = _safe_rl_image(
                    enh_meta.get("enhanced_path"),
                    data_root,
                    34 * mm,
                    32 * mm,
                    caption_style,
                )
                enh_caption = (
                    f"ENHANCED ({enh_meta.get('method', 'unknown')}, "
                    f"{enh_meta.get('scale', '?')}x, "
                    f"{enh_meta.get('model_version', 'unknown')})"
                )
                visual_cell = Table(
                    [
                        [orig_img, enh_img],
                        [
                            Paragraph("Original", caption_style),
                            _para(enh_caption, caption_style, body_unicode),
                        ],
                    ],
                    colWidths=[36 * mm, 36 * mm],
                )
                visual_cell.setStyle(
                    TableStyle(
                        [
                            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                            ("TOPPADDING", (0, 0), (-1, -1), 2),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                        ]
                    )
                )
            else:
                visual_cell = _safe_rl_image(
                    primary_rel, data_root, 70 * mm, 42 * mm, caption_style
                )

            scores_map = fr.flag_scores or {}
            if fr.flags:
                formatted_flags = []
                for flag in fr.flags:
                    if flag in scores_map:
                        formatted_flags.append(
                            f"{flag} (model estimate {float(scores_map[flag]):.2f})"
                        )
                    else:
                        formatted_flags.append(flag)
                flags_str = ", ".join(formatted_flags)
            else:
                flags_str = "none"

            face_box_str = str(fr.face_box) if fr.face_box is not None else "N/A"
            details_text = (
                f"Frame ID: {fr.frame_id} | Timestamp: {fr.timestamp_sec:.2f}s\n"
                f"Quality Score: {fr.quality_score:.3f} | Reliability: {fr.reliability}\n"
                f"Match Ready: {fr.match_ready if fr.match_ready is not None else 'N/A'} | Face Box: {face_box_str}\n"
                f"Flags: {flags_str}\n"
                f"Rank Reason: {fr.rank_reason or 'N/A'}"
            )
            frame_table_data.append(
                [visual_cell, _para(details_text, body_style, body_unicode)]
            )

        frame_table = Table(frame_table_data, colWidths=[76 * mm, 104 * mm], repeatRows=1)
        frame_table.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E2E8F0")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("ALIGN", (0, 1), (0, -1), "CENTER"),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        story.append(frame_table)

    if search is not None:
        story.append(Spacer(1, 5 * mm))
        story.append(
            Paragraph(f"Cross-Clip Similarity Search Results (Search #{search.id})", h2_style)
        )
        story.append(
            Paragraph(
                "Score note: uncalibrated similarity, tune on sample data. "
                "Scope: frames from processed runs only.",
                caption_style,
            )
        )
        story.append(Spacer(1, 2 * mm))
        matches = search.results or []
        if not matches:
            story.append(Paragraph("No cross-clip matches recorded.", body_style))
        else:
            search_rows: list[list] = [
                [
                    Paragraph("Filename", bold_style),
                    Paragraph("Run / Frame", bold_style),
                    Paragraph("Time", bold_style),
                    Paragraph("Score", bold_style),
                    Paragraph("Reliability / Flags", bold_style),
                ]
            ]
            for m in matches:
                flags = ", ".join(m.get("flags") or []) or "none"
                search_rows.append(
                    [
                        _para(f"{m.get('filename', '')}\n({m.get('clip_id', '')})", body_style, body_unicode),
                        _para(f"run {m.get('run_id')} / {m.get('frame_id')}", body_style, body_unicode),
                        Paragraph(f"{float(m.get('timestamp_sec', 0.0)):.2f}s", body_style),
                        Paragraph(f"{float(m.get('score', 0.0)):.4f}", body_style),
                        _para(f"{m.get('reliability', '')} ({flags})", body_style, body_unicode),
                    ]
                )
            search_table = Table(
                search_rows,
                colWidths=[54 * mm, 32 * mm, 18 * mm, 22 * mm, 54 * mm],
                repeatRows=1,
            )
            search_table.setStyle(
                TableStyle(
                    [
                        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")),
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E2E8F0")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("TOPPADDING", (0, 0), (-1, -1), 3),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ]
                )
            )
            story.append(search_table)

    doc.build(story, canvasmaker=_NumberedCanvas)
    pdf_bytes = buf.getvalue()
    pdf_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    return pdf_bytes, pdf_sha256, len(chosen_frames)
