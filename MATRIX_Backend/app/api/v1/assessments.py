from __future__ import annotations

import io
import json
import logging
import math
import re
from datetime import datetime, timezone
from typing import Annotated, Any
from uuid import UUID

# Pre-compiled pattern for numbered list items (1. / 1) / 10. / 10) etc.)
_NUMBERED_LIST_RE = re.compile(r"^\d+[.)]\s+")

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.units import inch, mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, ListFlowable, ListItem, Table, TableStyle, KeepTogether, Image
from reportlab.graphics.shapes import Drawing, String, Rect
from reportlab.lib.utils import ImageReader
from xml.sax.saxutils import escape

from app.api.dependencies.auth import get_app_settings, get_authenticated_user
from app.core.config import Settings
from app.repositories.profiles import (
    ProfileConfigurationError, ProfileDataError, ProfileDatabaseError,
    ProfileNotFoundError, SupabaseProfilesRepository,
)
from app.api.v1.me import get_profiles_repository
from app.services.supabase_jwt import AuthenticatedUser

router = APIRouter(tags=["Agentic Assessments"])
ISO_CURRENCIES = set(("AED AFN ALL AMD ANG AOA ARS AUD AWG AZN BAM BBD BDT BGN BHD BIF BMD BND BOB BRL BSD BTN BWP BYN BZD CAD CDF CHF CLP CNY COP CRC CUP CVE CZK DJF DKK DOP DZD EGP ERN ETB EUR FJD FKP GBP GEL GHS GIP GMD GNF GTQ GYD HKD HNL HTG HUF IDR ILS INR IQD IRR ISK JMD JOD JPY KES KGS KHR KMF KPW KRW KWD KYD KZT LAK LBP LKR LRD LSL LYD MAD MDL MGA MKD MMK MNT MOP MRU MUR MVR MWK MXN MYR MZN NAD NGN NIO NOK NPR NZD OMR PAB PEN PGK PHP PKR PLN PYG QAR RON RSD RUB RWF SAR SBD SCR SDG SEK SGD SHP SLE SLL SOS SRD SSP STN SVC SYP SZL THB TJS TMT TND TOP TRY TTD TWD TZS UAH UGX USD UYU UZS VES VND VUV WST XAF XCD XCG XOF XPF YER ZAR ZMW ZWG ZWL").split())
logger = logging.getLogger(__name__)

class AssessmentInput(BaseModel):
    product_name: str = Field(min_length=1, max_length=200)
    target_market: str = Field(min_length=1, max_length=120)
    decision_type: str = Field(min_length=1, max_length=80)
    currency: str = Field(min_length=3, max_length=3)
    product_category: str = Field(min_length=1, max_length=120)
    launch_stage: str = Field(min_length=1, max_length=40)
    planned_selling_price: float = Field(gt=0, allow_inf_nan=False)
    expected_sales_quantity: float = Field(gt=0, allow_inf_nan=False)
    estimated_unit_cost: float = Field(ge=0, allow_inf_nan=False)
    planned_marketing_budget: float = Field(ge=0, allow_inf_nan=False)
    intended_launch_period: str = Field(default="", max_length=120)

    @field_validator("product_name", "target_market", "decision_type", "product_category", "launch_stage")
    @classmethod
    def strip_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field is required.")
        return value

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        value = value.strip().upper()
        if value not in ISO_CURRENCIES:
            raise ValueError("Use a valid ISO 4217 currency code.")
        return value

    @field_validator("launch_stage")
    @classmethod
    def require_prelaunch(cls, value: str) -> str:
        if value.lower() != "pre_launch":
            raise ValueError("The connected n8n workflow currently supports pre_launch only.")
        return "pre_launch"


def _service_key(settings: Settings) -> str:
    key = settings.supabase_service_role_key
    if key is None or not key.get_secret_value() or not settings.supabase_url.startswith("https://"):
        raise RuntimeError("Server-side Supabase service configuration is missing")
    return key.get_secret_value()

async def _db(settings: Settings, method: str, table: str, *, params: dict[str, str], body: Any = None, prefer: str = "") -> Any:
    key = _service_key(settings)
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if prefer:
        headers["Prefer"] = prefer
    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
        response = await client.request(method, f"{settings.supabase_url.rstrip('/')}/rest/v1/{table}", params=params, json=body, headers=headers)
        response.raise_for_status()
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

async def _storage_upload(settings: Settings, path: str, pdf_bytes: bytes) -> None:
    key = _service_key(settings)
    url = f"{settings.supabase_url.rstrip('/')}/storage/v1/object/{settings.matrix_report_bucket}/{path}"
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/pdf", "x-upsert": "true"}
    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
        response = await client.post(url, content=pdf_bytes, headers=headers)
        response.raise_for_status()


def _extract_report_text(value: Any, depth: int = 0) -> str:
    """Extract a report string from common n8n Webhook response shapes."""
    if depth > 8 or value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = [_extract_report_text(item, depth + 1) for item in value]
        return "\n\n".join(part for part in parts if part)
    if isinstance(value, dict):
        # Prefer explicit report/output fields, avoiding arbitrary metadata.
        for key in ("report_text", "final_report", "report", "output", "markdown", "text", "content", "answer"):
            if key in value:
                text = _extract_report_text(value[key], depth + 1)
                if text:
                    return text
        # Common n8n wrappers.
        for key in ("data", "response", "result", "body"):
            if key in value:
                text = _extract_report_text(value[key], depth + 1)
                if text:
                    return text
    return ""


