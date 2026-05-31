from pathlib import Path

from utils.logger import logger


class ExportService:

    HEADERS = [
        "ID",
        "Full Name",
        "Nationality",
        "Passport Number",
        "Current Stage",
        "Arrival Date",
        "Visa Expiration",
        "Residency Expiration",
        "Prórroga Expiration",
        "Carnet Issue Date",
        "Cancelación Date",
        "Notes",
    ]

    def export_missionaries_to_excel(
        self,
        missionaries,
        output_path,
    ):
        try:
            import openpyxl
            from openpyxl.styles import (
                Font,
                PatternFill,
                Alignment,
                Border,
                Side,
            )

            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Missionaries"

            # ==========================================
            # Header row
            # ==========================================

            header_fill = PatternFill(
                start_color="1D4ED8",
                end_color="1D4ED8",
                fill_type="solid",
            )

            header_font = Font(
                bold=True,
                color="FFFFFF",
                size=11,
            )

            header_border = Border(
                bottom=Side(
                    border_style="thin",
                    color="FFFFFF",
                ),
            )

            for col, header in enumerate(
                self.HEADERS, 1
            ):
                cell = ws.cell(
                    row=1,
                    column=col,
                    value=header,
                )

                cell.font = header_font

                cell.fill = header_fill

                cell.border = header_border

                cell.alignment = Alignment(
                    horizontal="center",
                    vertical="center",
                )

            ws.row_dimensions[1].height = 30

            # ==========================================
            # Data rows
            # ==========================================

            alt_fill = PatternFill(
                start_color="EFF6FF",
                end_color="EFF6FF",
                fill_type="solid",
            )

            def fmt_date(d):
                if not d:
                    return ""
                return d.strftime("%d/%m/%Y")

            for i, m in enumerate(missionaries, 2):
                values = [
                    m.id,
                    m.full_name or "",
                    m.nationality or "",
                    m.passport_number or "",
                    m.current_stage or "",
                    fmt_date(m.arrival_date),
                    fmt_date(m.visa_expiration),
                    fmt_date(
                        m.residency_expiration
                    ),
                    fmt_date(
                        m.prorroga_expiration
                    ),
                    fmt_date(m.carnet_issue_date),
                    fmt_date(m.cancelacion_date),
                    m.notes or "",
                ]

                for col, val in enumerate(
                    values, 1
                ):
                    cell = ws.cell(
                        row=i,
                        column=col,
                        value=val,
                    )

                    cell.alignment = Alignment(
                        vertical="center",
                    )

                    if i % 2 == 0:
                        cell.fill = alt_fill

                ws.row_dimensions[i].height = 22

            # ==========================================
            # Column widths
            # ==========================================

            col_widths = [
                6,
                30,
                16,
                18,
                22,
                14,
                16,
                20,
                20,
                16,
                16,
                40,
            ]

            for col, width in enumerate(
                col_widths, 1
            ):
                ws.column_dimensions[
                    ws.cell(row=1, column=col)
                    .column_letter
                ].width = width

            # Freeze top row
            ws.freeze_panes = "A2"

            wb.save(output_path)

            logger.info(
                f"Exported {len(missionaries)} "
                f"missionaries to {output_path}"
            )

            return True

        except Exception:
            logger.exception(
                "Failed to export missionaries "
                "to Excel"
            )

            return False
