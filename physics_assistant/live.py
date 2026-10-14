"""Top Hat adapter based on user-supplied October 2026 HTML.

Reads visible multiple-choice questions. Optional selection can auto-save remotely.
No login automation, attendance entry, forced clicks, or automatic navigation.
"""
import argparse
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright, Error as PlaywrightError
from .bank import connect, records, match, normalize

ARTICLE = '[role="article"][aria-label="Content"]'
GROUP_LABEL = 'For the above question select one option that applies'

# Read the live DOM properties (checked/disabled), not only serialized attributes.
SNAPSHOT = r'''() => {
 const visible = e => !!(e.getClientRects().length) && getComputedStyle(e).visibility !== 'hidden';
 const articles = [...document.querySelectorAll('[role="article"][aria-label="Content"]')].filter(visible);
 if (articles.length !== 1) return {kind:'waiting',reason:'No single visible Content panel.'};
 const article=articles[0];
 if (article.querySelector('input[name="attendanceCode"]')) return {kind:'attendance',reason:'Attendance is manual.'};
 const groups=[...article.querySelectorAll('[role="group"]')].filter(e=>e.getAttribute('aria-label')==='For the above question select one option that applies' && visible(e));
 const areas=[...article.querySelectorAll('.question-renderer-content-area')].filter(visible);
 if(groups.length!==1 || areas.length!==1) return {kind:'unsupported',reason:'Expected one question text area and one single-choice group.'};
 const group=groups[0], area=areas[0];
 // In the supplied HTML the prompt precedes a direct child holding the choice block.
 const blocks=[...area.children].filter(e=>e.contains(group));
 if(blocks.length!==1) return {kind:'unsupported',reason:'Question and choice layout changed.'};
 const promptNodes=[...area.childNodes].slice(0,[...area.childNodes].indexOf(blocks[0]));
 const wording=promptNodes.map(e=>e.nodeType===3?e.textContent:(e.innerText||'')).join('\n').trim();
 const visualContent=promptNodes.some(e=>e.nodeType===1 && (e.matches('img,canvas,svg,math') || e.querySelector('img,canvas,svg,math')));
 const radios=[...group.querySelectorAll('input[type="radio"]')];
 if(!wording || radios.length<2 || group.querySelector('input:not([type="radio"])')) return {kind:'unsupported',reason:'Empty prompt or unsupported answer controls.'};
 const options=radios.map(e=>({label:e.getAttribute('aria-label')||'',value:e.value,
  checked:e.checked,enabled:!e.disabled && !e.closest('[aria-disabled="true"]') && !e.matches(':disabled'),visible:visible(e)}));
 const text=article.innerText;
 const closed=text.includes('Submission is closed');
 const saved=text.includes('Response saved');
 const autoSave=text.includes('Response is auto-saved');
 return {kind:'question',wording,options,closed,saved,autoSave,visualContent};
}'''


def allowed_url(url):
    parsed = urlsplit(url)
    return parsed.scheme == 'https' and parsed.hostname == 'app.tophat.com' and parsed.port in (None, 443)


def read_question(frame):
    if not allowed_url(frame.url):
        return {'kind': 'waiting', 'reason': 'Waiting for app.tophat.com after manual login.'}
    current = frame.evaluate(SNAPSHOT)
    if current['kind'] != 'question':
        return current
    choices = []
    for option in current['options']:
        label = re.fullmatch(r'\s*[A-Z],\s*(.+)', option['label'], flags=re.S)
        if not label:
            return {'kind': 'unsupported', 'reason': 'An answer has no recognizable accessible label.'}
        choices.append(label.group(1).strip())
    if len({normalize(c) for c in choices}) != len(choices):
        return {'kind': 'unsupported', 'reason': 'Duplicate answer text; cannot select uniquely.'}
    current['choices'] = choices
    return current


def identity(current):
    # Choice order can change; prevent repeated attempts on the same question.
    return json.dumps([normalize(current['wording']), sorted(normalize(c) for c in current['choices'])])


def selection_blocker(current, result):
    if current.get('kind') != 'question':
        return 'Not a supported multiple-choice question.'
    if current['closed'] or not all(o['enabled'] and o['visible'] for o in current['options']):
        return 'Question is closed, disabled, or its controls are not visible.'
    if current['saved'] or any(o['checked'] for o in current['options']):
        return 'Already answered; preserving your selection.'
    if not current['autoSave']:
        return 'Unrecognized save behavior; select manually.'
    if current['visualContent']:
        return 'Question includes visual content; review manually.'
    if result.get('status') != 'exact' or not result.get('verified') or not result.get('answer'):
        return 'Auto-selection requires an exact match and a verified prepared answer.'
    return None


