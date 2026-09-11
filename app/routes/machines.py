import io
import json
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import List, Optional
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from app.database.connection import get_db
from app.database.models import MachineStatus
from app.schemas.machine import MachineResponse, MachineCreate, MachineUpdate
from app.services import machine_service
from app.utils.excel_helper import get_report_logo, style_range, center_image_in_cell

router = APIRouter(prefix="/api/machines", tags=["machines"])

UTILIZATION_STATE_PATH = Path(__file__).resolve().parent.parent.parent / "utilization_state.json"


@router.get("", summary="Get all machines")
def get_machines(db: Session = Depends(get_db)):
    """
    Return the current status and metadata for all monitored machines,
    enriched with today's undetected_time from machine_utilization (0 if no data).
    """
    from datetime import date as date_type
    from app.database.models import MachineUtilization

    machines = machine_service.get_all_machines(db)
    today = date_type.today()

    # Build a map of mc_id -> today's undetected_time
    today_util = (
        db.query(MachineUtilization.mc_id, MachineUtilization.undetected_time)
        .filter(MachineUtilization.date == today)
        .all()
    )
    undetected_map = {row.mc_id: row.undetected_time for row in today_util}

    result = []
    for m in machines:
        machine_dict = {
            "id":             m.id,
            "mc_id":          m.mc_id,
            "name":           m.name,
            "image_url":      m.image_url,
            "video_url":      m.video_url,
            "status":         m.status,
            "detected_at":    m.detected_at,
            "camera_status":  m.camera_status,
            "created_at":     m.created_at,
            "updated_at":     m.updated_at,
            "undetected_time": undetected_map.get(m.mc_id, 0.0),
        }
        result.append(machine_dict)

    return result


from app.database.models import MachineUtilization

@router.get("/utilization/state", summary="Get day-wise utilization data from DB")
def get_utilization_state(
    from_date: Optional[datetime] = Query(None, alias="from", description="Start date (inclusive)"),
    to_date: Optional[datetime] = Query(None, alias="to", description="End date (inclusive)"),
    mc_ids: Optional[str] = Query(None, description="Comma-separated machine IDs, e.g. 'MC-001,MC-002'. Pass 'All' or omit to return all machines."),
    db: Session = Depends(get_db)
):
    """
    Returns one record per machine per calendar day within the given date range.
    The response is a list of day-wise utilization entries enriched with
    the machine's current image_url from MachineStatus.

    Use the `mc_ids` query parameter to filter by specific machines:
        ?from=2026-08-09&to=2026-09-08&mc_ids=MC-001,MC-002
        ?from=2026-08-09&to=2026-09-08&mc_ids=All   (or omit mc_ids — returns all machines)
    """
    # 1. Build image map from MachineStatus
    machine_statuses = db.query(MachineStatus).all()
    image_map = {ms.mc_id: ms.image_url for ms in machine_statuses}

    # 2. Query day-wise rows from MachineUtilization (no GROUP BY — raw daily records)
    query = db.query(MachineUtilization)

    if from_date:
        query = query.filter(MachineUtilization.date >= from_date.date())
    if to_date:
        query = query.filter(MachineUtilization.date <= to_date.date())

    # 3. Apply multi-machine filter (skip if not provided or value is "All")
    if mc_ids and mc_ids.strip().lower() != "all":
        selected_ids = [mid.strip() for mid in mc_ids.split(",") if mid.strip()]
        if selected_ids:
            query = query.filter(MachineUtilization.mc_id.in_(selected_ids))

    rows = query.order_by(MachineUtilization.date.desc()).all()

    # 4. Build response list — one entry per machine per day
    response_data = []
    for row in rows:
        response_data.append({
            "mc_id":                          row.mc_id,
            "date":                           str(row.date),
            "runtime":                        row.runtime,
            "downtime":                       row.downtime,
            "idle":                           row.idle,
            "total_available_time":           row.total_available_time,
            "total_available_time_formatted": row.total_available_time_formatted,
            "utilization_percent":            row.utilization_percent,
            "undetected_time":                row.undetected_time,
            "image_url":                      image_map.get(row.mc_id),
        })

    return response_data


def _seconds_to_hhmmss(seconds: float) -> str:
    """Convert a float of total seconds into a HH:MM:SS string (24-hr format)."""
    total = int(round(seconds))
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}:{m:02d}:{s:02d}"

