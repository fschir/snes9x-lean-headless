# Lean core

Tools for the lean-core work in this fork. The core is the SNES core of stable-retro 1.0.1.

## Build

Run the command in the root folder of the checkout:

```sh
lean/build.sh <out-dir>
```

`<out-dir>` is the core folder. It must be outside the checkout. The script creates it if necessary.

All arguments: `lean/build.sh <out-dir> [--flags stable-retro|default] [--extra "<flags>"]`

The script needs `git`, `rsync`, `make`, `gcc`, `g++` and `nm`.

### What the script does

- It copies the working tree into a temporary folder. The copy has the tracked files with their uncommitted changes. It
  also has the new files that git does not ignore. The script writes nothing into the checkout.
- It deletes `*.o` and `*.so` files from the copy, so make cannot use objects of an earlier build.
- It builds in `libretro/` of the copy with the recipe of stable-retro 1.0.1: the libretro Makefile, `CFLAGS`
  `-w -std=gnu17`, `CXXFLAGS` `-w`, `LDFLAGS` `-w -static-libstdc++ -Wl,--exclude-libs,ALL`, and `fpic=-fPIC`.
  `LAGFIX=1` stays, because it sets the point where a frame ends.
- It gives the commit of the checkout to the Makefile, so the core reports the version `1.54.1 <short commit>`.
- It compares the exported symbols of the library with the 25 names in `lean/exports.txt`. On a difference the script
  stops with an error and writes no core.

The build runs in `$TMPDIR` (default `/tmp`). The script removes the temporary folder at the end. If that place is full,
set `TMPDIR` to another folder outside the checkout.

### Flag sets

| Set            | Added compiler flags                                            |
|----------------|-----------------------------------------------------------------|
| `stable-retro` | None. This is the recipe of stable-retro.                       |
| `default`      | The flags that the flag A/B accepts. None yet.                  |

A build without `--flags` uses `default`. The table of the sets is the function `flags_of_set` in `lean/build.sh`.

`--extra "<flags>"` adds flags on top of the set, for example `--extra "-O3 -flto"`. The script passes the flags of the
set and the extra flags to make as `LEAN_FLAGS`. The Makefile puts them at the end of the compile lines and of the link
line, so a later `-O3` wins over the `-O2` of the Makefile.

### Core folder

| File                 | Content                                                  |
|----------------------|----------------------------------------------------------|
| `snes9x_libretro.so` | The core.                                                |
| `snes9x.json`        | The core info file of stable-retro 1.0.1.                |
| `build-info.txt`     | The build record.                                        |
| `build.log`          | The full output of make.                                 |

The script first removes these four files from `<out-dir>`. After a failed build the folder has no core.

The build record gives:

- `commit`: the commit of the checkout.
- `dirty`: `yes` when the checkout had changed or new files that were not committed.
- `flag set`: the set of the build.
- `extra flags`: the value of `--extra`.
- `LEAN_FLAGS`: all flags that the build added to the recipe.
- `compiler`: the first line of `gcc --version`.

### Use the core folder

Set `RETRO_CORE_PATH` to the full path of the core folder **before** Python imports `stable_retro`. A change after the
import has no effect.

This command shows the core file that the process loaded. It needs a Python with stable-retro 1.0.1 and an imported
Super Mario World ROM.

```sh
RETRO_CORE_PATH=<out-dir> <mario-gym>/.venv/bin/python -I -c '
import stable_retro
env = stable_retro.make("SuperMarioWorld-Snes-v0", state=stable_retro.State.NONE, render_mode=None)
print(*{line.split()[-1] for line in open("/proc/self/maps") if "snes9x_libretro" in line})
env.close()
'
```

The output must be `<out-dir>/snes9x_libretro.so`.

## Switches

(filled by a later task)

## Parity check

The parity check shows that a candidate core gives the same work RAM as the baseline core. It replays each recording on
the two cores and compares a hash of the 128 KB work RAM after each frame.

Use a Python that has stable-retro 1.0.1, numpy and the imported ROM. Run this command in the root folder of the
repository:

```sh
<mario-gym>/.venv/bin/python -I lean/check/parity.py --candidate <core-dir> --out-dir <out-dir> \
    <mario-gym>/local/build/recordings/ysp-direct.bk2 <mario-gym>/local/build/playthrough/s01.bk2
```

