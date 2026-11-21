#!/usr/bin/env python3
"""Relabel miniSEED channels in an Aspen test folder (headers and file names) and add a note saying what changed.

Default use: external SB infrasound sensors recorded through the geophone connector, which the firmware labels
EHZ/EHN/EHE. They become HDF with location codes 01/02/03:

    python relabel_channels.py 2026-11-21_FW0.8.5-75_4xSB_multiday_deck

Other mappings: --map OLD=LOC.NEW, repeated (e.g. --map EHZ=01.HDF --map EHN=02.HDF). --dry-run lists what would
change without touching anything. Running it again on a folder that is already done changes nothing.

Only the location and channel fields of each 512-byte record header change; the data bytes are untouched. File names
follow <time>.<network>.<station>.<location>.<channel>.mseed. Log files are left as recorded (their N line still shows
the firmware's codes), and the note NOTE_channel_codes.md says so.
"""
import argparse
import datetime
import glob
import os
import re
import struct
import sys

DEFAULT_MAP = ['EHZ=01.HDF', 'EHN=02.HDF', 'EHE=03.HDF']
DEFAULT_WHY = 'the external SB infrasound sensors, connected through the geophone connector,'
NOTE_NAME = 'NOTE_channel_codes.md'
NAME_RE = re.compile(r'^(?P<time>.+?)\.(?P<net>[A-Z0-9]{0,2})\.(?P<sta>[A-Z0-9]{1,5})\.(?P<loc>[A-Z0-9]{0,2})\.'
                     r'(?P<cha>[A-Z0-9]{3})\.mseed$')


def parse_map(items):
    """'EHZ=01.HDF' -> {('', 'EHZ'): ('01', 'HDF')}. The old side may also give a location: '00.EHZ=01.HDF'."""
    out = {}
    for item in items:
        old, sep, new = item.partition('=')
        if not sep:
            sys.exit(f'--map {item}: expected OLD=LOC.NEW, e.g. EHZ=01.HDF')
        pairs = []
        for side in (old, new):
            loc, _, cha = side.rpartition('.')
            if not re.fullmatch(r'[A-Z0-9]{3}', cha) or not re.fullmatch(r'[A-Z0-9]{0,2}', loc):
                sys.exit(f'--map {item}: channel codes are 3 characters, location codes 0-2 (e.g. 01.HDF)')
            pairs.append((loc, cha))
        out[pairs[0]] = pairs[1]
    if len(set(out.values())) != len(out):
        sys.exit('--map: two old channels would get the same new code')
    return out


def record_length(data, offset, path):
    """Record length from blockette 1000, following the blockette chain from the header's first-blockette offset."""
    nxt = struct.unpack('>H', data[offset + 46:offset + 48])[0]
    seen = 0
    while nxt and seen < 20:
        btype, after = struct.unpack('>HH', data[offset + nxt:offset + nxt + 4])
        if btype == 1000:
            return 2 ** data[offset + nxt + 6]
        nxt, seen = after, seen + 1
    sys.exit(f'{path}: record at byte {offset} has no blockette 1000 (not a miniSEED 2 file this script knows)')


def relabel_bytes(data, path, sta, old, new):
    """Rewrite location/channel in every record; checks each record's codes first. Returns (new bytes, records)."""
    data = bytearray(data)
    off, n = 0, 0
    while off < len(data):
        rl = record_length(data, off, path)
        if off + rl > len(data):
            sys.exit(f'{path}: last record is cut short (file size {len(data)}, record length {rl})')
        h_sta = data[off + 8:off + 13].decode('ascii').strip()
        h_loc = data[off + 13:off + 15].decode('ascii').strip()
        h_cha = data[off + 15:off + 18].decode('ascii').strip()
        if (h_sta, h_loc, h_cha) != (sta, old[0], old[1]):
            sys.exit(f'{path}: record at byte {off} says {h_sta}.{h_loc}.{h_cha}, not {sta}.{old[0]}.{old[1]}; '
                     'nothing in this file was changed')
        data[off + 13:off + 15] = new[0].ljust(2).encode('ascii')
        data[off + 15:off + 18] = new[1].encode('ascii')
        off += rl
        n += 1
    return bytes(data), n


def firmware_versions(folder):
    found = set()
    for log in glob.glob(os.path.join(folder, '*.log')):
        with open(log, errors='replace') as f:
            for line in f:
                if line.startswith('#Firmware'):
                    found.add(line[len('#Firmware'):].strip().split('_')[0])
                elif line[:2] in ('H,', 'G,', 'P,'):
                    break  # header is over
    return sorted(found)


