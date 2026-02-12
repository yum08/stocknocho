import pandas as pd
import matplotlib.pyplot as plt

# Config
EXCEL_FILE = 'GC-PUSCH_Core2_ProcTimeLine_PRB_50_MCS_28_BW_10MHz.xlsx'
SHEET_NAME = 'FDD_10MHz_UE_1_PRB_50_MCS_28'

# Read the Excel file
# Column-A: event names, Column-B: bar values

df = pd.read_excel(EXCEL_FILE, sheet_name=SHEET_NAME)


# Drop rows where any of the three columns is NaN
col_a = df.columns[0]  # Event name
col_b = df.columns[1]  # Bar value
col_c = df.columns[2]  # Cycles
df = df[[col_a, col_b, col_c]].dropna()

# Convert cycles to microseconds for X-axis
cycles = df[col_c].astype(float)
microsec = cycles / 1.2e9 * 1e6
y_values = df[col_b].astype(float)
event_labels = df[col_a].astype(str)

plt.figure(figsize=(max(8, len(microsec)*0.5), 6))
bars = plt.bar(microsec, y_values, color='#3B5998', width=0.8*(microsec[1]-microsec[0]) if len(microsec)>1 else 0.5)
plt.xlabel('Time (microseconds, from Column-C)', fontweight='semibold')
plt.ylabel('Value (Column-B)', fontweight='semibold')
plt.title('Bar Plot: Column-B vs. Time (Column-C, microsec)')
plt.tight_layout()

# Annotate bars with event names
for bar, label in zip(bars, event_labels):
    height = bar.get_height()
    plt.text(bar.get_x() + bar.get_width()/2, height, label, ha='center', va='bottom', fontsize=9, rotation=90)

plt.savefig('column_b_bar_plot.png')
plt.show()
