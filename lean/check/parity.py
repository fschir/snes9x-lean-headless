"""Parity check: compare the work RAM of a candidate core with the baseline core on .bk2 recordings.

Commands:
    parity.py --candidate <core-dir> [--baseline <core-dir>] [--switch VALUE] [--jobs N] [--out-dir DIR]
              <recording.bk2> ...
    parity.py --compare-only <dir> [--switch VALUE]

The first command replays each recording on the two cores, one replay.py process per core and recording, each under
`taskset -c 0-15`, at most N at a time (default 16). The default baseline folder is the cores folder of the installed
stable-retro. The baseline always runs with no switch. For each recording, DIR holds <name>.<side>.npy (hashes),
.out and .err (output of the process); <side> is baseline or candidate. Without --out-dir, DIR is a new temporary
folder. The second command compares the files of such a folder again, without a replay.

With a switch value, the standard error of the candidate must contain one line that names every switch of the value
(the switch report of the core). A name counts when no letter, digit, `_`, `-` or `/` is next to it.

Exit code: 0 when every recording is clean, 1 on a differing frame or a fault, 2 on a wrong command.
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # `python -I` does not add the folder of the script
sys.dont_write_bytecode = True  # no __pycache__ folder in the checkout
import replay  # noqa: E402

SIDES = ("baseline", "candidate")
PIN = ("taskset", "-c", "0-15")


@dataclass
class Result:
    frames: int = 0  # frames that were compared
    differing: int = 0
    first: int | None = None  # first differing frame, counted from 0
    compared: bool = False
    faults: list = field(default_factory=list)


def file_path(out_dir, name, side, suffix):
    return os.path.join(out_dir, f"{name}.{side}.{suffix}")


def read_text(path):
    try:
        with open(path, errors="replace") as file:
            return file.read()
    except FileNotFoundError:
        return ""


def has_report_line(stderr_text, switch):
    """True when one line of stderr_text names every switch of the value."""
    names = [name for name in switch.split(",") if name]
    patterns = [re.compile(rf"(?<![\w/-]){re.escape(name)}(?![\w/-])") for name in names]
    return bool(patterns) and any(all(p.search(line) for p in patterns) for line in stderr_text.splitlines())


def compare_recording(out_dir, name, switch="", exit_codes=None):
    """Compare the two hash files of one recording. exit_codes gives the replay exit code of each side, if known."""
    result = Result()
    hashes = {}
    for side in SIDES:
        log = file_path(out_dir, name, side, "err")
        code = (exit_codes or {}).get(side, 0)
        if code:
            tail = "".join(f"\n      {line}" for line in read_text(log).splitlines()[-5:])
            result.faults.append(f"{side} replay failed with exit code {code}, log {log}{tail}")
            continue
        if side == "candidate" and switch and not has_report_line(read_text(log), switch):
            result.faults.append(f"no switch report: no line of the candidate's standard error names every switch "
                                 f"of '{switch}', log {log}")
        try:
            array = np.load(file_path(out_dir, name, side, "npy"), allow_pickle=False)
        except (OSError, ValueError, EOFError) as error:
            result.faults.append(f"no hashes of the {side} core: {error}")
            continue
        if array.ndim != 1 or array.dtype != np.uint64 or not len(array):
            result.faults.append(f"the {side} hash file holds no list of frame hashes "
                                 f"(shape {array.shape}, type {array.dtype})")
            continue
        if np.all(array == array[0]):
            result.faults.append(f"hash control: all {len(array)} hashes of the {side} core are equal in recording "
                                 f"{name}; the check does not read the current work RAM")
        hashes[side] = array
    if len(hashes) == len(SIDES):
        baseline, candidate = hashes["baseline"], hashes["candidate"]
        result.compared = True
        result.frames = min(len(baseline), len(candidate))
        differing = np.flatnonzero(baseline[:result.frames] != candidate[:result.frames])
        result.differing = len(differing)
        result.first = int(differing[0]) if len(differing) else None
        if len(baseline) != len(candidate):
            result.faults.append(f"different frame counts: baseline {len(baseline)}, candidate {len(candidate)}")
    return result


def report(name, result):
    if not result.compared:
        print(f"{name}: not compared")
    else:
        first = f", first differing frame {result.first} (counted from 0)" if result.differing else ""
        print(f"{name}: {result.frames} frames, {result.differing} differing frames{first}")
    for fault in result.faults:
        print(f"  FAULT {name}: {fault}")
    sys.stdout.flush()


def total(results):
    """Print the total line and return the exit code."""
    frames = sum(r.frames for r in results)
    differing = sum(r.differing for r in results)
    faults = sum(len(r.faults) for r in results)
    passed = bool(results) and not differing and not faults
    print(f"TOTAL: {len(results)} recordings, {frames} frames, {differing} differing frames, {faults} faults: "
          f"{'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


def recording_names(recordings):
    """One name per recording for the output files: the file name without .bk2, with a number when it repeats."""
    names = []
    for path in recordings:
        stem = os.path.splitext(os.path.basename(path))[0]
        name, number = stem, 1
        while name in names:
            number += 1
            name = f"{stem}-{number}"
        names.append(name)
    return names


def run_replay(recording, core_dir, switch, out_dir, name, side):
    hashes = file_path(out_dir, name, side, "npy")
    if os.path.exists(hashes):
        os.remove(hashes)  # never compare the result of an earlier run
    environment = {key: value for key, value in os.environ.items()
                   if key not in (replay.SWITCH_VARIABLE, "RETRO_CORE_PATH")}
    command = [*PIN, sys.executable, "-I", os.path.join(HERE, "replay.py"), f"--switch={switch}", "--",
               recording, core_dir, hashes]
    with open(file_path(out_dir, name, side, "out"), "wb") as out, \
            open(file_path(out_dir, name, side, "err"), "wb") as err:
        return subprocess.run(command, env=environment, stdout=out, stderr=err).returncode


def compare_only(out_dir, switch):
    pattern = re.compile(rf"(.+)\.(?:{'|'.join(SIDES)})\.(?:npy|out|err)")
    # Logs count too: a recording whose two replays failed has no hash file, and it must not disappear.
    names = sorted({m.group(1) for m in map(pattern.fullmatch, os.listdir(out_dir)) if m})
    results = []
    for name in names:
        results.append(compare_recording(out_dir, name, switch))
        report(name, results[-1])
    return total(results)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Compare the work RAM of two cores on recordings.")
    parser.add_argument("recordings", nargs="*", help=".bk2 files")
    parser.add_argument("--candidate", help="core folder to check")
    parser.add_argument("--baseline", help="reference core folder (default: the installed stable-retro cores folder)")
    parser.add_argument("--switch", default="", help=f"value of {replay.SWITCH_VARIABLE} for the candidate")
    parser.add_argument("--jobs", type=int, default=16, help="replay processes at the same time (default 16)")
    parser.add_argument("--out-dir", help="folder for hashes and logs (default: a new temporary folder)")
    parser.add_argument("--compare-only", metavar="DIR", help="compare the files of DIR without a replay")
    args = parser.parse_args(argv)

    if args.compare_only:
        if args.recordings or args.candidate or args.baseline or args.out_dir:
            parser.error("--compare-only takes only --switch")
        if not os.path.isdir(args.compare_only):
            parser.error(f"no folder {args.compare_only}")
        return compare_only(args.compare_only, args.switch)

    if not args.candidate or not args.recordings:
        parser.error("give --candidate and at least one recording")
    if args.jobs < 1:
        parser.error("--jobs must be 1 or more")
    cores = {"baseline": os.path.realpath(args.baseline or replay.default_core_dir()),
             "candidate": os.path.realpath(args.candidate)}
    for side, core_dir in cores.items():
        for file in (replay.CORE_FILE, replay.CORE_INFO_FILE):
            if not os.path.isfile(os.path.join(core_dir, file)):
                parser.error(f"the {side} core folder {core_dir} has no file {file}")
    recordings = [os.path.abspath(path) for path in args.recordings]
    for path in recordings:
        if not os.path.isfile(path):
            parser.error(f"no recording file {path}")
    if args.out_dir:
        out_dir = os.path.abspath(args.out_dir)
        os.makedirs(out_dir, exist_ok=True)
    else:
        out_dir = tempfile.mkdtemp(prefix="parity-")
    switches = {"baseline": "", "candidate": args.switch}
    for side in SIDES:
        print(f"{side}: {cores[side]}, switch {switches[side] or '(none)'}")
    print(f"hashes and logs: {out_dir}", flush=True)

    names = recording_names(recordings)
    results = []
    with ThreadPoolExecutor(args.jobs) as pool:
        runs = [{side: pool.submit(run_replay, path, cores[side], switches[side], out_dir, name, side)
                 for side in SIDES}
                for path, name in zip(recordings, names)]
        for name, run in zip(names, runs):
            exit_codes = {side: future.result() for side, future in run.items()}
            results.append(compare_recording(out_dir, name, args.switch, exit_codes))
            report(name, results[-1])
    return total(results)


if __name__ == "__main__":
    sys.exit(main())
