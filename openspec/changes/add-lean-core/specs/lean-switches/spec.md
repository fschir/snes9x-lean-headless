# Spec Delta

## Purpose

This capability gives switches that stop the parts of the SNES core that a training program does not use: the drawing
of the screen and the sound DSP. With the switches, the game itself does not change: the work RAM after each frame is
the same as with the baseline core.

## ADDED Requirements

### Requirement: Switch variable
The core MUST read the environment variable `SNES9X_LEAN` one time, when the core starts. The value is a list of names
with a comma between two names. The names are `video` and `dsp`. A name in the list sets its switch. A name can occur
more than one time. When the variable is not set or is empty, the core MUST set no switch. A change of the variable
after the core starts MUST have no effect on the core.

#### Scenario: Variable not set
- **GIVEN** the environment has no variable `SNES9X_LEAN`
- **WHEN** a program starts the core and loads a game
- **THEN** the core sets no switch

#### Scenario: Both switches
- **GIVEN** `SNES9X_LEAN` is `video,dsp`
- **WHEN** a program starts the core and loads a game
- **THEN** the core sets the switch `video` and the switch `dsp`

#### Scenario: One switch
- **GIVEN** `SNES9X_LEAN` is `dsp`
- **WHEN** a program starts the core and loads a game
- **THEN** the core sets the switch `dsp` and does not set the switch `video`

#### Scenario: Change after the start
- **GIVEN** the core started with no variable `SNES9X_LEAN`
- **WHEN** the program sets `SNES9X_LEAN` to `video` and runs frames
- **THEN** the core continues with no switch

### Requirement: Bad switch value
When the value of `SNES9X_LEAN` contains a name that is not `video` or `dsp`, the core MUST reject the game load. An empty
name between two commas, at the start or at the end is a bad name. A space is part of a name. The core MUST write an
error message to the standard error stream. The message MUST contain the full value of the variable.

#### Scenario: Wrong name
- **GIVEN** `SNES9X_LEAN` is `video,sound`
- **WHEN** a program starts the core and tries to load a game
- **THEN** the game load fails
- **AND** the standard error stream shows a message that contains `video,sound`

#### Scenario: Empty name
- **GIVEN** `SNES9X_LEAN` is `video,`
- **WHEN** a program starts the core and tries to load a game
- **THEN** the game load fails

### Requirement: Switch report
When `SNES9X_LEAN` is set and its value is correct, the core MUST write one line to the standard error stream when it
starts. The line MUST give the name of each switch that is set.

#### Scenario: Report of the switches
- **GIVEN** `SNES9X_LEAN` is `dsp,video`
- **WHEN** a program starts the core
- **THEN** the standard error stream shows one line that contains `video` and `dsp`

### Requirement: Switch query
The core MUST export the function `snes9x_lean_flags`. After the core starts, the function MUST give the switches that
are set: bit 0 for `video`, bit 1 for `dsp`. When the value of `SNES9X_LEAN` is bad, it MUST give -1. The function MUST
NOT change a switch. A program can use it to make sure that the switches are on.

#### Scenario: Query of two switches
- **GIVEN** the core started with `SNES9X_LEAN` set to `video,dsp`
- **WHEN** a program calls `snes9x_lean_flags`
- **THEN** the function gives 3

#### Scenario: Query without switches
- **GIVEN** the core started with no variable `SNES9X_LEAN`
- **WHEN** a program calls `snes9x_lean_flags`
- **THEN** the function gives 0

#### Scenario: Query after a bad value
- **GIVEN** the core started with `SNES9X_LEAN` set to `video,sound`
- **WHEN** a program calls `snes9x_lean_flags`
- **THEN** the function gives -1

### Requirement: Baseline behavior without switches
When no switch is set, the core MUST operate as the baseline core. The baseline core is the core of the branch
`stable-retro-v1.0.1`. With the same start state and the same inputs, the work RAM after each frame MUST be equal. The
screen after each frame MUST be equal. The savestate after each frame MUST be equal, byte for byte.