@router.get("/utilization/download", summary="Download KPI utilization data as Excel")
def download_utilization_excel(
    from_date: Optional[datetime] = Query(None, alias="from", description="Start date (inclusive)"),
    to_date: Optional[datetime] = Query(None, alias="to", description="End date (inclusive)"),
    mc_ids: Optional[str] = Query(
        None,
        description="Comma-separated machine IDs, e.g. 'MC-001,MC-002'. Pass 'All' or omit to download all machines."
    ),
    db: Session = Depends(get_db)
):
    """
    Download the KPI utilization data visible on the KPI screen as an Excel (.xlsx) file.
    Accepts the same filters as /utilization/state:
        ?from=2026-08-09&to=2026-09-08&mc_ids=MC-001,MC-002
        ?from=2026-08-09&to=2026-09-08&mc_ids=All
    """
    # --- 1. Fetch data (same logic as /utilization/state) ---
    query = db.query(MachineUtilization)

    if from_date:
        query = query.filter(MachineUtilization.date >= from_date.date())
    if to_date:
        query = query.filter(MachineUtilization.date <= to_date.date())

    if mc_ids and mc_ids.strip().lower() != "all":
        selected_ids = [mid.strip() for mid in mc_ids.split(",") if mid.strip()]
        if selected_ids:
            query = query.filter(MachineUtilization.mc_id.in_(selected_ids))

    rows = query.order_by(MachineUtilization.date, MachineUtilization.mc_id).all()

    # --- 2. Build Excel workbook (Professional Industrial Report) ---
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "KPI Utilization"
    ws.views.sheetView[0].showGridLines = True

    headers = [
        "Date",
        "Machine ID",
        "Idle Time (HH:MM:SS)",
        "Runtime (HH:MM:SS)",
        "Downtime (HH:MM:SS)",
        "Utilization (%)",
    ]
    num_cols = len(headers)

    # 1. Top accent line
    ws.row_dimensions[1].height = 4
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=num_cols)
    style_range(ws, f"A1:{get_column_letter(num_cols)}1", fill=PatternFill("solid", fgColor="1F3864"))

    # 2. Header Block (Rows 2 - 4)
    ws.row_dimensions[2].height = 28
    ws.row_dimensions[3].height = 20
    ws.row_dimensions[4].height = 24

    # Insert corporate logo if available (centered horizontally in Column A)
    logo_img = get_report_logo(target_height=54)
    if logo_img:
        center_image_in_cell(ws, logo_img, col_idx=0, row_idx=1, col_width_chars=18, row_offset_px=8)

    # Date range formatting
    if from_date and to_date:
        date_str = f"{from_date.strftime('%d-%m-%Y')} to {to_date.strftime('%d-%m-%Y')}"
    elif from_date:
        date_str = f"From {from_date.strftime('%d-%m-%Y')}"
    elif to_date:
        date_str = f"Up to {to_date.strftime('%d-%m-%Y')}"
    else:
        date_str = "All Historical Dates"

    # Selected machines formatting (deduplicate IDs passed from frontend)
    selected_machine_ids = []
    if mc_ids and mc_ids.strip().lower() != "all":
        raw_ids = [mid.strip() for mid in mc_ids.split(",") if mid.strip()]
        selected_machine_ids = list(dict.fromkeys(raw_ids))

    if selected_machine_ids:
        if len(selected_machine_ids) > 10:
            machines_str = f"Machines: {', '.join(selected_machine_ids[:10])}... ({len(selected_machine_ids)} Total)"
        else:
            machines_str = f"Machines: {', '.join(selected_machine_ids)}"
    else:
        machines_str = "Scope: All Monitored Production Machines"

    # Header text info (Columns B to F)
    ws.merge_cells("B2:F2")
    ws.cell(row=2, column=2, value="MACHINES UTILISATION REPORT").font = Font(name="Calibri", size=15, bold=True, color="1F3864")
    ws.cell(row=2, column=2).alignment = Alignment(horizontal="center", vertical="center")

    ws.merge_cells("B3:F3")
    ws.cell(row=3, column=2, value=f"Reporting Period: {date_str}").font = Font(name="Calibri", size=10, bold=True, color="2C3E50")
    ws.cell(row=3, column=2).alignment = Alignment(horizontal="center", vertical="center")

    ws.merge_cells("B4:F4")
    ws.cell(row=4, column=2, value=machines_str).font = Font(name="Calibri", size=9.5, italic=True, color="4A5568")
    ws.cell(row=4, column=2).alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    # --- 3. Optional Executive Summary KPI Metric Cards (commented out for now; uncomment to enable) ---
    # ws.row_dimensions[5].height = 8
    # total_runtime_sec = sum(r.runtime or 0 for r in rows)
    # total_downtime_sec = sum(r.downtime or 0 for r in rows)
    # total_idle_sec = sum(r.idle or 0 for r in rows)
    # avg_utilization = (sum(r.utilization_percent or 0 for r in rows) / len(rows)) if rows else 0.0
    # unique_machines = len({r.mc_id for r in rows})
    # total_records = len(rows)
    # ws.row_dimensions[6].height = 16
    # ws.row_dimensions[7].height = 24
    # card_border = Border(
    #     left=Side(style="thin", color="D0D7DE"),
    #     right=Side(style="thin", color="D0D7DE"),
    #     top=Side(style="thin", color="D0D7DE"),
    #     bottom=Side(style="thin", color="D0D7DE"),
    # )
    # # Card 1: Plant Avg Utilization (A6:B7)
    # ws.merge_cells("A6:B6")
    # ws.cell(row=6, column=1, value="PLANT AVG UTILIZATION")
    # style_range(ws, "A6:B6", font=Font(name="Calibri", size=8.5, bold=True, color="334155"),
    #             fill=PatternFill("solid", fgColor="F1F5F9"), alignment=Alignment(horizontal="center", vertical="center"))
    # ws.merge_cells("A7:B7")
    # ws.cell(row=7, column=1, value=f"{avg_utilization:.2f}%")
    # style_range(ws, "A7:B7", font=Font(name="Calibri", size=14, bold=True, color="0F172A"),
    #             fill=PatternFill("solid", fgColor="F1F5F9"), alignment=Alignment(horizontal="center", vertical="center"))
    # # Card 2: Total Runtime (C6:C7)
    # ws.cell(row=6, column=3, value="TOTAL RUNTIME")
    # ws.cell(row=6, column=3).font = Font(name="Calibri", size=8.5, bold=True, color="166534")
    # ws.cell(row=6, column=3).fill = PatternFill("solid", fgColor="F0FDF4")
    # ws.cell(row=6, column=3).alignment = Alignment(horizontal="center", vertical="center")
    # ws.cell(row=7, column=3, value=_seconds_to_hhmmss(total_runtime_sec))
    # ws.cell(row=7, column=3).font = Font(name="Calibri", size=12, bold=True, color="15803D")
    # ws.cell(row=7, column=3).fill = PatternFill("solid", fgColor="F0FDF4")
    # ws.cell(row=7, column=3).alignment = Alignment(horizontal="center", vertical="center")
    # # Card 3: Total Downtime (D6:D7)
    # ws.cell(row=6, column=4, value="TOTAL DOWNTIME")
    # ws.cell(row=6, column=4).font = Font(name="Calibri", size=8.5, bold=True, color="991B1B")
    # ws.cell(row=6, column=4).fill = PatternFill("solid", fgColor="FEF2F2")
    # ws.cell(row=6, column=4).alignment = Alignment(horizontal="center", vertical="center")
    # ws.cell(row=7, column=4, value=_seconds_to_hhmmss(total_downtime_sec))
    # ws.cell(row=7, column=4).font = Font(name="Calibri", size=12, bold=True, color="B91C1C")
    # ws.cell(row=7, column=4).fill = PatternFill("solid", fgColor="FEF2F2")
    # ws.cell(row=7, column=4).alignment = Alignment(horizontal="center", vertical="center")
    # # Card 4: Assets & Records (E6:F7)
    # ws.merge_cells("E6:F6")
    # ws.cell(row=6, column=5, value="MONITORED ASSETS")
    # style_range(ws, "E6:F6", font=Font(name="Calibri", size=8.5, bold=True, color="1E293B"),
    #             fill=PatternFill("solid", fgColor="F8FAFC"), alignment=Alignment(horizontal="center", vertical="center"))
    # ws.merge_cells("E7:F7")
    # ws.cell(row=7, column=5, value=f"{unique_machines} Machines ({total_records} Logs)")
    # style_range(ws, "E7:F7", font=Font(name="Calibri", size=12, bold=True, color="1E293B"),
    #             fill=PatternFill("solid", fgColor="F8FAFC"), alignment=Alignment(horizontal="center", vertical="center"))
    # for rng in ["A6:B6", "A7:B7", "C6:C6", "C7:C7", "D6:D6", "D7:D7", "E6:F6", "E7:F7"]:
    #     for r in ws[rng]:
    #         for c in r:
    #             c.border = card_border
    # ws.row_dimensions[8].height = 10

    # 4. Table Headers (Row 5 directly after scope row)
    HEADER_ROW = 5
    ws.row_dimensions[HEADER_ROW].height = 26
    header_font = Font(name="Calibri", bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill(fill_type="solid", fgColor="1F3864")
    center_align = Alignment(horizontal="center", vertical="center")
    header_border = Border(
        left=Side(style="thin", color="1F3864"),
        right=Side(style="thin", color="1F3864"),
        top=Side(style="thin", color="1F3864"),
        bottom=Side(style="thin", color="1F3864"),
    )

    for col_idx, header in enumerate(headers, start=1):
        cell = ws.cell(row=HEADER_ROW, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center_align
        cell.border = header_border

    # Freeze panes so header row 9 stays fixed while scrolling
    ws.freeze_panes = f"A{HEADER_ROW + 1}"

    # 5. Data Rows
    data_border = Border(
        left=Side(style="thin", color="DCE1E7"),
        right=Side(style="thin", color="DCE1E7"),
        top=Side(style="thin", color="DCE1E7"),
        bottom=Side(style="thin", color="DCE1E7"),
    )
    alt_fill = PatternFill(fill_type="solid", fgColor="F8FAFC")
    white_fill = PatternFill(fill_type="solid", fgColor="FFFFFF")

    last_data_row = HEADER_ROW
    for row_idx, row in enumerate(rows, start=HEADER_ROW + 1):
        last_data_row = row_idx
        ws.row_dimensions[row_idx].height = 20
        base_fill = alt_fill if row_idx % 2 == 0 else white_fill
        util_val = round(row.utilization_percent or 0.0, 2)

        # Soft badge coloring for Utilization column
        if util_val >= 60.0:
            util_fill = PatternFill(fill_type="solid", fgColor="DCFCE7")
            util_font = Font(name="Calibri", size=10, bold=True, color="166534")
        elif util_val >= 25.0:
            util_fill = PatternFill(fill_type="solid", fgColor="FEF3C7")
            util_font = Font(name="Calibri", size=10, bold=True, color="92400E")
        else:
            util_fill = PatternFill(fill_type="solid", fgColor="FEE2E2")
            util_font = Font(name="Calibri", size=10, bold=True, color="991B1B")

        values_and_styles = [
            (row.date.strftime("%d-%m-%Y"), Font(name="Calibri", size=10, color="1E293B"), base_fill),
            (row.mc_id, Font(name="Calibri", size=10, bold=True, color="0F172A"), base_fill),
            ("00:00:00", Font(name="Calibri", size=10, color="64748B"), base_fill),
            (_seconds_to_hhmmss(row.runtime or 0), Font(name="Calibri", size=10, bold=True, color="15803D"), base_fill),
            (_seconds_to_hhmmss(row.downtime or 0), Font(name="Calibri", size=10, bold=True, color="B91C1C"), base_fill),
            (util_val, util_font, util_fill),
        ]

        for col_idx, (val, fnt, fll) in enumerate(values_and_styles, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=val)
            cell.font = fnt
            cell.fill = fll
            cell.border = data_border
            cell.alignment = center_align

    # Auto filter on the data table
    ws.auto_filter.ref = f"A{HEADER_ROW}:{get_column_letter(num_cols)}{max(last_data_row, HEADER_ROW)}"

    # --- 6. Optional Summary / Total Row (commented out for now; uncomment to enable) ---
    # total_runtime_sec = sum(r.runtime or 0 for r in rows)
    # total_downtime_sec = sum(r.downtime or 0 for r in rows)
    # total_idle_sec = sum(r.idle or 0 for r in rows)
    # avg_utilization = (sum(r.utilization_percent or 0 for r in rows) / len(rows)) if rows else 0.0
    # total_row_idx = last_data_row + 1
    # ws.row_dimensions[total_row_idx].height = 22
    # total_fill = PatternFill(fill_type="solid", fgColor="E2E8F0")
    # total_border = Border(
    #     top=Side(style="thin", color="94A3B8"),
    #     bottom=Side(style="double", color="0F172A"),
    #     left=Side(style="thin", color="E2E8F0"),
    #     right=Side(style="thin", color="E2E8F0"),
    # )
    # ws.merge_cells(start_row=total_row_idx, start_column=1, end_row=total_row_idx, end_column=2)
    # tot_label_cell = ws.cell(row=total_row_idx, column=1, value="TOTAL / OVERALL AVERAGE")
    # tot_label_cell.alignment = Alignment(horizontal="right", vertical="center")
    # style_range(ws, f"A{total_row_idx}:B{total_row_idx}",
    #             font=Font(name="Calibri", size=10, bold=True, color="0F172A"),
    #             fill=total_fill, border=total_border,
    #             alignment=Alignment(horizontal="right", vertical="center"))
    # total_values = [
    #     (3, "00:00:00", Font(name="Calibri", size=10, bold=True, color="64748B")),
    #     (4, _seconds_to_hhmmss(total_runtime_sec), Font(name="Calibri", size=10, bold=True, color="15803D")),
    #     (5, _seconds_to_hhmmss(total_downtime_sec), Font(name="Calibri", size=10, bold=True, color="B91C1C")),
    #     (6, round(avg_utilization, 2), Font(name="Calibri", size=10.5, bold=True, color="0F172A")),
    # ]
    # for col_idx, val, fnt in total_values:
    #     cell = ws.cell(row=total_row_idx, column=col_idx, value=val)
    #     cell.font = fnt
    #     cell.fill = total_fill
    #     cell.border = total_border
    #     cell.alignment = center_align

    # --- 7. Optional Footer Note (commented out for now; uncomment to enable) ---
    # footer_row_idx = (last_data_row + 2)
    # ws.row_dimensions[footer_row_idx].height = 18
    # ws.merge_cells(start_row=footer_row_idx, start_column=1, end_row=footer_row_idx, end_column=num_cols)
    # footer_cell = ws.cell(
    #     row=footer_row_idx,
    #     column=1,
    #     value="Machine Monitoring & Industrial Operations System | Automated Report | Confidential"
    # )
    # footer_cell.font = Font(name="Calibri", size=8.5, italic=True, color="64748B")
    # footer_cell.alignment = Alignment(horizontal="left", vertical="center")

    # 8. Column widths
    col_widths = {
        1: 18,  # Date
        2: 18,  # Machine ID
        3: 24,  # Idle Time
        4: 24,  # Runtime
        5: 24,  # Downtime
        6: 18,  # Utilization (%)
    }
    for col_idx, width in col_widths.items():
        col_letter = get_column_letter(col_idx)
        ws.column_dimensions[col_letter].width = width

    # --- 3. Stream the file to the client ---
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    filename = "KPI_Utilization"
    if from_date:
        filename += f"_{from_date.date()}"
    if to_date:
        filename += f"_to_{to_date.date()}"
    filename += ".xlsx"

    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{mc_id}", response_model=MachineResponse, summary="Get a single machine by ID")
def get_machine(mc_id: str, db: Session = Depends(get_db)):
    """
    Return the current status and metadata for a specific machine by its mc_id.
    """
    return machine_service.get_machine_by_mc_id(db, mc_id)


@router.post("", response_model=MachineResponse, status_code=201, summary="Create a new machine")
def create_machine(machine: MachineCreate, db: Session = Depends(get_db)):
    """
    Create a new machine with the specified details.
    """
    return machine_service.create_machine(db, machine)


@router.put("/{mc_id}", response_model=MachineResponse, summary="Update a machine")
def update_machine(mc_id: str, machine: MachineUpdate, db: Session = Depends(get_db)):
    """
    Update machine metadata and status.
    This can be used to process updates from an external system, like an AI prediction model.
    """
    return machine_service.update_machine(db, mc_id, machine)


@router.patch("/{mc_id}", response_model=MachineResponse, summary="Partially update a machine")
def patch_machine(mc_id: str, machine: MachineUpdate, db: Session = Depends(get_db)):
    """
    Partially update a machine's metadata or status.
    """
    return machine_service.update_machine(db, mc_id, machine)
