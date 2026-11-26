"""Replay one .bk2 recording on one SNES core and hash the work RAM after every frame.

Command:
    replay.py <recording.bk2> <core-dir> <out.npy> [--switch VALUE]

The script runs one recording on the core in <core-dir> (snes9x_libretro.so and snes9x.json) in this process. It
writes one unsigned 64-bit hash per frame to <out.npy> and prints one summary line to standard output. The exit code
is not 0 on an error. It needs a Python with stable-retro 1.0.1, numpy and the imported SuperMarioWorld-Snes-v0 ROM.

VALUE goes into SNES9X_LEAN. An empty value removes the variable. The script never writes the value to standard
error, because parity.py looks there for the switch report of the core.

API for the other check tools (stable-retro allows one emulator per process):

    CORE_FILE, SWITCH_VARIABLE     the names of the core file and of the switch variable
    default_core_dir()             the cores folder of the installed stable-retro, found without an import of it
    prepare(core_dir, switch="")   sets the environment, starts the emulator, checks the loaded core -> (env, ram)
    open_movie(env, path)          -> (start_state, masks) of a recording; masks yields one button mask per frame
    frame_hash(ram)                the 64-bit hash of the work RAM, as an int
    check_loaded_core(maps_lines, core_dir)   raises LoadedCoreError when the maps lines show another core file
    LoadedCoreError                the error of the loaded core control
    child_environment()            os.environ without SNES9X_LEAN and RETRO_CORE_PATH, for a child process

Call prepare() before anything imports stable_retro. It raises an error otherwise, because the core folder and the
switches work only when they are set before the import. `ram` is a live view of the 131,072 bytes of work RAM, not a
copy. It is valid only while `env` exists. open_movie() does not change the emulator: load the start state (or another
state) with env.em.set_state(), then call env.em.set_button_mask(mask, 0) and env.em.step() for each mask. Each mask
is a new array. A caller can stop the iteration early, and itertools.islice can skip frames.

A tool in this folder that runs with `python -I` imports this module in this way:

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    sys.dont_write_bytecode = True  # no __pycache__ folder in the checkout
    import replay
"""
import argparse
import ctypes
import importlib.util
import os
import sys
import time

import numpy as np

