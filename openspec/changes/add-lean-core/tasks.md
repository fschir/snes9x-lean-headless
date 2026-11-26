# Tasks

`<mario-gym>` below is the owner's mario-gym checkout (its path is local, not part of this repository). Python for the
tools and checks: `<mario-gym>/.venv/bin/python -I`, which has stable-retro 1.0.1, numpy and the imported ROM.
Recordings: the nine `.bk2` files under `<mario-gym>/local/build/` (`reference/a1-human-96exit`, `playthrough/s01`, `tour/t01`,
`recordings/full-run-01..05`, `recordings/ysp-direct`). Do not run pytest of mario-gym, `mario-gym train` or any
emulator-heavy step while a mario-gym training run is on. Parallel replays use `taskset -c 0-15`.

## 1. Build script and core folder

- [x] 1.1 Add the variable `LEAN_FLAGS` (empty by default) to `libretro/Makefile`, appended to `CFLAGS`, `CXXFLAGS` and `LDFLAGS` after the `-O2 -DNDEBUG` lines (design D4); verify that `make -n -f Makefile` in `libretro/` gives the same compile and link lines as before the change when `LEAN_FLAGS` is empty
- [x] 1.2 Add `lean/snes9x.json` (a copy of stable-retro 1.0.1's `stable_retro/cores/snes9x.json`) and verify it is byte-equal to the installed file
- [x] 1.3 Write `lean/build.sh <out-dir> [--flags stable-retro|default] [--extra "<flags>"]` (design D4: copy of the tracked and the untracked, not ignored files, with uncommitted edits, into a temp folder, the stable-retro recipe, `snes9x_libretro.so` + `snes9x.json` + `build-info.txt`, check of the 25 exported `retro_*` symbols); verify a build with `--flags stable-retro` succeeds, `git status` is clean after it, and the compile lines contain `-DLAGFIX`, `-w` and `-fPIC`
- [x] 1.4 Verify that the folder of 1.3 loads: a Python process with `RETRO_CORE_PATH=<out-dir>` set before `import stable_retro` maps `<out-dir>/snes9x_libretro.so` (check `/proc/self/maps`)
- [x] 1.5 Write the build section of `lean/README.md` (command, flag sets, build record, `RETRO_CORE_PATH` use) and verify the documented command runs as written

## 2. Parity check

- [x] 2.1 Write `lean/check/replay.py` (design D5: one recording on one core in one process, `RETRO_CORE_PATH` and `SNES9X_LEAN` set before the import, loaded-core control via `/proc/self/maps`, RAM view by `retro_get_memory_data`, weighted 64-bit hash per frame to a `.npy` file); verify on `ysp-direct` with the shipped core that it writes 3,144 hashes and that more than 3,000 of them are distinct
- [x] 2.2 Write `lean/check/parity.py` (recordings, baseline core folder, default = the installed stable-retro `cores` folder, candidate core folder, switch value; parallel replays with `taskset -c 0-15`; per-recording output, frame-count fault, hash control, total line, exit code); verify that the build of 1.3 against the shipped core gives 0 differing frames on all nine recordings (1,263,629 frames) and exit code 0
- [x] 2.3 Write `lean/check/selftest.py` (plain Python, no pytest, at most 10 cases) for the fault paths of 2.2 on small made-up hash files: one differing frame (exit code not 0, first frame shown), different frame counts, all-equal hashes (hash control), a wrong loaded core path; verify that all cases pass
- [x] 2.4 Write the parity section of `lean/README.md` and verify the documented command runs as written

## 3. Switches

- [ ] 3.1 Add `lean.h` (declarations of `lean_video_off`, `lean_dsp_off` and the parse error) and, in `libretro/libretro.cpp`, read and parse `SNES9X_LEAN` in `retro_init`, write the report line, and reject the game in `retro_load_game` on a bad value (design D1); verify with three processes: `video,sound` and `video,` fail to load with a stderr message that contains the value, and `dsp,video` writes one stderr line with both names
- [ ] 3.2 Add the video switch at the start of `retro_run` (design D2); verify the parity check with `video` gives 0 differing frames on the nine recordings, and that under `video` stable-retro's `get_screen()` (before the first frame, after 600 frames, after a state load) and an image-observation `make` raise an error while a RAM-observation environment runs on with changing work RAM
- [ ] 3.3 Add the DSP switch in `DSP::synchronize()` of `apu/bapu/dsp/sdsp.hpp` (design D3); verify the parity check with `dsp` and with `video,dsp` gives 0 differing frames on the nine recordings
- [ ] 3.4 Verify the baseline behavior without switches: the parity check with no switch gives 0 differing frames, and a process that sets `SNES9X_LEAN=video` only after the core started still draws (the screen changes over 60 frames of a recording)
- [ ] 3.5 Write the switch section of `lean/README.md` (names, effects, bad values, the screen and audio behavior, per-process use) and verify its examples run as written

## 4. Savestate check

- [ ] 4.1 Write `lean/check/savestate.py` (design D6: states at 25 %, 50 % and 75 % of each recording, loads in two directions, 900 frames, work RAM and, when the loading core draws, screen; with no switch also a byte comparison of the saved states); verify that the candidate with `video,dsp` gives 0 differing frames in both directions on the nine recordings, and that with no switch the saved states are byte-equal to the baseline's
- [ ] 4.2 Add the savestate section to `lean/README.md` and verify the documented command runs as written

## 5. Speed bench

- [ ] 5.1 Write `lean/check/bench.py` (design D7: four recordings x first 15,000 frames, 1 worker on CPU 4 and 16 workers on CPUs 0-15, the baseline core with no switch plus the candidate with each switch setting, three rounds in turn, median/lowest/highest, ratios, load-average stop above 2.0 with `--allow-load`); verify that it stops with an error on a load above 2.0 and that a run on a quiet machine prints all arms
- [ ] 5.2 Run the bench on the `stable-retro` build of the switches and record the table in `lean/README.md`; verify the ratios are near the measured ones (video about x1.48, video+dsp about x2.07 on one worker) or explain the difference in the README

## 6. Compiler flag A/B

- [ ] 6.1 Build the arms `stable-retro`, `+-O3`, `+-flto`, `+-march=x86-64-v3` with `lean/build.sh --extra` and run, for each, the parity check with no switch and with `video,dsp` and the 1-worker bench with `video,dsp`; verify each arm has a result row (differing frames, median time, gain against `stable-retro`)
- [ ] 6.2 Build the combination of the flags that passed (0 differing frames and a gain of at least 2 %) and run the same checks; verify the combination also passes or drop the flag that breaks it
- [ ] 6.3 Set the flag set `default` in `lean/build.sh` to the accepted flags, record the A/B table and, when `default` contains `-march=x86-64-v3`, the CPU need in `lean/README.md`; verify `lean/build.sh <dir>` without `--flags` writes `default` into `build-info.txt`

## 7. Integration

- [ ] 7.1 Build with the flag set `default` and run the parity check (no switch and `video,dsp`), the savestate check (`video,dsp`) and the speed bench; verify 0 differing frames everywhere and record the final numbers in `lean/README.md`
- [ ] 7.2 Run `lean/check/selftest.py` and `openspec validate add-lean-core --strict`; verify both pass, then commit the branch `add-lean-core` and push it to GitHub (never to master or to `stable-retro-v1.0.1`)

## Workflow follow-up

- The owner reviews the branch; the merge into master happens only on the owner's word.
- Archive the change after the merge, then commit and push again.
- mario-gym gets its own change: load the fork's core folder with `RETRO_CORE_PATH`, set `SNES9X_LEAN=video,dsp` only in its training workers, keep its video tools on the drawing core.