- `<core-dir>` holds `snes9x_libretro.so` and `snes9x.json`.
- The baseline is the core of the installed stable-retro. `--baseline <core-dir>` selects a different one. The baseline
  always runs with no switch.
- `--switch video,dsp` sets `SNES9X_LEAN` for the candidate. The candidate must then write one line to the standard
  error stream that names each switch.
- The replays run in parallel on CPUs 0 to 15 (`taskset`). `--jobs N` sets the number of processes. The default is 16.
- `--out-dir` keeps the hash files and the logs. Without it, the check makes a new temporary folder and shows its path.
  For all nine recordings, give `--out-dir` on a disk with space: the hash files of the long recordings are several MB.
- `--compare-only <out-dir>` compares the files of such a folder again, without a replay.

The check shows the frames and the differing frames of each recording, then a total line. It shows the first differing
frame, counted from 0. These are faults: a failed replay, a different number of frames, a missing switch report, a
different loaded core file, and a hash that is equal for all frames of a recording. The exit code is 0 only when all
recordings have no difference and no fault.

`<mario-gym>/.venv/bin/python -I lean/check/selftest.py` tests the fault paths on made-up files. It needs no emulator.

## Savestate check

The savestate check shows that a state of one core works in the other core. It saves states at 25 %, 50 % and 75 % of
each recording, in the two cores. Then it loads the states and runs 900 frames with the inputs of the recording.

Run this command in the root folder of the repository:

```sh
<mario-gym>/.venv/bin/python -I lean/check/savestate.py --candidate <core-dir> --out-dir <out-dir> \
    <mario-gym>/local/build/recordings/ysp-direct.bk2 <mario-gym>/local/build/playthrough/s01.bk2
```

- The reference is the baseline core that loads its own state.
- The baseline core loads the candidate state. The check compares the work RAM and the screen of each frame with the
  reference.
- The candidate core loads the baseline state. The check compares the work RAM. It compares the screen only when the
  switch value does not contain `video`.
- When a recording has less than 900 frames after a save frame, the check runs the remaining frames and shows this.
  `ysp-direct` is such a recording at 75 %. A save frame with no frame after it is a fault.
- With no switch, the savestates of the two cores must be equal, byte for byte.
- `--switch`, `--baseline`, `--jobs` and `--out-dir` work as in the parity check. Without `--out-dir`, the check makes a
  new temporary folder.

The check shows each load and a total line. The exit code is 0 only when there is no differing frame and no fault.

## Speed bench

The speed bench measures the time of one emulated frame: the button input and the frame step. Run it on a quiet
machine. Run this command in the root folder of the repository:

```sh
<mario-gym>/.venv/bin/python -I lean/check/bench.py --candidate <core-dir> \
    <mario-gym>/local/build/reference/a1-human-96exit.bk2 \
    <mario-gym>/local/build/recordings/full-run-02.bk2 \
    <mario-gym>/local/build/recordings/full-run-04.bk2 \
    <mario-gym>/local/build/recordings/full-run-05.bk2
```

- The settings are the baseline core with no switch (the reference) and the candidate core with no switch, `video`,
  `dsp` and `video,dsp`.
- `--settings` selects the settings with a comma between two names: `ref`, `none`, `video`, `dsp`, `video+dsp` (both
  switches). The default is all of them. The bench always measures the reference `ref`.
- Each measurement uses the first 15,000 frames of each recording (`--frames`).
- The bench measures 1 worker on CPU 4, then 16 workers on CPUs 0 to 15. `--workers 1` or `--workers 16` measures only
  one worker count. The default is `both`.
- The settings run in turn, in three rounds (`--rounds`). With 16 workers, the value of a round is the mean time of the
  workers.
- The bench shows the 1-minute load average. It stops when the load is more than 2.0. `--allow-load` starts it in spite
  of this; numbers from a busy machine are not measurements.

The table gives the median, the lowest and the highest time per frame in microseconds. `time/ref` is the time divided by
the time of the reference. `speed-up` is the reverse ratio. The exit code is 1 when the candidate writes no switch report
line for a switch setting, because the switch did not reach the core.

Results: (filled by task 5.2)

## Compiler flags

(filled by a later task)
