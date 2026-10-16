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

# The allowlist (#221): only these exact forms may push.
guard allow "$REPO" "git push origin issue-9-local-guardrails"
guard allow "$REPO" "git push -u origin issue-9-x"
guard allow "$REPO" "git push --set-upstream origin issue-9-x"
guard allow "$REPO" "git push origin HEAD:issue-9-x"
guard allow "$REPO" "git push -u origin HEAD:refs/heads/issue-9-x"
guard allow "$REPO" "git push --force-with-lease origin issue-9-x"
guard allow "$REPO" "git push --force-with-lease=issue-9-x:abc123 origin issue-9-x"
guard allow "$REPO" "  git push origin issue-221-agent-permissions  "
guard allow "$DEVREPO" "git push origin issue-9-x"

# Near misses of the allowlist.
guard block "$REPO" "git push origin issue-x"
guard block "$REPO" "git push origin issue-9-X"
guard block "$REPO" "git push origin issue-9-"
guard block "$REPO" "git push origin Issue-9-x"
guard block "$REPO" "git push origin issue-9--x:dev"
guard block "$REPO" "git push origin issue-9-x issue-8-y"
guard block "$REPO" "git push origin issue-9-x -u"
guard block "$REPO" "git push upstream issue-9-x"
guard block "$REPO" "git push  origin issue-9-x"
guard block "$REPO" "git push	origin issue-9-x"
guard block "$REPO" "git push origin issue-9-x;"
guard block "$REPO" "git push -u origin issue-9-x && echo done"
guard block "$REPO" "git push origin issue-9-x 2>&1 | tail -5"
guard block "$REPO" "git push origin issue-9-x # never dev"
guard block "$REPO" "git push origin issue-9-x:dev"
guard block "$REPO" "git push origin HEAD:refs/tags/issue-9-x"
guard block "$REPO" "git push origin refs/heads/issue-9-x"
guard block "$REPO" "git push --force-with-lease origin HEAD:issue-9-x"
guard block "$REPO" "git push --force-with-lease=x\$(id) origin issue-9-x"
guard block "$REPO" "git push --force-with-lease -u origin issue-9-x"
guard block "$REPO" "git push -f origin issue-9-x"
guard block "$REPO" "git push --force origin issue-9-x"
guard block "$REPO" "git push origin +issue-9-x"
guard block "$REPO" "git push --delete origin issue-9-x"
guard block "$REPO" "git push -d origin issue-9-x"
guard block "$REPO" "git push --prune origin issue-9-x"
guard block "$REPO" "git push --no-follow-tags origin issue-9-x"
guard block "$REPO" "git -c a.b=c push origin issue-9-x"
guard block "$REPO" "git -C $REPO push origin issue-9-x"
guard block "$REPO" "git --git-dir=$REPO/.git push origin issue-9-x"
guard block "$REPO" "GIT_DIR=$DEVREPO/.git git push origin issue-9-x"
guard block "$REPO" "ALLOW_PROTECTED_PUSH=1 git push origin dev"
guard block "$REPO" "git push origin issue-9-x
git push origin dev"
guard block "$REPO" "GIT PUSH origin dev"

