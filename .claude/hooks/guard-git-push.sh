#!/bin/sh
# Claude Code PreToolUse hook for the Bash tool (wired in .claude/settings.json).
#
# A strict allowlist that fails closed (#221). It does not parse shell. It
# checks a command that mentions "push" (any case, anywhere, also once quotes
# and backslashes are removed), and one that runs git together with "alias" or
# a shell metacharacter (; & | ` $ ( ) < > { } * ? [ ] or a newline), since
# those can build a push without the word (git p{u,}sh, git config alias.p).
# A checked command must be exactly one of these, with single spaces:
#   git push [-u|--set-upstream] origin issue-<n>-<slug>
#   git push [-u|--set-upstream] origin HEAD:[refs/heads/]issue-<n>-<slug>
#   git push --force-with-lease[=<lease>] origin issue-<n>-<slug>
# where <slug> is [a-z0-9][a-z0-9-]*. Shell metacharacters, git -c/-C,
# --git-dir, env prefixes, other remotes, bare pushes, tags, --delete and
# --force never match, so they are denied. A short-form push is also denied
# when a local tag has the branch's name or push.followTags is set, and a
# plain git command is denied when a configured alias mentions push or runs
# a shell (!).
#
# Text that only mentions push (a commit message, a PR body, echo) is denied
# too. Put it in a file instead: git commit -F <file>, gh pr create
# --body-file <file>. Run other git commands one at a time, without
# metacharacters. Everything else passes straight through.
#
# This is defence in depth; the rulesets on master and dev are the real
# protection. Protocol: hook JSON on stdin; exit 2 with a reason on stderr
# blocks the call, exit 0 allows it. Needs jq. Without jq, or with input jq
# cannot read, any input that would need a check is denied.

LC_ALL=C
export LC_ALL
input=$(cat)
nl='
'

deny() {
    echo "Blocked by .claude/hooks/guard-git-push.sh: $1" >&2
    echo "Pushes are allowlisted: use \`git push [-u] origin issue-<n>-<slug>\`; anything else needs the maintainer (ALLOW_PROTECTED_PUSH does not apply to agents)." >&2
    echo "To mention push in a message or body, put it in a file: git commit -F <file>, gh pr create --body-file <file>." >&2
    echo "Run other git commands one at a time, without alias or ; & | \` \$ ( ) < > { } * ? [ ]." >&2
    exit 2
}

# classify <text>: 0 if it mentions push or runs git with alias or a
# metacharacter (check it), 2 if it runs git plainly, 1 otherwise (pass).
# Quotes and backslashes are removed first, so p'u'sh and p\ush count.
classify() {
    norm=$(printf '%s' "$1" | tr -d "\\\\'\"" | tr '[:upper:]' '[:lower:]')
    case $norm in *push*) return 0 ;; esac
    printf '%s\n' "$norm" | grep -Eq '(^|[^a-z0-9_])git([^a-z0-9_]|$)' || return 1
    case $norm in *alias* | *[]\;\&\|\`\$\(\)\<\>\{\}\*\?\[]* | *"$nl"*) return 0 ;; esac
    return 2
}

if ! command -v jq >/dev/null 2>&1; then
    echo "guard-git-push.sh: jq not found; denying any command that mentions push or git" >&2
    classify "$input"
    [ $? -eq 1 ] || deny "jq is not installed, so the command cannot be checked."
    exit 0
fi

# The command, trimmed, with NUL bytes turned into newlines (denied below).
if ! cmd=$(printf '%s' "$input" | jq -r '(.tool_input.command // "")
    | if type == "string" then . else error("command is not a string") end
    | explode | map(if . == 0 then 10 else . end) | implode
    | sub("^\\s+"; "") | sub("\\s+$"; "")' 2>/dev/null); then
    classify "$input"
    [ $? -eq 1 ] || deny "the hook input could not be parsed."
    exit 0
fi

classify "$cmd"
rc=$?
dir=$(printf '%s' "$input" | jq -r '.cwd // "."' 2>/dev/null) || dir=.
if [ $rc -eq 2 ]; then
    # Plain git: deny if a configured alias could push or run a shell.
    case $(git -C "$dir" config --get-regexp '^alias[.]' 2>/dev/null | tr '[:upper:]' '[:lower:]') in
        *push* | *" !"*) deny "a git alias in your config can push or run a shell." ;;
    esac
    exit 0
fi
[ $rc -eq 0 ] || exit 0
case $cmd in *"$nl"*) deny "a multi-line command may not mention push or run git." ;; esac

branch='issue-[0-9]+-[a-z0-9][a-z0-9-]*'
up='( -u| --set-upstream)?'
allow="^(git push$up origin ($branch|HEAD:(refs/heads/)?$branch)"
allow="$allow|git push --force-with-lease(=[A-Za-z0-9._/:-]+)? origin $branch)\$"
printf '%s\n' "$cmd" | grep -Eq "$allow" ||
    deny "not an allowlisted push (or it runs git with alias or a metacharacter)."

# A short name that is also a local tag, or push.followTags, would push a tag.
name=${cmd##* }
case $name in
    HEAD:*) ;;
    *) if git -C "$dir" show-ref -q --verify "refs/tags/$name" 2>/dev/null; then
        deny "a local tag is named $name; use HEAD:refs/heads/$name."
    fi ;;
esac
if [ "$(git -C "$dir" config --bool --get push.followTags 2>/dev/null)" = true ]; then
    deny "push.followTags is set, so this push would also push tags."
fi
exit 0