def _normalize_agent_payload(payload: Any, input_data: dict[str, Any]) -> dict[str, Any]:
    """Normalize n8n output shapes into MATRIX's persisted report contract."""
    if isinstance(payload, dict):
        explicit_status = str(payload.get("status", "")).strip().lower()
        if explicit_status in {"error", "failed", "failure"}:
            return payload
        if explicit_status in {"success", "completed", "ok"}:
            normalized = dict(payload)
            text = _extract_report_text(payload)
            if text and not normalized.get("report_text"):
                normalized["report_text"] = text
            normalized.setdefault("product", {
                "product_name": input_data.get("product_name", ""),
                "product_category": input_data.get("product_category", ""),
                "target_market": input_data.get("target_market", ""),
                "currency": input_data.get("currency", ""),
            })
            normalized.setdefault("generated_at", datetime.now(timezone.utc).isoformat())
            return normalized

    report_text = _extract_report_text(payload)
    if report_text:
        # n8n commonly returns [{ "output": "..." }] or { "output": "..." }
        # even when the workflow itself completed successfully.
        return {
            "status": "success",
            "report_text": report_text,
            "product": {
                "product_name": input_data.get("product_name", ""),
                "product_category": input_data.get("product_category", ""),
                "target_market": input_data.get("target_market", ""),
                "currency": input_data.get("currency", ""),
            },
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "agent_layer_raw_response": payload,
        }
    return payload if isinstance(payload, dict) else {"status": "invalid", "raw_response": payload}


def _pdf_safe(text: str) -> str:
    """Keep the PDF renderable with ReportLab built-in latin-1 fonts.

    Covers common Unicode chars emitted by Gemini and other LLMs so the
    PDF does not silently replace them with '?' placeholders.
    """
    replacements: dict = {
        # Currency
        "₹": "INR ", "€": "EUR ", "£": "GBP ", "¥": "JPY ",
        "₩": "KRW ", "₦": "NGN ", "₫": "VND ", "₺": "TRY ",
        "₴": "UAH ", "₿": "BTC ",
        # Dashes and punctuation
        "—": "-", "–": "-", "−": "-",
        "•": "-", "‣": "-", "●": "-", "·": "-", "―": "-",
        "’": "'", "‘": "'", "“": '"', "”": '"',
        "…": "...",
        # Symbols
        "©": "(c)", "®": "(R)", "™": "(TM)",
        "°": " deg", "±": "+/-", "×": "x", "÷": "/",
        "≤": "<=", "≥": ">=", "≠": "!=", "∞": "inf",
        "→": "->", "←": "<-", "↔": "<->", "⇒": "=>",
        "✓": "OK", "✔": "OK", "✘": "X", "✗": "X",
        # Superscripts
        "²": "^2", "³": "^3", "¹": "^1",
        # Spaces
        " ": " ", " ": " ", " ": " ", "​": "",
        # Fractions
        "¼": "1/4", "½": "1/2", "¾": "3/4",
        # Other
        "█": "#", "■": "#", "░": ".",
    }
    for old_ch, new_ch in replacements.items():
        text = text.replace(old_ch, new_ch)
    return text.encode("latin-1", "replace").decode("latin-1")


def _inline_markup(safe_escaped: str) -> str:
    """Convert **bold** and *italic* in an already-XML-escaped string to ReportLab tags.

    The input must be XML-escaped before calling this so that entity refs
    like &amp; are preserved. Bold and italic patterns are matched non-greedily.
    """
    # Bold: **text**
    result = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", safe_escaped, flags=re.DOTALL)
    # Italic: *text* (not **text**)
    result = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", result)
    # Italic: _text_ (not __text__)
    result = re.sub(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)", r"<i>\1</i>", result)
    return result


def _markdown_to_story(report_text: str, styles: dict[str, Any]) -> list[Any]:
    """Convert a Markdown/plain-text report to a ReportLab story list.

    Handles headings (H1–H3), horizontal rules, bullet lists (-, *, +),
    numbered lists (1. / 1) / 10. / 10)), bold (**text**), and italic (*text*).
    """
    story: list[Any] = []
    body = styles["BodyText"]
    in_code_block = False
    for raw_line in report_text.splitlines():
        line = raw_line.strip()
        # Toggle code-block suppression; don't render fenced code lines.
        if line.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue
        if not line:
            story.append(Spacer(1, 5))
            continue
        if line.startswith("#### "):
            story.append(Paragraph(escape(_pdf_safe(line[5:])), styles["Sub"]))
            continue
        if line.startswith("### "):
            story.append(Paragraph(escape(_pdf_safe(line[4:])), styles["Heading3"]))
            continue
        if line.startswith("## "):
            story.append(Paragraph(escape(_pdf_safe(line[3:])), styles["Heading2"]))
            story.append(Spacer(1, 3))
            continue
        if line.startswith("# "):
            story.append(Paragraph(escape(_pdf_safe(line[2:])), styles["Heading1"]))
            story.append(Spacer(1, 4))
            continue
        if re.match(r"^-{3,}$|^\*{3,}$|^_{3,}$", line):
            story.append(Spacer(1, 6))
            continue
        # Bullet list items
        bullet = line.startswith(("- ", "* ", "+ "))
        # Numbered list: "1. ", "1) ", "10. ", "10) " etc.
        numbered_m = re.match(r"^\d+[.)]\s+", line)
        if bullet:
            line = line[2:]
        elif numbered_m:
            line = line[numbered_m.end():]
        # Apply inline markup (bold/italic) to the already-safe text.
        safe = _inline_markup(escape(_pdf_safe(line)))
        prefix = "- " if (bullet or numbered_m) else ""
        story.append(Paragraph(prefix + safe, body))
    return story



def _report_value(value: Any) -> str:
    """Convert a structured agent value into readable report text without inventing facts."""
    if value is None:
        return "Not provided by the Agent Layer"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, indent=2, default=str)
    return str(value)


def _report_paragraph(value: Any, style: Any) -> Paragraph:
    text = escape(_pdf_safe(_report_value(value))).replace("\n", "<br/>")
    return Paragraph(text, style)



