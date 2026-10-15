#!/bin/sh
# Claude Code PreToolUse hook for the Bash tool (wired in .claude/settings.json).
#
# Denies:
#   - git push whose target is master or dev, in any spelling ("origin dev",
#     "HEAD:dev", "x:refs/heads/master", "x:heads/dev", ":dev", "DEV", or a
#     bare "git push" / "git push origin HEAD" while on master or dev)
#   - git push --all / --mirror / --branches / --prune, wildcard refspecs and
#     ":" (they can update master and dev)
#   - any force push: --force, -f (also combined, e.g. -uf), or a +refspec
#   - any tag push: --tags, --follow-tags, push.followTags=true, a refspec
#     with refs/tags/ or tags/, or a refspec naming an existing local tag.
#     Tags come only from the maintainer.
#   - deleting a remote branch other than an issue-* branch
# Allows:
#   - --force-with-lease (and --force-if-includes) when every target branch
#     is an issue-* branch, because rebasing feature branches is normal.
#
# Fail closed (#221): the command is tokenized like a POSIX shell would (quotes,
# escapes, comments, redirections, heredocs, $(...) and backticks), and
# "git [global options] push" is found after env assignments and wrappers
# (env, command, exec, nohup, time, nice, sh/bash -c, eval). A push the guard
# cannot classify is denied, for example:
#   - git aliases for push (git -c alias.p=push p, or one in git config),
#     git -c push.*/remote.*/branch.*/alias.*/include.* with a push, and
#     push.default=matching/upstream or remote.*.push/mirror for a bare push;
#   - a computed push argument ($VAR, $(...)), a computed command name, or
#     git push run through another program (xargs, find -exec, timeout,
#     uv run, python -c ...), or commands piped into a shell;
#   - a push combined with commands that change what it would push: git
#     switch/checkout/branch before a bare push, git tag/config/remote/
#     update-ref, GIT_* variables, .git/ edits, or a cd the guard can't follow.
# Text that only mentions "git push" (echo, gh pr create --body, a commit
# message, a quoted heredoc) is not a push and is allowed. A script file run
# with sh/bash/python is not inspected.
#
# Protocol: reads the hook JSON on stdin. Exit 2 with a reason on stderr
# blocks the tool call; exit 0 lets it through. Requires jq and awk. Without
# jq, or with unparseable input, any command that mentions "push" is denied.

input=$(cat)
nl='
'

deny() {
    echo "Blocked by .claude/hooks/guard-git-push.sh: $1" >&2
    echo "master and dev change only through pull requests, and only the maintainer pushes tags (see AGENTS.md)." >&2
    exit 2
}

has_push() {
    case $1 in *[Pp][Uu][Ss][Hh]*) return 0 ;; esac
    return 1
}

lower() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]'; }

# q <word>: single-quote a word for eval.
q() { printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"; }

# abbrev <given> <full>: git accepts any unique prefix of a long option.
abbrev() {
    [ -n "$1" ] || return 1
    case $2 in "$1"*) return 0 ;; esac
    return 1
}

if ! command -v jq >/dev/null 2>&1; then
    case $input in *[Pp][Uu][Ss][Hh]* | *'\u'*)
        deny "jq not found, so a command that may push cannot be checked. Install jq." ;;
    esac
    echo "guard-git-push: jq not found; git push guard is disabled." >&2
    exit 0
fi

if ! cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // empty' 2>/dev/null); then
    case $input in *[Pp][Uu][Ss][Hh]* | *'\u'*)
        deny "could not parse the hook input of a command that may push." ;;
    esac
    echo "guard-git-push: could not parse hook input; allowing." >&2
    exit 0
fi
cwd=$(printf '%s' "$input" | jq -r '.cwd // empty' 2>/dev/null)

[ -n "$cmd" ] || exit 0
# Fast path: nothing here can run git or a push.
case $cmd in *[Pp][Uu][Ss][Hh]* | *[Gg][Ii][Tt]*) ;; *) exit 0 ;; esac

CMD=$cmd
if [ -n "$cwd" ] && [ -d "$cwd" ]; then CANDS=$cwd; else CANDS=$(pwd); fi
CD_UNK=0
GOPTS=""
set -f
IFS=$nl

