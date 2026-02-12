import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyBboxPatch

IN = 'data/linkedin_sample.csv'
OUT = 'linkedin_style.png'

# Load data
df = pd.read_csv(IN)
labels = df['Age Group']
facebook = df['Facebook']
twitter = df['Twitter']
linkedin = df['LinkedIn']

# Styling choices inspired by the LinkedIn post
COL_FACEBOOK = '#3B5998'
COL_TWITTER = '#0ABAB5'  # teal/cyan similar to example
COL_LINKEDIN = '#7F7F7F'
FONT = {'family': 'DejaVu Sans', 'size': 11}

plt.rc('font', **FONT)

x = np.arange(len(labels))
width = 0.24

fig, ax = plt.subplots(figsize=(10, 5))
bars_f = ax.bar(x - width, facebook, width, label='Facebook', color=COL_FACEBOOK)
bars_t = ax.bar(x, twitter, width, label='Twitter', color=COL_TWITTER)
bars_l = ax.bar(x + width, linkedin, width, label='LinkedIn', color=COL_LINKEDIN)

# Labels and ticks
ax.set_ylabel('Percentage of users (%)', fontweight='semibold')
ax.set_xlabel('Age groups (in years)', fontweight='semibold')
ax.set_xticks(x)
ax.set_xticklabels(labels, rotation=0)

# Legend with rounded box and shadow
leg = ax.legend(frameon=True)
frame = leg.get_frame()
frame.set_facecolor('white')
frame.set_edgecolor('#AAAAAA')
frame.set_boxstyle('round,pad=0.4')
frame.set_alpha(0.95)

# Numeric annotations above bars (small grey boxes)
def annotate_bars(bars):
	for bar in bars:
		h = bar.get_height()
		if np.isnan(h):
			continue
		ax.annotate(f'{int(h)}', xy=(bar.get_x() + bar.get_width() / 2, h), xytext=(0, 3),
					textcoords='offset points', ha='center', va='bottom', fontsize=9, color='#333333')

annotate_bars(bars_f)
annotate_bars(bars_t)
annotate_bars(bars_l)

# Minor grid lines and style
ax.yaxis.grid(True, linestyle='--', linewidth=0.5, alpha=0.6)
ax.set_axisbelow(True)

plt.title('Age Distribution by Platform', fontsize=13, fontweight='semibold')
plt.tight_layout()
plt.savefig(OUT, dpi=150)
print(f'Wrote {OUT}')