def _pdf_bytes(result: dict[str, Any], assessment_id: str, input_data: dict[str, Any] | None = None) -> bytes:
    """Generate the production MATRIX-branded assessment PDF from the actual Agent Layer result."""
    import os as _os
    output = io.BytesIO()

    # ── Color palette ─────────────────────────────────────────────────────────
    navy      = colors.HexColor("#101A35")
    dark_navy = colors.HexColor("#24234F")
    purple    = colors.HexColor("#6D4BC3")
    lt_purple = colors.HexColor("#A98BEA")
    lavender  = colors.HexColor("#F5F3FF")
    lav_mid   = colors.HexColor("#E8E4FA")
    white     = colors.white
    grey      = colors.HexColor("#6B7280")
    charcoal  = colors.HexColor("#1F2937")
    border_c  = colors.HexColor("#D5D0F0")
    go_green  = colors.HexColor("#16A34A")
    nogo_red  = colors.HexColor("#DC2626")
    cond_amber= colors.HexColor("#D97706")
    muted_txt = colors.HexColor("#9CA3AF")

    LOGO = r"C:\\Users\\Dell\\Downloads\\MATRIX_Complete_Starter_Admin_Fix\\MATRIX_Frontend\\public\\brand\\matrix-mark.jpg"

    # ── Layout constants ───────────────────────────────────────────────────────
    LM = 18 * mm   # left margin
    RM = 18 * mm   # right margin
    TM = 22 * mm   # top margin (body starts below header)
    BM = 20 * mm   # bottom margin (body ends above footer)
    PW = A4[0]     # 595.28 pt
    PH = A4[1]     # 841.89 pt
    BODY_W = PW - LM - RM   # usable body width ≈ 559 pt

    doc = SimpleDocTemplate(
        output, pagesize=A4,
        rightMargin=RM, leftMargin=LM,
        topMargin=TM + 10 * mm,   # extra for header bar
        bottomMargin=BM + 8 * mm,
        title=f"MATRIX Product Assessment Report - {assessment_id}",
        author="MATRIX by Tanishq Tomar",
    )

    # ── Styles ─────────────────────────────────────────────────────────────────
    base = getSampleStyleSheet()

    def S(name, parent="Normal", **kw) -> ParagraphStyle:
        return ParagraphStyle(f"MX_{name}", parent=base[parent], **kw)

    styles = {
        # Cover
        "CoverEyebrow": S("CoverEyebrow", fontName="Helvetica-Bold", fontSize=8, leading=11,
                           textColor=grey, spaceAfter=4, alignment=TA_CENTER, letterSpacing=2),
        "CoverTitle":   S("CoverTitle",   fontName="Helvetica-Bold", fontSize=28, leading=34,
                           textColor=navy, spaceAfter=6, alignment=TA_CENTER),
        "CoverSub":     S("CoverSub",     fontName="Helvetica",      fontSize=11, leading=16,
                           textColor=grey, spaceAfter=14, alignment=TA_CENTER),
        "MetaLabel":    S("MetaLabel",    fontName="Helvetica",      fontSize=7.5, leading=10,
                           textColor=grey, spaceAfter=1),
        "MetaValue":    S("MetaValue",    fontName="Helvetica-Bold", fontSize=10, leading=13,
                           textColor=navy),
        # Sections
        "Section":      S("Section",  "Heading1", fontName="Helvetica-Bold", fontSize=13, leading=17,
                           textColor=navy, spaceBefore=10, spaceAfter=5, keepWithNext=True),
        "Sub":          S("Sub",      "Heading2", fontName="Helvetica-Bold", fontSize=10, leading=13,
                           textColor=dark_navy, spaceBefore=6, spaceAfter=4, keepWithNext=True),
        "Body":         S("Body",     "BodyText", fontName="Helvetica",      fontSize=8.5, leading=12,
                           textColor=charcoal, spaceAfter=4, wordWrap="CJK"),
        "Small":        S("Small",    "BodyText", fontName="Helvetica",      fontSize=7,   leading=9.5,
                           textColor=grey, spaceAfter=3),
        # Table cells
        "Cell":         S("Cell",     "BodyText", fontName="Helvetica",      fontSize=7.5, leading=10,
                           textColor=charcoal),
        "CellHead":     S("CellHead", "BodyText", fontName="Helvetica-Bold", fontSize=7.5, leading=10,
                           textColor=white),
        # KPI
        "KpiVal":       S("KpiVal",   "Normal",   fontName="Helvetica-Bold", fontSize=18, leading=22,
                           textColor=white, alignment=TA_CENTER),
        "KpiLbl":       S("KpiLbl",   "Normal",   fontName="Helvetica",      fontSize=7.5, leading=10,
                           textColor=lt_purple, alignment=TA_CENTER, spaceAfter=2),
        # Markdown compat aliases
    }
    styles.update({
        "Heading1": styles["Section"], "Heading2": styles["Sub"],
        "Heading3": styles["Sub"],     "BodyText":  styles["Body"],
    })

    # ── Helper: safe paragraph ─────────────────────────────────────────────────
    def para(text: Any, st="Body") -> Paragraph:
        return _report_paragraph(text, styles[st])

    # ── Helper: section heading card ───────────────────────────────────────────
    def section(title: str) -> list:
        return [Paragraph(escape(_pdf_safe(title)), styles["Section"]), Spacer(1, 2)]

    # ── Helper: styled data table ──────────────────────────────────────────────
    def make_table(rows: list, widths: list, header=True) -> Table:
        converted = []
        for ri, row in enumerate(rows):
            converted.append([
                Paragraph(escape(_pdf_safe(str(cell))).replace("\n", "<br/>"),
                          styles["CellHead"] if header and ri == 0 else styles["Cell"])
                for cell in row
            ])
        t = Table(converted, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
        cmds = [
            ("GRID",          (0, 0), (-1, -1), 0.4, border_c),
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING",   (0, 0), (-1, -1), 5),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 5),
            ("TOPPADDING",    (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("ROWBACKGROUNDS",(0, 1), (-1, -1), [white, lavender]),
        ]
        if header:
            cmds.append(("BACKGROUND", (0, 0), (-1, 0), dark_navy))
            cmds.append(("ROUNDEDCORNERS", [4, 4, 0, 0]))
        t.setStyle(TableStyle(cmds))
        return t

    # ── Extract data ───────────────────────────────────────────────────────────
    product  = result.get("product") or {}
    data     = input_data or {}
    name     = product.get("product_name")     or data.get("product_name")     or "Product Assessment"
    category = product.get("product_category") or data.get("product_category") or "Not specified"
    market   = product.get("target_market")    or data.get("target_market")    or "Not specified"
    currency = product.get("currency")          or data.get("currency")         or "USD"
    launch_p = data.get("intended_launch_period") or "Not specified"
    dec_type = data.get("decision_type") or "Pre-Launch"

    decision_raw   = result.get("decision_report") or result.get("decision") or result.get("final_decision") or ""
    decision_text  = _extract_report_text(decision_raw) or _report_value(decision_raw)
    decision_match = re.search(r"(CONDITIONAL\s+GO|NO\s+GO|GO|DEFER|LAUNCH|DO\s+NOT\s+LAUNCH)", decision_text, re.I)
    decision       = decision_match.group(1).upper() if decision_match else "See analysis"
    conf_match     = re.search(r"confidence\s*[:=-]\s*([A-Za-z]+(?:\s+\d+%?)?|\d+%?)", decision_text, re.I)
    confidence     = conf_match.group(1).upper() if conf_match else "N/A"

    # Decision color
    if re.search(r"\bNO\s+GO\b", decision, re.I):
        dec_color = nogo_red
    elif re.search(r"\bCONDITIONAL\b", decision, re.I):
        dec_color = cond_amber
    elif re.search(r"\bGO\b", decision, re.I) or re.search(r"\bLAUNCH\b", decision, re.I):
        dec_color = go_green
    else:
        dec_color = grey

    # Financial
    price     = data.get("planned_selling_price")
    quantity  = data.get("expected_sales_quantity")
    unit_cost = data.get("estimated_unit_cost")
    marketing = data.get("planned_marketing_budget")
    financial = None
    if all(isinstance(v, (int, float)) and math.isfinite(float(v)) for v in (price, quantity, unit_cost, marketing)):
        price, quantity, unit_cost, marketing = map(float, (price, quantity, unit_cost, marketing))
        revenue    = price * quantity
        total_cost = unit_cost * quantity + marketing
        profit     = revenue - total_cost
        margin     = (profit / revenue * 100) if revenue else 0.0
        financial  = dict(quantity=quantity, revenue=revenue, unit_cost=unit_cost,
                         marketing=marketing, total_cost=total_cost, profit=profit,
                         margin=margin, price=price)

    roi_txt = f"{financial['margin']:.1f}%" if financial else "N/A"

    # ── PAGE DECORATION CALLBACK ───────────────────────────────────────────────
    def page_decor(canvas, page_doc):
        canvas.saveState()
        pn   = page_doc.page
        logo_w = 32 * mm
        logo_h = logo_w * (270 / 315)   # preserve 315×270 aspect ratio

        # ── Watermark (behind everything) ──────────────────────────────────────
        if _os.path.isfile(LOGO):
            canvas.saveState()
            canvas.setFillAlpha(0.04)
            wm_size = 160 * mm
            wm_x = (PW - wm_size) / 2
            wm_y = (PH - wm_size) / 2
            canvas.drawImage(LOGO, wm_x, wm_y, width=wm_size, height=wm_size * (270/315),
                             mask="auto", preserveAspectRatio=True)
            canvas.restoreState()

        # ── Header bar ─────────────────────────────────────────────────────────
        canvas.setStrokeColor(border_c)
        canvas.setLineWidth(0.5)
        canvas.line(LM, PH - 14 * mm, PW - RM, PH - 14 * mm)

        if _os.path.isfile(LOGO):
            canvas.drawImage(LOGO, LM, PH - 13 * mm, width=logo_w, height=logo_h,
                             mask="auto", preserveAspectRatio=True)

        canvas.setFont("Helvetica-Bold", 7.5)
        canvas.setFillColor(purple)
        canvas.drawString(LM + logo_w + 4 * mm, PH - 8.5 * mm, "MATRIX")
        canvas.setFont("Helvetica", 6.5)
        canvas.setFillColor(grey)
        canvas.drawString(LM + logo_w + 4 * mm, PH - 11.5 * mm, "by Tanishq Tomar")

        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(muted_txt)
        canvas.drawRightString(PW - RM, PH - 8.5 * mm, "CONFIDENTIAL ASSESSMENT")

        # ── Footer bar ─────────────────────────────────────────────────────────
        canvas.setStrokeColor(border_c)
        canvas.line(LM, BM, PW - RM, BM)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(grey)
        canvas.drawString(LM, BM - 5 * mm,
                          "MATRIX by Tanishq Tomar  |  Product Assessment Report")
        canvas.drawRightString(PW - RM, BM - 5 * mm,
                               f"Page {pn} of {page_doc.page}")
        canvas.restoreState()

    # ── STORY FACTORY ──────────────────────────────────────────────
    # ReportLab flowables are stateful; consumed on the first doc.build() call.
    # Factory function ensures a fresh story list for every build pass.
    def _make_story() -> list[Any]:
        story: list[Any] = []
        # ── COVER PAGE ─────────────────────────────────────────────────────────────
        # Logo centered at top of body
        if _os.path.isfile(LOGO):
            logo_w_cov = 28 * mm
            logo_h_cov = logo_w_cov * (270 / 315)
            logo_img = Image(LOGO, width=logo_w_cov, height=logo_h_cov)
            logo_img.hAlign = "CENTER"
            story.append(logo_img)
            story.append(Spacer(1, 2 * mm))

        # Brand name + founder credit (centered)
        story.append(Paragraph(
            '<font color="#6D4BC3"><b>MATRIX</b></font>'
            '  <font color="#6B7280" size="8">by Tanishq Tomar</font>',
            S("BrandCover", alignment=TA_CENTER, fontName="Helvetica-Bold", fontSize=15,
              leading=19, spaceAfter=8, textColor=navy)
        ))
        story.append(Spacer(1, 4 * mm))
        story.append(Paragraph("PRODUCT MARKET INTELLIGENCE", styles["CoverEyebrow"]))
        story.append(Paragraph("Product Assessment Report", styles["CoverTitle"]))
        story.append(Paragraph(
            "Pre-Launch Market Intelligence, Risk Analysis &amp; Launch Recommendation",
            styles["CoverSub"]
        ))

        # Purple decorative rule
        dec_line = Drawing(BODY_W, 6)
        dec_line.add(Rect(BODY_W / 2 - 22, 1, 44, 4, fillColor=purple, strokeColor=purple,
                          rx=2, ry=2))
        story.append(dec_line)
        story.append(Spacer(1, 7 * mm))

        # Metadata grid — 3 columns × 2 rows
        def meta_cell(label: str, value: str) -> list:
            return [Paragraph(escape(label), styles["MetaLabel"]),
                    Paragraph(escape(_pdf_safe(value)), styles["MetaValue"])]

        col_w = BODY_W / 3 - 2 * mm
        meta_rows = [
            [meta_cell("Product",         name),
             meta_cell("Target Market",   market),
             meta_cell("Assessment Type", dec_type.replace("_", " ").title())],
            [meta_cell("Category",        category),
             meta_cell("Currency",        currency),
             meta_cell("Intended Launch", launch_p)],
        ]
        for meta_row in meta_rows:
            t = Table([meta_row], colWidths=[col_w] * 3)
            t.setStyle(TableStyle([
                ("VALIGN",        (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING",   (0, 0), (-1, -1), 8),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
                ("TOPPADDING",    (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                ("BOX",           (0, 0), (-1, -1), 0.4, border_c),
                ("LINEAFTER",     (0, 0), (-2, -1), 0.4, border_c),
                ("BACKGROUND",    (0, 0), (-1, -1), white),
            ]))
            story.append(t)
            story.append(Spacer(1, 2 * mm))

        story.append(Spacer(1, 6 * mm))

        # ── EXECUTIVE SUMMARY CARD ─────────────────────────────────────────────────
        # Strip markdown headings, bold markers and bullet chars from the preview snippet
        _exec_clean = re.sub(r"#{1,6}\s*", "", decision_text)
        _exec_clean = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", _exec_clean)
        _exec_clean = re.sub(r"_{1,2}([^_]+)_{1,2}", r"\1", _exec_clean)
        _exec_clean = re.sub(r"^\s*[-*+]\s+", "", _exec_clean, flags=re.MULTILINE)
        _exec_clean = re.sub(r"\n{2,}", " ", _exec_clean).strip()
        exec_text = _exec_clean[:600] if len(_exec_clean) > 600 else _exec_clean
        exec_text = exec_text.strip() or "See the full decision analysis in this report."
        exec_para = Paragraph(escape(_pdf_safe(exec_text)), styles["Body"])
        exec_card = Table(
            [[Paragraph('<b><font color="#6D4BC3">Executive Summary</font></b>',
                        S("ExecHead", fontName="Helvetica-Bold", fontSize=12, leading=16,
                          textColor=purple, spaceAfter=5))],
             [exec_para]],
            colWidths=[BODY_W - 16]
        )
        exec_card.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), lavender),
            ("LEFTPADDING",   (0, 0), (-1, -1), 12),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 12),
            ("TOPPADDING",    (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ("BOX",           (0, 0), (-1, -1), 0.6, border_c),
            ("ROUNDEDCORNERS",(0, 0), (-1, -1), [6, 6, 6, 6]),
        ]))
        story.append(exec_card)
        story.append(Spacer(1, 5 * mm))

        # ── DECISION / KPI DARK CARD ───────────────────────────────────────────────
        kpi_col_w = (BODY_W - 2) / 3

        def _kpi_col(label: str, value: str, val_color=white) -> list:
            return [
                Paragraph(escape(label), styles["KpiLbl"]),
                Paragraph(escape(_pdf_safe(value)),
                          S(f"KpiV_{label[:4]}", fontName="Helvetica-Bold", fontSize=18, leading=22,
                            alignment=TA_CENTER, textColor=val_color)),
            ]

        dec_val_color = dec_color
        kpi_data = [[
            _kpi_col("Final Decision",      decision,   dec_val_color),
            _kpi_col("Confidence Score",    confidence, white),
            _kpi_col("Expected ROI (3 Yr)", roi_txt,    lt_purple),
        ]]
        kpi_t = Table(kpi_data, colWidths=[kpi_col_w] * 3)
        kpi_t.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), dark_navy),
            ("LINEAFTER",     (0, 0), (-2, -1), 0.5, colors.HexColor("#3A3870")),
            ("LEFTPADDING",   (0, 0), (-1, -1), 10),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
            ("TOPPADDING",    (0, 0), (-1, -1), 12),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("ROUNDEDCORNERS",(0, 0), (-1, -1), [6, 6, 6, 6]),
        ]))
        story.append(kpi_t)
        story.append(Spacer(1, 5 * mm))

        # ── FINANCIAL SECTION ──────────────────────────────────────────────────────
        if financial:
            story += section("Baseline Financial Projection")

            # KPI cards row
            def fin_card(label: str, value: str) -> Table:
                inner = [
                    [Paragraph(escape(label), S("FKL", fontName="Helvetica", fontSize=7, leading=9,
                                                textColor=grey))],
                    [Paragraph(escape(value), S("FKV", fontName="Helvetica-Bold", fontSize=10,
                                                leading=13, textColor=navy))],
                ]
                w = (BODY_W - 10) / 3
                c = Table(inner, colWidths=[w])
                c.setStyle(TableStyle([
                    ("BOX",           (0, 0), (-1, -1), 0.5, border_c),
                    ("BACKGROUND",    (0, 0), (-1, -1), white),
                    ("LEFTPADDING",   (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
                    ("TOPPADDING",    (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ]))
                return c

            kpis = [
                ("Expected Quantity",     f"{financial['quantity']:,.0f} units"),
                ("Projected Revenue",     f"{currency} {financial['revenue']:,.2f}"),
                ("Estimated Total Cost",  f"{currency} {financial['total_cost']:,.2f}"),
                ("Estimated Profit/Loss", f"{currency} {financial['profit']:,.2f}"),
                ("Profit Margin",         f"{financial['margin']:.1f}%"),
                ("Marketing Budget",      f"{currency} {financial['marketing']:,.2f}"),
            ]
            for i in range(0, len(kpis), 3):
                row = [fin_card(lbl, val) for lbl, val in kpis[i:i+3]]
                # Pad to 3 columns with invisible spacers (not empty Tables which render as gray boxes)
                while len(row) < 3:
                    spacer_w = (BODY_W - 10) / 3
                    empty = Table([[Spacer(spacer_w, 1)]], colWidths=[spacer_w])
                    empty.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), white)]))
                    row.append(empty)
                row_t = Table([row], colWidths=[(BODY_W - 10) / 3 + 5] * 3)
                row_t.setStyle(TableStyle([
                    ("VALIGN",        (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING",   (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING",  (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]))
                story.append(row_t)

            story.append(Spacer(1, 4 * mm))
            story += section("Scenario Comparison")
            scenarios = []
            for label, factor in (("Base Case", 1.0), ("Optimistic (+15%)", 1.15), ("Downside (-15%)", 0.85)):
                q    = financial["quantity"] * factor
                rev  = financial["price"] * q
                cost = financial["unit_cost"] * q + financial["marketing"]
                prof = rev - cost
                marg = (prof / rev * 100) if rev else 0.0
                scenarios.append([label, f"{q:,.0f}",
                                   f"{currency} {rev:,.2f}", f"{currency} {cost:,.2f}",
                                   f"{currency} {prof:,.2f}", f"{marg:.1f}%"])
            story.append(make_table(
                [["Scenario", "Units", "Revenue", "Total Cost", "Profit / Loss", "Margin"]] + scenarios,
                [38*mm, 18*mm, 32*mm, 32*mm, 32*mm, 18*mm]
            ))
            story.append(para(
                "Sensitivity cases apply an explicit ±15% quantity assumption to the submitted baseline. "
                "They are not market forecasts.", "Small"
            ))
            story.append(Spacer(1, 4 * mm))

            # Revenue vs Cost bar chart
            story += section("Revenue vs Cost Overview")
            maxval  = max(financial["revenue"], financial["total_cost"], 1.0)
            chart_w = BODY_W
            bar_x   = 72.0
            bar_max = chart_w - bar_x - 20.0
            chart   = Drawing(chart_w, 90)
            # Revenue bar
            chart.add(String(0, 68, "Revenue", fontName="Helvetica", fontSize=8, fillColor=navy))
            rev_w = bar_max * financial["revenue"] / maxval
            chart.add(Rect(bar_x, 62, rev_w, 14, fillColor=purple, strokeColor=purple, rx=2, ry=2))
            chart.add(String(bar_x + rev_w + 4, 67,
                             f"{currency} {financial['revenue']:,.0f}",
                             fontName="Helvetica-Bold", fontSize=7, fillColor=purple))
            # Cost bar
            chart.add(String(0, 36, "Total Cost", fontName="Helvetica", fontSize=8, fillColor=navy))
            cost_w = bar_max * financial["total_cost"] / maxval
            chart.add(Rect(bar_x, 30, cost_w, 14, fillColor=lt_purple,
                           strokeColor=lt_purple, rx=2, ry=2))
            chart.add(String(bar_x + cost_w + 4, 35,
                             f"{currency} {financial['total_cost']:,.0f}",
                             fontName="Helvetica-Bold", fontSize=7, fillColor=lt_purple))
            # Profit line
            chart.add(String(0, 7, f"Profit / Loss: {currency} {financial['profit']:,.0f}  |  Margin: {financial['margin']:.1f}%",
                             fontName="Helvetica", fontSize=7.5,
                             fillColor=go_green if financial["profit"] >= 0 else nogo_red))
            story.append(chart)
            story.append(Spacer(1, 4 * mm))
        else:
            story += section("Financial Projection")
            story.append(para(
                "The submitted assessment did not include all required numeric financial inputs. "
                "Financial KPI cards and scenario calculations are omitted rather than estimated.", "Body"
            ))

        # ── AGENT LAYER SECTIONS ───────────────────────────────────────────────────
        sections_data = [
            ("Executive Summary and Decision",         result.get("decision_report")     or result.get("final_decision")),
            ("Market Research",                        result.get("research_report")     or result.get("market_research")),
            ("Risk Analysis",                          result.get("risk_report")         or result.get("risk_analysis")),
            ("Simulation Analysis",                    result.get("simulation_report")   or result.get("simulation_analysis")),
            ("Simulation Calculation",                 result.get("simulation_calculation")),
            ("External Market Factors & Event Impact", result.get("external_market_factors")),
        ]
        rendered_any = False
        for heading, value in sections_data:
            if value is None or value == "":
                continue
            story += section(heading)
            text = _extract_report_text(value) or _report_value(value)
            story.extend(_markdown_to_story(text, styles))
            rendered_any = True

        consolidated = _extract_report_text(
            result.get("report_text") or result.get("final_report") or result.get("output")
        )
        if consolidated and not any(
            consolidated.strip() == _extract_report_text(v).strip()
            for _, v in sections_data if v is not None
        ):
            story += section("Complete Agent Layer Report")
            story.extend(_markdown_to_story(consolidated, styles))
            rendered_any = True

        if not rendered_any:
            story += section("Agent Layer Result")
            story.extend(_markdown_to_story(_report_value(result), styles))

        # ── LIMITATIONS ────────────────────────────────────────────────────────────
        story += section("Limitations and Next Actions")
        story.append(para(
            "This report reflects the information returned by the MATRIX Agent Layer and the values "
            "submitted for this assessment. Any assumptions or missing evidence stated by the agents "
            "should be reviewed before making a launch decision.", "Body"
        ))
        story.append(Spacer(1, 2 * mm))
        story.append(para(
            f"Assessment ID: {assessment_id}  |  "
            f"Generated: {result.get('generated_at', datetime.now(timezone.utc).isoformat())}", "Small"
        ))

        return story

    # ── BUILD ──────────────────────────────────────────────────────────────────
    # First pass: count pages
    _count_buf = io.BytesIO()
    _count_doc = SimpleDocTemplate(
        _count_buf, pagesize=A4, rightMargin=RM, leftMargin=LM,
        topMargin=TM + 10 * mm, bottomMargin=BM + 8 * mm,
    )
    _total_pages = [0]
    def _count_cb(canvas, doc):
        _total_pages[0] = max(_total_pages[0], doc.page)
    _count_doc.build(_make_story(), onFirstPage=_count_cb, onLaterPages=_count_cb)
    total_pages = _total_pages[0]

    # Second pass: real PDF with correct "Page X of N"
    def page_decor_final(canvas, page_doc):
        canvas.saveState()
        pn = page_doc.page
        logo_w = 32 * mm
        logo_h = logo_w * (270 / 315)

        # Watermark — JPEG has no alpha channel, use canvas alpha state only (no mask="auto")
        if _os.path.isfile(LOGO):
            canvas.saveState()
            canvas.setFillAlpha(0.06)
            canvas.setStrokeAlpha(0.06)
            wm_size = 160 * mm
            wm_h    = wm_size * (270 / 315)
            canvas.drawImage(LOGO, (PW - wm_size) / 2, (PH - wm_h) / 2,
                             width=wm_size, height=wm_h,
                             preserveAspectRatio=True)
            canvas.restoreState()

        # Header line
        canvas.setStrokeColor(border_c)
        canvas.setLineWidth(0.5)
        canvas.line(LM, PH - 14 * mm, PW - RM, PH - 14 * mm)

        # Logo in header — no mask needed for JPEG
        if _os.path.isfile(LOGO):
            canvas.drawImage(LOGO, LM, PH - 13 * mm, width=logo_w, height=logo_h,
                             preserveAspectRatio=True)

        canvas.setFont("Helvetica-Bold", 7.5)
        canvas.setFillColor(purple)
        canvas.drawString(LM + logo_w + 4 * mm, PH - 8.5 * mm, "MATRIX")
        canvas.setFont("Helvetica", 6.5)
        canvas.setFillColor(grey)
        canvas.drawString(LM + logo_w + 4 * mm, PH - 11.5 * mm, "by Tanishq Tomar")
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(muted_txt)
        canvas.drawRightString(PW - RM, PH - 8.5 * mm, "CONFIDENTIAL ASSESSMENT")

        # Footer
        canvas.setStrokeColor(border_c)
        canvas.line(LM, BM, PW - RM, BM)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(grey)
        canvas.drawString(LM, BM - 5 * mm,
                          "MATRIX by Tanishq Tomar  |  Product Assessment Report")
        canvas.drawRightString(PW - RM, BM - 5 * mm, f"Page {pn} of {total_pages}")
        canvas.restoreState()

    doc.build(_make_story(), onFirstPage=page_decor_final, onLaterPages=page_decor_final)
    return output.getvalue()



async def _require_access(user: AuthenticatedUser, profiles: SupabaseProfilesRepository) -> None:
    try:
        profile = await profiles.get_for_user(user_id=user.user_id, access_token=user.access_token)
    except (ProfileConfigurationError, ProfileDataError, ProfileDatabaseError, ProfileNotFoundError) as exc:
        raise HTTPException(503, "MATRIX access status is temporarily unavailable.") from exc
    if profile.activation_completed_at is None:
        raise HTTPException(403, "Complete MATRIX activation before running an assessment.")

@router.post("/assessments")
async def create_assessment(body: AssessmentInput, user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)], settings: Annotated[Settings, Depends(get_app_settings)], profiles: Annotated[SupabaseProfilesRepository, Depends(get_profiles_repository)]) -> dict[str, Any]:
    await _require_access(user, profiles)
    if not settings.n8n_webhook_url.startswith("https://") or not settings.n8n_auth_header_name or settings.n8n_auth_header_value is None or not settings.n8n_auth_header_value.get_secret_value():
        raise HTTPException(503, "Agent Layer integration is not configured on the server.")
    data = body.model_dump()
    owner = str(user.user_id)
    try:
        product_rows = await _db(settings, "GET", "products", params={"select": "id", "user_id": f"eq.{owner}", "product_name": f"eq.{data['product_name']}", "order": "created_at.desc", "limit": "1"})
        if product_rows:
            product_id = product_rows[0]["id"]
        else:
            product_rows = await _db(settings, "POST", "products", params={"select": "id"}, body={"user_id": owner, "product_name": data["product_name"], "category": data["product_category"], "price": data["planned_selling_price"], "features": []}, prefer="return=representation")
            product_id = product_rows[0]["id"]
        analysis_rows = await _db(settings, "POST", "analyses", params={"select": "id,created_at"}, body={"user_id": owner, "product_id": product_id, "analysis_type": "pre_launch", "status": "pending", "result": {}}, prefer="return=representation")
        analysis_id = analysis_rows[0]["id"]
    except Exception as exc:
        logger.exception("assessment_persist_start_failed user_id=%s", owner)
        raise HTTPException(503, "Could not create the assessment record. Check backend Supabase configuration.") from exc
    headers = {settings.n8n_auth_header_name: settings.n8n_auth_header_value.get_secret_value(), "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=settings.n8n_timeout_seconds, follow_redirects=False) as client:
            response = await client.post(settings.n8n_webhook_url, json=data, headers=headers)
    except httpx.TimeoutException as exc:
        # The workflow may still be running. Leave pending and never retry automatically.
        raise HTTPException(504, detail={"code": "workflow_outcome_unknown", "message": "The Agent Layer did not respond before the timeout. Its execution may still be running; do not resubmit until its outcome is checked.", "assessment_id": analysis_id}) from exc
    except httpx.HTTPError as exc:
        try:
            await _db(settings, "PATCH", "analyses", params={"id": f"eq.{analysis_id}", "user_id": f"eq.{owner}"}, body={"status": "failed", "result": {"error": "workflow_transport_error"}})
        except Exception: logger.exception("assessment_failure_persist_failed")
        raise HTTPException(502, "The Agent Layer could not be reached.") from exc
    try:
        raw_payload = response.json()
    except ValueError:
        raw_payload = response.text
    payload = _normalize_agent_payload(raw_payload, data)
    if not response.is_success or not isinstance(payload, dict) or payload.get("status") != "success":
        logger.warning(
            "agent_layer_unsuccessful assessment_id=%s http_status=%s payload_type=%s payload_keys=%s",
            analysis_id, response.status_code, type(raw_payload).__name__,
            list(raw_payload.keys())[:20] if isinstance(raw_payload, dict) else None,
        )
        try:
            await _db(settings, "PATCH", "analyses", params={"id": f"eq.{analysis_id}", "user_id": f"eq.{owner}"}, body={"status": "failed", "result": payload if isinstance(payload, dict) else {"error": "invalid_workflow_response"}})
        except Exception: logger.exception("assessment_failure_persist_failed")
        raise HTTPException(400 if response.status_code == 400 else 502, detail={"message": payload.get("message", "Agent Layer returned an unsuccessful response."), "errors": payload.get("errors", [])})
    try:
        await _db(settings, "PATCH", "analyses", params={"id": f"eq.{analysis_id}", "user_id": f"eq.{owner}"}, body={"status": "completed", "result": payload})
    except Exception as exc:
        logger.exception("assessment_result_persist_failed assessment_id=%s", analysis_id)
        raise HTTPException(503, detail={"message": "The workflow completed, but its result could not be saved. Do not rerun until the assessment is checked.", "assessment_id": analysis_id}) from exc
    report_state = "not_generated"
    try:
        pdf = _pdf_bytes(payload, analysis_id, data)
        file_path = f"{owner}/{analysis_id}/report.pdf"
        await _storage_upload(settings, file_path, pdf)
        await _db(settings, "POST", "reports", params={"select": "id,file_path,created_at"}, body={"user_id": owner, "analysis_id": analysis_id, "file_path": file_path}, prefer="return=representation")
        report_state = "generated"
    except Exception:
        # Assessment remains completed; report failure must not invalidate the AI result.
        logger.exception("report_generation_or_upload_failed assessment_id=%s", analysis_id)
    return {"assessment_id": analysis_id, "status": "completed", "result": payload, "report_status": report_state}

@router.get("/assessments")
async def list_assessments(user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)], settings: Annotated[Settings, Depends(get_app_settings)], profiles: Annotated[SupabaseProfilesRepository, Depends(get_profiles_repository)], limit: int = Query(50, ge=1, le=100)) -> dict[str, Any]:
    await _require_access(user, profiles)
    try:
        rows = await _db(settings, "GET", "analyses", params={"select": "id,product_id,analysis_type,status,created_at,result", "user_id": f"eq.{user.user_id}", "order": "created_at.desc", "limit": str(limit)})
        return {"items": rows}
    except Exception as exc: raise HTTPException(503, "Assessment history is unavailable.") from exc

