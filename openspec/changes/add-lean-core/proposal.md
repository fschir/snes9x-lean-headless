# Proposal

## Why

mario-gym trains on this core and spends most of a training update waiting for the emulator. Of `em.step` (392.5 us per
frame on one worker, measured 2026-11-26 on the shipped stable-retro core), about a third draws pictures and about a
third makes sound, and training uses neither: it reads only the 128 KB work RAM after each frame. Tests on the shipped
binary (drawing off by its `IPPU.RenderThisFrame` flag, the sound DSP off by a code patch in a test process) gave
264.6 us with drawing off and 189.6 us with both off (x2.07), and the work RAM stayed equal on every one of the
1,263,629 frames of the owner's nine recordings. This change builds those two cuts into the fork as real, documented
switches, and measures whether the compiler can give more (the build uses plain `-O2` today).

## What Changes

- New environment variable `SNES9X_LEAN`, read once when the core starts (`retro_init`). Its value is a list of names
  separated by commas:
  - `video`: the core draws no pictures. The CPU, the PPU registers, DMA/HDMA and the sprite range/time-over flags run
    as before; only the drawing of the screen stops. A state load cannot turn the drawing on again.
  - `dsp`: the sound DSP does not run. The SPC700 sound CPU keeps running, so the game and the sound CPU talk as before.
  - Unset or empty: the core behaves as the baseline, bit for bit.
  - Any other value: the core refuses to load a game and writes the error to stderr.
- The core writes one line to stderr that names the active switches when `SNES9X_LEAN` is set.
- A build script for the fork that builds the core the same way stable-retro does and writes a core folder
  (`snes9x_libretro.so` + `snes9x.json`) that mario-gym can load with `RETRO_CORE_PATH`.
- A compiler-flag A/B over `-O3`, `-flto` and `-march=x86-64-v3`. A flag becomes part of the default build only when
  the parity check stays at 0 differing frames and the speed bench shows a gain.
- Check tools in the fork: a parity check (the nine recordings, a work-RAM hash after every frame, candidate core
  against the baseline core), a savestate cross-load check, and a speed bench (1 worker and 16 workers, each switch
  setting).
- Not part of this change: a skip of SMW's wait-for-NMI loop, a newer Snes9x version, any change in mario-gym (it gets
  its own change to load this core and set the variable for training only).

## Capabilities

### New Capabilities
- `lean-switches`: the `SNES9X_LEAN` variable, what each switch stops and what it keeps, the refusal of bad values, and
  the promise that the game sees the same work RAM on every frame and that savestates load in both directions.
- `core-build`: how the fork builds its core and core folder, which compiler flags the default build uses, and what the
  build must keep (`LAGFIX=1`, the stable-retro build recipe).
- `core-verification`: the parity check, the savestate cross-load check and the speed bench that every core change
  must pass or report, with their inputs, rules and output.

### Modified Capabilities
- None (the project has no specs yet).

## Impact

- Code: `libretro/libretro.cpp` (read the variable, refuse bad values, apply the video switch at each `retro_run`),
  `apu/bapu/dsp/sdsp.hpp` (`DSP::synchronize`, the only caller of `SPC_DSP::run`), and the build files
  (`libretro/Makefile` or a wrapper script). New folder for the build script, the core info file and the check tools.
- Savestates: the format does not change. A state saved with `dsp` off differs from a normal one in the sound block
  (DSP registers, echo buffer) and with `video` off in one PPU byte; both load in both directions with equal work RAM.
- Consumers: mario-gym (separate change). stable-retro's own core stays as it is; the fork's core is used only where
  `RETRO_CORE_PATH` points at its folder.
- Tools need a Python with stable-retro 1.0.1 and numpy (mario-gym's `.venv`), the ROM imported into stable-retro, and
  the owner's recordings; none of these go into this repository.
- Licence: the Snes9x licence applies to the fork and its builds.
