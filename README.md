# Physics assistant: slide bank + live Top Hat browser prototype

Python reads lecture slides into a local answer bank. A separate Chromium window
opens Top Hat for your manual login. The assistant reads visible multiple-choice
questions and shows matching prepared answers. An optional auto-selection mode
selects an exact, verified match. **Top Hat's interface says responses are auto-saved:
selecting can immediately record a response, without a Submit button.**

This prototype was tested locally against sanitized copies of your open, closed,
answered, and attendance HTML. It has not been tested against your authenticated
live Top Hat session. There is no AI solver: unmatched questions remain manual.

## Windows: download and run

1. Download the project ZIP and **extract it** to a normal folder, such as
   `Documents\TopHat`. Do not run scripts from inside the ZIP.
2. Install Python 3.12 from python.org, including the Python launcher and
   **Add Python to PATH**. VS Code is optional.
3. Double-click `setup_windows.cmd` once. It creates a private Python environment,
   installs the dependencies, downloads Chromium, and runs the basic tests.
   Keep the window open to read any errors. Internet access is needed for setup.
4. Double-click `dashboard_windows.cmd`. Keep its terminal window open, then open
   `http://127.0.0.1:5000` in your regular browser.
5. Upload PDF/PPTX lecture slides. Check the original wording and choices against
   the slides. Choose the correct answer **by full text**, enter its reasoning or
   equation, check **Verified by me**, and click **Save answer**.
6. Double-click `live_readonly_windows.cmd` for your first real-page test. In the
   Chromium window it opens, log in yourself, open your course, and select a question
   through normal Top Hat navigation. The terminal displays the extracted question,
   choices, match, and any reason it would decline automatic selection. This mode
   does not click an answer.
7. After confirming reading and matching, close that browser/program and launch
   `live_autoselect_windows.cmd` if you want auto-selection. Read its terminal
   output and verify the response in Top Hat. Ctrl+C stops the program. Close the
   previous assistant browser before launching another: both use the same profile.

The bank starts empty. You must prepare verified answers before auto-selection can
work. Marking an answer verified means **you checked it**, not that Python solved
it. No match is not an installation error; that question stays manual.

For VS Code, open the extracted folder, select `.venv` using **Python: Select
Interpreter**, and run equivalent commands from its terminal:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe -m physics_assistant.web
```

In a second terminal:

```powershell
# Read-only live reader
.\.venv\Scripts\python.exe -m physics_assistant.live
# Optional auto-selection; selecting may immediately save the response
.\.venv\Scripts\python.exe -m physics_assistant.live --auto-select
```

A course URL can be supplied with `--url https://app.tophat.com/...`. Reading and
selection are scoped to HTTPS `app.tophat.com`, including same-origin frames and
new tabs. Other login-provider pages are left alone while you log in manually.
Keep only one question tab open for auto-selection. No attendance codes are entered.

## What auto-selection will and won't do

- Requires normalized exact wording (case/whitespace normalization), the same full
  choice set ignoring order, one unique matching answer, and a verified bank entry.
- Waits for two matching observations, rechecks the current question before acting,
  and uses the actual radio button's accessible label from the page. Choice letters,
  numeric input values, and shuffled order do not determine the answer.
- Leaves closed, disabled, already selected, or saved responses alone. It never
  removes `disabled`, forces a click, or bypasses authentication/access restrictions.
- Leaves fuzzy matches, missing answers, ambiguous matches, detected visual prompts,
  attendance pages, and unrecognized layouts/save behavior for manual review.
- Attempts selection once per question per run. It checks for the selected control
  and **Response saved**. An unconfirmed result needs your inspection, not repeated
  automatic clicks. Browser/app changes can still race with automation.
- Watches the question you open manually. It does not automatically open each new
  question from the classroom list or answer questions that are not accessible.

The DOM adapter uses the observed `Content` article, `question-renderer-content-area`,
choice-group label, and radio-button labels from your October 2026 samples. It does
not use guessed selectors or generated style class suffixes. Different question types
or future Top Hat page changes may require another adapter. Diagrams encoded as CSS
or other unusual markup might not be detected; always check extracted text.

## Test before class

Use the dashboard's **Open classroom simulator** link after importing slides. Run
this in another terminal for the original simulator-only watcher:

```powershell
.\.venv\Scripts\python.exe -m physics_assistant.browser
```

Select a question in the launched simulator window. It opens in the same tab with
reversed choices. This watcher remains read-only.

Basic tests:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Full Chromium tests (including the Top Hat HTML fixtures):

```powershell
$env:RUN_BROWSER_TESTS='1'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Browser tests use local HTML and intercept fixture URLs; they **do not contact
Top Hat or submit real answers**. They cover live-DOM selection state, closed/saved
questions, shuffled choices, simulated save confirmation, attendance, changed
layouts, and refusing uncertain/unverified answers. The basic run deliberately
skips browser tests unless enabled.

When no question is available, the live reader waits; it may report an unsupported
panel on the course dashboard. An open question is needed for real selection testing.
If an open question produces `unsupported`, share that message and a redacted
question-container HTML excerpt. Do not share login cookies or profile files.

## Extraction and matching limitations

- pypdf/python-pptx extract selectable text. Questions need `?` or an explicit
  `Question`/`Q1` label. Options need A–H or 1–8 followed by a period/parenthesis
  (letters also allow a colon). Original extracted wording and full slide context
  are kept for review; titles, complex columns, and multiline options may be misparsed.
- Embedded images appear with the page's questions. PowerPoint vector diagrams are
  not rendered. Scanned PDFs need OCR, which is not included. The upload result lists
  pages with no recognized questions. Convert older `.ppt` files to `.pptx` first.
- Fuzzy text matches require 94/100 similarity and a 5-point lead over another
  candidate. This is a heuristic, not a probability that the answer is correct.
  Fuzzy results are displayed but never automatically selected.
- A slide title or wording change can prevent an exact match. Review the suggestion
  and answer manually in that case. The program does not invent answers.

## Local files and privacy

`data/bank.sqlite3` stores your questions/answers, `data/images` contains extracted
images, and `data/live-events.jsonl` logs question text and actions for troubleshooting.
Back up `data` to keep reviewed answers. `--no-log` disables the live event log.
`PHYSICS_DATA_DIR` can set the data folder; use the same value for the dashboard and
live reader. The browser session is in `.browser-profile`; keep it private. Delete
that folder to clear its saved login state. These files are ignored by Git and
excluded from the downloadable project package.

The dashboard binds only to localhost and uses a per-process write token. Do not
expose it publicly. Upload trusted files only (maximum 30 MB). No AI API keys needed.

## Cloud/Linux development

Use the existing `/workspace/TopHat` checkout; cloud tasks are already isolated.
Use `.venv/bin/python` instead of the Windows Python path. This cloud machine has
`/usr/bin/chromium`; the Playwright browser download was blocked by network policy,
so the full tests use the existing browser:

```bash
RUN_BROWSER_TESTS=1 CHROMIUM_EXECUTABLE=/usr/bin/chromium .venv/bin/python -m unittest discover -s tests -v
```

A visible desktop is required for the live manual-login session. Headless cloud
fixture tests do not establish real-account compatibility or Windows validation.
On a Linux desktop with system Chromium, use
`.venv/bin/python -m physics_assistant.live --executable-path /usr/bin/chromium`.
For managed browser installations on Linux, install required system dependencies
with `python -m playwright install --with-deps chromium` where supported.
