import argparse
import re
import pandas as pd
from pathlib import Path

# default clock 1.2 GHz
DEFAULT_CLOCK = 1.2e9

TS_REGEX = re.compile(r"(\d+)\s*$")


def cycles_to_microsec(cycles, clock_hz):
    return cycles / clock_hz * 1e6


def parse_plain_log(path):
    """Parses a simple plain-text log where lines contain 'CoreX ... cycles is <number>' or similar.
    Returns rows: Version, Core, Function, CycleStart, CycleEnd, Cycles
    """
    rows = []
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            # Try to find phrases like 'Core2 Channel Estimation Even Slot Max Profile in cycles is 5993'
            m = re.search(r'Core(\d+)\D+(?:cycles is|in cycles is|is in cycles is)?\s*(\d+)', line)
            if m:
                core = int(m.group(1))
                cycles = int(m.group(2))
                # extract a function-like label
                func = 'Unknown'
                # try to get words between core and 'in cycles'
                m2 = re.search(rf'Core{core}(.+?)\s+(?:in cycles|cycles is|is in cycles)', line)
                if m2:
                    func = m2.group(1).strip()
                rows.append({'Version': 'v?', 'Core': core, 'Function': func, 'CycleStart': None, 'CycleEnd': None, 'Cycles': cycles})
    return rows


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--input', '-i', required=True, help='Input log file (plain text)')
    p.add_argument('--output', '-o', default='parsed_dsp_cycles.xlsx')
    p.add_argument('--clock', type=float, default=DEFAULT_CLOCK, help='Clock frequency in Hz (default 1.2e9)')
    args = p.parse_args()

    rows = parse_plain_log(args.input)
    if not rows:
        print('No rows parsed from log')
        return

    df = pd.DataFrame(rows)
    df['Microsec'] = df['Cycles'].apply(lambda x: cycles_to_microsec(x, args.clock))

    # write to Excel
    df.to_excel(args.output, index=False)
    print(f'Wrote {args.output} with {len(df)} rows')


if __name__ == '__main__':
    main()
