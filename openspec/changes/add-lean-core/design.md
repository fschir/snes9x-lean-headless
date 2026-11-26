# Design

## Context

See proposal.md (Why) for the measured costs. Facts that shape the approach (all checked on 2026-11-26 in this
checkout or on the shipped binary of stable-retro 1.0.1):

- **Drawing.** `IPPU.RenderThisFrame` decides if the PPU draws a frame. `S9xSyncSpeed` is an empty function in the
  libretro port, so nothing sets the flag per frame. Only `S9xUnfreezeFromStream` (`snapshot.cpp:1703`, a state load)
  sets it back to TRUE; the TRUE in `gfx.cpp:453` is under `#ifdef DEBUGGER` and is not built. With the flag FALSE,
  `RenderLine` still runs `S9xSetupOBJ` and keeps `PPU.RangeTimeOver` (Snes9x's frameskip design), and
  `S9xEndScreenRefresh` does not call `video_cb`. With the switch set from the core start, `video_cb` is never called,
  so stable-retro has no framebuffer: `get_screen()` and image observations raise `RuntimeError` ("Core did not provide
  a CPU framebuffer"), while RAM observations work (found in task 3.2; an earlier test that switched drawing off after
  the first picture had shown a black screen instead). The owner chose this loud error over a black picture
  (2026-11-26): a program that needs pictures fails at once instead of seeing only black.
- **Sound.** In this build (`SNES9X` is defined in `apu/bapu/snes/snes.hpp:6`) the SPC700 only counts `dsp.clock`; the DSP runs only when
  `DSP::synchronize()` (`apu/bapu/dsp/sdsp.hpp`) catches it up: on a DSP register read or write and at
  `S9xAPUEndScanline`. `synchronize()` calls `spc_dsp.run(clock)` and then sets `clock = 0`. The game CPU talks only to the
  SPC700 (four ports), never to the DSP.
- **Measured with the shipped binary** (flag poke and a `ret` patch of `SNES::SPC_DSP::run`, test processes only):
  work RAM equal on all 1,263,629 frames of the nine recordings with both cuts; em.step 392.5 -> 264.6 (video) ->
  ~190 us (both) on one worker, ~660 -> 455 -> 317 us per worker with 16 workers. Savestates differ in one PPU byte
  (video, a renderer flag that clears at the next drawn frame) and in the sound block (dsp: DSP registers, echo buffer);
  all four cross-loads gave equal work RAM, and equal pictures when the loading core draws.
- **Build.** The Makefile appends `-O2 -DNDEBUG` (`libretro/Makefile:430-434`) after the `CFLAGS`/`CXXFLAGS` of the
  environment, so an `-O3` in the environment would be overridden by the later `-O2`. The export list `link.T` exports
  `retro_*` only (25 symbols today). The GCC-16.2 build of the baseline passed the replay of all nine recordings against
  the shipped GCC-14.2 binary.
- **Consumer.** mario-gym loads the core with `RETRO_CORE_PATH` before `import stable_retro` (the setter after the import
  has no effect) and runs one emulator per process.

## Goals / Non-Goals

**Goals:**
- Each switch is a small guard at the one place where its part of the emulator starts, so a review can see that nothing
  else changes.
- With no switch, the build is the baseline: same code paths, same savestate bytes.
- The checks are tools in this repository that any later core change can run again.

**Non-Goals:**
- No change of the frame boundary, the savestate format, the input rules or any emulated timing.
- No new libretro core option and no exported function: stable-retro answers no core option, and the owner chose the
  environment variable.
- No cache of baseline hashes in this change (the two cores replay side by side in about 5 minutes on 16 CPUs).

## Decisions

### D1. Read `SNES9X_LEAN` in `retro_init`, reject a bad value in `retro_load_game`
`retro_init` reads the variable with `getenv` one time, parses it into two flags (`lean_video_off`, `lean_dsp_off`) and
writes the report line to stderr. `retro_init` returns `void`, so a bad value is kept as an error, and `retro_load_game`
writes the error and returns `false`. stable-retro is expected to fail to create the emulator then (not yet checked:
task 3.1 verifies it). A bad value never runs silently as the baseline or as a lean core.
- *Alternative:* parse in `retro_load_game` (read per game load). Rejected: the spec reads the variable once per core
  start, and mario-gym creates one emulator per process anyway.
- *Alternative:* ignore unknown names. Rejected: a typo (`vidoe`) would silently run the slow core.

### D2. Video: force `IPPU.RenderThisFrame = FALSE` at the start of every `retro_run`
One line before `S9xMainLoop()`, only when `lean_video_off`. It covers every way the flag comes back (state load, reset,
power-on) without a change in `snapshot.cpp` or `gfx.cpp`.
- *Alternative:* change `S9xUnfreezeFromStream` and the init code. Rejected: more places, and a missed path turns drawing
  on again without a visible error.

### D3. DSP: skip `spc_dsp.run(clock)` in `DSP::synchronize()`, keep `clock = 0`
`if (clock) { if (!lean_dsp_off) spc_dsp.run(clock); clock = 0; }`. This is the only caller of `SPC_DSP::run` in this
build, and it is the same effect as the measured `ret` patch. The flags live in a small header `lean.h` (declarations)
and `libretro/libretro.cpp` (definitions), so the APU code needs only the header.
- *Alternative:* an early return in `SPC_DSP::run`. Equal in effect, but `SPC_DSP` is blargg's generic DSP code; the guard
  in the SNES wrapper keeps the vendored DSP file unchanged.

### D4. Build script `lean/build.sh`
`lean/build.sh <out-dir> [--flags stable-retro|default] [--extra "<flags>"]`:
1. Copy the files of the working tree into a temporary build folder: the tracked files with their uncommitted edits and
   the new files that git does not ignore (`git ls-files --cached --others --exclude-standard`, so a new `lean.h` is
   part of the build before its first commit). The checkout stays clean (spec "Clean source tree").
2. Run the stable-retro recipe in `libretro/` of the copy:
   `env CFLAGS="-w -std=gnu17" CXXFLAGS="-w" LDFLAGS="-w -static-libstdc++ -Wl,--exclude-libs,ALL" make -f Makefile fpic=-fPIC LEAN_FLAGS="<set>"`.
3. Write `snes9x_libretro.so`, `snes9x.json` (a copy of `lean/snes9x.json`, equal to stable-retro 1.0.1's file) and
   `build-info.txt` (commit, dirty yes/no, flag set and extra flags, `gcc --version` line) into `<out-dir>`.
4. Check that the library exports the same 25 `retro_*` symbols (LTO must not drop or add exports).

The Makefile gets one variable `LEAN_FLAGS`, empty by default, added to `CFLAGS`, `CXXFLAGS` and `LDFLAGS` after the
`-O2` lines, so a later `-O3` wins and `-flto` reaches the link step. With `LEAN_FLAGS` empty the compile lines are the
lines of today. `lean/flagsets.sh` (or a table in the script) names the sets: `stable-retro` = empty; `default` = the flags
that D8 accepts (empty until the A/B is done).

### D5. Check tools in Python under `lean/check/`
`replay.py` (one recording on one core in one process: sets `RETRO_CORE_PATH` and `SNES9X_LEAN` before
`import stable_retro`, checks `/proc/self/maps` for the loaded core file, writes one 64-bit hash per frame to a `.npy`
file), and three commands on top of it: `parity.py`, `savestate.py`, `bench.py`. They run with a Python that has
stable-retro 1.0.1 and numpy (mario-gym's `.venv`), and they take the recordings and the core folders as arguments; the
default baseline core folder is the `cores` folder of the installed stable-retro (the shipped binary).
- **RAM read:** a numpy view on `retro_get_memory_data(RETRO_MEMORY_SYSTEM_RAM)` of the loaded core (ctypes,
  `RTLD_NOLOAD`), the same 131,072 bytes that mario-gym's snapshot reads.
- **Hash:** the RAM as 16,384 64-bit words, dotted with fixed odd random weights (wrap-around arithmetic). An odd weight
  is invertible modulo 2^64, so a change in exactly one word always changes the hash; a larger change escapes with a
  chance of about 2^-64. It costs about 15 us per frame (blake2b of 128 KB costs about 130 us).
- **Parallel runs:** one process per (core, recording), pinned with `taskset -c 0-15`.
- **Hash control:** the check fails when a recording's hashes are all equal (a stale RAM view).

### D6. Savestate check
For each recording and each frame at 25 %, 50 % and 75 % of its length: the baseline core and the candidate core each
replay to that frame and save a state; each state is loaded in the other core, and both continue 900 frames with the
recording's inputs. The reference is the baseline core that continues from its own state. The check compares the work RAM
after each frame, and the screen when the loading core draws.

### D7. Speed bench
Inputs: the first 15,000 frames of four recordings (`a1-human-96exit`, `full-run-02`, `full-run-04`, `full-run-05`),
from each recording's start state. Timed region: button input plus the frame step, as in the measurements above.
Workers: 1 on CPU 4; 16 on CPUs 0-15. Arms: the baseline core with no switch (the reference) and the candidate with each
of the four switch settings, in turn, three rounds. Output: median, lowest and highest time per frame, and the ratio to
the reference. The bench stops when the 1-minute load average is above 2.0, unless `--allow-load` is given.

### D8. Flag A/B
Arms: `stable-retro`, `+-O3`, `+-flto` (compile and link), `+-march=x86-64-v3`, then the combination of the flags that
passed. Each arm: the parity check with no switch and with `video,dsp`, and the 1-worker bench with `video,dsp` (the
training setting). A flag passes with 0 differing frames and a gain of at least 2 % against `stable-retro` (the earlier
measurements varied by less than 0.5 %). The result table goes into `lean/README.md`; the passed flags become the set
`default`. No `-ffast-math` and no PGO in this change.

### D9. Documentation
`lean/README.md`: the switches, the build command and flag sets, the CPU need of `default` (when it contains
`-march=x86-64-v3`), how mario-gym loads the core folder, the three checks and their last results.

## Risks / Trade-offs

- [The recordings do not cover a game situation in which the sound driver reads a DSP register (ENVX, OUTX, ENDX)] ->
  The switches are separate; the parity check is part of every change; mario-gym can drop `dsp` at once if a parity
  sample in training ever differs.
- [`-march=x86-64-v3` stops the core on a CPU without AVX2, for example a cloud pod] -> The flag set `stable-retro`
  stays available, the README states the need, and the owner checks `/proc/cpuinfo` (avx2) on a pod before use.
- [LTO changes the exported symbols or breaks `--exclude-libs`] -> `build.sh` compares the export list with the 25
  `retro_*` symbols and stops on a difference.
- [A new compiler version changes behavior] -> `build-info.txt` records the compiler; the parity check runs after each
  toolchain change.
- [A child process inherits `SNES9X_LEAN` and draws no pictures, for example a video tool started from a training
  process] -> The variable is a per-process choice of the consumer; the mario-gym change sets it only in its training
  workers and clears it for its tools.
- [Lean savestates are not byte-equal to baseline savestates] -> Accepted (spec "Savestates in two directions");
  mario-gym compares RAM and observations, never savestate bytes (checked: no state-byte comparison in its `src/`).
- [A speed bench near another job's load gives wrong numbers] -> The load-average stop (D7); CPU sets fixed.

## Migration Plan

Opt-in: nothing changes for a program that does not set `RETRO_CORE_PATH` to the fork's core folder. With the folder
and no `SNES9X_LEAN`, the core is the baseline. Rollback = unset the variable, or unset `RETRO_CORE_PATH`.

## Open Questions

- Where mario-gym keeps the built core folder and how its pods get it: decided in the mario-gym change.
