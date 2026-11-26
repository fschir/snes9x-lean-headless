# snes9x libretro: lean core fork

This is a fork of [libretro/snes9x](https://github.com/libretro/snes9x) for
[stable-retro](https://github.com/Farama-Foundation/stable-retro) 1.0.1. It makes the SNES core about twice as fast for
programs that only read the game's memory, for example a reinforcement-learning agent that plays Super Mario World.
The emulation stays the same.

## Why

A training program steps the emulator and reads the 128 KB work RAM after each frame. It uses no pictures and no sound.
In the stock core, about a third of each frame goes to drawing the screen and about a third to sound: the sound CPU
(SPC700) and the sound chip (DSP). This fork can switch off the drawing and the DSP. The game logic and the sound CPU
still run, so the game behaves the same.

## What the fork adds

- **Switches**, set by the environment variable `SNES9X_LEAN` before the core starts:
  - `video`: the core draws no pictures. A screen read through stable-retro is an error, so a program cannot train on
    blank pictures by mistake. RAM observations work as before.
  - `dsp`: the sound DSP does not run. The audio output is empty.
  - Example: `SNES9X_LEAN=video,dsp`. Without the variable the core is the stock core.
- **`snes9x_lean_flags()`**, an exported function that returns the active switches (bit 0 = `video`, bit 1 = `dsp`,
  -1 = bad value). A program can use it to make sure that it loaded this core with the switches on.
- **`lean/build.sh`**, which builds a core folder for stable-retro with stable-retro's own build recipe. The default
  build adds `-flto` (link-time optimization). Each build writes a record with the commit, the flags, the compiler and
  the lowest glibc it needs.
- **Checks in `lean/check/`**: a parity check (replays input recordings on this core and on the stock core and compares
  the work RAM after every frame), a savestate check (states load in both directions) and a speed bench.

## Results

Measured on 2026-11-26 on an Intel i7-13700K, both switches on, compared with the core that stable-retro ships:

| Build                         | 1 worker | 16 workers |
|-------------------------------|---------:|-----------:|
| stable-retro recipe           |   x2.12  |    x2.19   |
| default (`-flto`)             |   x2.27  |    x2.33   |

In milliseconds: one frame takes about 0.40 ms in the stock core and about 0.17 ms in this core (1 worker).

Parity: on nine input recordings (1,263,629 frames, a full play of the game among them), the work RAM is equal to the
stock core's after every frame, with each switch setting. Without switches, the savestates are byte-identical to the
stock core's.

## Use

```sh
lean/build.sh <out-dir>                              # build the core folder (default flags)
RETRO_CORE_PATH=<out-dir> SNES9X_LEAN=video,dsp python my_training.py
```

Set `RETRO_CORE_PATH` before Python imports `stable_retro`, and make the environment with
`obs_type=stable_retro.Observations.RAM`. [`lean/README.md`](lean/README.md) has the full details: build options, the
switches, the checks and all measurements.

## Branches

- `master`: this fork's main line.
- `stable-retro-v1.0.1` and the tag `baseline-stable-retro-v1.0.1`: the core of stable-retro 1.0.1, byte for byte
  (libretro/snes9x commit `05cb2edc` with stable-retro's small build patch). It never changes and is the reference for
  all checks.
- One branch per change; the planning documents are in `openspec/`.

## Licence

The [Snes9x licence](docs/snes9x-license.txt) applies: non-commercial use; when you share the core, share it free of
charge and with its source.

## Upstream

snes9x libretro. Issue Tracker: https://github.com/libretro/libretro-meta/labels/core:%20snes9x
