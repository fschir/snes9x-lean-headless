"""Self test of the fault paths of the check tools, on made-up result files and maps lines.

Command:
    selftest.py

It starts no emulator and does not import stable_retro; it needs numpy. It prints PASS or FAIL for each case. The
exit code is 0 only when every case passes.
"""
import json
import os
import subprocess
import sys
import tempfile
import types

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # `python -I` does not add the folder of the script
sys.dont_write_bytecode = True  # no __pycache__ folder in the checkout
import bench  # noqa: E402
import parity  # noqa: E402
import replay  # noqa: E402
import savestate  # noqa: E402

FRAMES = np.arange(1, 101, dtype=np.uint64)  # 100 different made-up frame hashes


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def run_parity(folder, *options):
    """Run parity.py on the files of folder; return (exit code, standard output)."""
    command = [sys.executable, "-I", os.path.join(HERE, "parity.py"), "--compare-only", folder, *options]
    run = subprocess.run(command, capture_output=True, text=True)
    return run.returncode, run.stdout + run.stderr


def write(folder, name, baseline, candidate, stderr=None):
    for side, hashes in (("baseline", baseline), ("candidate", candidate)):
        if hashes is not None:
            np.save(os.path.join(folder, f"{name}.{side}.npy"), hashes)
    if stderr is not None:
        with open(os.path.join(folder, f"{name}.candidate.err"), "w") as file:
            file.write(stderr)


def expect(folder, passes, *texts, options=()):
    code, output = run_parity(folder, *options)
    check(code == (0 if passes else 1), f"exit code {code}\n{output}")
    for text in texts:
        check(text in output, f"the output lacks '{text}'\n{output}")


def equal_hashes(folder):
    write(folder, "one", FRAMES, FRAMES)
    write(folder, "two", FRAMES[:40], FRAMES[:40])
    expect(folder, True, "one: 100 frames, 0 differing frames", "two: 40 frames, 0 differing frames",
           "TOTAL: 2 recordings, 140 frames, 0 differing frames, 0 faults: PASS")


def one_differing_frame(folder):
    changed = FRAMES.copy()
    changed[37] += np.uint64(1)
    write(folder, "clean", FRAMES, FRAMES)
    write(folder, "broken", FRAMES, changed)
    expect(folder, False, "broken: 100 frames, 1 differing frames, first differing frame 37",
           "TOTAL: 2 recordings, 200 frames, 1 differing frames, 0 faults: FAIL")


def different_frame_counts(folder):
    write(folder, "short", FRAMES, FRAMES[:99])  # equal in the first 99 frames
    expect(folder, False, "FAULT short: different frame counts: baseline 100, candidate 99",
           "0 differing frames, 1 faults: FAIL")


def all_hashes_equal(folder):
    stale = np.full(100, 7, dtype=np.uint64)  # the two sides agree: only the hash control can see it
    write(folder, "stale", stale, stale)
    expect(folder, False, "FAULT stale: hash control: all 100 hashes of the baseline core are equal",
           "FAULT stale: hash control: all 100 hashes of the candidate core are equal", "FAIL")


def missing_hashes(folder):
    expect(folder, False, "TOTAL: 0 recordings")  # nothing to compare is not a pass
    write(folder, "half", FRAMES, None)
    write(folder, "none", None, None, stderr="error\n")  # both replays failed: only a log is left
    expect(folder, False, "half: not compared", "FAULT half: no hashes of the candidate core",
           "none: not compared", "TOTAL: 2 recordings")


def wrong_loaded_core(folder):
    expected = os.path.join(os.path.realpath(folder), replay.CORE_FILE)
    other = "/opt/other cores/" + replay.CORE_FILE
    line = "7f0000000000-7f0000001000 r-xp 00000000 00:00 42    {}\n"
    plain = ["7f0000002000-7f0000003000 rw-p 00000000 00:00 0 \n", line.format("/usr/lib/libc.so.6")]
    replay.check_loaded_core(plain + [line.format(expected)] * 2, folder)  # the right core raises nothing
    for lines, text in (([line.format(other)], other),
                        ([line.format(expected), line.format(other)], other),
                        (plain, "no snes9x_libretro file is loaded")):
        try:
            replay.check_loaded_core(lines, folder)
        except replay.LoadedCoreError as error:
            check(text in str(error), f"the error lacks '{text}': {error}")
        else:
            raise AssertionError(f"no error for {lines}")


def switch_report(folder):
    # No line is a report: one name per line, and names that are only parts of a path or of a longer word.
    noise = "note: /tmp/core-video-dsp/snes9x_libretro.so\nvideo only\ndsp only\nvideos and adsp\n"
    for stderr in (noise, ""):
        write(folder, "silent", FRAMES, FRAMES, stderr=stderr)
        expect(folder, False, "FAULT silent: no switch report", "0 differing frames, 1 faults: FAIL",
               options=("--switch", "video,dsp"))
    expect(folder, True, "PASS")  # without a switch, no report is necessary
    # A failed candidate replay shows the missing report too.
    faults = parity.compare_recording(folder, "silent", "video", {"candidate": 1}).faults
    check(len(faults) == 2 and "replay failed" in faults[0] and "no switch report" in faults[1], f"{faults}")
    # With the report line, the same recording passes.
    for stderr, switch in (("other line\nSNES9X_LEAN: switches dsp, video.\n", "video,dsp"),
                           ("SNES9X_LEAN=video\n", "video")):
        write(folder, "silent", FRAMES, FRAMES, stderr=stderr)
        expect(folder, True, "0 faults: PASS", options=("--switch", switch))