@router.get("/assessments/{assessment_id}")
async def get_assessment(assessment_id: UUID, user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)], settings: Annotated[Settings, Depends(get_app_settings)], profiles: Annotated[SupabaseProfilesRepository, Depends(get_profiles_repository)]) -> dict[str, Any]:
    await _require_access(user, profiles)
    try:
        rows = await _db(settings, "GET", "analyses", params={"select": "id,product_id,analysis_type,status,created_at,result", "id": f"eq.{assessment_id}", "user_id": f"eq.{user.user_id}", "limit": "1"})
        if not rows: raise HTTPException(404, "Assessment not found.")
        return rows[0]
    except HTTPException: raise
    except Exception as exc: raise HTTPException(503, "Assessment is unavailable.") from exc

@router.get("/reports")
async def list_reports(user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)], settings: Annotated[Settings, Depends(get_app_settings)], profiles: Annotated[SupabaseProfilesRepository, Depends(get_profiles_repository)], limit: int = Query(50, ge=1, le=100)) -> dict[str, Any]:
    await _require_access(user, profiles)
    try:
        rows = await _db(settings, "GET", "reports", params={"select": "id,analysis_id,file_path,created_at", "user_id": f"eq.{user.user_id}", "order": "created_at.desc", "limit": str(limit)})
        return {"items": rows}
    except Exception as exc: raise HTTPException(503, "Report history is unavailable.") from exc

