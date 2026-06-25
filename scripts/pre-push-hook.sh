#!/bin/sh
# Pre-push gate. Install with:  cp scripts/pre-push-hook.sh .git/hooks/pre-push && chmod +x .git/hooks/pre-push
# Three layers:
#   1. ruff — lints the Python for real bugs (undefined names, unused imports,
#      bad f-strings). BLOCKS on a hit so broken imports can't be pushed.
#   2. gitleaks — scans the commits being pushed for secrets. BLOCKS on a hit.
#   3. Claude security review — semantic review of the diff. ADVISORY (never
#      blocks). Runs only on INTERACTIVE pushes (skipped when there's no TTY).
#
# Override the gates in a true emergency with:  git push --no-verify
z40=0000000000000000000000000000000000000000
fail=0

# --- Layer 1: ruff lint (blocking) ------------------------------------------
RUFF=""
if [ -x ".venv/bin/ruff" ]; then RUFF=".venv/bin/ruff"
elif command -v ruff >/dev/null 2>&1; then RUFF="ruff"; fi
if [ -n "$RUFF" ]; then
    if ! "$RUFF" check . >&2; then
        echo "" >&2
        echo "❌ ruff found lint errors — PUSH BLOCKED. Fix them (or run '$RUFF check . --fix')." >&2
        echo "   To override (discouraged): git push --no-verify" >&2
        fail=1
    fi
else
    echo "⚠  ruff not installed — skipping lint (pip install ruff)" >&2
fi

# --- Layer 2: gitleaks secret scan (blocking) -------------------------------
while read -r local_ref local_sha remote_ref remote_sha; do
    [ "$local_sha" = "$z40" ] && continue                 # deleting a remote ref
    if [ "$remote_sha" = "$z40" ]; then
        logopts="$local_sha"                              # new branch: all commits
    else
        logopts="$remote_sha..$local_sha"                 # just the new commits
    fi

    if command -v gitleaks >/dev/null 2>&1; then
        if ! gitleaks git --no-banner --redact --exit-code 1 \
                          --log-opts="$logopts" . 2>&1; then
            echo "" >&2
            echo "❌ gitleaks found a potential secret in the commits being pushed — PUSH BLOCKED." >&2
            echo "   Inspect the finding above. If it is a real key, remove it from history." >&2
            echo "   To override (discouraged): git push --no-verify" >&2
            fail=1
        fi
    else
        echo "⚠  gitleaks not installed — skipping secret scan (brew install gitleaks)" >&2
    fi
done

[ "$fail" = 1 ] && exit 1

# --- Layer 3: advisory AI review, interactive pushes only -------------------
if [ -t 2 ] && command -v claude >/dev/null 2>&1; then
    diff=$(git diff '@{push}' 2>/dev/null || git diff 'HEAD~3' 2>/dev/null)
    if [ -n "$diff" ]; then
        echo "🔎 Claude security review (advisory — push proceeds either way)…" >&2
        printf '%s' "$diff" | claude -p \
"Security-review this git diff. Flag ONLY real vulnerabilities: injection (SQL/command/template), \
hardcoded secrets, auth/authz flaws, SSRF, path traversal, unsafe deserialization, XSS, or unsafe \
subprocess/eval. For each finding give: SEVERITY, file, one-line issue, one-line fix. If there are \
none, reply exactly 'No security issues found.' Be concise." \
            --tools "" >&2 2>/dev/null || true
        echo "" >&2
    fi
fi
exit 0