# Earlier must-deny cases: all denied by default now.
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
guard block "$REPO" "git push"
guard block "$REPO" "git push origin HEAD"
guard block "$REPO" "git push --force-with-lease"
guard block "$REPO" "git push -o"
guard block "$REPO" "git push -o ci.skip origin issue-9-x"
guard block "$REPO" "git push origin :issue-9-y"
# tags (only the maintainer pushes tags)
g tag v1.2.3
guard block "$REPO" "git push origin v1.2.3"
guard block "$REPO" "git push --tags"
guard block "$REPO" "git push origin --tags"
guard block "$REPO" "git push origin refs/tags/v1"
guard block "$REPO" "git push origin HEAD:refs/tags/v1"
guard block "$REPO" "git push --follow-tags origin issue-x"
guard block "$REPO" "git push --delete origin v1.2.3"
guard block "$REPO" "git status && git push origin v1.2.3"
guard block "$REPO" "git push --tag origin"
guard block "$REPO" "git push --follow origin issue-x"
guard block "$REPO" "git push origin tags/v1"
guard block "$REPO" "git push origin v1:refs/tags/v1"
guard block "$REPO" "git push origin issue-x:v1.2.3"
g tag issue-7-tagged
guard block "$REPO" "git push origin issue-7-tagged"
guard allow "$REPO" "git push origin HEAD:refs/heads/issue-7-tagged"
g tag -d issue-7-tagged >/dev/null
g config push.followTags true
guard block "$REPO" "git push origin issue-9-x"
guard block "$REPO" "git push --no-follow-tags origin issue-9-x"
g config --unset push.followTags
# git global options, aliases and config
guard block "$REPO" "git --no-pager push origin dev"
guard block "$REPO" "git --git-dir=$REPO/.git push origin dev"
guard block "$REPO" "git -c core.askPass=x push origin dev"
guard block "$REPO" "git -c alias.p=push p origin dev"
guard block "$REPO" "git -c alias.p=push p origin issue-x"
guard block "$REPO" "git -c alias.p='!git push' p origin dev"
guard block "$REPO" "git -c push.default=matching push"
guard block "$REPO" "git -c remote.origin.push=HEAD:dev push origin"
guard block "$REPO" "git -c remote.origin.pushurl=x push origin issue-9-x"
guard block "$REPO" "git -c remote.origin.mirror=true push origin"
guard block "$REPO" "git -c branch.issue-9-x.merge=refs/heads/dev push"
guard block "$REPO" "git -c push.followTags=true push origin issue-x"
guard block "$REPO" "git --exec-path=/tmp push origin issue-x"
guard block "$REPO" "git config push.default matching && git push"
guard block "$REPO" "git config branch.issue-9-x.merge refs/heads/dev; git push"
guard block "$REPO" "git config remote.origin.pushurl x; git push origin issue-9-x"
# aliases defined earlier in the same command (#221 second review)
guard block "$REPO" "git config alias.sync push; git sync origin dev"
guard block "$REPO" "git config --global alias.p push && git p origin dev"
guard block "$REPO" "git config alias.s pu''sh; git s origin dev"
guard block "$REPO" "git -c alias.s=pu\\sh s origin dev"
guard block "$REPO" "git config alias.sync"
# brace and other expansion that splits the word push (#221 second review)
guard block "$REPO" "git push origin {dev,x}"
guard block "$REPO" "git {push,} origin dev"
guard block "$REPO" "git p{u,}sh origin dev"
guard block "$REPO" "git pu{s,}h origin dev"
guard block "$REPO" "git pu[s]h origin dev"
guard block "$REPO" "git pu?h origin dev"
guard block "$REPO" "git pu*h origin dev"
guard block "$REPO" "git \$(printf pu)sh origin dev"
guard block "$REPO" "git \`printf pu\`sh origin dev"
guard block "$REPO" "P=pu; git \${P}sh origin dev"
guard block "$REPO" "git \$'\\x70ush' origin dev"
guard block "$REPO" "git pu''sh origin dev"
guard block "$REPO" "git p\"u\"sh origin dev"
guard block "$REPO" "git p\\ush origin dev"
guard block "$REPO" "echo pu sh | tr -d ' ' | xargs -I x git x origin dev"
# refspec spellings
guard block "$REPO" "git push origin HEAD:heads/dev"
guard block "$REPO" "git push origin issue-x:DEV"
guard block "$REPO" "git push origin +issue-x:dev"
guard block "$REPO" "git push origin refs/heads/master"
guard block "$REPO" "git push origin :"
guard block "$REPO" "git push origin 'refs/heads/*:refs/heads/*'"
guard block "$REPO" "git push origin -- dev"
guard block "$REPO" "git push origin issue-x:HEAD"
guard block "$REPO" "git push -d origin feature"
guard block "$REPO" "git push origin :feature"
guard block "$REPO" "git push https://example.invalid/r.git HEAD:master"
guard block "$REPO" "git push origin issue-x --force"
guard block "$REPO" "git push origin issue-x -f"
guard block "$REPO" "git push -uf origin issue-x"
guard block "$REPO" "git push --forc origin issue-x"
guard block "$REPO" "git push --mirr origin"
guard block "$REPO" "git push --al origin"
guard block "$REPO" "git push --prune origin issue-x"
guard block "$REPO" "git push --force-if-includes origin feature"
guard block "$REPO" "git push --force-with-lease origin HEAD:feature"
# shell-level tricks
guard block "$REPO" "true; git push origin dev"
guard block "$REPO" "true | git push origin dev"
guard block "$REPO" "true
git push origin dev"
guard block "$REPO" "echo \$(git push origin dev)"
guard block "$REPO" "echo \`git push origin dev\`"
guard block "$REPO" "(git push origin dev)"
guard block "$REPO" "{ git push origin dev; }"
guard block "$REPO" "if true; then git push origin dev; fi"
guard block "$REPO" "env FOO=1 git push origin dev"
guard block "$REPO" "command git push origin dev"
guard block "$REPO" "nohup git push origin dev"
guard block "$REPO" "\\git push origin dev"
guard block "$REPO" "/usr/bin/git push origin dev"
guard block "$REPO" "git \"push\" origin 'dev'"
guard block "$REPO" "git push origin de\"\"v"
guard block "$REPO" "git push origin d\\ev"
guard block "$REPO" "git  push	origin	dev"
guard block "$REPO" "echo dev | xargs git push origin"
guard block "$REPO" "timeout 60 git push origin dev"
guard block "$REPO" "uv run git push origin dev"
guard block "$REPO" "sh -c \"git push origin dev\""
guard block "$REPO" "bash -lc 'git push origin dev'"
guard block "$REPO" "sh -c 'git push origin \"\$1\"' _ dev"
guard block "$REPO" "eval \"git push origin dev\""
guard block "$REPO" "B=dev; git push origin \$B"
guard block "$REPO" "CMD='git push origin dev'; \$CMD"
guard block "$REPO" "echo git push origin dev | sh"
guard block "$REPO" "sh <<'EOF'
git push origin dev
EOF"
guard block "$REPO" "python3 -c \"import os; os.system('git push origin dev')\""
guard block "$REPO" "git-push origin dev"
guard block "$REPO" "git push origin issue-x \$(echo dev)"
guard block "$REPO" "alias p='git push origin dev'"
g config alias.pp push
guard block "$REPO" "git pp origin dev"
guard block "$REPO" "git status"
g config --unset alias.pp
g config alias.sh '!sh -c x'
guard block "$REPO" "git sh"
g config --unset alias.sh
g config alias.st status
guard allow "$REPO" "git st"
g config --unset alias.st
# commands that change what a push would update
guard block "$REPO" "git checkout dev && git push"
guard block "$REPO" "git switch dev; git push origin HEAD"
guard block "$REPO" "git tag v2 && git push origin v2"
guard block "$REPO" "cd $DEVREPO && git push"
guard block "$REPO" "cd \$X && git push origin issue-x"
guard block "$REPO" "GIT_DIR=$DEVREPO/.git git push"
guard block "$REPO" "git -C $DEVREPO push"
guard block "$REPO" "git -C $REPO push -u origin issue-x"
guard block "$REPO" "cd $REPO && git push -u origin issue-9-x"
guard block "$REPO" "git add -A && git commit -m wip && git push"
guard block "$REPO" "git branch --show-current && git push"