def select_answer(frame, expected, result):
    """Recheck current question and pin its actual control before any action."""
    current = read_question(frame)
    if current != expected:
        return {'action': 'skipped', 'reason': 'Page changed before selection.'}
    blocker = selection_blocker(current, result)
    if blocker:
        return {'action': 'skipped', 'reason': blocker}
    indices = [i for i,c in enumerate(current['choices']) if normalize(c) == normalize(result['answer'])]
    if len(indices) != 1:
        return {'action': 'skipped', 'reason': 'Answer text is not unique.'}
    index = indices[0]
    # Exact accessible label comes from this DOM snapshot, not a fixed letter/index.
    control = frame.locator(ARTICLE).get_by_role('group', name=GROUP_LABEL, exact=True).get_by_role(
        'radio', name=current['options'][index]['label'], exact=True)
    if control.count() != 1:
        return {'action': 'skipped', 'reason': 'Answer control is ambiguous.'}
    handle = control.element_handle()
    if handle is None:
        return {'action': 'skipped', 'reason': 'Answer disappeared.'}
    try:
        if read_question(frame) != expected or handle.is_checked() or not handle.is_enabled():
            return {'action': 'skipped', 'reason': 'Question or selection changed.'}
        # Ordinary Playwright actionability checks; never force or enable controls.
        handle.check(timeout=2000)
        confirmed = False
        for _ in range(10):
            after = read_question(frame)
            if after.get('kind') != 'question' or identity(after) != identity(current):
                break
            selected = [c for c,o in zip(after['choices'],after['options']) if o['checked']]
            if selected == [current['choices'][index]] and after['saved']:
                confirmed = True
                break
            frame.page.wait_for_timeout(500)
        return {'action': 'selected', 'answer': result['answer'], 'save_confirmed': confirmed,
                'reason': 'Response saved was observed.' if confirmed else 'Selection attempted; verify saved status in Top Hat. No automatic retry.'}
    finally:
        handle.dispose()


def emit(event, log_path):
    print(json.dumps(event, indent=2, ensure_ascii=False), flush=True)
    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open('a', encoding='utf-8') as file:
            file.write(json.dumps({'time': time.time(), **event}, ensure_ascii=False) + '\n')


def watch(context, db_path, auto_select=False, log_path=None):
    attempted, previous, stable = set(), {}, {}
    ambiguity_reported = False
    while context.pages:
        try:
            candidates = []
            for page in list(context.pages):
                for frame in page.frames:
                    if allowed_url(frame.url):
                        current = read_question(frame)
                        key = id(frame)
                        signature = json.dumps(current, sort_keys=True)
                        stable[key] = stable.get(key, 0) + 1 if previous.get(key) == signature else 1
                        if previous.get(key) != signature:
                            previous[key] = signature
                            if current['kind'] != 'question':
                                emit(current, log_path)
                        if current['kind'] == 'question':
                            candidates.append((frame,current,signature))
            if len(candidates) > 1:
                if not ambiguity_reported:
                    emit({'action':'waiting','reason':'Multiple question tabs/frames are open. Keep only one question open.'},log_path)
                    ambiguity_reported = True
            else:
                ambiguity_reported = False
                if candidates:
                    frame,current,signature = candidates[0]
                    with connect(db_path) as db:
                        result = match(records(db), current['wording'], current['choices'])
                    # Re-read the bank each poll: a reviewed answer can become available later.
                    report = json.dumps([signature,result], sort_keys=True)
                    key = ('report',id(frame))
                    if previous.get(key) != report:
                        emit({'question':current,'assistance':result,'auto_select':auto_select,
                              'selection_blocker':selection_blocker(current,result)},log_path)
                        previous[key] = report
                    question_id = identity(current)
                    if auto_select and stable[id(frame)] >= 2 and question_id not in attempted and not selection_blocker(current,result):
                        # At most one attempt per question per process, including failed attempts.
                        attempted.add(question_id)
                        try:
                            emit(select_answer(frame,current,result),log_path)
                        except PlaywrightError as exc:
                            emit({'action':'selection_unconfirmed','reason':f'{type(exc).__name__}: page changed or control was unavailable; no retry. Check Top Hat manually.'},log_path)
            time.sleep(1)
        except PlaywrightError:
            # A manual navigation/closed tab can invalidate a read; next poll starts fresh.
            time.sleep(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='https://app.tophat.com/')
    parser.add_argument('--auto-select', action='store_true', help='Select exact, verified prepared answers. Top Hat may immediately save them.')
    parser.add_argument('--executable-path', help='Optional existing Chromium executable.')
    parser.add_argument('--data-dir', type=Path, default=Path(os.environ.get('PHYSICS_DATA_DIR','data')))
    parser.add_argument('--no-log', action='store_true', help='Do not save question text/results to a local JSONL log.')
    args = parser.parse_args()
    try:
        valid = allowed_url(args.url)
    except ValueError:
        valid = False
    if not valid:
        parser.error('Use an HTTPS app.tophat.com URL.')
    print('Live mode: '+('AUTO-SELECTION ON — selecting can immediately record your response.' if args.auto_select else 'READ ONLY — no answers will be selected.'))
    print('Log in manually, open your course, then open a question. Attendance remains manual.')
    print('Prepared answers only; this version does not solve new questions. Ctrl+C stops the program.')
    log = None if args.no_log else args.data_dir / 'live-events.jsonl'
    with sync_playwright() as p:
        try:
            context = p.chromium.launch_persistent_context(str(Path('.browser-profile').resolve()),
                       headless=False, executable_path=args.executable_path)
            try:
                page = context.pages[0] if context.pages else context.new_page()
                try:
                    page.goto(args.url,wait_until='domcontentloaded',timeout=60000)
                except PlaywrightError:
                    print('Initial navigation did not finish. Navigate/login manually in the open browser.')
                watch(context, args.data_dir / 'bank.sqlite3', args.auto_select, log)
            finally:
                context.close()
        except KeyboardInterrupt:
            print('Stopped.')
        except PlaywrightError:
            print('Browser could not start or was disconnected. Close other assistant windows, check Chromium installation, and rerun.')
            raise SystemExit(1)

if __name__ == '__main__':
    main()
