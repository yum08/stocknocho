import openpyxl
from openpyxl.utils import get_column_letter

OUT = 'dsp_cycles_template.xlsx'

headers = ['Version', 'Core', 'Function', 'CycleStart', 'CycleEnd', 'Cycles', 'Microsec']

sample_rows = []
# v1: 4 cores
for core in range(4):
    sample_rows.append(['v1', core, 'ChannelEstimation', 3784196625 + core * 1000, 3784202625 + core * 1000, 6000, None])
# v2: 8 cores
for core in range(8):
    sample_rows.append(['v2', core, 'PUSCH_Proc', 6489834542323 + core * 500, 6489834594923 + core * 500, 52600, None])

wb = openpyxl.Workbook()
ws = wb.active
ws.title = 'DSP_cycles'

for c, h in enumerate(headers, start=1):
    ws.cell(row=1, column=c, value=h)

for r, row in enumerate(sample_rows, start=2):
    for c, v in enumerate(row, start=1):
        ws.cell(row=r, column=c, value=v)

# auto-width
for i, _ in enumerate(headers, start=1):
    ws.column_dimensions[get_column_letter(i)].width = 18

wb.save(OUT)
print(f'Wrote {OUT}')