# Text that only mentions push is denied too (fail closed). The documented
# workaround is a file: git commit -F <file>, gh pr create --body-file <file>.
guard block "$REPO" "git commit -m 'docs: never git push -f to dev'"
guard block "$REPO" "git commit -F - <<'EOF'
Avoid git push -f origin dev.
EOF"
guard block "$REPO" "gh pr create --title t --body 'Run git push origin dev? No.'"
guard block "$REPO" "gh pr comment 230 --body 'pushed'"
guard block "$REPO" "echo \"git push origin dev\""
guard block "$REPO" "echo push dev"
guard block "$REPO" "uv run pytest tests/test_push.py"
guard block "$REPO" "git log --grep=push"
guard allow "$REPO" "git commit -F msg.txt"
guard allow "$REPO" "gh pr create --title t --body-file body.md"

# git with a metacharacter or alias is denied even without push; plain git
# commands and everything else pass.
guard block "$REPO" "git status && git log --oneline -3"
guard block "$REPO" "git log --oneline | head -5"
guard block "$REPO" "git diff > out.patch"
guard block "$REPO" "git config --get-regexp alias"
guard allow "$REPO" "git status"
guard allow "$REPO" "git log --oneline -5"
guard allow "$REPO" "git fetch origin dev"
guard allow "$REPO" "git switch dev"
guard allow "$REPO" "git tag --list"
guard allow "$REPO" "git commit -m \"fix the parser\""
guard allow "$REPO" "uv run pytest -q && uv run ruff check ."
guard allow "$REPO" "ls .github/workflows/*.yml | head -3"
guard allow "$REPO" "echo \$HOME"

