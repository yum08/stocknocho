4G Layer-1 DSP cycles analysis tools

This small project includes utilities to generate an Excel template for DSP core cycle timing and to parse DSP logs into an Excel workbook.

Files:
- scripts/generate_template.py: creates `dsp_cycles_template.xlsx` with sample rows for v1 (4 cores) and v2 (8 cores).
- scripts/parse_logs.py: parses plain-text or CSV logs and writes per-core cycle timing and converted microseconds to an Excel workbook.
- requirements.txt: Python dependencies.

Usage (PowerShell):
1. Install Python 3.8+ and create a virtual environment.
   python -m venv .venv; .\.venv\Scripts\Activate.ps1
2. Install deps:
   pip install -r requirements.txt
3. Generate template:
   python .\scripts\generate_template.py
4. Parse logs:
   python .\scripts\parse_logs.py --input sample_logs/sample_log.txt --clock 1.2e9

Clock: default 1.2e9 (1.2 GHz). Cycles are converted to microseconds by: microsec = cycles / clock * 1e6
