#!/bin/sh
# Tests for .githooks/pre-commit, .githooks/pre-push, and
# .claude/hooks/guard-git-push.sh.
#
# Everything runs in throwaway repos and a local bare remote under a temp
# dir. Nothing touches the real origin, and no network is used.
# Usage: sh tests/hooks/run.sh
#        HOOK_SHELL=dash sh tests/hooks/run.sh   (run the guard under dash)
#        HOOKS_JUNIT=hooks-junit.xml sh tests/hooks/run.sh
#            (also write a JUnit report, one testcase per check, for Codecov
#            Test Analytics, #182)

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
HOOKS="$ROOT/.githooks"
GUARD="$ROOT/.claude/hooks/guard-git-push.sh"

TMP=$(mktemp -d "${TMPDIR:-/tmp}/hooks-test.XXXXXX")
trap 'rm -rf "$TMP"' EXIT INT TERM

pass=0
fail=0
ok() { pass=$((pass + 1)); echo "ok   - $1"; junit_case "$1" ""; }
not_ok() { fail=$((fail + 1)); echo "FAIL - $1"; junit_case "$1" "$1"; }

# junit_case <name> <failure message, empty if passed>: buffered for HOOKS_JUNIT.
xml_escape() { printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g' -e 's/"/\&quot;/g'; }
junit_case() {
    [ -n "${HOOKS_JUNIT:-}" ] || return 0
    printf '    <testcase classname="hooks.%s" name="%s"' "${HOOK_SHELL:-sh}" "$(xml_escape "$1")" >>"$TMP/junit"
    if [ -n "$2" ]; then
        printf '>\n      <failure message="%s"/>\n    </testcase>\n' "$(xml_escape "$2")" >>"$TMP/junit"
    else
        printf '/>\n' >>"$TMP/junit"
    fi
}
write_junit() {
    [ -n "${HOOKS_JUNIT:-}" ] || return 0
    {
        echo '<?xml version="1.0" encoding="UTF-8"?>'
        echo '<testsuites>'
        printf '  <testsuite name="hooks.%s" tests="%d" failures="%d">\n' "${HOOK_SHELL:-sh}" $((pass + fail)) "$fail"
        cat "$TMP/junit" 2>/dev/null
        echo '  </testsuite>'
        echo '</testsuites>'
    } >"$HOOKS_JUNIT"
}

# expect <allow|block> <description> <command...>
expect() {
    want=$1
    desc=$2
    shift 2
    if "$@" >"$TMP/out" 2>&1; then got=allow; else got=block; fi
    # A block only counts if a hook produced it, not some unrelated error.
    if [ "$got" = block ] && ! grep -q -e "refusing to" -e "Blocked by" "$TMP/out"; then
        got="error (no hook message)"
    fi
    if [ "$got" = "$want" ]; then ok "$desc"; else not_ok "$desc (wanted $want, got $got)"; fi
    # Show hook output on failure, or always with HOOKS_TEST_VERBOSE=1.
    if [ "$got" != "$want" ] || [ -n "${HOOKS_TEST_VERBOSE:-}" ]; then sed 's/^/     /' "$TMP/out"; fi
}

# --- Setup --------------------------------------------------------------------
REPO="$TMP/repo"
REMOTE="$TMP/remote.git"
git init -q --bare "$REMOTE"
git init -q "$REPO"
g() { git -C "$REPO" "$@"; }
g config user.email test@example.com
g config user.name Test
g config commit.gpgsign false
g config core.hooksPath "$HOOKS"
g remote add origin "$REMOTE"
g switch -q -c issue-x
echo init >"$REPO/README"
g add README
g commit -q --no-verify -m init

# commit_file <path> <content>: stage one file and try to commit it.
commit_file() {
    mkdir -p "$(dirname "$REPO/$1")"
    printf '%s\n' "$2" >"$REPO/$1"
    g add -f -- "$1"
    g commit -q -m "add $1"
}
# Unstage and drop anything left over from a blocked commit.
reset_repo() {
    g reset -q --hard
    g clean -qfdx
}

# --- pre-commit: protected branches ---------------------------------------------
for b in dev master; do
    g switch -q -c "$b"
    expect block "pre-commit blocks commits on $b" commit_file "on-$b.txt" hello
    reset_repo
    g switch -q issue-x
done
expect allow "pre-commit allows commits on issue-x" commit_file ok.txt hello

# --- pre-commit: FTDI vendor libraries ---------------------------------------------
for f in LibFT4222-64.dll lib/libft4222.so.1.4.4.44 libft4222.dylib ftd2xx.dll FTD2XX.DLL libftd2xx.dylib; do
    expect block "pre-commit blocks staged $f" commit_file "$f" "binary"
    reset_repo
done
expect allow "pre-commit allows ft4222.py" commit_file src/ft4222.py "x = 1"

# --- pre-commit: large files ---------------------------------------------------------
big_file() {
    head -c 1048577 /dev/zero >"$REPO/capture.bin"
    g add -f capture.bin
    g commit -q -m "add capture"
}
expect block "pre-commit blocks a file over 1 MiB" big_file
reset_repo
small_file() {
    head -c 8192 /dev/zero >"$REPO/frames.bin"
    g add -f frames.bin
    g commit -q -m "add frames"
}
expect allow "pre-commit allows a small binary fixture" small_file

# --- pre-push -------------------------------------------------------------------
expect allow "pre-push allows pushing issue-x" g push -q origin issue-x
expect block "pre-push blocks HEAD:dev" g push -q origin HEAD:dev
expect block "pre-push blocks HEAD:refs/heads/master" g push -q origin HEAD:refs/heads/master
g branch -q -f dev issue-x
expect block "pre-push blocks pushing local dev" g push -q origin dev
expect block "pre-push blocks a mixed push that includes dev" g push -q origin issue-x dev
expect allow "pre-push allows issue-x:issue-y" g push -q origin issue-x:issue-y
expect allow "pre-push allows dev with ALLOW_PROTECTED_PUSH=1" env ALLOW_PROTECTED_PUSH=1 git -C "$REPO" push -q origin dev
if git -C "$REMOTE" rev-parse -q --verify refs/heads/master >/dev/null; then
    not_ok "bare remote has no master after blocked pushes"
else
    ok "bare remote has no master after blocked pushes"
fi

# --- guard-git-push.sh ---------------------------------------------------------------
DEVREPO="$TMP/on-dev"
git init -q "$DEVREPO"
git -C "$DEVREPO" symbolic-ref HEAD refs/heads/dev

# guard <allow|block> <cwd> <command>
guard() {
    json=$(jq -n --arg c "$3" --arg d "$2" '{tool_name: "Bash", cwd: $d, tool_input: {command: $c}}')
    run_guard() { printf '%s' "$json" | ${HOOK_SHELL:-sh} "$GUARD"; }
    expect "$1" "guard $1s: $3" run_guard
}
guard block "$REPO" "git push origin dev"
guard block "$REPO" "git push origin master"
guard block "$REPO" "git push origin HEAD:dev"
guard block "$REPO" "git push origin \"HEAD:dev\""
guard block "$REPO" "git push -u origin issue-x:refs/heads/master"
guard block "$REPO" "git push origin :dev"
guard block "$REPO" "git push --delete origin dev"
guard block "$REPO" "git push --force origin issue-x"
guard block "$REPO" "git push -f origin issue-x"
guard block "$REPO" "git push -fu origin issue-x"
guard block "$REPO" "git push origin +issue-x"
guard block "$REPO" "git push --force --force-with-lease origin issue-x"
guard block "$REPO" "git push --force-with-lease origin feature"
guard block "$REPO" "git push --force-with-lease origin issue-x:dev"
guard block "$REPO" "git push --all origin"
guard block "$REPO" "git push --mirror origin"
guard block "$REPO" "uv run pytest && git push origin dev"
guard block "$REPO" "git -C /some/path push origin dev"
guard block "$DEVREPO" "git push"
guard block "$DEVREPO" "git push origin"
guard block "$DEVREPO" "git push origin HEAD"
guard block "$DEVREPO" "git push --force-with-lease"

guard allow "$REPO" "git push -u origin issue-x"
guard allow "$REPO" "git push origin issue-9-local-guardrails"
guard allow "$REPO" "git push --force-with-lease origin issue-x"
guard allow "$REPO" "git push --force-with-lease=issue-x:abc123 origin issue-x"
guard allow "$REPO" "git push --force-with-lease"
guard allow "$REPO" "git push"
guard allow "$REPO" "git push origin HEAD"
guard allow "$REPO" "git status && git log --oneline -3"
guard allow "$REPO" "git fetch origin dev"
guard allow "$REPO" "git switch dev"
guard allow "$REPO" "echo push dev"
guard allow "$REPO" "git push -o"

# Non-Bash payloads and bad input fail open (with a warning).
guard_raw() { printf '%s' "$1" | ${HOOK_SHELL:-sh} "$GUARD"; }
expect allow "guard allows input with no command" guard_raw '{"tool_name":"Read","tool_input":{"file_path":"x"}}'
expect allow "guard allows unparseable input" guard_raw 'not json'

# Without jq the guard allows and warns on stderr.
# Git for Windows' MSYS binaries cannot run from symlinked copies, so there
# the "no jq" PATH is the MSYS core bin directory (jq is not part of Git).
case "$(uname -s)" in
    MINGW* | MSYS* | CYGWIN*)
        NOJQ_PATH="/usr/bin"
        NOJQ_SH="/usr/bin/sh"
        ;;
    *)
        NOJQ_PATH="$TMP/nojq-bin"
        NOJQ_SH="$NOJQ_PATH/sh"
        mkdir -p "$NOJQ_PATH"
        for tool in cat git tr sh; do ln -s "$(command -v "$tool")" "$NOJQ_PATH/$tool"; done
        ;;
