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

router = APIRouter(prefix="/api/machines", tags=["machines"])

UTILIZATION_STATE_PATH = Path(__file__).resolve().parent.parent.parent / "utilization_state.json"


@router.get("", response_model=List[MachineResponse], summary="Get all machines")
def get_machines(db: Session = Depends(get_db)):
    """
    Return the current status and metadata for all monitored machines.
    """
    return machine_service.get_all_machines(db)


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

    # --- 2. Build Excel workbook ---
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "KPI Utilization"

    # Header styling
    header_font  = Font(name="Calibri", bold=True, color="FFFFFF", size=11)
    header_fill  = PatternFill(fill_type="solid", fgColor="1F3864")   # dark navy
    center_align = Alignment(horizontal="center", vertical="center")
    thin_border  = Border(
        left=Side(style="thin"),
        right=Side(style="thin"),
        top=Side(style="thin"),
        bottom=Side(style="thin"),
    )

    headers = [
        "Date",
        "Machine ID",
        "Idle Time (HH:MM:SS)",
        "Runtime (HH:MM:SS)",
        "Downtime (HH:MM:SS)",
        "Utilization (%)",
    ]

    num_cols = len(headers)

    # ── Row 1 : Report title (merged across all columns) ──────────────────────
    title_parts = ["Machines Utilisation Report"]

    # Date range in brackets e.g. (2026-08-01 to 2026-09-08)
    if from_date or to_date:
        if from_date and to_date:
            date_str = f"{from_date.date()} to {to_date.date()}"
        elif from_date:
            date_str = f"From {from_date.date()}"
        else:
            date_str = f"Up to {to_date.date()}"
        title_parts.append(f"({date_str})")

    # Selected machines in brackets e.g. [MC-001, MC-002]
    if mc_ids and mc_ids.strip().lower() != "all":
        sel = [mid.strip() for mid in mc_ids.split(",") if mid.strip()]
        if sel:
            title_parts.append(f"[{', '.join(sel)}]")

    title_font = Font(name="Calibri", bold=True, size=14, color="FFFFFF")
    title_fill = PatternFill(fill_type="solid", fgColor="1F3864")

    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=num_cols)
    title_cell = ws.cell(row=1, column=1, value="  ".join(title_parts))
    title_cell.font      = title_font
    title_cell.fill      = title_fill
    title_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 28

    # ── Row 2 : Column headers ────────────────────────────────────────────────
    HEADER_ROW = 2
    for col_idx, header in enumerate(headers, start=1):
        cell = ws.cell(row=HEADER_ROW, column=col_idx, value=header)
        cell.font        = header_font
        cell.fill        = header_fill
        cell.alignment   = center_align
        cell.border      = thin_border

    # Freeze rows 1+2 so title and headers stay visible while scrolling
    ws.freeze_panes = "A3"
    ws.auto_filter.ref = f"A{HEADER_ROW}:{get_column_letter(num_cols)}{HEADER_ROW}"

    # Data row styling
    data_font        = Font(name="Calibri", size=10)
    alt_fill         = PatternFill(fill_type="solid", fgColor="DCE6F1")  # light blue alternate

    # Write data rows  (start at row 3 — row 1 = title, row 2 = headers)
    for row_idx, row in enumerate(rows, start=3):
        fill = alt_fill if row_idx % 2 == 0 else PatternFill()   # alternate row shading
        values = [
            # str(row.date),
            row.date.strftime("%d-%m-%Y"),
            row.mc_id,
            # _seconds_to_hhmmss(row.idle),
            "00:00:00",
            _seconds_to_hhmmss(row.runtime),
            _seconds_to_hhmmss(row.downtime),
            round(row.utilization_percent, 2),
        ]
        for col_idx, value in enumerate(values, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=value)
            cell.font      = data_font
            cell.fill      = fill
            cell.border    = thin_border
            cell.alignment = Alignment(horizontal="center", vertical="center")

    # Auto-fit column widths
    for col_idx, header in enumerate(headers, start=1):
        col_letter = get_column_letter(col_idx)
        ws.column_dimensions[col_letter].width = max(len(header) + 4, 18)

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
