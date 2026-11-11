# VILTARA SHOP frontend

## Local development

From this directory:

```bash
npm install
npm run dev
```

The Mini App can run with the public catalog without Telegram authentication. The Playwright E2E suite stubs the Telegram WebApp bridge and every `/api/**` request; it does not connect to a real Telegram account, backend, database, wallet or production secret.

## Playwright E2E

Install the Chromium browser used by the configured project:

```bash
npx playwright install chromium
```

Run the full browser suite:

```bash
npm run test:e2e
```

Open Playwright's interactive UI:

```bash
npm run test:e2e:ui
```

Run one spec or one named scenario:

```bash
npx playwright test e2e/marketplace.spec.ts
npx playwright test e2e/marketplace.spec.ts --grep "listing start_param"
```

Playwright starts Vite automatically through `webServer` in `playwright.config.ts`. By default it serves on `http://127.0.0.1:5173`; no backend service is needed.

## Reports and traces

After a run, open the HTML report:

```bash
npx playwright show-report
```

The report is written to `playwright-report/`. Test output, screenshots and retained-on-failure traces are written to `test-results/`. Open a trace archive with:

```bash
npx playwright show-trace test-results/<test-folder>/trace.zip
```

In GitHub Actions, the `playwright-diagnostics-*` artifact contains the HTML report and test-results directory, including traces/screenshots for failed browser tests.