# Tokenizer. Output, one record per line:
#   s:<word>  a word with quotes and escapes removed
#   d:<word>  a word with an expansion ($x, $(...), `...`); its text is partial
#   R         the next word is a redirection target, not an argument
#   H:q:<body> / H:u:<body>  heredoc body (quoted / unquoted delimiter) of the
#             current segment, newlines encoded as \036
#   S         end of a simple command (; & | && || ( ) newline)
#   E         unbalanced quotes or parentheses
# Command substitutions are emitted as their own segments, after the rest.
TOKENIZER='
function out(x) { buf[dep] = buf[dep] x "\n" }
function addc(x) { wd[dep] = wd[dep] x; inw[dep] = 1 }
function flushw() {
    if (inw[dep]) { gsub(/\n/, " ", wd[dep]); out((dyn[dep] ? "d:" : "s:") wd[dep]) }
    wd[dep] = ""; inw[dep] = 0; dyn[dep] = 0; qt[dep] = 0
}
function newlevel() { dep++; buf[dep] = ""; wd[dep] = ""; inw[dep] = 0; dyn[dep] = 0; qt[dep] = 0 }
function subst(stop) {
    dyn[dep] = 1; inw[dep] = 1
    newlevel(); parse(stop); flushw(); out("S")
    extra = extra buf[dep]; dep--
}
function subtext(t,   ss, pp, nn) {
    ss = s; pp = p; nn = n; s = t; p = 1; n = length(t)
    subst("")
    s = ss; p = pp; n = nn
}
function backtick(   t, c, found) {
    t = ""; found = 0
    while (p <= n) {
        c = substr(s, p, 1)
        if (c == "\\" && p < n) {
            c = substr(s, p + 1, 1)
            if (c != "`" && c != "\\" && c != "$") t = t "\\"
            t = t c; p += 2; continue
        }
        if (c == "`") { p++; found = 1; break }
        t = t c; p++
    }
    if (!found) err = 1
    subtext(t)
}
function dollar(   c, c2) {
    c2 = substr(s, p + 1, 1)
    if (c2 == "(") { p += 2; subst(")"); return }
    if (c2 == "{") { p += 2; subst("}"); return }
    if (c2 == "\047") {
        p += 2; dyn[dep] = 1; inw[dep] = 1
        while (p <= n) {
            c = substr(s, p, 1)
            if (c == "\\") { addc(substr(s, p, 2)); p += 2; continue }
            if (c == "\047") { p++; return }
            addc(c); p++
        }
        err = 1; return
    }
    if (c2 ~ /[A-Za-z0-9_@*#?$!-]/) {
        dyn[dep] = 1; inw[dep] = 1; p += 2
        if (c2 ~ /[A-Za-z_]/) while (p <= n && substr(s, p, 1) ~ /[A-Za-z0-9_]/) p++
        return
    }
    addc("$"); p++
}
function dquote(   c, c2) {
    inw[dep] = 1; qt[dep] = 1
    while (p <= n) {
        c = substr(s, p, 1)
        if (c == "\"") { p++; return }
        if (c == "\\") {
            c2 = substr(s, p + 1, 1)
            if (c2 == "\n") { p += 2; continue }
            if (c2 == "$" || c2 == "`" || c2 == "\"" || c2 == "\\") { addc(c2); p += 2; continue }
            addc(c); p++; continue
        }
        if (c == "`") { p++; backtick(); continue }
        if (c == "$") { dollar(); continue }
        addc(c); p++
    }
    err = 1
}
function heredoc_start(   strip, d, quoted, c) {
    p += 2; strip = 0
    if (substr(s, p, 1) == "-") { strip = 1; p++ }
    while (substr(s, p, 1) == " " || substr(s, p, 1) == "\t") p++
    d = ""; quoted = 0
    while (p <= n) {
        c = substr(s, p, 1)
        if (c ~ /[ \t\n;&|<>()]/) break
        if (c == "\047" || c == "\"" || c == "\\") { quoted = 1; p++; continue }
        d = d c; p++
    }
    hn++; hd[hn] = d; hs[hn] = strip; hq[hn] = quoted
}
function hdexpand(t,   ss, pp, nn, c) {
    ss = s; pp = p; nn = n; s = t; p = 1; n = length(t)
    newlevel()
    while (p <= n) {
        c = substr(s, p, 1)
        if (c == "\\") { p += 2; continue }
        if (c == "`") { p++; backtick(); continue }
        if (c == "$") { dollar(); continue }
        p++
    }
    dep--
    s = ss; p = pp; n = nn
}
function heredocs(   i, body, line, k, rest, cmp, t) {
    for (i = 1; i <= hn; i++) {
        body = ""
        while (p <= n) {
            rest = substr(s, p); k = index(rest, "\n")
            if (k) { line = substr(rest, 1, k - 1); p += k } else { line = rest; p = n + 1 }
            cmp = line
            if (hs[i]) sub(/^\t+/, "", cmp)
            if (cmp == hd[i]) break
            body = body line "\n"
        }
        if (!hq[i]) hdexpand(body)
        t = body; gsub(/\n/, "\036", t)
        out("H:" (hq[i] ? "q" : "u") ":" t)
    }
    hn = 0
}
function redir(   c) {
    if (inw[dep] && !qt[dep] && !dyn[dep] && wd[dep] ~ /^[0-9]+$/) { wd[dep] = ""; inw[dep] = 0 }
    else flushw()
    c = substr(s, p, 1)
    if (c == "<" && substr(s, p + 1, 1) == "<") {
        if (substr(s, p + 2, 1) == "<") { p += 3; out("R"); return }
        heredoc_start(); return
    }
    p++
    if (substr(s, p, 1) == "(") { p++; subst(")"); flushw(); return }
    while (p <= n && substr(s, p, 1) ~ /[>&|]/) p++
    out("R")
}
function parse(stop,   c, c2, cnt) {
    cnt = 0
    while (p <= n) {
        c = substr(s, p, 1)
        if (c == "\\") {
            c2 = substr(s, p + 1, 1)
            if (c2 == "\n") { p += 2; continue }
            qt[dep] = 1; addc(c2); p += 2; continue
        }
        if (c == "\047") {
            p++; k = index(substr(s, p), "\047"); qt[dep] = 1; inw[dep] = 1
            if (!k) { err = 1; addc(substr(s, p)); p = n + 1; break }
            wd[dep] = wd[dep] substr(s, p, k - 1); p += k; continue
        }
        if (c == "\"") { p++; dquote(); continue }
        if (c == "`") { p++; backtick(); continue }
        if (c == "$") { dollar(); continue }
        if (c == " " || c == "\t" || c == "\r") { flushw(); p++; continue }
        if (c == "\n") { p++; flushw(); heredocs(); out("S"); continue }
        if (c == "#" && !inw[dep]) { while (p <= n && substr(s, p, 1) != "\n") p++; continue }
        if (c == ";" || c == "|") { flushw(); out("S"); p++; continue }
        if (c == "&") {
            if (substr(s, p + 1, 1) == ">") { p++; redir(); continue }
            flushw(); out("S"); p++; continue
        }
        if (c == "(") { flushw(); out("S"); cnt++; p++; continue }
        if (c == ")") {
            p++
            if (cnt == 0 && stop == ")") return
            flushw(); out("S"); if (cnt > 0) cnt--; continue
        }
        if (c == "}" && stop == "}") { p++; return }
        if (c == "<" || c == ">") { redir(); continue }
        addc(c); p++
    }
    if (stop != "") err = 1
}
{ s = (NR > 1) ? s "\n" $0 : $0 }
END {
    n = length(s); p = 1; dep = 0; buf[0] = ""; extra = ""; hn = 0; err = 0
    parse("")
    flushw()
    if (hn) heredocs()
    out("S")
    printf "%s%s", buf[0], extra
    if (err) print "E"
}
'

# repo_git <dir> <git args...>: git in <dir>, with the -C/--git-dir/--work-tree
# options of the git command being checked (GOPTS, already quoted).
repo_git() {
    rg_dir=$1
    shift
    eval "git -C \"\$rg_dir\" $GOPTS \"\$@\"" 2>/dev/null
}

# Directories the command may run git in that are git repositories.
valid_cands() {
    for vc in $CANDS; do
        [ -d "$vc" ] && repo_git "$vc" rev-parse --git-dir >/dev/null 2>&1 && printf '%s\n' "$vc"
    done
}

is_tag_any() {
    [ -n "$1" ] || return 1
    for tc in $(valid_cands); do
        repo_git "$tc" show-ref --verify --quiet "refs/tags/$1" && return 0
    done
    return 1
}

flag() { FLAGS="$FLAGS$nl$1"; }

# child <command text>: check a nested command (sh -c, eval, heredoc to a shell).
child() {
    child_out=$(scan "$1" $((DEPTH + 1))) || exit 2
    FLAGS="$FLAGS$nl$child_out"
}

# check_target <branch> <is-delete>
check_target() {
    ct=$1
    case $ct in refs/heads/*) ct=${ct#refs/heads/} ;; heads/*) ct=${ct#heads/} ;; esac
    ctl=$(lower "$ct")
    case $ctl in master | dev) deny "git push to $ctl." ;; esac
    if [ "$PL_LEASE" = 1 ]; then
        case $ct in issue-*) ;; *) deny "--force-with-lease is only allowed on issue-* branches (target: $ct)." ;; esac
    fi
    if [ "$2" = 1 ] || [ "$PL_DEL" = 1 ]; then
        case $ct in issue-*) ;; *) deny "deleting a remote branch is only allowed for issue-* branches (target: $ct)." ;; esac
    fi
}

# The current branch of every repository the command may run in.
head_targets() {
    flag pushhead
    for hc in $(valid_cands); do
        hb=$(repo_git "$hc" symbolic-ref --short -q HEAD)
        [ -n "$hb" ] || deny "git push from a detached HEAD cannot be checked; name the branch."
        check_target "$hb" 0
    done
}

check_refspec() {
    cr=$1
    case $cr in +*) PL_FORCE=1; cr=${cr#+} ;; esac
    case $cr in *'*'* | *'?'* | *'['*)
        deny "git push with a wildcard refspec ($1) can update master, dev, or tags." ;;
    esac
    case $cr in
        *:*) src=${cr%%:*}; dst=${cr#*:} ;;
        *) src=$cr; dst="" ;;
    esac
    [ -n "$src$dst" ] || deny "git push ':' pushes every matching branch."
    for cx in "$src" "$dst"; do
        case $cx in *refs/tags/* | tags/*) deny "git push of a tag ($1)." ;; esac
    done
    if is_tag_any "$src" || is_tag_any "$dst"; then deny "git push of a tag ($1)."; fi
    if [ -n "$dst" ]; then
        case $(lower "$dst") in head | @) deny "git push to the remote HEAD ($1) cannot be checked; name the branch." ;; esac
        if [ -z "$src" ]; then check_target "$dst" 1; else check_target "$dst" 0; fi
        return
    fi
    case $(lower "$src") in head | @) head_targets; return ;; esac
    case $src in *'~'* | *'^'* | *'@{'*) deny "give git push an explicit destination for $1." ;; esac
    check_target "$src" 0
}

# check_push <words after "push">
check_push() {
    flag push
    PL_FORCE=0 PL_LEASE=0 PL_DEL=0
    nofollow=0 remote_seen=0 endopt=0 refspecs="" optvals=""
    while [ $# -gt 0 ]; do
        case $1 in d:*) deny "git push with a computed argument cannot be checked; spell out the remote and branch." ;; esac
        a=${1#?:}
        shift
        if [ "$endopt" = 0 ]; then
            case $a in
                --)
                    endopt=1
                    continue
                    ;;
                --no-*)
                    n=${a#--no-}
                    n=${n%%=*}
                    abbrev "$n" follow-tags && nofollow=1
                    continue
                    ;;
                --*)
                    n=${a#--}
                    n=${n%%=*}
                    if abbrev "$n" tags || abbrev "$n" follow-tags; then
                        deny "git push $a pushes tags."
                    elif abbrev "$n" all || abbrev "$n" mirror || abbrev "$n" branches || abbrev "$n" prune; then
                        deny "git push $a can update or delete master, dev, or tags."
                    elif [ ${#n} -ge 7 ] && { abbrev "$n" force-with-lease || abbrev "$n" force-if-includes; }; then
                        PL_LEASE=1
                    elif abbrev "$n" force; then
                        PL_FORCE=1
                    elif abbrev "$n" delete; then
                        PL_DEL=1
                    else
                        case $a in
                            *=*) ;;
                            *)
                                if abbrev "$n" repo || abbrev "$n" receive-pack || abbrev "$n" exec \
                                    || abbrev "$n" push-option || abbrev "$n" recurse-submodules; then
                                    if [ $# -gt 0 ]; then
                                        case $1 in d:*) deny "git push with a computed argument cannot be checked." ;; esac
                                        optvals="$optvals${1#?:}$nl"
                                        shift
                                    fi
                                fi
                                ;;
                        esac
                    fi
                    continue
                    ;;
                -?*)
                    c=${a#-}
                    while [ -n "$c" ]; do
                        ch=${c%"${c#?}"}
                        c=${c#?}
                        case $ch in
                            f) PL_FORCE=1 ;;
                            d) PL_DEL=1 ;;
                            o)
                                if [ -n "$c" ]; then
                                    optvals="$optvals$c$nl"
                                elif [ $# -gt 0 ]; then
                                    case $1 in d:*) deny "git push with a computed argument cannot be checked." ;; esac
                                    optvals="$optvals${1#?:}$nl"
                                    shift
                                fi
                                c=""
                                ;;
                        esac
                    done
                    continue
                    ;;
            esac
        fi
        if [ "$remote_seen" = 0 ]; then
            remote_seen=1
            continue
        fi
        refspecs="$refspecs$a$nl"
    done

    # Option values are not refspecs, but fail closed on protected names.
    for ov in $optvals; do
        case $(lower "$ov") in master | dev | refs/heads/master | refs/heads/dev | *refs/tags/*)
            deny "git push option value '$ov' names a protected ref." ;;
        esac
    done

    if [ -z "$refspecs" ]; then
        [ "$PL_DEL" = 0 ] || deny "git push --delete needs a branch name."
        head_targets
        for ic in $(valid_cands); do
            hb=$(repo_git "$ic" symbolic-ref --short -q HEAD)
            pd=$(lower "$(repo_git "$ic" config --get push.default)")
            case $pd in
                '' | simple | current | nothing) ;;
                upstream | tracking)
                    m=$(repo_git "$ic" config --get "branch.$hb.merge")
                    [ -z "$m" ] || check_target "$m" 0
                    ;;
                *) deny "push.default=$pd can push master or dev; name the branch: git push origin <issue-branch>." ;;
            esac
            if repo_git "$ic" config --get-regexp '^remote\..*\.(push|mirror)$' >/dev/null; then
                deny "a remote.<name>.push or .mirror setting decides what a bare git push updates; name the branch."
            fi
        done
    else
        for r in $refspecs; do check_refspec "$r"; done
    fi

    [ "$PL_FORCE" = 0 ] || deny "force push (--force, -f, or +refspec). Use --force-with-lease on an issue-* branch."

    if [ "$nofollow" = 0 ]; then
        for fc in $(valid_cands); do
            if [ "$(repo_git "$fc" config --bool --get push.followTags)" = true ]; then
                deny "push.followTags is set, so git push would also push tags. Add --no-follow-tags."
            fi
        done
    fi
}

# Git builtins that are never looked up as aliases.
is_builtin() {
    case $1 in
        add | am | annotate | apply | archive | bisect | blame | branch | bundle | cat-file | check-ignore \
            | checkout | cherry | cherry-pick | clean | clone | commit | config | count-objects | describe \
            | diff | difftool | fetch | for-each-ref | format-patch | fsck | gc | grep | hash-object | help \
            | init | log | ls-files | ls-remote | ls-tree | merge | merge-base | mergetool | mv | notes \
            | pull | push | range-diff | rebase | reflog | remote | repack | replace | reset | restore \
            | revert | rev-list | rev-parse | rm | shortlog | show | show-branch | show-ref \
            | sparse-checkout | stash | status | submodule | switch | symbolic-ref | tag | update-index \
            | update-ref | var | verify-commit | verify-tag | version | whatchanged | worktree | write-tree)
            return 0
            ;;
    esac
    return 1
}

# git_cmd <words after "git">
git_cmd() {
    GOPTS=""
    risky=""
    caliases=""
    execp=0
    while [ $# -gt 0 ]; do
        case $1 in d:*)
            has_push "$CMD" && deny "a git command with a computed subcommand or option cannot be checked."
            return 0
            ;;
        esac
        w=${1#?:}
        case $w in
            -C | --git-dir | --work-tree)
                [ $# -ge 2 ] || return 0
                case $2 in d:*)
                    has_push "$CMD" && deny "git $w with a computed path cannot be checked."
                    return 0
                    ;;
                esac
                GOPTS="$GOPTS $w $(q "${2#?:}")"
                shift 2
                ;;
            --git-dir=* | --work-tree=*)
                GOPTS="$GOPTS $(q "$w")"
                shift
                ;;
            -c | --config-env)
                [ $# -ge 2 ] || return 0
                kv=${2#?:}
                shift 2
                k=$(lower "${kv%%=*}")
                case $k in
                    alias.*) caliases="$caliases${k#alias.}=${kv#*=}$nl" ;;
                    push.* | remote.* | branch.* | include.* | includeif.*) risky="$risky $k" ;;
                esac
                ;;
            --config-env=*)
                kv=${w#--config-env=}
                shift
                k=$(lower "${kv%%=*}")
                case $k in
                    alias.*) deny "git --config-env $k defines an alias the guard cannot see." ;;
                    push.* | remote.* | branch.* | include.* | includeif.*) risky="$risky $k" ;;
                esac
                ;;
            --exec-path=*)
                execp=1
                shift
                ;;
            --namespace | --super-prefix)
                shift
                [ $# -gt 0 ] && shift
                ;;
            -*) shift ;;
            *) break ;;
        esac
    done
    [ $# -gt 0 ] || return 0
    sub=$(lower "${1#?:}")
    shift

    # Resolve aliases (git -c alias.x=..., or alias.x in git config).
    hops=0
    while ! is_builtin "$sub" && [ "$hops" -lt 5 ]; do
        av=""
        for ca in $caliases; do
            case $ca in "$sub="*) av=${ca#*=} ;; esac
        done
        if [ -z "$av" ]; then
            for ac in $(valid_cands); do
                av=$(repo_git "$ac" config --get "alias.$sub")
                [ -n "$av" ] && break
            done
        fi
        [ -n "$av" ] || break
        has_push "$av" && deny "git alias '$sub' runs push; use git push directly."
        case $av in
            '!'*)
                child "${av#!}"
                return 0
                ;;
        esac
        sub=$(lower "${av%%[ 	]*}")
        hops=$((hops + 1))
    done

    case $sub in
        push)
            [ -z "$risky" ] || deny "git -c$risky with git push can change what it pushes."
            [ "$execp" = 0 ] || deny "git --exec-path with git push cannot be checked."
            check_push "$@"
            ;;
        switch | checkout | symbolic-ref) flag stateH ;;
        update-ref | init | clone | replace) flag stateA ;;
        config)
            ro=0
            for ca in "$@"; do
                case ${ca#?:} in --get* | -l | --list | get | list | --show-* | --name-only) ro=1 ;; esac
            done
            [ "$ro" = 1 ] || flag stateA
            ;;
        tag)
            ro=1
            for ca in "$@"; do
                case ${ca#?:} in -l | --list | -v | --verify) ro=1; break ;; -*) ;; *) ro=0 ;; esac
            done
            [ "$ro" = 1 ] || flag stateA
            ;;
        remote)
            for ca in "$@"; do
                case ${ca#?:} in
                    -*) ;;
                    add | rename | remove | rm | set-head | set-branches | set-url | prune) flag stateA; break ;;
                    *) break ;;
                esac
            done
            ;;
        branch)
            for ca in "$@"; do
                case ${ca#?:} in
                    --show-current | -a | --all | -r | --remotes | -v | -vv | --verbose | -l | --list \
                        | --contains* | --no-contains* | --merged* | --no-merged* | --format* | --sort* \
                        | --points-at* | --column* | --no-column | --color* | --no-color) ;;
                    *) flag stateH; break ;;
                esac
            done
            ;;
        rebase | bisect | submodule | filter-branch | difftool | mergetool)
            for ca in "$@"; do
                has_push "${ca#?:}" && deny "git $sub running a push cannot be checked; run git push directly."
            done
            ;;
    esac
}

# segment <mode>: check one simple command (words in SEG_WORDS, heredoc bodies
# in SEG_HDS). Mode "cd" only follows directory changes; "check" does the rest.
segment() {
    mode=$1
    set -- $SEG_WORDS
    # Skip assignments, keywords, and wrappers that run the next word.
    while [ $# -gt 0 ]; do
        w=${1#?:}
        case $w in
            *=*)
                nm=${w%%=*}
                case $nm in '' | [0-9]* | *[!A-Za-z0-9_]*) break ;; esac
                shift
                continue
                ;;
            if | then | else | elif | do | done | fi | while | until | '!' | '{' | '}' | '[[' | time | nohup \
                | builtin | exec | command)
                shift
                while [ $# -gt 0 ]; do
                    case ${1#?:} in --) shift; break ;; -?*) shift ;; *) break ;; esac
                done
                continue
                ;;
            nice)
                shift
                while [ $# -gt 0 ]; do
                    case ${1#?:} in -n) shift; [ $# -gt 0 ] && shift ;; -?*) shift ;; *) break ;; esac
                done
                continue
                ;;
            env)
                shift
                while [ $# -gt 0 ]; do
                    case ${1#?:} in
                        -u | --unset) shift; [ $# -gt 0 ] && shift ;;
                        -C | --chdir) CD_UNK=1; shift; [ $# -gt 0 ] && shift ;;
                        -C* | --chdir=*) CD_UNK=1; shift ;;
                        -S* | --split-string*)
                            [ "$mode" = check ] && has_push "$CMD" && deny "env -S with a push cannot be checked."
                            return 0
                            ;;
                        --) shift; break ;;
                        -?*) shift ;;
                        *) break ;;
                    esac
                done
                continue
                ;;
        esac
        break
    done
    [ $# -gt 0 ] || return 0

    cmddyn=0
    case $1 in d:*) cmddyn=1 ;; esac
    cw=${1#?:}
    shift
    base=${cw##*/}
    base=${base##*\\}
    base=$(lower "$base")
    base=${base%.exe}

    if [ "$mode" = cd ]; then
        case $base in
            cd | pushd)
                while [ $# -gt 0 ]; do
                    case ${1#?:} in -[LPe@]) shift ;; --) shift; break ;; *) break ;; esac
                done
                if [ $# -eq 0 ]; then
                    tgt=$HOME
                else
                    case $1 in d:*) CD_UNK=1; return 0 ;; esac
                    tgt=${1#?:}
                fi
                case $tgt in
                    -) CD_UNK=1; return 0 ;;
                    '~') tgt=$HOME ;;
                    '~/'*) tgt=$HOME/${tgt#'~/'} ;;
                    '~'*) CD_UNK=1; return 0 ;;
                esac
                case $tgt in
                    /* | [A-Za-z]:[\\/]*) CANDS="$CANDS$nl$tgt" ;;
                    *)
                        newc=""
                        for oc in $CANDS; do newc="$newc$nl$oc/$tgt"; done
                        CANDS="$CANDS$newc"
                        ;;
                esac
                ;;
        esac
        return 0
    fi

    if [ "$cmddyn" = 1 ]; then
        has_push "$CMD" && deny "a command whose name is computed cannot be checked for a git push."
        return 0
    fi

    case $base in
        git)
            git_cmd "$@"
            return 0
            ;;
        git-push)
            GOPTS=""
            check_push "$@"
            return 0
            ;;
        sh | bash | dash | zsh | ksh | mksh | ash)
            hasc=0
            while [ $# -gt 0 ]; do
                case ${1#?:} in
                    --) shift; break ;;
                    --*) shift ;;
                    -o | +o | -O | +O) shift; [ $# -gt 0 ] && shift ;;
                    [-+]*c*) hasc=1; shift; break ;;
                    [-+]*) shift ;;
                    *) break ;;
                esac
            done
            if [ "$hasc" = 1 ]; then
                [ $# -gt 0 ] || return 0
                case $1 in d:*)
                    has_push "$CMD" && deny "a shell running a computed script cannot be checked for a git push."
                    ;;
                esac
                child "${1#?:}"
            elif [ $# -eq 0 ]; then
                if [ -n "$SEG_HDS" ]; then
                    for hb in $SEG_HDS; do
                        child "$(printf '%s' "${hb#?:}" | tr '\036' '\n')"
                    done
                else
                    has_push "$CMD" && deny "commands piped into a shell cannot be checked for a git push."
                fi
            fi
            return 0
            ;;
        eval)
            joined=""
            for ew in "$@"; do
                case $ew in d:*) has_push "$CMD" && deny "eval of a computed string cannot be checked for a git push." ;; esac
                joined="$joined ${ew#?:}"
            done
            child "$joined"
            return 0
            ;;
        gh)
            [ "${1#?:}" = alias ] && has_push "$CMD" && deny "a gh alias that runs a push cannot be checked."
            return 0
            ;;
        echo | printf | cat | grep | egrep | fgrep | rg | jq | test | '[' | true | false | : | ls | head \
            | tail | wc | sort | uniq | tr | cut | tee | mkdir | touch | rm | cp | mv | diff | less | more \
            | sleep | pwd | which | type | cmp | basename | dirname | date | stat | file | realpath \
            | readlink | export | unset | set | read | exit | return | shift | wait | printenv | popd | cd \
            | pushd)
            return 0
            ;;
    esac

    # Any other program: deny if it could run a git push we cannot see.
    sawgit=0
    for gw in "$@"; do
        w=${gw#?:}
        b=${w##*/}
        b=${b##*\\}
        b=$(lower "$b")
        b=${b%.exe}
        case $b in
            git) sawgit=1 ;;
            git-push) deny "git push run through $base cannot be checked; run git push directly." ;;
        esac
        if [ "$sawgit" = 1 ] && [ "$(lower "$w")" = push ]; then
            deny "git push run through $base cannot be checked; run git push directly."
        fi
        case $w in *[Gg][Ii][Tt][!A-Za-z0-9_]*[Pp][Uu][Ss][Hh]*)
            deny "a git push run by $base cannot be checked; run git push directly." ;;
        esac
    done
    for hb in $SEG_HDS; do
        case $hb in *[Gg][Ii][Tt][!A-Za-z0-9_]*[Pp][Uu][Ss][Hh]*)
            deny "a git push run by $base cannot be checked; run git push directly." ;;
        esac
    done
}

