# Dependency security status

Last reviewed: 2026-11-17

## Tracked development-tool advisory

The frontend lockfile currently resolves `picomatch@4.0.7` through the Vite/Vitest toolchain. GitHub Advisory `GHSA-fc5q-39xc-vjpf` describes a high-severity ReDoS in single-branch repeated extglob handling and currently lists affected versions as `<=4.0.7`, with **no patched version published**.

The affected dependency is reachable through frontend build/test tooling in `devDependencies`; it is not part of the shipped browser runtime dependency graph. This is a temporary, explicitly tracked development-tool exception, not a claim that the vulnerable package is fixed.

## CI enforcement

- `npm audit --omit=dev --audit-level=high` remains blocking for the production dependency graph.
- The full development dependency audit is still executed.
- The only accepted development-tool advisory is `GHSA-fc5q-39xc-vjpf`; any different advisory, severity, or additional package-level advisory fails CI.
- Remove this exception as soon as upstream publishes a version outside the affected range and the lockfile resolves to it. Do not force an unpatched or breaking version just to make the audit green.

The exception does not authorize adding `picomatch` to production dependencies or feeding attacker-controlled glob patterns into build tooling.
