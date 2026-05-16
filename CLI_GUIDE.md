# Running Browser-Use from the CLI

Yes, `browser-use` can run entirely from the Command Line Interface (CLI) without requiring a visible browser UI (running headlessly). The `skills/browser-use` provides a robust method to call an entire agent prompt directly from the shell.

## Running a Complete Prompt from the CLI

You can pass a complete instruction prompt to the browser-use agent using the `run` command. By default, it will use a headless Chromium browser (so you won't see it running).

### Standard Execution
```bash
browser-use run "Your complete prompt/task goes here"
```
Example:
```bash
browser-use run "Go to github.com/browser-use/browser-use and find the number of stars"
```

### Remote / Cloud Execution
If you prefer to run the browser securely in the cloud rather than locally:
```bash
browser-use -b remote run "Your complete prompt/task goes here"
```

### Key CLI Features
- **Headless by default:** When using the CLI without the `--headed` flag, the browser runs silently in the background.
- **Persistent Sessions:** The CLI keeps the browser session active between commands, meaning you can execute tasks sequentially.
- **Monitoring Tasks:** If running remotely, you can monitor the status with:
  ```bash
  browser-use task status <task-id>
  ```

Ensure you have your LLM API keys (e.g., `BROWSER_USE_API_KEY` or `OPENAI_API_KEY`) set in your environment variables for the agent to work.
