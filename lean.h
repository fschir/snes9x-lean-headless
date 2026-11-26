/* The switches of the environment variable SNES9X_LEAN (lean/README.md).

   libretro/libretro.cpp reads the variable in retro_init and defines these
   values. Include this header at global scope only: apu/bapu/dsp/sdsp.hpp is
   included inside namespace SNES, so snes.hpp includes this header before it
   opens the namespace. */

#ifndef _LEAN_H_
#define _LEAN_H_

/* Switch "video": the PPU draws no picture. */
extern bool lean_video_off;
/* Switch "dsp": the sound DSP does not run. */
extern bool lean_dsp_off;
/* Parse error: a copy of the full value when it has a bad name, else NULL.
   retro_load_game rejects the game then. */
extern char *lean_bad_value;

/* Exported query for the program that loads the core: bit 0 = "video",
   bit 1 = "dsp", -1 = bad value. Valid after retro_init. It changes nothing. */
extern "C" int snes9x_lean_flags(void);

#endif