# Non-Bash payloads pass; unparseable input that needs a check is denied.
guard_raw() { printf '%s' "$1" | ${HOOK_SHELL:-sh} "$GUARD"; }
expect allow "guard allows input with no command" guard_raw '{"tool_name":"Read","tool_input":{"file_path":"x"}}'
expect allow "guard allows unparseable input" guard_raw 'not json'
expect block "guard blocks unparseable input that mentions push" guard_raw 'not json: git push origin dev'
expect block "guard blocks truncated JSON that mentions push" guard_raw '{"tool_input":{"command":"git push origin issue-9-x'
expect block "guard blocks unparseable input that runs git" guard_raw 'not json: git pp origin dev'
expect block "guard blocks unparseable input with git and a brace" guard_raw 'not json: git p{u,}sh origin dev'
expect block "guard blocks a non-string command that mentions push" guard_raw '{"tool_input":{"command":["git","push","origin","dev"]}}'
expect block "guard blocks a NUL byte after an allowed push" guard_raw '{"tool_input":{"command":"git push origin issue-9-x\u0000git push origin dev"}}'
expect block "guard blocks an escaped newline after an allowed push" guard_raw '{"tool_input":{"command":"git push origin issue-9-x\ngit push origin dev"}}'

# Without jq the guard warns, and denies anything that would need a check.
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
        for tool in cat git tr grep sh; do ln -s "$(command -v "$tool")" "$NOJQ_PATH/$tool"; done
        ;;
esac
nojq_run() { printf '%s' "$1" | PATH="$NOJQ_PATH" "$NOJQ_SH" "$GUARD"; }
nojq() { nojq_run '{"tool_input":{"command":"ls -la"}}'; }
nojq_git() { nojq_run '{"tool_input":{"command":"git status"}}'; }
nojq_push() { nojq_run '{"tool_input":{"command":"git push origin issue-9-x"}}'; }
nojq_brace() { nojq_run '{"tool_input":{"command":"git p{u,}sh origin dev"}}'; }
if PATH="$NOJQ_PATH" command -v jq >/dev/null 2>&1; then
    for i in 1 2 3 4 5; do ok "skip: jq is present in $NOJQ_PATH, cannot simulate a missing jq"; done
else
    expect allow "guard allows a command without push or git when jq is missing" nojq
    if nojq 2>&1 | grep -q "jq not found"; then ok "guard warns when jq is missing"; else not_ok "guard warns when jq is missing"; fi
    # Fail closed: without jq the guard cannot check the command (the raw
    # JSON always has braces), so any git or push is denied.
    expect block "guard blocks git when jq is missing" nojq_git
    expect block "guard blocks a push when jq is missing" nojq_push
    expect block "guard blocks a brace push when jq is missing" nojq_brace
fi

# Blocked output explains why on stderr, with the workaround.
reason=$(printf '%s' '{"tool_input":{"command":"git push origin dev"}}' | ${HOOK_SHELL:-sh} "$GUARD" 2>&1 >/dev/null)
case "$reason" in
    *"Pushes are allowlisted"*"ALLOW_PROTECTED_PUSH does not apply to agents"*"--body-file"*) ok "guard prints the reason on stderr" ;;
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
