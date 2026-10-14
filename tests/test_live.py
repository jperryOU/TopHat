"""Local Chromium tests of sanitized supplied HTML, never the real service."""
import os
import unittest
import tempfile
import json
from unittest.mock import patch
from pathlib import Path
from playwright.sync_api import sync_playwright
from physics_assistant.live import read_question, select_answer, selection_blocker, allowed_url, watch
from physics_assistant.bank import match, connect

FIXTURES = Path(__file__).parent / 'fixtures'

@unittest.skipUnless(os.environ.get('RUN_BROWSER_TESTS') == '1', 'Opt in with RUN_BROWSER_TESTS=1; requires Chromium')
class LiveAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True,executable_path=os.environ.get('CHROMIUM_EXECUTABLE'))

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.page = self.browser.new_page()
        self.page.route('**/*',lambda route: route.fulfill(status=200,content_type='text/html',body=(FIXTURES/'open.html').read_text()))
        self.page.goto('https://app.tophat.com/test-fixture')

    def tearDown(self):
        self.page.close()

    def load(self, name):
        self.page.set_content((FIXTURES/(name+'.html')).read_text())
        return read_question(self.page)

    def prepared(self, current, verified=True):
        return match([{'wording':current['wording'],'options':current['choices'],
                      'answer':'200 m/s','explanation':'Momentum: 2000(100) = 1500v + 500(-200), so v = 200 m/s.',
                      'verified':verified,'source':'lecture','page':1}],current['wording'],current['choices'])

    def simulate_autosave(self):
        # This listener is test-only: fixture snapshots have no Top Hat application JS.
        self.page.evaluate('''() => {window.changes=0;document.addEventListener('change',event=>{
            if(event.target.type==='radio'){window.changes++;
              document.querySelectorAll('[class*="StatusMessagestyles__MessageContainer"],p[aria-live="polite"]').forEach(e=>e.textContent='Response saved');}
        });}''')

    def test_open_reads_prompt_without_instructions_or_choices(self):
        q = read_question(self.page)
        self.assertEqual(q['kind'],'question')
        self.assertTrue(q['wording'].startswith('A rocket is coasting'))
        self.assertTrue(q['wording'].endswith('What is the speed of the rocket afterward?'))
        self.assertNotIn('Multiple Choice',q['wording'])
        self.assertEqual(q['choices'],['50 m/s','67 m/s','150 m/s','200 m/s','300 m/s'])
        self.assertIsNone(selection_blocker(q,self.prepared(q)))

    def test_selects_answer_text_and_observes_saved(self):
        q=read_question(self.page);self.simulate_autosave()
        outcome=select_answer(self.page,q,self.prepared(q))
        self.assertEqual(outcome['action'],'selected')
        self.assertTrue(outcome['save_confirmed'])
        self.assertTrue(self.page.get_by_role('radio',name='D, 200 m/s',exact=True).is_checked())
        self.assertEqual(self.page.evaluate('window.changes'),1)
        after=read_question(self.page)
        self.assertEqual(select_answer(self.page,after,self.prepared(after))['action'],'skipped')
        self.assertEqual(self.page.evaluate('window.changes'),1)

    def test_shuffled_choices_not_letters_or_values(self):
        self.page.evaluate('''() => {const group=document.querySelector('[role="group"]');
            [...group.children].reverse().forEach(e=>group.append(e));
            [...group.querySelectorAll('input')].forEach((e,i)=>e.setAttribute('aria-label',String.fromCharCode(65+i)+', '+e.getAttribute('aria-label').split(', ').slice(1).join(', ')));}''')
        q=read_question(self.page);self.simulate_autosave()
        self.assertEqual(q['choices'][1],'200 m/s')
        self.assertEqual(select_answer(self.page,q,self.prepared(q))['action'],'selected')
        self.assertTrue(self.page.get_by_role('radio',name='B, 200 m/s',exact=True).is_checked())

    def test_closed_and_answered_never_change(self):
        for fixture in ('closed','answered'):
            q=self.load(fixture)
            result={'status':'exact','verified':True,'answer':q['choices'][0]}
            self.assertEqual(select_answer(self.page,q,result)['action'],'skipped')
            self.assertEqual(self.page.locator('input:checked').count(),0)

    def test_reads_live_checked_property_even_without_attribute(self):
        self.page.get_by_role('radio',name='A, 50 m/s',exact=True).check()
        q=read_question(self.page)
        self.assertTrue(q['options'][0]['checked'])
        self.assertEqual(select_answer(self.page,q,self.prepared(q))['action'],'skipped')

    def test_unverified_fuzzy_and_no_match_do_not_select(self):
        q=read_question(self.page)
        results=[self.prepared(q,False),{'status':'uncertain_fuzzy','verified':True,'answer':'200 m/s'},
                 {'status':'manual_review'}]
        for result in results:self.assertEqual(select_answer(self.page,q,result)['action'],'skipped')
        self.assertEqual(self.page.locator('input:checked').count(),0)

    def test_attendance_and_changed_page(self):
        q=read_question(self.page)
        result=self.prepared(q)
        attendance=self.load('attendance')
        self.assertEqual(attendance['kind'],'attendance')
        self.assertEqual(select_answer(self.page,q,result)['action'],'skipped')
        self.assertEqual(self.page.locator('input[name="attendanceCode"]').input_value(),'')

    def test_disabled_visual_or_unknown_save_behavior(self):
        self.page.locator('input').first.evaluate('(e)=>e.disabled=true')
        q=read_question(self.page)
        self.assertIsNotNone(selection_blocker(q,self.prepared(q)))
        q=self.load('open')
        self.page.locator('.question-renderer-content-area').evaluate("e=>e.prepend(document.createElement('canvas'))")
        q=read_question(self.page)
        self.assertTrue(q['visualContent'])
        self.assertEqual(select_answer(self.page,q,self.prepared(q))['action'],'skipped')
        q=self.load('open')
        self.page.locator('[class*="StatusMessagestyles__MessageContainer"],p[aria-live="polite"]').evaluate_all("els=>els.forEach(e=>e.textContent='Ready')")
        q=read_question(self.page)
        self.assertEqual(select_answer(self.page,q,self.prepared(q))['action'],'skipped')

    def test_ambiguous_or_changed_layout(self):
        self.page.locator('.question-renderer-content-area').evaluate("e=>e.className='new-layout'")
        self.assertEqual(read_question(self.page)['kind'],'unsupported')
        self.load('open')
        self.page.locator('[role="article"]').evaluate('e=>e.after(e.cloneNode(true))')
        self.assertEqual(read_question(self.page)['kind'],'waiting')

    def test_watcher_waits_and_does_not_repeat_attempt(self):
        q=read_question(self.page)
        self.simulate_autosave()
        with tempfile.TemporaryDirectory() as folder:
            db_path=Path(folder)/'bank.sqlite3'
            with connect(db_path) as db:
                db.execute("INSERT INTO questions (id,source,page,wording,options,context,images,answer,explanation,verified) VALUES (?,?,?,?,?,?,?,?,?,?)",
                           ('test','lecture',1,q['wording'],json.dumps(q['choices']),'','[]','200 m/s','Momentum conservation',1))
                db.commit()
            ticks=[]
            events=[]
            def tick(_):
                ticks.append(1)
                if len(ticks)==1:
                    self.assertEqual(self.page.evaluate('window.changes'),0)
                if len(ticks)==2:
                    self.assertEqual(self.page.evaluate('window.changes'),1)
                    # Simulate the server reverting a response: never click it again automatically.
                    self.page.evaluate("() => {document.querySelectorAll('input').forEach(e=>e.checked=false);document.querySelectorAll('[class*=StatusMessagestyles__MessageContainer],p[aria-live=polite]').forEach(e=>e.textContent='Response is auto-saved');}")
                if len(ticks)==4:
                    self.assertEqual(self.page.evaluate('window.changes'),1)
                    self.page.close()
            with patch('physics_assistant.live.time.sleep',side_effect=tick), patch('physics_assistant.live.emit',side_effect=lambda e,p: events.append(e)):
                watch(self.page.context,db_path,auto_select=True)
            self.assertEqual(sum(e.get('action')=='selected' for e in events),1)

class DomainTests(unittest.TestCase):
    def test_scope(self):
        self.assertTrue(allowed_url('https://app.tophat.com/course'))
        for url in ('http://app.tophat.com','https://app.tophat.com.evil.example','https://other.example','https://app.tophat.com:8443'):
            self.assertFalse(allowed_url(url))

if __name__ == '__main__':unittest.main()
