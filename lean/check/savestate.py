"""Savestate check: save states in one core, load them in the other core, and compare the frames after the load.

Command:
    savestate.py --candidate <core-dir> [--baseline <core-dir>] [--switch VALUE] [--jobs N] [--out-dir DIR]
                 <recording.bk2> ...

The save frames are at 25 %, 50 % and 75 % of each recording. First, each core replays the recording to these frames
and saves a state at each one. Then each load runs 900 frames with the inputs of the recording, or the frames that the
recording still has:

    reference                      the baseline core loads its own state
    baseline loads candidate state work RAM and screen, compared with the reference
    candidate loads baseline state work RAM, compared with the reference; the screen too when the switch value does not
                                   contain `video`

With no switch, the two saved states of each save frame must also be equal byte for byte. With a switch value, the
standard error of each candidate process must contain the switch report line (see parity.py).

There is one process per core, recording and step (save, load), each under `taskset -c 0-15`, at most N at a time
(default 16). DIR holds the states, the hashes and the output of the processes; without --out-dir it is a new
temporary folder. The default baseline folder is the cores folder of the installed stable-retro, with no switch.

Exit code: 0 when every recording is clean, 1 on a difference or a fault, 2 on a wrong command.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # `python -I` does not add the folder of the script
sys.dont_write_bytecode = True  # no __pycache__ folder in the checkout
import parity  # noqa: E402
import replay  # noqa: E402

SIDES = parity.SIDES
PHASES = ("save", "load")
FRAMES_AFTER_LOAD = 900
# The states that each core loads. The baseline loads its own state first: that run is the reference.
SOURCES = {"baseline": ("baseline", "candidate"), "candidate": ("baseline",)}


@dataclass
class Result:
    header: str = "not compared"
    lines: list = field(default_factory=list)
    loads: int = 0  # loads in the other core that were compared
    frames: int = 0  # frames after these loads
    ram_differing: int = 0
    screen_differing: int = 0
    faults: list = field(default_factory=list)


def state_path(out_dir, name, side, number):
    return parity.file_path(out_dir, name, side, f"p{number}.state")


def video_off(switch):
    return "video" in switch.split(",")


def state_blocks(state):
    """The blocks of a Snes9x savestate: {name: (offset of the data, size)}."""
    blocks = {}
    position = state.find(b"\n") + 1  # after the version line; then blocks "NAM:000123:<data>"
    while position and position + 11 <= len(state):
        head = state[position:position + 11]
        if head[3:4] != b":" or head[10:11] != b":" or not head[4:10].isdigit():
            break
        size = int(head[4:10])
        blocks[head[:3].decode("latin-1")] = (position + 11, size)
        position += 11 + size
    return blocks


def state_difference(first, second):
    """None when the two savestates are equal, else a text that says where they differ."""
    if first == second:
        return None
    if len(first) != len(second):
        return f"sizes of {len(first)} and {len(second)} bytes"
    differing = np.flatnonzero(np.frombuffer(first, np.uint8) != np.frombuffer(second, np.uint8))
    parts = []
    for block, (start, size) in state_blocks(first).items():
        count = int(((differing >= start) & (differing < start + size)).sum())
        if count:
            parts.append(f"{block} {count}")
    return (f"{len(differing)} bytes differ, the first at offset {differing[0]} "
            f"(per block: {', '.join(parts) or 'none, outside the blocks'})")


# --- the worker processes -----------------------------------------------------------------------------------------

def screen_hash(screen):
    digest = hashlib.blake2b(str(screen.shape).encode(), digest_size=8)
    digest.update(screen.tobytes())
    return int.from_bytes(digest.digest(), "little")


def load_state(em, state, what):
    if em.set_state(state) is not True:  # a rejected state leaves the emulator as it was
        raise RuntimeError(f"the core rejected {what}")


def step(em, mask):
    em.set_button_mask(mask, 0)
    em.step()


def save_worker(job, env, ram, start_state, masks):
    em = env.em
    load_state(em, start_state, "the start state of the recording")
    points = [len(masks) * quarter // 4 for quarter in (1, 2, 3)]
    ram_hashes = []
    done = 0
    for number, point in enumerate(points, 1):
        for mask in masks[done:point]:
            step(em, mask)
        done = point
        with open(state_path(job["out_dir"], job["name"], job["side"], number), "wb") as file:
            file.write(em.get_state())
        ram_hashes.append(replay.frame_hash(ram))
    with open(parity.file_path(job["out_dir"], job["name"], job["side"], "save.json"), "w") as file:
        json.dump({"frames": len(masks), "points": points, "ram_hashes": ram_hashes}, file)


def load_worker(job, env, ram, masks):
    em = env.em
    arrays = {}
    points = [len(masks) * quarter // 4 for quarter in (1, 2, 3)]
    for number, point in enumerate(points, 1):
        for source in SOURCES[job["side"]]:
            path = state_path(job["out_dir"], job["name"], source, number)
            with open(path, "rb") as file:
                load_state(em, file.read(), f"the savestate {path}")
            key = f"{source}.p{number}"
            arrays[f"{key}.loaded"] = np.uint64(replay.frame_hash(ram))
            ram_hashes, screen_hashes = [], []
            for mask in masks[point:point + FRAMES_AFTER_LOAD]:
                step(em, mask)
                ram_hashes.append(replay.frame_hash(ram))
                if job["screen"]:
                    screen_hashes.append(screen_hash(em.get_screen()))
            arrays[f"{key}.ram"] = np.array(ram_hashes, dtype=np.uint64)
            arrays[f"{key}.screen"] = np.array(screen_hashes, dtype=np.uint64)
    with open(parity.file_path(job["out_dir"], job["name"], job["side"], "load.npz"), "wb") as file:
        np.savez(file, **arrays)


def worker(job):
    env, ram = replay.prepare(job["core_dir"], job["switch"])
    start_state, masks = replay.open_movie(env, job["recording"])
    masks = list(masks)
    if job["phase"] == "save":
        save_worker(job, env, ram, start_state, masks)
    else:
        load_worker(job, env, ram, masks)
    return 0


def run_worker(job):
    command = [*parity.PIN, sys.executable, "-I", os.path.join(HERE, "savestate.py"), "--worker", json.dumps(job)]
    prefix = f"{job['phase']}."
    with open(parity.file_path(job["out_dir"], job["name"], job["side"], prefix + "out"), "wb") as out, \
            open(parity.file_path(job["out_dir"], job["name"], job["side"], prefix + "err"), "wb") as err:
        return subprocess.run(command, env=replay.child_environment(), stdout=out, stderr=err).returncode


# --- the comparison -----------------------------------------------------------------------------------------------

def compare_recording(out_dir, name, switch="", exit_codes=None):
    """Compare the files of one recording. exit_codes gives the exit code of each (side, phase) process that ran."""
    result = Result()
    exit_codes = exit_codes or {}
    for (side, phase), code in exit_codes.items():
        log = parity.file_path(out_dir, name, side, f"{phase}.err")
        if code:
            tail = "".join(f"\n      {line}" for line in parity.read_text(log).splitlines()[-5:])
            result.faults.append(f"{side} {phase} process failed with exit code {code}, log {log}{tail}")
    if any(exit_codes.values()):
        return result
    if switch:
        for phase in PHASES:
            log = parity.file_path(out_dir, name, "candidate", f"{phase}.err")
            if not parity.has_report_line(parity.read_text(log), switch):
                result.faults.append(f"no switch report: no line of the standard error of the candidate {phase} "
                                     f"process names every switch of '{switch}', log {log}")
    try:
        _compare_files(out_dir, name, switch, result)
    except (OSError, ValueError, KeyError, IndexError, zipfile.BadZipFile) as error:
        result.faults.append(f"missing or damaged result files: {type(error).__name__}: {error}")
    return result


def _compare_files(out_dir, name, switch, result):
    saves, loads = {}, {}
    for side in SIDES:
        with open(parity.file_path(out_dir, name, side, "save.json")) as file:
            saves[side] = json.load(file)
        with np.load(parity.file_path(out_dir, name, side, "load.npz"), allow_pickle=False) as arrays:
            loads[side] = dict(arrays)
    frames, points = saves["baseline"]["frames"], saves["baseline"]["points"]
    result.header = f"{frames} frames, save frames {', '.join(map(str, points))}"
    if saves["candidate"]["frames"] != frames or saves["candidate"]["points"] != points or len(points) != 3:
        result.faults.append("the two save processes used different save frames")
        return
    for number, point in enumerate(points, 1):
        if saves["baseline"]["ram_hashes"][number - 1] != saves["candidate"]["ram_hashes"][number - 1]:
            result.faults.append(f"the work RAM of the two cores differs at the save frame {point}")

    runs = {}  # (core that loads, core that saved) -> lists of the hash arrays of the three loads
    for loader, sources in SOURCES.items():
        for source in sources:
            runs[loader, source] = {"ram": [], "screen": []}
            for number, point in enumerate(points, 1):
                key = f"{source}.p{number}"
                if int(loads[loader][f"{key}.loaded"]) != saves[source]["ram_hashes"][number - 1]:
                    result.faults.append(f"the {loader} core loaded the {source} state of frame {point}, and the work "
                                         f"RAM after the load is not the work RAM at the save")
                for kind in ("ram", "screen"):
                    runs[loader, source][kind].append(loads[loader][f"{key}.{kind}"])

    reference = runs["baseline", "baseline"]
    for loader, source in (("baseline", "candidate"), ("candidate", "baseline")):
        draws = loader == "baseline" or not video_off(switch)
        for index, point in enumerate(points):
            what = f"{loader} loads {source} state, frame {point}"
            expected, got = reference["ram"][index], runs[loader, source]["ram"][index]
            count = min(len(expected), len(got))
            if not count or len(expected) != len(got):
                result.faults.append(f"{what}: {len(got)} frames after the load, {len(expected)} in the reference")
            if not count:
                continue
            short = " (the recording ends)" if count < FRAMES_AFTER_LOAD else ""
            text, differing = _differences("RAM", expected[:count], got[:count])
            result.ram_differing += differing
            if draws:
                expected_screen = reference["screen"][index]
                got_screen = runs[loader, source]["screen"][index]
                if len(expected_screen) != len(expected) or len(got_screen) != len(got):
                    result.faults.append(f"{what}: the screen hashes are not complete")
                shown = min(len(expected_screen), len(got_screen))
                screen_text, differing = _differences("screen", expected_screen[:shown], got_screen[:shown])
                result.screen_differing += differing
            else:
                screen_text = "screen not compared (video off)"
            result.loads += 1
            result.frames += count
            result.lines.append(f"{what}: {count} frames{short}, {text}, {screen_text}")

    # Hash control: a stale RAM view or screen gives equal values in all frames, also in equal runs.
    for (loader, source), run in runs.items():
        for kind, label in (("ram", "RAM"), ("screen", "screen")):
            values = np.concatenate(run[kind])
            if len(values) > 1 and np.all(values == values[0]):
                result.faults.append(f"hash control: all {len(values)} {label} hashes are equal when the {loader} core "
                                     f"loads the {source} states of recording {name}")

    if not switch:
        unequal = 0
        for number, point in enumerate(points, 1):
            states = []
            for side in SIDES:
                with open(state_path(out_dir, name, side, number), "rb") as file:
                    states.append(file.read())
            difference = state_difference(*states)
            if difference:
                unequal += 1
                result.faults.append(f"savestates of the two cores at frame {point} are not equal: {difference}")
        if not unequal:
            result.lines.append("savestates of the two cores: byte-equal at the 3 save frames")


def _differences(label, expected, got):
    differing = np.flatnonzero(expected != got)
    first = f" (first at frame {differing[0]} after the load, counted from 0)" if len(differing) else ""
    return f"{label} {len(differing)} differing{first}", len(differing)


def report(name, result):
    print(f"{name}: {result.header}")
    for line in result.lines:
        print(f"  {line}")
    for fault in result.faults:
        print(f"  FAULT {name}: {fault}")
    sys.stdout.flush()


def total(results):
    """Print the total line and return the exit code."""
    ram = sum(r.ram_differing for r in results)
    screen = sum(r.screen_differing for r in results)
    faults = sum(len(r.faults) for r in results)
    passed = bool(results) and not ram and not screen and not faults
    print(f"TOTAL: {len(results)} recordings, {sum(r.loads for r in results)} loads, "
          f"{sum(r.frames for r in results)} frames, {ram} differing RAM frames, {screen} differing screen frames, "
          f"{faults} faults: {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


def main(argv=None, after_save=None):
    """Run the check. after_save(out_dir) is a test hook: it runs between the save processes and the loads."""
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["--worker"]:
        return worker(json.loads(argv[1]))
    parser = argparse.ArgumentParser(description="Compare two cores after savestate loads in two directions.")
    parser.add_argument("recordings", nargs="+", help=".bk2 files")
    parser.add_argument("--candidate", required=True, help="core folder to check")
    parser.add_argument("--baseline", help="reference core folder (default: the installed stable-retro cores folder)")
    parser.add_argument("--switch", default="", help=f"value of {replay.SWITCH_VARIABLE} for the candidate")
    parser.add_argument("--jobs", type=int, default=16, help="processes at the same time (default 16)")
    parser.add_argument("--out-dir", help="folder for states, hashes and logs (default: a new temporary folder)")
    args = parser.parse_args(argv)

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
        out_dir = tempfile.mkdtemp(prefix="savestate-")
    switches = {"baseline": "", "candidate": args.switch}
    for side in SIDES:
        print(f"{side}: {cores[side]}, switch {switches[side] or '(none)'}")
    print(f"states, hashes and logs: {out_dir}", flush=True)

    names = parity.recording_names(recordings)
    for name in names:  # never use the files of an earlier run
        old = re.compile(rf"{re.escape(name)}\.(?:{'|'.join(SIDES)})\.(?:save\.json|load\.npz|p\d\.state)")
        for file in filter(old.fullmatch, os.listdir(out_dir)):
            os.remove(os.path.join(out_dir, file))

    def job(path, name, side, phase):
        screen = side == "baseline" or not video_off(args.switch)
        return {"phase": phase, "recording": path, "core_dir": cores[side], "switch": switches[side],
                "out_dir": out_dir, "name": name, "side": side, "screen": screen}

    exit_codes = {name: {} for name in names}
    with ThreadPoolExecutor(args.jobs) as pool:
        for phase in PHASES:  # all states exist before the first load starts
            jobs = [job(path, name, side, phase) for path, name in zip(recordings, names) for side in SIDES
                    if not any(exit_codes[name].values())]
            for done, code in zip(jobs, pool.map(run_worker, jobs)):
                exit_codes[done["name"]][done["side"], phase] = code
            if phase == "save" and after_save:
                after_save(out_dir)
    results = []
    for name in names:
        results.append(compare_recording(out_dir, name, args.switch, exit_codes[name]))
        report(name, results[-1])
    return total(results)


if __name__ == "__main__":
    sys.exit(main())
