---
name: Theme / styling
description: How the global QSS theme is applied and the design system used
---

**How to apply:** Stylesheet is loaded in `main.py` via `app.setStyleSheet(open("assets/styles/theme.qss").read())`. This applies globally to all widgets.

**Design palette:**
- Page background: #F4F4F5
- Cards / panels: #FFFFFF with border 1px solid #E4E4E7, border-radius 10px
- Primary text: #18181B
- Secondary text: #71717A
- Accent blue: #3B82F6 (primary actions, selected state)
- Warning amber: #D97706
- Danger red: #DC2626
- Success green: #059669

**Key objectNames for QSS targeting:**
- Sidebar QListWidget → objectName="Sidebar"
- Page header frame → objectName="PageHeader"
- Stat cards → objectName="StatCard"
- List card containers → objectName="ListCard"
- Column header rows → objectName="ColumnHeaderRow"
- Table rows → objectName="TableRow" or "TableRowAlt" (alternating)
- Page title label → objectName="PageTitle"
- Section headers → objectName="SectionHeader"

**Why:** Qt does not support CSS classes; objectName is the selector mechanism for targeting specific widget instances in QSS.