def write_note(folder, mapping, why, done, n_files, n_records, example):
    rows = '\n'.join(f'| {o[1]:<16} | {o[0] or "(blank)":<17} | {n[1]:<11} | {n[0] or "(blank)":<17} |'
                     for o, n in mapping.items())
    fw = ', '.join(firmware_versions(folder)) or 'unknown'
    untouched = sorted({m.group('cha') if not m.group('loc') else f"{m.group('loc')}.{m.group('cha')}"
                        for f in os.listdir(folder) if (m := NAME_RE.match(f))} -
                       {f'{n[0]}.{n[1]}' if n[0] else n[1] for n in mapping.values()})
    old_codes = '/'.join(o[1] for o in mapping)
    text = f"""# Channel code correction ({done})

The firmware (FW {fw}) wrote {why}
with channel codes {old_codes}. Their codes were changed after the recording with `relabel_channels.py`
(in the firmware_test_recordings folder):

| Original channel | Original location | New channel | New location code |
|------------------|-------------------|-------------|-------------------|
{rows}

Channels left as recorded: {', '.join(untouched) or 'none'}.

What changed:
- miniSEED headers: the location and channel fields were rewritten in every record ({n_records:,} records in
  {n_files} files). The data bytes were not touched.
- File names: for example, `{example[0]}` is now `{example[1]}`.
  The pattern is `time.network.station.location.channel.mseed`.

NOT changed:
- The `.log` files (including any `pending_*.log`) are the original firmware output. Their channel-list line
  (`N,...`) still shows the old codes.
- `CONFIG.TXT`, if present, is as used in the test.

The mapping assumes the original channels correspond to the new location codes in the order listed above.
"""
    path = os.path.join(folder, NOTE_NAME)
    if os.path.exists(path):  # keep earlier notes (e.g. a second relabeling) and add this one below
        with open(path) as f:
            text = f.read().rstrip() + '\n\n' + text
    with open(path, 'w') as f:
        f.write(text)
    return path


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('folder')
    ap.add_argument('--map', action='append', metavar='OLD=LOC.NEW',
                    help=f'channel relabeling, repeatable (default: {" ".join(DEFAULT_MAP)})')
    ap.add_argument('--station', help='only this station (default: every station in the folder)')
    ap.add_argument('--why', default=DEFAULT_WHY,
                    help='what the relabeled channels are, for the note (finishes "The firmware wrote ...")')
    ap.add_argument('--dry-run', action='store_true', help='list the changes without making them')
    a = ap.parse_args()
    mapping = parse_map(a.map or DEFAULT_MAP)

    jobs = []  # (old path, new path, station, old, new)
    already = 0
    for name in sorted(os.listdir(a.folder)):
        m = NAME_RE.match(name)
        if not m or (a.station and m.group('sta') != a.station):
            continue
        key = (m.group('loc'), m.group('cha'))
        if key in mapping:
            new = mapping[key]
            new_name = f"{m.group('time')}.{m.group('net')}.{m.group('sta')}.{new[0]}.{new[1]}.mseed"
            if os.path.exists(os.path.join(a.folder, new_name)):
                sys.exit(f'{new_name} already exists next to {name}; nothing was changed')
            jobs.append((os.path.join(a.folder, name), os.path.join(a.folder, new_name), m.group('sta'), key, new))
        elif key in mapping.values():
            already += 1
    if not jobs:
        print(f'Nothing to relabel in {a.folder}' + (f' ({already} files already have the new codes)' if already
                                                     else ' (no files with the old codes)'))
        return

    # check every file before changing any, so a surprise leaves the folder as it was
    results = []
    for old_path, new_path, sta, old, new in jobs:
        with open(old_path, 'rb') as f:
            data, n = relabel_bytes(f.read(), old_path, sta, old, new)
        results.append((old_path, new_path, data, n))
    n_records = sum(r[3] for r in results)
    for old_path, new_path, _, n in results:
        print(f'{os.path.basename(old_path)} -> {os.path.basename(new_path)} ({n} records)')
    if a.dry_run:
        print(f'dry run: {len(results)} files, {n_records} records would change')
        return

    for old_path, new_path, data, _ in results:
        tmp = new_path + '.tmp'
        with open(tmp, 'wb') as f:
            f.write(data)
        os.replace(tmp, new_path)
        os.remove(old_path)
    example = (os.path.basename(results[0][0]), os.path.basename(results[0][1]))
    note = write_note(a.folder, mapping, a.why, datetime.date.today().isoformat(), len(results), n_records, example)
    print(f'{len(results)} files, {n_records} records relabeled; note: {note}')


if __name__ == '__main__':
    main()