GAME = "SuperMarioWorld-Snes-v0"
CORE_FILE = "snes9x_libretro.so"
CORE_INFO_FILE = "snes9x.json"
SWITCH_VARIABLE = "SNES9X_LEAN"
_SYSTEM_RAM = 2  # RETRO_MEMORY_SYSTEM_RAM
_RAM_BYTES = 128 * 1024
# Odd weights: a change in exactly one 64-bit word always changes the hash. Keep the seed, so that hash files of
# different runs stay comparable.
_WEIGHTS = (np.random.default_rng(2026).integers(0, 2**63, size=_RAM_BYTES // 8, dtype=np.uint64)
            * np.uint64(2) + np.uint64(1))


class LoadedCoreError(RuntimeError):
    """The process did not load the core file of the given core folder."""


def default_core_dir():
    spec = importlib.util.find_spec("stable_retro")  # does not execute the package
    if spec is None or not spec.submodule_search_locations:
        raise RuntimeError("stable_retro is not installed for this Python")
    return os.path.join(spec.submodule_search_locations[0], "cores")


def child_environment():
    """The environment for a process that calls prepare(), without values that the parent process has inherited."""
    return {key: value for key, value in os.environ.items() if key not in (SWITCH_VARIABLE, "RETRO_CORE_PATH")}


def check_loaded_core(maps_lines, core_dir):
    """Check the lines of /proc/<pid>/maps: every mapped snes9x_libretro file must be the one of core_dir."""
    expected = os.path.realpath(os.path.join(core_dir, CORE_FILE))
    loaded = set()
    for line in maps_lines:
        fields = line.rstrip("\n").split(None, 5)  # the sixth field is the path; it can contain spaces
        if len(fields) == 6 and "snes9x_libretro" in fields[5]:
            loaded.add(fields[5])
    if not loaded:
        raise LoadedCoreError(f"no snes9x_libretro file is loaded; expected {expected}")
    wrong = sorted(loaded - {expected})
    if wrong:
        raise LoadedCoreError(f"wrong core loaded: {', '.join(wrong)} (expected {expected})")


def _set_environment(core_dir, switch):
    if "stable_retro" in sys.modules:
        raise RuntimeError("stable_retro is already imported: the core folder and the switches cannot be set now")
    core_dir = os.path.realpath(core_dir)
    for name in (CORE_FILE, CORE_INFO_FILE):
        if not os.path.isfile(os.path.join(core_dir, name)):
            raise FileNotFoundError(f"the core folder {core_dir} has no file {name}")
    os.environ["RETRO_CORE_PATH"] = core_dir  # the core_path() setter after the import has no effect
    if switch:
        os.environ[SWITCH_VARIABLE] = switch
    else:
        os.environ.pop(SWITCH_VARIABLE, None)
    return core_dir


def _ram_view(core_dir):
    # RTLD_NOLOAD: take the library that the emulator loaded, never a second copy with its own memory.
    library = ctypes.CDLL(os.path.join(core_dir, CORE_FILE), mode=os.RTLD_NOLOAD | os.RTLD_LAZY)
    library.retro_get_memory_data.argtypes = [ctypes.c_uint]
    library.retro_get_memory_data.restype = ctypes.c_void_p
    library.retro_get_memory_size.argtypes = [ctypes.c_uint]
    library.retro_get_memory_size.restype = ctypes.c_size_t
    address = library.retro_get_memory_data(_SYSTEM_RAM)
    size = library.retro_get_memory_size(_SYSTEM_RAM)
    if not address or size != _RAM_BYTES:
        raise RuntimeError(f"the core gives {size} bytes of work RAM at {address}; expected {_RAM_BYTES} bytes")
    return np.ctypeslib.as_array((ctypes.c_uint8 * size).from_address(address))


def prepare(core_dir, switch=""):
    """Start the emulator on the core of core_dir with the switch value; return (env, ram)."""
    core_dir = _set_environment(core_dir, switch)
    import stable_retro

    env = stable_retro.make(GAME, state=stable_retro.State.NONE, render_mode=None,
                            use_restricted_actions=stable_retro.Actions.ALL, obs_type=stable_retro.Observations.RAM)
    with open("/proc/self/maps") as maps:
        check_loaded_core(maps, core_dir)
    return env, _ram_view(core_dir)


def open_movie(env, path):
    """Open a recording; return its start state and an iterator of the button masks, one per frame."""
    stable_retro = sys.modules.get("stable_retro")
    if stable_retro is None:
        raise RuntimeError("call prepare() before open_movie()")
    if not os.path.isfile(path):
        raise FileNotFoundError(f"no recording file {path}")
    movie = stable_retro.Movie(path)
    if not movie.step():  # the first step gives no frame of the replay; it precedes get_state()
        raise ValueError(f"the recording {path} has no frames")
    return movie.get_state(), _masks(movie, len(env.buttons))


def _masks(movie, buttons):
    while movie.step():
        yield np.array([movie.get_key(button, 0) for button in range(buttons)], dtype=np.uint8)


def frame_hash(ram):
    return int(np.dot(ram.view(np.uint64), _WEIGHTS))  # integer arithmetic wraps around at 2**64


def main(argv=None):
    parser = argparse.ArgumentParser(description="Replay one recording on one core and hash the work RAM per frame.")
    parser.add_argument("recording", help=".bk2 file")
    parser.add_argument("core_dir", help=f"folder with {CORE_FILE} and {CORE_INFO_FILE}")
    parser.add_argument("out", help="output file for the hashes (.npy)")
    parser.add_argument("--switch", default="", help=f"value of {SWITCH_VARIABLE}; empty = the variable is not set")
    args = parser.parse_args(argv)

    env, ram = prepare(args.core_dir, args.switch)
    start_state, masks = open_movie(env, args.recording)
    em = env.em
    if em.set_state(start_state) is False:
        raise RuntimeError("the core rejected the start state of the recording")
    hashes = []
    spent = 0
    for mask in masks:
        before = time.perf_counter_ns()
        em.set_button_mask(mask, 0)
        em.step()
        spent += time.perf_counter_ns() - before
        hashes.append(frame_hash(ram))
    if not hashes:
        raise ValueError(f"the recording {args.recording} gave no frame")
    with open(args.out, "wb") as out:  # a file object: np.save then adds no suffix to the name
        np.save(out, np.array(hashes, dtype=np.uint64))
    core = os.path.join(os.path.realpath(args.core_dir), CORE_FILE)
    print(f"{os.path.basename(args.recording)}: {len(hashes)} frames, {len(set(hashes))} distinct hashes, "
          f"{spent / len(hashes) / 1000:.1f} us/frame (button input and frame step), core {core}, "
          f"switch {args.switch or '(none)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