# walk <tokens> <mode>
walk() {
    SEG_WORDS=""
    SEG_HDS=""
    skip=0
    for tok in $1; do
        case $tok in
            S)
                [ -z "$SEG_WORDS" ] || segment "$2"
                SEG_WORDS=""
                SEG_HDS=""
                skip=0
                ;;
            R) skip=1 ;;
            H:*) SEG_HDS="$SEG_HDS${tok#H:}$nl" ;;
            [sd]:*)
                if [ "$skip" = 1 ]; then
                    skip=0
                else
                    SEG_WORDS="$SEG_WORDS$tok$nl"
                fi
                ;;
        esac
    done
}

# scan <command> <depth>: check a command; print flags (push, pushhead,
# stateA, stateH, cdunknown) on stdout. Denies exit 2.
scan() {
    DEPTH=$2
    FLAGS=""
    [ "$DEPTH" -le 4 ] || deny "commands nested too deeply to check."
    toks=$(printf '%s' "$1" | awk "$TOKENIZER") || deny "could not tokenize the command."
    case $toks in E | *"${nl}E")
        has_push "$1" && deny "unbalanced quotes or parentheses in a command that mentions push."
        ;;
    esac
    walk "$toks" cd
    walk "$toks" check
    [ "$CD_UNK" = 0 ] || flag cdunknown
    printf '%s\n' "$FLAGS"
}

flags=$(scan "$cmd" 0) || exit 2
flags="$nl$flags$nl"

case $flags in *"${nl}push$nl"*)
    case $cmd in *GIT_* | *.git/* | *'.git\'*)
        deny "a git push combined with GIT_* variables or .git/ edits cannot be checked; run git push on its own." ;;
    esac
    case $flags in *"${nl}stateA$nl"*)
        deny "this command changes git tags, refs, remotes, or config and also pushes; run git push on its own." ;;
    esac
    case $flags in *"${nl}cdunknown$nl"*)
        deny "this command changes to a directory the guard cannot follow and also pushes; run git push on its own." ;;
    esac
    case $flags in *"${nl}pushhead$nl"*)
        case $flags in *"${nl}stateH$nl"*)
            deny "this command switches branches and pushes without naming the branch; run git push origin <issue-branch> on its own." ;;
        esac
        ;;
    esac
    ;;
esac

exit 0
