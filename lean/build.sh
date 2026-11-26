#!/usr/bin/env bash
# Build the SNES core of this checkout into a core folder for stable-retro.
#
#   lean/build.sh <out-dir> [--flags stable-retro|default] [--extra "<flags>"]
#
# The build runs in a temporary copy of the working tree. See lean/README.md.
set -euo pipefail

# The flag sets: the compiler flags that each set adds to the stable-retro recipe.
flags_of_set() {
    case $1 in
        stable-retro) echo "" ;;
        default)      echo "" ;;  # the flags that the flag A/B accepts; none yet
        *)            return 1 ;;
    esac
}

usage="usage: lean/build.sh <out-dir> [--flags stable-retro|default] [--extra \"<flags>\"]"

die() {
    echo "build.sh: error: $*" >&2
    exit 1
}

out_arg=""
flag_set="default"
extra=""
while (($#)); do
    case $1 in
        --flags)
            (($# >= 2)) || die "--flags needs a value. $usage"
            flag_set=$2
            shift 2
            ;;
        --extra)
            (($# >= 2)) || die "--extra needs a value. $usage"
            extra=$2
            shift 2
            ;;
        -h | --help)
            echo "$usage"
            exit 0
            ;;
        -*)
            die "unknown option '$1'. $usage"
            ;;
        *)
            [[ -z $out_arg ]] || die "more than one output folder: '$out_arg' and '$1'. $usage"
            out_arg=$1
            shift
            ;;
    esac
done
[[ -n $out_arg ]] || die "no output folder. $usage"
set_flags=$(flags_of_set "$flag_set") || die "unknown flag set '$flag_set'. $usage"
lean_flags="$set_flags${set_flags:+${extra:+ }}$extra"

for tool in git rsync make gcc g++ nm objdump; do
    command -v "$tool" >/dev/null || die "'$tool' is not installed"
done

lean_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
root=$(git -C "$lean_dir" rev-parse --show-toplevel) || die "$lean_dir is not in a git checkout"
root=$(realpath -- "$root")
info_file="$lean_dir/snes9x.json"
export_list="$lean_dir/exports.txt"
[[ -f $info_file ]] || die "missing $info_file"
[[ -f $export_list ]] || die "missing $export_list"

in_checkout() {
    [[ $1/ == "$root"/* ]]
}

out=$(realpath -m -- "$out_arg")
! in_checkout "$out" || die "the output folder must be outside the checkout: $out"
tmp_base=$(realpath -m -- "${TMPDIR:-/tmp}")
! in_checkout "$tmp_base" || die "TMPDIR must be outside the checkout: $tmp_base"

# The state of the checkout at the start of the build.
commit=$(git -C "$root" rev-parse HEAD)
commit_short=$(git -C "$root" rev-parse --short HEAD)
changes=$(git --no-optional-locks -C "$root" status --porcelain)
dirty=no
[[ -z $changes ]] || dirty=yes
compiler=$(gcc --version | sed -n 1p)

mkdir -p -- "$out"
# A failed build must not leave an older core in the folder. Removing the files
# (not writing over them) also keeps a running process on its old library.
rm -f -- "$out/snes9x_libretro.so" "$out/snes9x.json" "$out/build-info.txt" "$out/build.log"

tmp=$(mktemp -d "$tmp_base/snes9x-lean-build.XXXXXX")
trap 'rm -rf -- "$tmp"' EXIT
src="$tmp/src"

# Copy the tracked files (with uncommitted edits) and the new files that git does
# not ignore. A tracked file that is deleted in the working tree is skipped.
(
    cd -- "$root"
    git ls-files -z --cached --others --exclude-standard |
        rsync -a --from0 --files-from=- --ignore-missing-args ./ "$src/"
)
# make would reuse object files of an earlier build in the checkout.
find "$src" -type f \( -name '*.o' -o -name '*.so' \) -delete

# The stable-retro recipe. LEAN_FLAGS carries the flags of the set and of --extra.
# GIT_VERSION is the value that the Makefile would read in the checkout itself;
# the quotes are part of the value.
echo "build.sh: building (flag set '$flag_set', LEAN_FLAGS '$lean_flags') ..."
if ! env -u CPPFLAGS -u INCFLAGS -u MAKEFLAGS -u GNUMAKEFLAGS -u MAKEOVERRIDES -u platform \
    CFLAGS="-w -std=gnu17" \
    CXXFLAGS="-w" \
    LDFLAGS="-w -static-libstdc++ -Wl,--exclude-libs,ALL" \
    make -C "$src/libretro" -j8 -f Makefile CC=gcc CXX=g++ fpic=-fPIC \
    GIT_VERSION="\" $commit_short\"" \
    LEAN_FLAGS="$lean_flags" \
    >"$out/build.log" 2>&1; then
    tail -n 20 -- "$out/build.log" >&2
    die "make failed, see $out/build.log (the build ran under $tmp_base; set TMPDIR for another place)"
fi
lib="$src/libretro/snes9x_libretro.so"
[[ -f $lib ]] || die "make wrote no snes9x_libretro.so, see $out/build.log"

# The library must export exactly the symbols of lean/exports.txt.
nm -D --defined-only "$lib" | awk '{print $NF}' | LC_ALL=C sort >"$tmp/exports.built"
LC_ALL=C sort -- "$export_list" >"$tmp/exports.expected"
if ! diff -u --label lean/exports.txt --label built-library \
    "$tmp/exports.expected" "$tmp/exports.built" >&2; then
    die "the exported symbols differ from lean/exports.txt; no core was written to $out"
fi

# The highest glibc version that the library needs. It comes from the glibc of this
# machine; a machine that runs the core needs this version or a newer one.
glibc=$(objdump -T "$lib" | grep -oE 'GLIBC_[0-9]+(\.[0-9]+)+' | sed 's/^GLIBC_//' | sort -uV | tail -n 1) ||
    die "found no GLIBC_ symbol version in the library; no core was written to $out"

cp -- "$info_file" "$out/snes9x.json"
{
    echo "commit: $commit"
    echo "dirty: $dirty"
    echo "flag set: $flag_set"
    echo "extra flags: $extra"
    echo "LEAN_FLAGS: $lean_flags"
    echo "compiler: $compiler"
    echo "glibc needed: $glibc"
} >"$out/build-info.txt"
cp -- "$lib" "$out/snes9x_libretro.so"

echo "build.sh: export check passed ($(wc -l <"$tmp/exports.built") symbols)"
echo "build.sh: core folder written to $out"
