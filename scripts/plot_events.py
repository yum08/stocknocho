import argparse
from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt

DEFAULT_CLOCK = 1.2e9

# ...existing code...

def plot_grouped_bar_events(path, sheet_name, event_col=None, tag_col=None, cycle_col=None, clock_hz=DEFAULT_CLOCK, out_png='grouped_bar_events.png'):
    df = read_sheet(path, sheet_name)
    cols = list(df.columns)
    if event_col is None or tag_col is None or cycle_col is None:
        if len(cols) < 3:
            raise ValueError('Sheet must have at least 3 columns or specify event/tag/cycle column names')
        event_col = event_col or cols[0]
        tag_col = tag_col or cols[1]
        cycle_col = cycle_col or cols[2]
    for c in (event_col, tag_col, cycle_col):
        if c not in df.columns:
            raise KeyError(f'Column "{c}" not found in sheet. Available columns: {cols}')
    events = df[event_col].astype(str)
    tags = df[tag_col].astype(str)
    cycles = pd.to_numeric(df[cycle_col], errors='coerce')
    mask = cycles.notna()
    events = events[mask].reset_index(drop=True)
    tags = tags[mask].reset_index(drop=True)
    cycles = cycles[mask].reset_index(drop=True)
    cycles_us = cycles.apply(lambda x: cycles_to_microsec(x, clock_hz))
    # Only keep events of interest
    event_types = ['OneMsEnd', 'OneMsStart', 'TenMsStart', 'TenMsEnd']
    data = []
    for tag in tags.unique():
        for et in event_types:
            # Find the first occurrence of this event type for this tag
            idxs = (tags == tag) & (events.str.contains(et, case=False, na=False))
            if idxs.any():
                val = cycles_us[idxs].iloc[0]
                data.append((tag, et, val))
            else:
                data.append((tag, et, None))
    # Prepare for grouped bar plot
    import numpy as np
    tag_list = sorted(tags.unique())
    x = np.arange(len(tag_list))
    width = 0.18
    plt.figure(figsize=(max(10, len(tag_list)*0.6), 6))
    for i, et in enumerate(event_types):
        vals = [next((v for t, e, v in data if t == tag and e == et), 0) for tag in tag_list]
        vals = [0 if v is None else v for v in vals]
        plt.bar(x + i*width, vals, width, label=et)
    plt.xlabel('Tag')
    plt.ylabel('Cycle Time (us)')
    plt.title('Event Cycles per Tag (OneMsEnd, OneMsStart, TenMsStart, TenMsEnd)')
    plt.xticks(x + width*1.5, tag_list, rotation=90)
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_png)
    print(f'Wrote {out_png}')

import argparse
from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt

DEFAULT_CLOCK = 1.2e9

def read_sheet(path, sheet_name):
    try:
        df = pd.read_excel(path, sheet_name=sheet_name, engine='openpyxl')
    except Exception:
        # propagate to caller with helpful message
        raise
    return df

def cycles_to_microsec(cycles, clock_hz):
    return cycles / clock_hz * 1e6

def extract_events_from_functions(df, event_names, time_col='CycleTime'):
    """
    Find rows where the 'Function' column contains any of the event names.
    Returns dict: event_name -> Series of cycle timestamps (numeric) or empty series.
    """
    if 'Function' not in df.columns:
        return {}

    out = {}
    funcs = df['Function'].astype(str)
    for e in event_names:
        mask = funcs.str.contains(e, case=False, na=False)
        if mask.any():
            # get the corresponding time column if present
            if time_col in df.columns:
                vals = pd.to_numeric(df.loc[mask, time_col], errors='coerce').dropna()
            else:
                # attempt to find a numeric column (first numeric)
                numeric_cols = df.select_dtypes(include=['number']).columns.tolist()
                vals = pd.Series(dtype=float)
                if numeric_cols:
                    vals = pd.to_numeric(df.loc[mask, numeric_cols[0]], errors='coerce').dropna()
            out[e] = vals
        else:
            out[e] = pd.Series(dtype=float)
    return out

def plot_bar_end_start(path, sheet_name, event_col=None, tag_col=None, cycle_col=None, clock_hz=DEFAULT_CLOCK, out_png='bar_end_start.png'):
    df = read_sheet(path, sheet_name)
    cols = list(df.columns)
    if event_col is None or tag_col is None or cycle_col is None:
        if len(cols) < 3:
            raise ValueError('Sheet must have at least 3 columns or specify event/tag/cycle column names')
        event_col = event_col or cols[0]
        tag_col = tag_col or cols[1]
        cycle_col = cycle_col or cols[2]
    for c in (event_col, tag_col, cycle_col):
        if c not in df.columns:
            raise KeyError(f'Column "{c}" not found in sheet. Available columns: {cols}')
    events = df[event_col].astype(str)
    tags = df[tag_col].astype(str)
    cycles = pd.to_numeric(df[cycle_col], errors='coerce')
    mask = cycles.notna()
    events = events[mask].reset_index(drop=True)
    tags = tags[mask].reset_index(drop=True)
    cycles = cycles[mask].reset_index(drop=True)
    cycles_us = cycles.apply(lambda x: cycles_to_microsec(x, clock_hz))
    # For each tag, find Start/End pairs
    results = []
    for tag in tags.unique():
        idxs = tags[tags == tag].index.tolist()
        tag_events = events.loc[idxs]
        tag_cycles = cycles_us.loc[idxs]
        # Find all Start/End pairs by event name order
        start_idxs = [i for i, e in zip(idxs, tag_events) if 'start' in e.lower()]
        end_idxs = [i for i, e in zip(idxs, tag_events) if 'end' in e.lower()]
        # Pair each Start with the next End after it
        for s in start_idxs:
            # Find the first End after this Start
            e = next((ei for ei in end_idxs if ei > s), None)
            if e is not None:
                duration = cycles_us[e] - cycles_us[s]
                label = f'{tag}: {events[s]}→{events[e]}'
                results.append((label, duration))
    if not results:
        print('No Start/End event pairs found for bar plot.')
        return
    labels, durations = zip(*results)
    plt.figure(figsize=(max(10, len(labels)*0.6), 6))
    plt.bar(labels, durations, color='skyblue')
    plt.ylabel('Duration (us)')
    plt.title('End-Start Duration per Event/Tag')
    plt.xticks(rotation=90)
    plt.tight_layout()
    plt.savefig(out_png)
    print(f'Wrote {out_png}')


