"""Local dashboard, upload form, and safe same-tab classroom simulator."""
import os
import secrets
import tempfile
from pathlib import Path
from flask import Flask, request, jsonify, render_template_string, send_from_directory
from .bank import connect, records, import_slides, match

DATA = Path(os.environ.get('PHYSICS_DATA_DIR', 'data')).resolve()
DATA.mkdir(parents=True, exist_ok=True)
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 30 * 1024 * 1024
TOKEN = secrets.token_urlsafe(32)

@app.before_request
def local_only():
    # Reject DNS rebinding and cross-origin writes to this local application.
    if request.host.split(':')[0] not in ('localhost', '127.0.0.1'):
        return 'Local access only', 403
    if request.method == 'POST' and request.headers.get('X-Local-Token') != TOKEN:
        return 'Reload the dashboard before making changes', 403

@app.get('/')
def home():
    return render_template_string(DASHBOARD, token=TOKEN)

@app.get('/api/questions')
def questions():
    with connect(DATA / 'bank.sqlite3') as db:
        return jsonify(records(db))

@app.post('/api/upload')
def upload():
    file = request.files.get('slides')
    if not file or Path(file.filename).suffix.lower() not in ('.pdf', '.pptx'):
        return jsonify(error='Choose a PDF or PPTX file.'), 400
    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ('slides' + Path(file.filename).suffix.lower())
            file.save(path)
            with connect(DATA / 'bank.sqlite3') as db:
                result = import_slides(db, path, DATA / 'images', Path(file.filename).name)
        return jsonify(result)
    except Exception as exc:
        return jsonify(error=f'Could not parse slides: {type(exc).__name__}. Check file format/encryption.'), 400

@app.post('/api/questions/<identity>')
def edit(identity):
    body = request.get_json()
    answer = body.get('answer', '').strip()
    explanation = body.get('explanation', '').strip()
    with connect(DATA / 'bank.sqlite3') as db:
        row = db.execute('SELECT options FROM questions WHERE id=?', (identity,)).fetchone()
        if row is None:
            return jsonify(error='Question not found'), 404
        import json
        options = json.loads(row['options'])
        if options and answer and answer not in options:
            return jsonify(error='Choose the full answer text from the extracted options.'), 400
        verified = bool(body.get('verified')) and bool(answer) and bool(explanation)
        db.execute('UPDATE questions SET answer=?,explanation=?,verified=? WHERE id=?',
                   (answer, explanation, int(verified), identity))
        db.commit()
    return jsonify(saved=True, verified=verified)

@app.post('/api/match')
def matching():
    body = request.get_json()
    with connect(DATA / 'bank.sqlite3') as db:
        return jsonify(match(records(db), body.get('wording', ''), body.get('choices', [])))

@app.get('/images/<path:name>')
def images(name):
    return send_from_directory(DATA / 'images', name)

@app.get('/simulator')
def simulator():
    return render_template_string(SIMULATOR)

@app.get('/simulator/question/<identity>')
def simulated_question(identity):
    with connect(DATA / 'bank.sqlite3') as db:
        question = next((q for q in records(db) if q['id'] == identity), None)
    if not question:
        return 'Import slides and select a question first.', 404
    return render_template_string(QUESTION, q=question, choices=list(reversed(question['options'])))

DASHBOARD = '''<!doctype html><html><meta charset="utf-8"><title>Physics answer bank</title>
<style>body{font:16px system-ui;max-width:950px;margin:30px auto;padding:15px}article{border:1px solid #aaa;padding:16px;margin:18px 0}textarea{width:95%;min-height:70px}img{max-width:300px}pre{white-space:pre-wrap}button{padding:8px}input{padding:7px}</style>
<h1>Physics answer bank</h1><p>Read and verify each extraction against the original slide. This dashboard edits your local bank. The separate live auto-selection mode can save responses in Top Hat.</p>
<form id="upload"><input type="file" name="slides" accept=".pdf,.pptx" required><button>Import slides</button></form><pre id="status"></pre>
<p><a href="/simulator" target="_blank">Open classroom simulator</a></p><input id="search" placeholder="Search original wording"><div id="bank"></div>
<script>
const token={{ token|tojson }};let questions=[];
async function post(url,body,form=false){const r=await fetch(url,{method:'POST',headers:form?{'X-Local-Token':token}:{'X-Local-Token':token,'Content-Type':'application/json'},body:form?body:JSON.stringify(body)});return await r.json()}
function node(tag,text){let n=document.createElement(tag);n.textContent=text;return n}
async function load(){questions=await(await fetch('/api/questions')).json();draw()}
function draw(){const bank=document.getElementById('bank');bank.replaceChildren();for(const q of questions.filter(q=>q.wording.toLowerCase().includes(document.getElementById('search').value.toLowerCase()))){
const a=node('article','');a.append(node('small',q.source+' · slide/page '+q.page),node('pre',q.wording));for(const c of q.options)a.append(node('p',c));
const detail=node('details','');detail.append(node('summary','Full extracted slide context'),node('pre',q.context));a.append(detail);
for(const name of q.images){const img=document.createElement('img');img.src='/images/'+encodeURIComponent(name);img.alt='Embedded slide image; inspect original for layout';a.append(img)}
let answer;if(q.options.length){answer=document.createElement('select');answer.append(new Option('No prepared answer',''));for(const c of q.options)answer.append(new Option(c,c));answer.value=q.answer}else{answer=document.createElement('input');answer.value=q.answer;answer.placeholder='Prepared answer'}
const explanation=document.createElement('textarea');explanation.value=q.explanation;explanation.placeholder='Reasoning / equation (e.g. F = ma), checked against lecture';const verified=document.createElement('input');verified.type='checkbox';verified.checked=!!q.verified;
const label=node('label',' Verified by me ');label.prepend(verified);const save=node('button','Save answer');save.onclick=async()=>{const result=await post('/api/questions/'+q.id,{answer:answer.value,explanation:explanation.value,verified:verified.checked});document.getElementById('status').textContent=JSON.stringify(result,null,2);await load()};
a.append(node('p',q.verified?'Verified answer':'Needs verification — no automatic solution'),answer,explanation,label,save);bank.append(a)}}
document.getElementById('upload').onsubmit=async e=>{e.preventDefault();document.getElementById('status').textContent=JSON.stringify(await post('/api/upload',new FormData(e.target),true),null,2);await load()};document.getElementById('search').oninput=draw;load();
</script></html>'''
SIMULATOR = '''<!doctype html><html><meta charset="utf-8"><title>Classroom simulator</title><h1>Available questions</h1><p>Select a question. It opens in this same tab. Choices are reversed to test answer-text matching.</p><div id="questions"></div><script>
fetch('/api/questions').then(r=>r.json()).then(qs=>{for(const q of qs){const p=document.createElement('p'),a=document.createElement('a');a.href='/simulator/question/'+q.id;a.textContent=q.wording;p.append(a);document.getElementById('questions').append(p)}});
</script></html>'''
QUESTION = '''<!doctype html><html><meta charset="utf-8"><title>Simulated physics question</title><a href="/simulator">Back to available questions</a><h1 data-question>{{q.wording}}</h1><form>{% for c in choices %}<p><label><input type="radio" name="answer"><span data-choice>{{c}}</span></label></p>{% endfor %}</form><p>Simulation only. No submit button.</p></html>'''

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=False)
