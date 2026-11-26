"""Speed bench: the time of one emulated frame (button input and frame step) on the inputs of recordings.

Command:
    bench.py --candidate <core-dir> [--baseline <core-dir>] [--rounds 3] [--frames 15000] [--allow-load]
             [--settings LIST] [--workers 1|16|both] <recording.bk2> ...

The settings are the baseline core with no switch (`ref`, the reference) and the candidate core with no switch
(`none`), `video`, `dsp` and `video+dsp` (SNES9X_LEAN=video,dsp). --settings takes names of this list with a comma
between two names; the default is all five. The reference is always measured, also when the list does not name it.

Each measurement replays the first --frames frames of each recording from the start state of the recording. With 1
worker, the worker is pinned to CPU 4. With 16 workers, one is pinned to each of the CPUs 0 to 15; all workers of a
measurement run the same setting at the same time. --workers selects one of the two counts; the default is both,
first 1 and then 16. The settings run in turn, one after the other in each round. The default baseline folder is the
cores folder of the installed stable-retro.

With 16 workers, the timed part starts when all workers are ready. A worker that has its result continues to step
frames without a time measurement until all workers have their results. The value of a measurement is the mean time
per frame of its workers.

The bench shows the 1-minute load average and stops when it is more than 2.0, unless --allow-load is given.

Exit code: 0 on success; 1 on a high load, a failed worker, or a switch setting for which the candidate wrote no switch
report line (then the row does not measure the switch); 2 on a wrong command.
"""
import argparse
import itertools
import json
import os
import select
import statistics
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # `python -I` does not add the folder of the script
sys.dont_write_bytecode = True  # no __pycache__ folder in the checkout
import parity  # noqa: E402
import replay  # noqa: E402

LOAD_LIMIT = 2.0
REFERENCE = "ref"  # the baseline core with no switch
CANDIDATE_SETTINGS = {"none": "", "video": "video", "dsp": "dsp", "video+dsp": "video,dsp"}  # name: switch value
SETTING_NAMES = (REFERENCE, *CANDIDATE_SETTINGS)
WORKER_CPUS = {"1": (4,), "16": tuple(range(16))}  # worker count: the CPUs, one per worker
MARK = "BENCH"  # starts each line of the protocol on the standard output of a worker


class BenchError(RuntimeError):
    pass


def load_allowed(load, allow_load):
    return allow_load or load <= LOAD_LIMIT


def setting_names(text):
    names = text.split(",")
    for name in names:
        if name not in SETTING_NAMES:
            raise argparse.ArgumentTypeError(f"unknown setting '{name}'; the settings are {', '.join(SETTING_NAMES)}")
    return names


def summarize(values):
    return statistics.median(values), min(values), max(values)


def table(arms, values, unreported=()):
    """The result table. values[worker count, arm label] is the list of the times per frame of the rounds."""
    lines = [f"{'workers':>7}  {'setting':<28}{'median':>8}{'lowest':>8}{'highest':>9}{'time/ref':>10}{'speed-up':>10}"]
    reference = arms[0][0]
    for count in sorted({count for count, _ in values}):
        reference_median = statistics.median(values[count, reference])
        for label, _, _ in arms:
            median, lowest, highest = summarize(values[count, label])
            note = "  NO SWITCH REPORT" if label in unreported else ""
            lines.append(f"{count:>7}  {label:<28}{median:>8.1f}{lowest:>8.1f}{highest:>9.1f}"
                         f"{median / reference_median:>10.3f}{'x' + format(reference_median / median, '.2f'):>10}"
                         f"{note}")
    return "\n".join(lines)


# --- the worker process -------------------------------------------------------------------------------------------

def say(*words):
    print(MARK, *words, flush=True)


def worker(job):
    env, _ = replay.prepare(job["core_dir"], job["switch"])
    em = env.em
    inputs = []
    for path in job["recordings"]:  # read all inputs before the timed part
        start_state, masks = replay.open_movie(env, path)
        inputs.append((start_state, list(itertools.islice(masks, job["frames"]))))
        if not inputs[-1][1]:
            raise ValueError(f"the recording {path} gave no frame")
    say("ready", *(len(masks) for _, masks in inputs))
    if sys.stdin.readline() != "go\n":
        return 1
    spent = frames = 0
    clock = time.perf_counter_ns
    for start_state, masks in inputs:
        if em.set_state(start_state) is not True:
            raise RuntimeError("the core rejected the start state of a recording")
        for mask in masks:
            before = clock()
            em.set_button_mask(mask, 0)
            em.step()
            spent += clock() - before
        frames += len(masks)
    say("result", spent, frames)
    # Keep this CPU busy, so that the slower workers are measured under the same load, until the parent writes a line.
    for index in itertools.count():
        if index % 256 == 0 and select.select([sys.stdin], [], [], 0)[0]:
            return 0
        em.set_button_mask(masks[index % len(masks)], 0)
        em.step()


# --- the parent process -------------------------------------------------------------------------------------------

def expect(process, word, log):
    """Read the standard output of a worker up to its next protocol line; return the numbers of that line."""
    for line in process.stdout:
        fields = line.split()
        if fields[:2] == [MARK, word]:
            return [int(number) for number in fields[2:]]
    process.wait()
    tail = "".join(f"\n  {line}" for line in parity.read_text(log).splitlines()[-5:])
    raise BenchError(f"a worker ended with exit code {process.returncode} before its '{word}' line{tail}")


def send(process, line):
    try:
        process.stdin.write(line + "\n")
        process.stdin.flush()
    except BrokenPipeError:
        raise BenchError(f"a worker ended before the '{line}' line") from None