def plot_events(path, sheet_name, clock_hz, out_png, time_col='CycleTime'):
    df = read_sheet(path, sheet_name)

    targets = ['OneMsStart', 'OneMsEnd', 'TenMsStart', 'TenMsEnd']
    events = extract_events_from_functions(df, targets, time_col=time_col)

    # If none of the targets had values, print helpful info and exit
    if not any(len(s) for s in events.values()):
        print('No matching Function rows found for events. Available Function samples:')
        sample = df['Function'].dropna().astype(str).head(40).tolist() if 'Function' in df.columns else []
        print(sample)
        print('\nAvailable columns:')
        print(list(df.columns))
        return

    plt.figure(figsize=(12, 6))
    for name, series in events.items():
        if series.empty:
            continue
        # convert cycles to microsec
        s_us = series.apply(lambda x: cycles_to_microsec(x, clock_hz))
        # plot as points at their original row order (use index)
        plt.scatter(s_us.index, s_us.values, label=name)
        # connect if more than one point
        if len(s_us) > 1:
            plt.plot(s_us.index, s_us.values, alpha=0.6)

    plt.xlabel('Row index')
    plt.ylabel('Microseconds (us)')
    plt.title(f'Events from {Path(path).name} / {sheet_name}')
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    plt.savefig(out_png)
    print(f'Wrote {out_png}')


def plot_by_columns(path, sheet_name, event_col=None, tag_col=None, cycle_col=None, clock_hz=DEFAULT_CLOCK, out_png='events_by_tag.png'):
    df = read_sheet(path, sheet_name)

    # Determine columns: default to first three columns if not specified
    cols = list(df.columns)
    if event_col is None or tag_col is None or cycle_col is None:
        if len(cols) < 3:
            raise ValueError('Sheet must have at least 3 columns or specify event/tag/cycle column names')
        # default mapping: A -> cols[0], B -> cols[1], C -> cols[2]
        event_col = event_col or cols[0]
        tag_col = tag_col or cols[1]
        cycle_col = cycle_col or cols[2]

    # Ensure columns exist
    for c in (event_col, tag_col, cycle_col):
        if c not in df.columns:
            raise KeyError(f'Column "{c}" not found in sheet. Available columns: {cols}')

    events = df[event_col].astype(str)
    tags = df[tag_col].astype(str)
    cycles = pd.to_numeric(df[cycle_col], errors='coerce')

    mask = cycles.notna()
    if not mask.any():
        print(f'No numeric cycle values found in column "{cycle_col}"')
        return

    cycles_us = cycles[mask].apply(lambda x: cycles_to_microsec(x, clock_hz)).values
    events_valid = events[mask].values
    tags_valid = tags[mask].values

    # Map tags to y positions in order of appearance
    tag_order = []
    tag_to_idx = {}
    for t in tags_valid:
        if t not in tag_to_idx:
            tag_to_idx[t] = len(tag_order)
            tag_order.append(t)

    # Map event names to groups for coloring
    unique_events = []
    event_to_idx = {}
    for e in events_valid:
        if e not in event_to_idx:
            event_to_idx[e] = len(unique_events)
            unique_events.append(e)

    # Build per-event arrays of x and y
    xs_by_event = {e: [] for e in unique_events}
    ys_by_event = {e: [] for e in unique_events}
    for x_us, e, t in zip(cycles_us, events_valid, tags_valid):
        xs_by_event[e].append(x_us)
        ys_by_event[e].append(tag_to_idx[t])

    plt.figure(figsize=(14, 6))
    cmap = plt.get_cmap('tab20')
    for i, e in enumerate(unique_events):
        xs = xs_by_event[e]
        ys = ys_by_event[e]
        if not xs:
            continue
        color = cmap(i % 20)
        plt.scatter(xs, ys, label=e, color=color, s=28, alpha=0.8)

    plt.yticks(range(len(tag_order)), tag_order)
    plt.xlabel('Microseconds (us)')
    plt.title(f'Events (col "{event_col}") vs Tag (col "{tag_col}") from {Path(path).name} / {sheet_name}')
    plt.legend(bbox_to_anchor=(1.02, 1), loc='upper left')
    plt.grid(axis='x')
    plt.tight_layout()
    plt.savefig(out_png)
    print(f'Wrote {out_png}')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--file', '-f', required=True, help='Excel file path')
    p.add_argument('--sheet', '-s', default='FDD_10MHz_UE_1_PRB_50_MCS_28', help='Sheet name')
    p.add_argument('--clock', type=float, default=DEFAULT_CLOCK, help='Clock frequency in Hz')
    p.add_argument('--out', '-o', default='events_plot.png')
    p.add_argument('--time-col', default='CycleTime', help='Column that contains cycle timestamps (default CycleTime)')
    args = p.parse_args()
    plot_events(args.file, args.sheet, args.clock, args.out, time_col=args.time_col)
