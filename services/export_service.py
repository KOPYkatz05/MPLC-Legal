from pathlib import Path

from services.missionary_service import missionary_display_id
from utils.i18n import tr
from utils.logger import logger


class ExportService:

    def _headers(self):
        return [
            "ID",
            "Full Name",
            "Nationality",
            "Passport Number",
            "Current Stage",
            "Arrival Date",
            "Visa Expiration",
            tr("export_passport_exp"),
            "Residency Expiration",
            "Prórroga Expiration",
            "Carnet Issue Date",
            "Cancelación Date",
            tr("export_interpol_appt"),
            tr("export_biometric_appt"),
            tr("export_pickup_appt"),
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

            headers = self._headers()

            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Missionaries"

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

            for col, header in enumerate(headers, 1):
                cell = ws.cell(row=1, column=col, value=header)
                cell.font = header_font
                cell.fill = header_fill
                cell.border = header_border
                cell.alignment = Alignment(
                    horizontal="center",
                    vertical="center",
                )

            ws.row_dimensions[1].height = 30

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
                    missionary_display_id(m),
                    m.full_name or "",
                    m.nationality or "",
                    m.passport_number or "",
                    m.current_stage or "",
                    fmt_date(m.arrival_date),
                    fmt_date(m.visa_expiration),
                    fmt_date(m.passport_expiration),
                    fmt_date(m.residency_expiration),
                    fmt_date(m.prorroga_expiration),
                    fmt_date(m.carnet_issue_date),
                    fmt_date(m.cancelacion_date),
                    fmt_date(m.interpol_appointment_date),
                    fmt_date(m.biometric_appointment_date),
                    fmt_date(m.pickup_appointment_date),
                    m.notes or "",
                ]

                for col, val in enumerate(values, 1):
                    cell = ws.cell(row=i, column=col, value=val)
                    cell.alignment = Alignment(vertical="center")
                    if i % 2 == 0:
                        cell.fill = alt_fill

                ws.row_dimensions[i].height = 22

            col_widths = [
                12, 30, 16, 18, 22, 14, 16, 16, 20, 20,
                16, 16, 16, 16, 16, 40,
            ]

            for col, width in enumerate(col_widths, 1):
                ws.column_dimensions[
                    ws.cell(row=1, column=col).column_letter
                ].width = width

            ws.freeze_panes = "A2"
            wb.save(output_path)

            logger.info(
                f"Exported {len(missionaries)} "
                f"missionaries to {output_path}"
            )

            return True

        except Exception:
            logger.exception(
                "Failed to export missionaries to Excel"
            )

            return False
