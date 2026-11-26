# Spec Delta

## Purpose

This capability gives the checks that each core change must pass: a parity check of the work RAM on recordings, a
savestate check in two directions, and a speed bench. The checks compare a candidate core with the baseline core.

## ADDED Requirements

### Requirement: Parity check
The project MUST give a parity check. Its inputs are a list of `.bk2` recordings, a baseline core folder, a candidate
core folder and a switch value for the candidate. The check MUST replay each recording on each core. After each frame,
it MUST calculate a hash of the work RAM. It MUST compare the hashes of the two cores frame by frame.

#### Scenario: Equal cores
- **GIVEN** a candidate core that operates as the baseline core
- **WHEN** the owner runs the parity check on the nine recordings
- **THEN** the check shows 0 differing frames for each recording
- **AND** the check stops with exit code 0

#### Scenario: Different cores
- **GIVEN** a candidate core that gives a different work RAM in one frame
- **WHEN** the owner runs the parity check
- **THEN** the check shows the recording, the number of differing frames and the first differing frame
- **AND** the check stops with an exit code that is not 0

### Requirement: Parity check output
For each recording, the parity check MUST show the number of frames and the number of differing frames. When the two
cores give a different number of frames for a recording, the check MUST show this as a fault. At the end, the check
MUST show the total number of frames and the total number of differing frames.

#### Scenario: Different frame count
- **GIVEN** a recording that gives 100 frames on the baseline core and 99 frames on the candidate core
- **WHEN** the parity check compares the two cores
- **THEN** the check shows a fault for this recording and stops with an exit code that is not 0

### Requirement: Loaded core control
Each replay MUST make sure that the process loaded the core file of the given core folder. When the process loaded a
different core file, the check MUST stop with an error that gives the path of the loaded file.

#### Scenario: Wrong core loaded
- **GIVEN** a replay process that loaded the core of stable-retro instead of the candidate core
- **WHEN** the parity check starts the replay
- **THEN** the check stops with an error that gives the path of the loaded core file

### Requirement: Hash control
The parity check MUST stop with an error when the hash of the work RAM has the same value for all frames of a recording.
This error shows that the check does not read the current work RAM.

#### Scenario: Hash does not change
- **GIVEN** a replay that gives the same hash for all frames of a recording
- **WHEN** the parity check reads the hashes
- **THEN** the check stops with an error that gives the name of the recording

### Requirement: Savestate check
The project MUST give a savestate check. Its inputs are the recordings, the baseline core folder, the candidate core
folder and a switch value. At three frames of each recording, the check MUST save a state in one core and load it in the
other core, in the two directions. After each load, it MUST run 900 frames with the inputs of the recording and compare
the work RAM after each frame with the baseline core.

#### Scenario: Two directions
- **GIVEN** the candidate core with the switches `video` and `dsp`
- **WHEN** the owner runs the savestate check on the nine recordings
- **THEN** the check shows 0 differing frames for each load in each direction
- **AND** the check stops with exit code 0

### Requirement: Speed bench
The project MUST give a speed bench. It MUST measure the time of one emulated frame (button input and frame step). It
MUST use the inputs of recordings. It MUST measure one worker on CPU 4 and 16 workers on CPUs 0 to 15, one worker on each
CPU. It MUST measure each of these settings: no switch, `video`, `dsp`, `video,dsp`.

#### Scenario: Bench output
- **GIVEN** a core folder
- **WHEN** the owner runs the speed bench
- **THEN** the bench shows, for each setting and each worker count, the median time per frame in microseconds
- **AND** the bench shows the ratio of each time to the time of the baseline core with no switch

### Requirement: Bench repeats
The speed bench MUST run each measurement three times. It MUST run the settings in turn, not one setting three times in
sequence. It MUST show the median of the three runs and the lowest and highest value.

#### Scenario: Three runs in turn
- **GIVEN** the speed bench with two settings A and B
- **WHEN** the bench runs
- **THEN** the run order is A, B, A, B, A, B or a similar order in turn

### Requirement: Quiet machine
At the start, the speed bench MUST show the 1-minute load average of the machine. When the load average is more than 2.0,
the bench MUST stop with an error. A command option MUST let the owner run the bench at a higher load.

#### Scenario: Busy machine
- **GIVEN** a machine with a 1-minute load average of 7.8
- **WHEN** the owner starts the speed bench without the option
- **THEN** the bench stops with an error that gives the load average
