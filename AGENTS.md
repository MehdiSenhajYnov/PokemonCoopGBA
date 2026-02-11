# Repository Guidelines

## Project Structure & Module Organization
- `client/`: mGBA Lua runtime (`main.lua` entry, modules like `hal.lua`, `network.lua`, `render.lua`, `battle.lua`).
- `server/`: Node TCP relay (`server.js`, `test-connection.js`, `package.json`).
- `config/`: ROM-specific profiles loaded by the client.
- `docs/`: testing and reverse-engineering notes (`TESTING.md`, `MEMORY_GUIDE.md`).
- `scripts/`: helper scripts and diagnostics; `archive/` contains retired scanners.
- `rom/`, `mgba/`, `ghidra_*`, `refs/`: local runtime/tooling assets; avoid committing generated files from these areas.

## Build, Test, and Development Commands
- `cd server && npm install`: install Node.js 18+ dependencies.
- `cd server && npm start`: run the TCP relay (`server.js`) on default `PORT` (currently `3333` unless overridden).
- `cd server && npm run dev`: run the server in watch mode for local development.
- `cd server && npm test`: execute `test-connection.js` TCP smoke test (start server first).
- mGBA loop: load `client/main.lua` from `Tools > Scripting` and verify overlay/connectivity.

## Coding Style & Naming Conventions
- Use 2-space indentation in both Lua and JavaScript.
- Lua modules use `lower_snake_case` filenames (example: `run_and_bun.lua`).
- JavaScript uses `camelCase` for functions/variables and `UPPER_SNAKE_CASE` for constants (example: `HEARTBEAT_INTERVAL`).
- Keep protocol messages as explicit JSON objects with a `type` field and typed payloads.
- Prefer small, focused modules over adding large blocks to `client/main.lua` or `server/server.js`.

## Testing Guidelines
- Follow `docs/TESTING.md` for current phase checks and multiplayer validation.
- For network changes, run `npm test` and verify register/join/position flow.
- For gameplay/rendering changes, validate with two mGBA instances and confirm ghost sync behavior.
- No coverage gate exists yet; include manual verification evidence in each PR.

## Commit & Pull Request Guidelines
- Recent history mainly uses concise Conventional Commit subjects (`feat: ...`, `fix: ...`); keep this format.
- Scope commits by subsystem (`client`, `server`, `docs`) and keep unrelated changes separate.
- PRs should include: summary, impacted ROM/config, exact test steps run, and screenshots/log snippets for UI or sync changes.
- Reference related task or issue IDs when available.
