# Spec Delta

## Purpose

This capability builds the fork's SNES core and puts it in a core folder that stable-retro can load. It keeps the build
recipe of stable-retro, and it gives the compiler flags of the default build.

## ADDED Requirements

### Requirement: Core folder
The project MUST give one build command. The command MUST build the core from the source files of the checkout, also
with changes that are not committed. It MUST write a core folder with `snes9x_libretro.so`, `snes9x.json` and a build
record. `snes9x.json` MUST be equal to the core info file of stable-retro 1.0.1. stable-retro MUST load the core of the
folder when `RETRO_CORE_PATH` gives the folder.

#### Scenario: Build and load
- **GIVEN** a clean checkout of the fork
- **WHEN** the owner runs the build command with an output folder
- **THEN** the folder contains `snes9x_libretro.so` and `snes9x.json`
- **AND** a Python program with `RETRO_CORE_PATH` set to the folder before `import stable_retro` loads this `snes9x_libretro.so`

### Requirement: Build record
The build record of a core folder MUST give the commit of the checkout, if the checkout had uncommitted changes, the
flag set, the added compiler flags, the compiler version and the highest glibc version that the core needs.

#### Scenario: Build with uncommitted changes
- **GIVEN** a checkout with one changed source file that is not committed
- **WHEN** the owner runs the build command
- **THEN** the build record gives the commit and shows that the checkout had uncommitted changes

### Requirement: Clean source tree
The build command MUST NOT write files into the source tree of the checkout. After a build, the version control MUST show
no changed file and no new file.

#### Scenario: Status after a build
- **GIVEN** a checkout with no changes
- **WHEN** the owner runs the build command
- **THEN** `git status` shows no changed file and no new file

### Requirement: Build recipe of stable-retro
Each build MUST use the build recipe of stable-retro 1.0.1: the libretro Makefile, the C flags `-w -std=gnu17`, the C++
flag `-w`, the linker flags `-w -static-libstdc++ -Wl,--exclude-libs,ALL` and position-independent code. Each build MUST
keep `LAGFIX=1`, because it sets the point where a frame ends.

#### Scenario: Recipe in the build log
- **GIVEN** the build command
- **WHEN** the owner runs a build
- **THEN** the compile lines of the build log contain `-DLAGFIX`, `-w` and `-fPIC`

### Requirement: Flag sets
The build command MUST accept a flag set. The flag set `stable-retro` MUST add no compiler flag to the recipe. The flag
set `default` MUST add the flags that the flag A/B accepted. A build without a flag set MUST use `default`.

#### Scenario: Build with the recipe only
- **GIVEN** the build command
- **WHEN** the owner builds with the flag set `stable-retro`
- **THEN** the compile lines contain no flag that the recipe does not give

#### Scenario: Build without a flag set
- **GIVEN** the build command
- **WHEN** the owner builds and gives no flag set
- **THEN** the build uses the flag set `default`

### Requirement: Accepted compiler flags
A compiler flag MUST be part of the flag set `default` only when it passed the flag A/B. The candidates are `-O3`,
`-flto` and `-march=x86-64-v3`. A flag passes when the parity check gives 0 differing frames with no switch and with the
switches `video` and `dsp`, and the speed bench shows a gain of at least 2 % for one worker.

#### Scenario: Flag with a parity fault
- **GIVEN** a build with a candidate flag
- **WHEN** the parity check finds one or more differing frames
- **THEN** the flag is not part of the flag set `default`

#### Scenario: Flag without a gain
- **GIVEN** a build with a candidate flag and 0 differing frames
- **WHEN** the speed bench shows a gain of less than 2 % for one worker
- **THEN** the flag is not part of the flag set `default`

### Requirement: glibc need
The glibc version that a core needs comes from the glibc of the build machine. The build documentation MUST say this.
It MUST give the glibc version that a build on the owner's desktop needs, and it MUST tell the owner to compare the
version in the build record with the glibc of the target machine.

#### Scenario: glibc version in the build record
- **GIVEN** a build on the owner's desktop
- **WHEN** the owner reads the build record
- **THEN** the record gives the highest glibc version that the core needs, for example 2.38

### Requirement: CPU of the default build
When the flag set `default` contains `-march=x86-64-v3`, the project documentation MUST say that the core needs a CPU
with x86-64-v3 (AVX2). The flag set `stable-retro` MUST stay available for a CPU without x86-64-v3.

#### Scenario: Documentation of the CPU need
- **GIVEN** the flag set `default` contains `-march=x86-64-v3`
- **WHEN** the owner reads the build documentation
- **THEN** the documentation says that the core needs x86-64-v3 and gives the build with the flag set `stable-retro`