def measure(core_dir, switch, cpus, recordings, frames, log_dir):
    """One measurement: (microseconds per frame, switch report present, frames of each recording)."""
    processes, logs = [], []
    try:
        for index, cpu in enumerate(cpus):
            shift = index % len(recordings)  # the workers are in different recordings at the same time
            job = {"core_dir": core_dir, "switch": switch, "frames": frames,
                   "recordings": recordings[shift:] + recordings[:shift]}
            command = ["taskset", "-c", str(cpu), sys.executable, "-I", os.path.join(HERE, "bench.py"), "--worker",
                       json.dumps(job)]
            logs.append(os.path.join(log_dir, f"worker-{cpu}.err"))
            with open(logs[-1], "wb") as err:
                processes.append(subprocess.Popen(command, env=replay.child_environment(), stdin=subprocess.PIPE,
                                                  stdout=subprocess.PIPE, stderr=err, text=True))
        counts = [expect(process, "ready", log) for process, log in zip(processes, logs)]
        for process in processes:
            send(process, "go")
        results = [expect(process, "result", log) for process, log in zip(processes, logs)]
        for process in processes:
            send(process, "stop")
        for process, log in zip(processes, logs):
            process.communicate()
            if process.returncode:
                raise BenchError(f"a worker ended with exit code {process.returncode}, see {log}")
    finally:
        for process in processes:  # only the processes that this call started
            if process.poll() is None:
                process.kill()
                process.wait()
    reported = not switch or all(parity.has_report_line(parity.read_text(log), switch) for log in logs)
    microseconds = sum(spent for spent, _ in results) / sum(count for _, count in results) / 1000
    return microseconds, reported, counts[0]  # worker 0 has the recordings in the order of the command


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["--worker"]:
        return worker(json.loads(argv[1]))
    parser = argparse.ArgumentParser(description="Measure the time per emulated frame of the switch settings.")
    parser.add_argument("recordings", nargs="+", help=".bk2 files")
    parser.add_argument("--candidate", required=True, help="core folder to measure")
    parser.add_argument("--baseline", help="reference core folder (default: the installed stable-retro cores folder)")
    parser.add_argument("--rounds", type=int, default=3, help="measurements per setting and worker count (default 3)")
    parser.add_argument("--frames", type=int, default=15000, help="first frames of each recording (default 15000)")
    parser.add_argument("--allow-load", action="store_true", help=f"run at a load average above {LOAD_LIMIT}")
    parser.add_argument("--settings", type=setting_names, default=",".join(SETTING_NAMES), metavar="LIST",
                        help=f"settings to measure, with commas: {', '.join(SETTING_NAMES)} (default: all); "
                             f"{REFERENCE} is always measured")
    parser.add_argument("--workers", choices=(*WORKER_CPUS, "both"), default="both",
                        help="worker counts to measure (default: both)")
    args = parser.parse_args(argv)

    if args.rounds < 1 or args.frames < 1:
        parser.error("--rounds and --frames must be 1 or more")
    baseline = os.path.realpath(args.baseline or replay.default_core_dir())
    candidate = os.path.realpath(args.candidate)
    for core_dir in (baseline, candidate):
        for file in (replay.CORE_FILE, replay.CORE_INFO_FILE):
            if not os.path.isfile(os.path.join(core_dir, file)):
                parser.error(f"the core folder {core_dir} has no file {file}")
    recordings = [os.path.abspath(path) for path in args.recordings]
    for path in recordings:
        if not os.path.isfile(path):
            parser.error(f"no recording file {path}")

    load = os.getloadavg()[0]
    print(f"1-minute load average: {load:.2f}", flush=True)
    if not load_allowed(load, args.allow_load):
        print(f"error: the 1-minute load average {load:.2f} is above {LOAD_LIMIT}; stop the other work, or give "
              f"--allow-load", file=sys.stderr)
        return 1

    arms = [("baseline, no switch", baseline, "")]
    arms += [(f"candidate, {switch or 'no switch'}", candidate, switch)
             for name, switch in CANDIDATE_SETTINGS.items() if name in args.settings]
    print(f"baseline: {baseline}\ncandidate: {candidate}", flush=True)
    values, unreported, shown = {}, [], False
    with tempfile.TemporaryDirectory(prefix="bench-") as log_dir:
        for cpus in [cpus for count, cpus in WORKER_CPUS.items() if args.workers in (count, "both")]:
            for round_number in range(1, args.rounds + 1):
                for label, core_dir, switch in arms:
                    try:
                        microseconds, reported, counts = measure(core_dir, switch, cpus, recordings, args.frames,
                                                                 log_dir)
                    except BenchError as error:
                        print(f"error: {len(cpus)} workers, {label}: {error}", file=sys.stderr)
                        return 1
                    if not shown:
                        shown = True
                        for path, count in zip(recordings, counts):
                            print(f"recording {os.path.basename(path)}: the first {count} frames")
                    values.setdefault((len(cpus), label), []).append(microseconds)
                    if not reported and label not in unreported:
                        unreported.append(label)
                    print(f"workers {len(cpus)}, round {round_number}/{args.rounds}, {label}: "
                          f"{microseconds:.1f} us/frame", flush=True)
    print("\nmicroseconds per frame (button input and frame step); time/ref = median / median of the reference "
          "(the first setting) at the same worker count; speed-up = reference / median")
    print(table(arms, values, unreported))
    for label in unreported:
        print(f"FAULT {label}: no switch report line from the candidate; the switch did not reach the core, so these "
              f"rows do not measure it")
    return 1 if unreported else 0


if __name__ == "__main__":
    sys.exit(main())
