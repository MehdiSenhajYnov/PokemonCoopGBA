---
name: CreateSkill
description: Create a new Claude Code skill in .claude/skills/. Use when the user wants to create a reusable slash command.
---

# CreateSkill - Create a Skill

You are tasked with creating a NEW skill in `.claude/skills/` based on the user's description: $ARGUMENTS

**CRITICAL RULES:**
1. **You are creating a `SKILL.md` file in `.claude/skills/{SkillName}/`. That is your ONLY output.**
2. **Do NOT execute the task described by the user. Do NOT run any commands related to the task content.**
3. **Do NOT modify source code, do NOT run builds, do NOT run git commands.**
4. **The ONLY files you may create are inside `.claude/skills/` directory.**

---

## Step 1: Understand what the user wants

Parse `$ARGUMENTS` to determine:
- **Skill name**: the slash command name (PascalCase, e.g., `RunTests`, `DeployStaging`)
- **Purpose**: what the skill should do when invoked later
- **Scope**: is it a simple utility or a complex multi-step procedure?

If the description is ambiguous, ask the user to clarify before creating anything.

---

## Step 2: Explore context if needed

- If the skill relates to project code (e.g., "run tests", "lint backend"), read the relevant files to reference real paths, real commands, real tool names
- If the skill is generic (e.g., "git update", "clear cache"), no exploration needed
- **REMINDER: You are only gathering info to WRITE the skill file. Do NOT execute anything.**

---

## Step 3: Write the skill file

Create `.claude/skills/{SkillName}/SKILL.md` following this structure:

```markdown
---
name: SkillName
description: Brief description of what this skill does. Used by Claude to know when to suggest it.
---

# SkillName - Short Description

You are tasked with [what this skill does]. Optional user context: $ARGUMENTS

**IMPORTANT: [Any critical constraints, e.g., "Do NOT modify source code"]**

---

## Step 1: [First action]

[Clear instructions for what to do]

---

## Step 2: [Second action]

[Clear instructions]

---

## Step N: [Final action]

[Clear instructions including confirmation/output to show the user]
```

### Writing guidelines:

- **Write as instructions TO Claude** — the file is a prompt that Claude will follow when the skill is invoked
- **Always include YAML frontmatter** with `name:` and `description:` fields
- **Use `$ARGUMENTS`** to accept optional user input (e.g., custom message, file filter, target)
- **Be explicit about constraints** — if the skill should NOT do something, say it clearly and early
- **Include safety checks** where appropriate (e.g., check for sensitive files before git operations)
- **End with a confirmation step** — the user should always see a summary of what was done
- **Keep it concise** — skills should be focused, not 500-line essays

### Optional frontmatter fields:

- `disable-model-invocation: true` — only the user can invoke this skill (for skills with side effects like deploy, send notifications)
- `context: fork` — run the skill in an isolated context (useful for heavy skills that shouldn't pollute the main conversation)
- `allowed-tools: [Bash, Read, Glob]` — restrict which tools the skill can use

---

## Step 4: Confirm

Tell the user:
- The file path created: `.claude/skills/{SkillName}/SKILL.md`
- How to invoke it: `/{SkillName}` or `/{SkillName} <arguments>`
- A 1-line summary of what it does

**STOP HERE. Do not do anything else.**
