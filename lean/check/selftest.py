"""Self test of the fault paths of the parity check, on made-up hash files and maps lines.

Command:
    selftest.py

It starts no emulator and does not import stable_retro; it needs numpy. It prints PASS or FAIL for each case. The
exit code is 0 only when every case passes.
"""
import os
import subprocess
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # `python -I` does not add the folder of the script
sys.dont_write_bytecode = True  # no __pycache__ folder in the checkout
import replay  # noqa: E402

FRAMES = np.arange(1, 101, dtype=np.uint64)  # 100 different made-up frame hashes


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def parity(folder, *options):
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
    code, output = parity(folder, *options)
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


def missing_switch_report(folder):
    # No line is a report: one name per line, and names that are only parts of a path or of a longer word.
    noise = "note: /tmp/core-video-dsp/snes9x_libretro.so\nvideo only\ndsp only\nvideos and adsp\n"
    for stderr in (noise, ""):
        write(folder, "silent", FRAMES, FRAMES, stderr=stderr)
        expect(folder, False, "FAULT silent: no switch report", "0 differing frames, 1 faults: FAIL",
               options=("--switch", "video,dsp"))
    expect(folder, True, "PASS")  # without a switch, no report is necessary


def switch_report_present(folder):
    write(folder, "lean", FRAMES, FRAMES, stderr="other line\nSNES9X_LEAN: switches dsp, video.\n")
    expect(folder, True, "0 faults: PASS", options=("--switch", "video,dsp"))
    write(folder, "lean", FRAMES, FRAMES, stderr="SNES9X_LEAN=video\n")
    expect(folder, True, "0 faults: PASS", options=("--switch", "video"))


CASES = (equal_hashes, one_differing_frame, different_frame_counts, all_hashes_equal, missing_hashes,
         wrong_loaded_core, missing_switch_report, switch_report_present)


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
