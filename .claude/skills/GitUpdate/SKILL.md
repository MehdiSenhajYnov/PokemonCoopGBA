---
name: GitUpdate
description: Git add, commit and push with auto-generated commit message. Use when the user wants to commit and push changes.
---

# GitUpdate - Git Add, Commit & Push

You are tasked with staging all changes, creating a commit with an auto-generated message, and pushing to the remote. Optional user context: $ARGUMENTS

**IMPORTANT: This command performs git operations. Do NOT modify any source code, documentation, or task files.**

---

## Step 1: Assess current state

Run these commands in parallel:
- `git status` — see all modified, added, and deleted files
- `git diff --stat` — summary of changes
- `git log --oneline -5` — recent commit style reference
- `git branch --show-current` — current branch name

---

## Step 2: Safety checks

Before staging:
1. **Check for sensitive files** in the untracked/modified list. NEVER stage:
   - `.env*`, `*.credentials*`, secrets, API keys
   - `data/` directory (runtime data: profiles, cache, logs)
   - `TestSounds/` (local test audio files)
   - Any file > 50MB (binary blobs)
2. If any sensitive/large files are found, warn the user and exclude them
3. If there are NO changes at all (clean working tree), tell the user and stop

---

## Step 3: Stage all changes

- Run `git add -A` to stage everything
- If Step 2 identified files to exclude, unstage them with `git reset HEAD <file>`
- Run `git diff --cached --stat` to confirm what will be committed

---

## Step 4: Generate commit message

Analyze the staged changes to generate a descriptive commit message:

1. **Categorize changes** by looking at files modified:
   - Rust backend (`src-tauri/`) → code changes
   - Frontend (`src/`) → UI/store/hook changes
   - Config files (`Cargo.toml`, `package.json`, `tauri.conf.json`) → dependency/config changes
   - Documentation (`*.md`, `CLAUDE.md`) → docs changes
   - Task files (`Tasks/`, `.claude/`) → project management

2. **Choose prefix** based on dominant change type:
   - `feat:` — new functionality
   - `fix:` — bug fix
   - `refactor:` — code restructuring without behavior change
   - `perf:` — performance improvement
   - `docs:` — documentation only
   - `chore:` — maintenance, dependencies, config
   - `style:` — formatting, no code change

3. **Write message**: 1 line summary (max 72 chars). If changes span multiple categories, use the dominant one or `chore: sync changes`

4. If `$ARGUMENTS` contains a custom message, use that instead of auto-generating

---

## Step 5: Commit

Create the commit using a HEREDOC:

```bash
git commit -m "$(cat <<'EOF'
<prefix>: <generated or custom message>

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Step 6: Push

1. Push to remote: `git push origin <current-branch>`
2. If push fails because remote is ahead:
   - Tell the user
   - Ask if they want to `git pull --rebase` then retry
3. If push succeeds, confirm with the commit hash

---

## Step 7: Confirm

Run `git status` to verify clean working tree and show the user:
- Commit hash
- Commit message used
- Branch pushed to
- Number of files changed