@router.get("/reports/{report_id}/url")
async def get_report_url(report_id: UUID, user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)], settings: Annotated[Settings, Depends(get_app_settings)], profiles: Annotated[SupabaseProfilesRepository, Depends(get_profiles_repository)]) -> dict[str, str]:
    await _require_access(user, profiles)
    try:
        rows = await _db(settings, "GET", "reports", params={"select": "id,file_path", "id": f"eq.{report_id}", "user_id": f"eq.{user.user_id}", "limit": "1"})
        if not rows: raise HTTPException(404, "Report not found.")
        key = _service_key(settings)
        url = f"{settings.supabase_url.rstrip('/')}/storage/v1/object/sign/{settings.matrix_report_bucket}/{rows[0]['file_path']}"
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
            response = await client.post(url, json={"expiresIn": 300}, headers={"apikey": key, "Authorization": f"Bearer {key}"})
            response.raise_for_status(); signed = response.json()
        path = signed.get("signedURL") or signed.get("signedUrl")
        if not path: raise RuntimeError("Signed URL missing")
        if path.startswith("http"): return {"url": path}
        return {"url": f"{settings.supabase_url.rstrip('/')}/storage/v1{path}"}
    except HTTPException: raise
    except Exception as exc: raise HTTPException(503, "Report download is unavailable.") from exc
