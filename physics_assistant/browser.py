"""Read-only simulator watcher. No Top Hat DOM assumptions or answer clicks."""
import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
from .bank import connect, records, match


def read_simulator(page, origin="http://127.0.0.1:5000"):
    if not page.url.startswith(origin + '/simulator/question/'):
        return None
    prompt = page.locator('[data-question]')
    if prompt.count() != 1:
        return None
    return {'wording': prompt.inner_text(), 'choices': page.locator('[data-choice]').all_inner_texts()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--headless', action='store_true', help='Cloud simulator checks without a desktop; not for manual login.')
    parser.add_argument('--executable-path', help='Use an existing Chromium executable instead of the Playwright download.')
    parser.add_argument('--inspect-url', help='Open a real HTTPS page for manual login and inspection only; no matching or automatic reading.')
    args = parser.parse_args()
    if args.inspect_url and args.headless:
        parser.error('Manual inspection requires a visible desktop browser.')
    if args.inspect_url and not args.inspect_url.startswith('https://'):
        parser.error('Inspection requires an HTTPS URL.')
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(str(Path('.browser-profile').resolve()), headless=args.headless, executable_path=args.executable_path)
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(args.inspect_url or 'http://127.0.0.1:5000/simulator')
        if args.inspect_url:
            print('Manual inspection mode. Log in yourself; use browser developer tools to inspect visible question elements.')
            print('No Top Hat selectors, automatic navigation, answer reading, or submission have been enabled.')
            print('Keep account credentials and session files private. Close the browser to finish.')
        previous = None
        print('Browser open. Select questions manually. Ctrl+C to stop.')
        try:
            while context.pages:
                if not args.inspect_url:
                    try:
                        current = read_simulator(page)
                        fingerprint = json.dumps(current, sort_keys=True)
                        if current and fingerprint != previous:
                            with connect(Path('data') / 'bank.sqlite3') as db:
                                result = match(records(db), current['wording'], current['choices'])
                            print(json.dumps({'question': current, 'assistance': result}, indent=2, ensure_ascii=False), flush=True)
                        previous = fingerprint
                    except Exception as exc:
                        if page.is_closed():
                            break
                        print(f'Page changed while reading ({type(exc).__name__}); will retry.', flush=True)
                page.wait_for_timeout(1000)
        except KeyboardInterrupt:
            pass
        finally:
            context.close()

if __name__ == '__main__':
    main()