#### Scenario: Recordings without switches
- **GIVEN** the core with no switch and the baseline core
- **WHEN** the parity check replays the recordings on the two cores
- **THEN** the work RAM is equal after each frame of each recording

#### Scenario: Savestate bytes without switches
- **GIVEN** the core with no switch and the baseline core, with the same start state and the same inputs
- **WHEN** each core saves a state after the same frame
- **THEN** the two savestates are equal, byte for byte

### Requirement: Same game state with switches
With any set of switches, the work RAM after each frame MUST be equal to the work RAM of the baseline core. The start
state and the inputs MUST be the same. The work RAM is the 128 KB memory at `$7E0000`.

#### Scenario: Recordings with the switch video
- **GIVEN** the core with the switch `video` and the baseline core
- **WHEN** the parity check replays the recordings on the two cores
- **THEN** the work RAM is equal after each frame of each recording

#### Scenario: Recordings with the switch dsp
- **GIVEN** the core with the switch `dsp` and the baseline core
- **WHEN** the parity check replays the recordings on the two cores
- **THEN** the work RAM is equal after each frame of each recording

#### Scenario: Recordings with the two switches
- **GIVEN** the core with the switches `video` and `dsp` and the baseline core
- **WHEN** the parity check replays the recordings on the two cores
- **THEN** the work RAM is equal after each frame of each recording

### Requirement: Video switch stops the drawing
With the switch `video`, the core MUST NOT draw the screen and MUST NOT give a picture to the program. A state load
MUST NOT start the drawing again. The switch applies from the start of the core, so the program never gets a picture.
stable-retro then rejects a screen read and image observations with an error. After that error, the emulator MUST
continue, and RAM observations MUST operate as without the switch.

#### Scenario: Drawing after a state load
- **GIVEN** the core with the switch `video`
- **WHEN** the program loads a state and runs 60 frames
- **THEN** the core draws no picture in these frames

#### Scenario: Screen read under the switch video
- **GIVEN** a stable-retro environment with RAM observations on the core with the switch `video`
- **WHEN** the program reads the screen before the first frame, after 600 frames or after a state load
- **THEN** stable-retro raises an error
- **AND** the program can continue to run frames and the work RAM changes as without the switch

#### Scenario: Image observations under the switch video
- **GIVEN** the core with the switch `video`
- **WHEN** a program makes a stable-retro environment with image observations
- **THEN** stable-retro raises an error and makes no environment

### Requirement: DSP switch stops the sound DSP
With the switch `dsp`, the sound DSP MUST NOT run. The sound CPU (SPC700) MUST continue to run, so the game and the sound
CPU exchange data as with the baseline core. The audio samples that the core gives have no defined content. The core
MUST NOT stop when the program reads the audio samples.

#### Scenario: Game with the switch dsp
- **GIVEN** the core with the switch `dsp`
- **WHEN** the program replays a recording that loads new music in a level change
- **THEN** the work RAM is equal after each frame to the work RAM of the baseline core

### Requirement: Savestates in two directions
The savestate format MUST stay the format of the baseline core. A state that the core saves with any set of switches
MUST load in the baseline core. A state that the baseline core saves MUST load in the core with any set of switches.
After each load, the work RAM after each frame MUST be equal to the work RAM of the baseline core with the same inputs.

#### Scenario: Lean state into the baseline core
- **GIVEN** a state that the core saved with the switches `video` and `dsp`
- **WHEN** the baseline core loads the state and runs 900 frames with the inputs of a recording
- **THEN** the work RAM is equal after each frame to the work RAM of the baseline core that started from its own state of the same frame
- **AND** the screen is equal after each frame

#### Scenario: Baseline state into the lean core
- **GIVEN** a state that the baseline core saved
- **WHEN** the core with the switches `video` and `dsp` loads the state and runs 900 frames with the inputs of a recording
- **THEN** the work RAM is equal after each frame to the work RAM of the baseline core