esac
nojq() { printf '{"tool_input":{"command":"git push origin dev"}}' | PATH="$NOJQ_PATH" "$NOJQ_SH" "$GUARD"; }
if PATH="$NOJQ_PATH" command -v jq >/dev/null 2>&1; then
    ok "skip: jq is present in $NOJQ_PATH, cannot simulate a missing jq"
    ok "skip: jq is present in $NOJQ_PATH, cannot simulate a missing jq"
else
    expect allow "guard allows when jq is missing" nojq
    if nojq 2>&1 | grep -q "jq not found"; then ok "guard warns when jq is missing"; else not_ok "guard warns when jq is missing"; fi
fi

# Blocked output explains why on stderr.
reason=$(printf '%s' '{"tool_input":{"command":"git push origin dev"}}' | ${HOOK_SHELL:-sh} "$GUARD" 2>&1 >/dev/null)
case "$reason" in
    *"git push to dev"*) ok "guard prints the reason on stderr" ;;
    *) not_ok "guard prints the reason on stderr (got: $reason)" ;;
esac

# --- File modes ----------------------------------------------------------------------
for f in "$HOOKS/pre-commit" "$HOOKS/pre-push" "$GUARD"; do
    if [ -x "$f" ]; then ok "executable: ${f#"$ROOT"/}"; else not_ok "executable: ${f#"$ROOT"/}"; fi
done

echo
echo "passed: $pass, failed: $fail"
write_junit
[ "$fail" -eq 0 ]