def switch_flags(folder):
    def core(flags):  # a made-up library; flags None = a core without the export
        return types.SimpleNamespace() if flags is None else types.SimpleNamespace(snes9x_lean_flags=lambda: flags)

    for flags, switch in ((3, "video,dsp"), (3, "dsp,video"), (1, "video"), (2, "dsp,dsp"), (0, ""), (None, "")):
        replay.check_switch_flags(core(flags), switch)  # these raise nothing
    for flags, switch, text in ((None, "video", "no snes9x_lean_flags"), (0, "video", "expected 1, "),
                                (1, "video,dsp", "expected 3, "), (3, "dsp", "gives 3"), (1, "", "expected 0, "),
                                (-1, "", "gives -1"), (3, "video,sound", "not a switch")):
        try:
            replay.check_switch_flags(core(flags), switch)
        except replay.SwitchError as error:
            check(text in str(error), f"{flags} '{switch}': the error lacks '{text}': {error}")
            check(not parity.has_report_line(str(error), switch or "video"), f"the error reads as a report: {error}")
        else:
            raise AssertionError(f"no error for flags {flags} and switch '{switch}'")


def write_savestate_run(folder, change=None, states=(b"state", b"state")):
    """Made-up result files of savestate.py for one recording "r"; change(arrays) can edit the load results."""
    saved = [11, 12, 13]  # RAM hashes at the three save frames
    arrays = {}
    for side, sources in savestate.SOURCES.items():
        arrays[side] = {}
        for source in sources:
            for number in (1, 2, 3):
                key = f"{source}.p{number}"
                arrays[side][f"{key}.loaded"] = np.uint64(saved[number - 1])
                arrays[side][f"{key}.ram"] = FRAMES + np.uint64(1000 * number)
                arrays[side][f"{key}.screen"] = FRAMES + np.uint64(5000 * number)
    if change:
        change(arrays)
    for side, state in zip(savestate.SIDES, states):
        with open(os.path.join(folder, f"r.{side}.save.json"), "w") as file:
            json.dump({"frames": 400, "points": [100, 200, 300], "ram_hashes": saved}, file)
        np.savez(os.path.join(folder, f"r.{side}.load.npz"), **arrays[side])
        for number in (1, 2, 3):
            with open(savestate.state_path(folder, "r", side, number), "wb") as file:
                file.write(state)
        for phase in savestate.PHASES:
            with open(os.path.join(folder, f"r.{side}.{phase}.err"), "w") as file:
                file.write("SNES9X_LEAN: video,dsp\n" if side == "candidate" else "")


def savestate_comparison(folder):
    def result(switch="", **options):
        write_savestate_run(folder, **options)
        return savestate.compare_recording(folder, "r", switch)

    def faults(run, text):
        check(any(text in fault for fault in run.faults), f"no fault with '{text}': {run.faults}")

    clean = result()
    check((clean.loads, clean.frames, clean.ram_differing, clean.screen_differing, clean.faults) == (6, 600, 0, 0, []),
          f"clean run: {clean}")

    def one_ram_frame(arrays):
        arrays["candidate"]["baseline.p2.ram"][7] += np.uint64(1)

    broken = result(change=one_ram_frame)
    check(broken.ram_differing == 1 and any("candidate loads baseline state, frame 200" in line
                                            and "first at frame 7 " in line for line in broken.lines), f"{broken}")

    def screens(arrays):
        arrays["candidate"]["baseline.p1.screen"][0] += np.uint64(1)
        arrays["baseline"]["candidate.p3.screen"][0] += np.uint64(1)

    check(result(change=screens).screen_differing == 2, "both screen differences count when the candidate draws")
    lean = result("video,dsp", change=screens, states=(b"state", b"stats"))
    check((lean.screen_differing, lean.faults) == (1, []), f"video off: only the baseline screen counts: {lean}")
    faults(result(states=(b"state", b"stats")), "savestates of the two cores at frame 100 are not equal: 1 bytes")

    def failed_load(arrays):
        arrays["baseline"]["candidate.p1.loaded"] = np.uint64(99)

    faults(result(change=failed_load), "the work RAM after the load is not the work RAM at the save")
    faults(savestate.compare_recording(folder, "r", "", {("candidate", "load"): 1}), "failed with exit code 1")
    os.remove(os.path.join(folder, "r.candidate.load.err"))
    faults(savestate.compare_recording(folder, "r", "video,dsp"), "no switch report")


def bench_rules(folder):
    check(not bench.load_allowed(7.8, False), "a load of 7.8 must stop the bench")
    check(bench.load_allowed(7.8, True) and bench.load_allowed(2.0, False), "the option and the limit 2.0 pass")
    check(bench.summarize([400.0, 410.0, 390.0]) == (400.0, 390.0, 410.0), "median, lowest, highest")
    arms = [("reference", "", ""), ("lean", "", "video")]
    text = bench.table(arms, {(1, "reference"): [300.0, 301.0, 299.0], (1, "lean"): [200.0, 150.0, 250.0]}, ["lean"])
    row = text.splitlines()[-1].split()
    check(row == ["1", "lean", "200.0", "150.0", "250.0", "0.667", "x1.50", "NO", "SWITCH", "REPORT"], text)


CASES = (equal_hashes, one_differing_frame, different_frame_counts, all_hashes_equal, missing_hashes,
         wrong_loaded_core, switch_report, switch_flags, savestate_comparison, bench_rules)


def main():
    failed = 0
    for case in CASES:
        with tempfile.TemporaryDirectory(prefix="selftest-") as folder:
            try:
                case(folder)
            except Exception as error:
                failed += 1
                print(f"FAIL {case.__name__}: {error}")
            else:
                print(f"PASS {case.__name__}")
    print(f"{len(CASES) - failed} of {len(CASES)} cases passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
