"""人物マップのE2Eテスト（Playwright for Python）

実行:  pip install playwright && playwright install chromium
       python tests/jinbutsu_map_e2e.py
別のURLを試す場合は、環境変数 JINBUTSU_MAP_URL にURLかfile://のパスを指定する。
"""
import json, os, re, sys, tempfile
from pathlib import Path
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
URL = os.environ.get("JINBUTSU_MAP_URL") or (HERE.parent / "小説関連のツール" / "人物マップ.html").as_uri()
LEGACY = HERE / "fixtures" / "legacy-export.json"
STORE = "jinbutsu-map:v1"

results = []
def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"   [{detail}]" if (detail and not cond) else ""))

# ---------------------------------------------------------------- ヘルパー
def new_page(b, w=1440, h=900, touch=False):
    ctx = b.new_context(viewport={"width": w, "height": h}, has_touch=touch, is_mobile=touch, accept_downloads=True)
    pg = ctx.new_page()
    pg.errors, pg.dialogs, pg.dialog_accept = [], [], True
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    def on_dialog(d):
        pg.dialogs.append(d.message)
        d.accept() if pg.dialog_accept else d.dismiss()
    pg.on("dialog", on_dialog)
    pg.goto(URL, wait_until="load")
    pg.wait_for_timeout(600)
    return pg

def store(pg):
    pg.wait_for_timeout(700)
    return pg.evaluate(f"JSON.parse(localStorage.getItem('{STORE}'))")
def cur(pg):
    s = store(pg)
    return next(m for m in s["maps"] if m["id"] == s["current"])
def by_name(m, name):
    return next(c for c in m["cards"] if c["name"] == name)

def card_box(pg, name):
    return pg.evaluate("""n => { const e=[...document.querySelectorAll('.card')].find(c=>c.getAttribute('aria-label')===n);
        if(!e) return null; const r=e.getBoundingClientRect(); return [r.left,r.top,r.width,r.height]; }""", name)

def add_card(pg, x, y, name):
    pg.mouse.dblclick(x, y); pg.wait_for_timeout(350)
    pg.fill("[data-role=name]", name); pg.wait_for_timeout(150)

def connect(pg, a, b, label=""):
    """a のカードから b のカードへ線を引き、関係の名前を入れて確定する"""
    A, B = card_box(pg, a), card_box(pg, b)
    side = "h-r" if B[0] > A[0] else "h-l"
    pg.mouse.move(A[0] + A[2] / 2, A[1] + A[3] / 2); pg.wait_for_timeout(120)
    hd = pg.evaluate("""([n,side]) => { const e=[...document.querySelectorAll('.card')].find(c=>c.getAttribute('aria-label')===n);
        const r=e.querySelector('.'+side).getBoundingClientRect(); return [r.left+r.width/2, r.top+r.height/2]; }""", [a, side])
    pg.mouse.move(*hd); pg.mouse.down()
    pg.mouse.move(B[0] + B[2] / 2, B[1] + B[3] / 2, steps=10); pg.mouse.up(); pg.wait_for_timeout(250)
    if label: pg.keyboard.type(label)
    pg.keyboard.press("Enter"); pg.wait_for_timeout(250)

def open_link_detail(pg, label_text):
    tb = pg.evaluate("""t => { const e=[...document.querySelectorAll('.ltag')].find(x=>x.textContent===t); const r=e.getBoundingClientRect(); return [r.left+r.width/2,r.top+r.height/2]; }""", label_text)
    pg.mouse.click(*tb); pg.wait_for_timeout(300)
    pg.keyboard.press("Escape"); pg.wait_for_timeout(200)       # ポップオーバーを閉じる（選択は残る）

def two_linked(b, label="幼なじみ"):
    pg = new_page(b)
    add_card(pg, 330, 360, "灯"); add_card(pg, 800, 380, "蒼真")
    connect(pg, "灯", "蒼真", label)
    open_link_detail(pg, label)
    return pg

def poly_points(d):
    nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", d)]
    return list(zip(nums[0::2], nums[1::2]))

def geometry_problems(pg):
    """全リンクについて、線の両端・矢印が自分のカードのふちの外にあるかを調べる"""
    m = cur(pg)
    return pg.evaluate("""links => {
      const rect = el => { const t=/translate\\(([-\\d.]+)px,\\s*([-\\d.]+)px\\)/.exec(el.style.transform); const w=el.offsetWidth,h=el.offsetHeight;
        return {cx:+t[1]+w/2, cy:+t[2]+h/2, hw:w/2, hh:h/2}; };
      const R = {}; document.querySelectorAll('.card').forEach(e => R[e.dataset.id] = rect(e));
      const pts = d => { const n=(d.match(/-?\\d+(?:\\.\\d+)?/g)||[]).map(Number); const o=[]; for(let i=0;i<n.length;i+=2) o.push([n[i],n[i+1]]); return o; };
      const inside = (p,r,e) => Math.abs(p[0]-r.cx) < r.hw+e && Math.abs(p[1]-r.cy) < r.hh+e;
      const out = [];
      for (const l of links) {
        const g = document.querySelector(`.lk[data-id="${l.id}"]`); if (!g) continue;
        const P = pts(g.children[0].getAttribute('d')); if (P.length < 2) continue;
        const ra = R[l.a], rb = R[l.b];
        const arrB = l.dir==='ab'||l.dir==='both', arrA = l.dir==='ba'||l.dir==='both';
        const gapA = arrA ? 12 : 8, gapB = arrB ? 12 : 8;
        if (inside(P[0], ra, gapA-0.6)) out.push(l.id+': 始点がカードに近すぎる');
        if (inside(P[P.length-1], rb, gapB-0.6)) out.push(l.id+': 終点がカードに近すぎる');
        for (const p of P) { if (inside(p, ra, 7.5) || inside(p, rb, 7.5)) { out.push(l.id+': 線がカードに被っている'); break; } }
        const ahB = pts(g.children[3].getAttribute('d')), ahA = pts(g.children[2].getAttribute('d'));
        for (const p of ahB) if (inside(p, rb, 2) || inside(p, ra, 2)) { out.push(l.id+': 矢印(終点)がカードに被っている'); break; }
        for (const p of ahA) if (inside(p, ra, 2) || inside(p, rb, 2)) { out.push(l.id+': 矢印(始点)がカードに被っている'); break; }
      }
      return out; }""", m["links"])

def make_png(path, w=400, h=600):
    from PIL import Image
    im = Image.new("RGB", (w, h))
    px = im.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = (int(255 * x / w), int(255 * y / h), 140)
    im.save(path)

# ---------------------------------------------------------------- テスト
def t_existing_features(b):
    print("\n[既存機能が壊れていない]")
    pg = new_page(b)
    check("起動時に人物がいない・空の案内が出る", pg.evaluate("document.querySelectorAll('.card').length") == 0 and pg.evaluate("!document.getElementById('empty').hidden"))
    add_card(pg, 330, 360, "灯"); add_card(pg, 800, 380, "蒼真")
    pg.fill("#drBody label:nth-of-type(4) input", "幼なじみ") if False else None
    check("ダブルクリックで人物が作れ、名前がマス目に出る", pg.evaluate("[...document.querySelectorAll('.card .nm .cell')].map(c=>c.textContent).join('')") == "灯蒼真")
    connect(pg, "灯", "蒼真", "幼なじみ")
    check("ふちの点からドラッグして関係が作れる（荷札に名前）", pg.evaluate("[...document.querySelectorAll('.ltag')].map(t=>t.textContent)") == ["幼なじみ"])
    # 何もない所へ引くと、つながった新しい人物ができる
    A = card_box(pg, "灯")
    pg.mouse.move(A[0] + A[2] / 2, A[1] + A[3] / 2); pg.wait_for_timeout(120)
    hb = pg.evaluate("""() => { const e=[...document.querySelectorAll('.card')].find(c=>c.getAttribute('aria-label')==='灯'); const r=e.querySelector('.h-b').getBoundingClientRect(); return [r.left+r.width/2, r.top+r.height/2]; }""")
    pg.mouse.move(*hb); pg.mouse.down(); pg.mouse.move(hb[0] + 30, hb[1] + 230, steps=10); pg.mouse.up(); pg.wait_for_timeout(300)
    pg.keyboard.type("師弟"); pg.keyboard.press("Enter"); pg.wait_for_timeout(300)
    check("線を空きへ引くと、新しい人物と関係ができ、名前入力へ進む", pg.evaluate("document.querySelectorAll('.card').length") == 3 and pg.evaluate("document.activeElement.dataset.role") == "name")
    pg.keyboard.type("ノエル"); pg.mouse.click(900, 140); pg.wait_for_timeout(300)
    n = pg.evaluate("document.querySelectorAll('.card').length")
    pg.keyboard.press("Control+z"); pg.wait_for_timeout(250)
    pg.keyboard.press("Control+Shift+z"); pg.wait_for_timeout(250)
    check("元に戻す／やり直す", pg.evaluate("document.querySelectorAll('.card').length") == n)
    pg.wait_for_timeout(500); pg.reload(wait_until="load"); pg.wait_for_timeout(700)
    check("再読み込み後も人物・関係が残る（自動保存）", pg.evaluate("document.querySelectorAll('.card').length") == 3 and pg.evaluate("document.querySelectorAll('.lk').length") == 2)
    pg.click("#relaxBtn"); pg.wait_for_timeout(3500)
    check("並べ直すが動く", pg.evaluate("document.querySelectorAll('.card').length") == 3)
    # 検索（人物一覧）
    pg.keyboard.press("Escape"); pg.mouse.click(1000, 120); pg.wait_for_timeout(300)
    pg.fill("#drBody input[type=search]", "ノエ"); pg.wait_for_timeout(200)
    check("人物一覧の検索", pg.evaluate("document.querySelectorAll('.prow').length") == 1)
    # マップの切り替え
    pg.click("#mapMenuBtn"); pg.click("text=新しいマップをつくる"); pg.wait_for_timeout(400)
    check("新しいマップは空で、元のマップに切り替えて戻せる", pg.evaluate("document.querySelectorAll('.card').length") == 0)
    pg.click("#mapMenuBtn"); pg.click(".menu .mi >> nth=0"); pg.wait_for_timeout(400)
    check("マップを切り替えると人物が戻る", pg.evaluate("document.querySelectorAll('.card').length") == 3)
    check("JSエラーなし", not pg.errors, pg.errors)
    pg.context.close()

def t_attitudes_and_diffs(b):
    print("\n[他人への態度・他人との違い]")
    pg = two_linked(b)
    check("関係を選ぶと右の欄が「関係の詳細」になる", pg.evaluate("document.getElementById('drTitle').textContent") == "関係の詳細")
    pg.fill("[data-role=att-attAB]", "好意を持っている"); pg.wait_for_timeout(100)
    m = cur(pg); l = m["links"][0]
    check("A→Bだけに態度を入れると、B→Aは空のまま（一方通行を表現できる）", l["attAB"] == "好意を持っている" and l["attBA"] == "")
    check("態度は矢印方向・関係の種類と別の項目として保存される", l["dir"] == "none" and l["kind"] == "other" and "attAB" in l)
    pg.fill("[data-role=att-attBA]", "警戒している"); pg.click("[data-role=att-attBA] >> xpath=../div[@class='chips']/button[text()='信頼している']"); pg.wait_for_timeout(100)
    l = cur(pg)["links"][0]
    check("B→Aは別に書ける。例の候補をクリックすると追記される", l["attAB"] == "好意を持っている" and l["attBA"] == "警戒している、信頼している", l)
    pg.click("[data-role=add-diff]"); pg.wait_for_timeout(150)
    pg.select_option(".diffitem select", "ability"); pg.fill(".diffitem textarea", "灯は直感型、蒼真は分析型"); pg.wait_for_timeout(100)
    pg.click("[data-role=add-diff]"); pg.wait_for_timeout(150)
    check("違いのメモは分類つきで複数入れられる", len(cur(pg)["links"][0]["diffs"]) == 2)
    pg.reload(wait_until="load"); pg.wait_for_timeout(700)
    l = cur(pg)["links"][0]
    check("再読み込み後も態度・違いが残る", l["attBA"] == "警戒している、信頼している" and l["diffs"][0]["cat"] == "ability" and "分析型" in l["diffs"][0]["text"])
    for name in ("灯", "蒼真"):
        box = card_box(pg, name); pg.mouse.click(box[0] + box[2] / 2, box[1] + 40); pg.wait_for_timeout(350)
        sub = pg.evaluate("[...document.querySelectorAll('.relsub')].map(e=>e.textContent).join('|')")
        check(f"どちらのカード（{name}）からも、態度と違いを関係経由で確認できる", "態度" in sub and "違い：能力・得意不得意" in sub, sub)
    c = cur(pg)
    check("態度・違いは人物データに重複保存されない", all("attAB" not in x and "diffs" not in x for x in c["cards"]))
    check("JSエラーなし", not pg.errors, pg.errors)
    pg.context.close()

def t_changes(b):
    print("\n[関係の変化の記録]")
    pg = two_linked(b)
    pg.click("[data-role=add-change]"); pg.wait_for_timeout(200)
    pg.select_option(".chg [data-role=pattern]", "trust"); pg.wait_for_timeout(100)
    check("パターンを選ぶと変化前・変化後の初期値が入る", pg.input_value(".chg [data-role=before]") == "友人" and pg.input_value(".chg [data-role=after]") == "信頼できる相手")
    pg.fill(".chg [data-role=before]", "親友")
    pg.select_option(".chg [data-role=pattern]", "special"); pg.wait_for_timeout(100)
    check("自分で書き換えた内容は、パターンを変えても上書きされない", pg.input_value(".chg [data-role=before]") == "親友" and pg.input_value(".chg [data-role=after]") == "特別な相手")
    pg.select_option(".chg [data-role=pattern]", ""); pg.wait_for_timeout(100)
    check("「変化パターンなし」でも登録でき、書いた内容は残る", pg.input_value(".chg [data-role=after]") == "特別な相手" and cur(pg)["links"][0]["changes"][0]["pattern"] == "")
    pg.select_option(".chg [data-role=pattern]", "other"); pg.wait_for_timeout(100)
    check("「その他（自由入力）」でパターン名を入れられる", pg.evaluate("!document.querySelector('.chgform input[aria-label=パターン名]').hidden"))
    pg.fill(".chg [data-role=trigger]", "禁書庫で身をかばわれる"); pg.fill(".chg [data-role=impact]", "秘密を打ち明ける"); pg.wait_for_timeout(100)
    summary = pg.evaluate("document.querySelector('.chg-sum').textContent")
    check("一覧で「変化前 → 変化後」と「きっかけ」がわかる", "親友 → 特別な相手" in summary and "禁書庫で身をかばわれる" in summary, summary)
    pg.click("[data-role=add-change]"); pg.wait_for_timeout(200)
    second_before = pg.locator(".chg").nth(1).locator("[data-role=before]").input_value()
    check("2つ目の「変化前」は、1つ目の「変化後」が初期値になる（複数登録・順序）", second_before == "特別な相手", second_before)
    pg.click("[data-role=add-change]"); pg.wait_for_timeout(200)     # 何も書かない記録も作れる
    ch = cur(pg)["links"][0]["changes"]
    check("1つの関係に複数の変化記録を登録でき、空欄のままでもよい", len(ch) == 3 and ch[2]["trigger"] == "" and ch[2]["impact"] == "")
    nums = pg.evaluate("[...document.querySelectorAll('.chg .no')].map(e=>e.textContent)")
    check("一覧に番号がつき順序がわかる", nums == ["1", "2", "3"])
    first_id = ch[0]["id"]
    pg.locator(".chg").nth(1).locator(".chg-ops button").nth(0).click(); pg.wait_for_timeout(200)     # 2つ目を上へ
    ch = cur(pg)["links"][0]["changes"]
    check("順番を入れ替えられる", ch[1]["id"] == first_id)
    pg.locator(".chg").nth(0).locator("[data-role=chg-delete]").click(); pg.wait_for_timeout(200)
    check("変化記録を削除できる", len(cur(pg)["links"][0]["changes"]) == 2)
    pg.click("#toast button"); pg.wait_for_timeout(300)
    check("削除は「元に戻す」で戻せる", len(cur(pg)["links"][0]["changes"]) == 3)
    pg.reload(wait_until="load"); pg.wait_for_timeout(700)
    check("再読み込み後も変化記録が残る", len(cur(pg)["links"][0]["changes"]) == 3)
    check("JSエラーなし", not pg.errors, pg.errors)
    pg.context.close()

def t_person_view(b):
    print("\n[人物カードから見る：変化・隠れた一面・目的]")
    pg = two_linked(b)
    pg.click("[data-role=add-change]"); pg.wait_for_timeout(200)
    pg.select_option(".chg [data-role=pattern]", "rebel"); pg.fill(".chg [data-role=trigger]", "師の裏切りを知る"); pg.wait_for_timeout(100)
    for name in ("灯", "蒼真"):
        box = card_box(pg, name); pg.mouse.click(box[0] + box[2] / 2, box[1] + 40); pg.wait_for_timeout(350)
        items = pg.evaluate("[...document.querySelectorAll('[data-role=person-change]')].map(e=>e.textContent)")
        check(f"人物カード（{name}）から、関わる変化記録の一覧が見える", len(items) == 1 and "尊敬 → 反発" in items[0], items)
    c = cur(pg)
    check("変化記録は関係にだけ保存され、人物ごとに重複保存されない", all("changes" not in x for x in c["cards"]) and len(c["links"][0]["changes"]) == 1)
    pg.click("[data-role=person-change]"); pg.wait_for_timeout(300)
    check("一覧から該当の変化記録（関係の詳細）へ移動できる", pg.evaluate("document.getElementById('drTitle').textContent") == "関係の詳細" and pg.evaluate("document.querySelectorAll('.chg.open').length") == 1)
    box = card_box(pg, "灯"); pg.mouse.click(box[0] + box[2] / 2, box[1] + 40); pg.wait_for_timeout(350)
    pg.fill("[data-role=inner]", "強気だが、本当は居場所に自信がない"); pg.wait_for_timeout(100)
    pg.reload(wait_until="load"); pg.wait_for_timeout(700)
    c = cur(pg)
    check("「隠れた一面」を入力でき、保存される", by_name(c, "灯")["inner"] == "強気だが、本当は居場所に自信がない")
    check("隠れた一面は、既存の「性格」「過去」を置き換えない", [f["k"] for f in by_name(c, "灯")["fields"]] == ["外見", "性格", "目的・動機", "過去"])
    check("隠れた一面は、キャンバス上のカードには出ない", "居場所" not in pg.evaluate("document.querySelector('.card').textContent"))
    box = card_box(pg, "灯"); pg.mouse.click(box[0] + box[2] / 2, box[1] + 40); pg.wait_for_timeout(350)
    labels = pg.evaluate("[...document.querySelectorAll('#drBody .cf-head input')].map(e=>e.value)")
    check("目的は既存の「目的・動機」だけで、重複する欄がない", labels.count("目的・動機") == 1 and not any(("目的" in x and x != "目的・動機") for x in labels), labels)
    check("JSエラーなし", not pg.errors, pg.errors)
    pg.context.close()

def t_delete(b):
    print("\n[関係を削除したときの変化記録の扱い]")
    pg = two_linked(b)
    pg.click("[data-role=add-change]"); pg.fill(".chg [data-role=trigger]", "きっかけ"); pg.wait_for_timeout(150)
    pg.dialog_accept = False
    pg.click(".danger-btn"); pg.wait_for_timeout(300)
    check("変化記録がある関係の削除は、確認が出る", len(pg.dialogs) == 1 and "変化の記録が1件" in pg.dialogs[0], pg.dialogs)
    check("確認で「いいえ」なら削除されない", len(cur(pg)["links"]) == 1 and len(cur(pg)["links"][0]["changes"]) == 1)
    pg.dialog_accept = True
    pg.click(".danger-btn"); pg.wait_for_timeout(300)
    check("削除すると、関係と一緒に変化記録も消える", len(cur(pg)["links"]) == 0)
    pg.click("#toast button"); pg.wait_for_timeout(300)
    l = cur(pg)["links"]
    check("元に戻すと、変化記録ごと戻る", len(l) == 1 and len(l[0]["changes"]) == 1 and l[0]["changes"][0]["trigger"] == "きっかけ")
    box = card_box(pg, "灯"); pg.mouse.click(box[0] + box[2] / 2, box[1] + 40); pg.wait_for_timeout(250); pg.keyboard.press("Delete"); pg.wait_for_timeout(300)
    check("人物を削除したときも、つながる関係の変化記録の件数を確認する", any("変化の記録が1件" in d for d in pg.dialogs), pg.dialogs)
    check("JSエラーなし", not pg.errors, pg.errors)
    pg.context.close()

def t_legacy(b):
    print("\n[旧形式のデータの読み込み（後方互換）]")
    pg = new_page(b)
    pg.click("#fileBtn")
    with pg.expect_file_chooser() as fc:
        pg.click("#importBtn")
    fc.value.set_files(str(LEGACY)); pg.wait_for_timeout(1200)
    check("旧形式の.jsonを読み込める", pg.evaluate("document.querySelectorAll('.card').length") == 6 and pg.evaluate("document.querySelectorAll('.lk').length") == 7)
    m = cur(pg); l = m["links"][0]
    check("新しい項目は既定値で補われる", l["changes"] == [] and l["diffs"] == [] and l["attAB"] == "" and l["pts"] == [] and l["shape"] == "curve" and by_name(m, "灯")["img"] == "" and by_name(m, "灯")["inner"] == "")
    pg.click(".ltag >> nth=0"); pg.wait_for_timeout(300); pg.keyboard.press("Escape")
    check("旧データの関係でも詳細欄が開ける", pg.evaluate("document.getElementById('drTitle').textContent") == "関係の詳細")
    check("JSエラーなし", not pg.errors, pg.errors)
    pg.context.close()

def t_image(b):
    print("\n[プロフィール画像]")
    tmp = Path(tempfile.mkdtemp()); png = tmp / "face.png"; make_png(png)
    pg = new_page(b)
    add_card(pg, 330, 360, "灯"); add_card(pg, 800, 380, "蒼真")
    box = card_box(pg, "灯"); pg.mouse.click(box[0] + box[2] / 2, box[1] + 40); pg.wait_for_timeout(300)
    check("画像を設定する前は、カードに画像が出ない", pg.evaluate("document.querySelector('.card .av').hidden"))
    with pg.expect_file_chooser() as fc:
        pg.click("[data-role=img-choose]")
    fc.value.set_files(str(png)); pg.wait_for_timeout(700)
    info = pg.evaluate("""() => { const im=document.querySelector('.card .av img'); return {hidden:document.querySelector('.card .av').hidden, src:im.src.slice(0,22), w:im.naturalWidth, h:im.naturalHeight}; }""")
    check("画像を選ぶと、カードに表示される", (not info["hidden"]) and info["src"].startswith("data:image/jpeg"), info)
    check("保存用に長辺256px以内へ縮小される", max(info["w"], info["h"]) <= 256 and info["h"] > info["w"], info)
    m = cur(pg); size = len(by_name(m, "灯")["img"])
    check("保存サイズが小さい（ブラウザの保存領域を圧迫しない）", 0 < size < 60000, size)
    pg.fill("#drBody input[type=range]", "60") if False else pg.evaluate("""() => { const r=document.querySelector('#drBody input[type=range]'); r.value=60; r.dispatchEvent(new Event('input',{bubbles:true})); }""")
    pg.wait_for_timeout(200)
    check("表示位置（上下）を調整できる", cur(pg)["cards"][0]["imgY"] == 60 and "60%" in pg.evaluate("document.querySelector('.card .av img').style.objectPosition"))
    check("名前が長くても画像と並んで折り返す（カードの幅が崩れない）", pg.evaluate("document.querySelector('.card').offsetWidth") == 232)
    pg.reload(wait_until="load"); pg.wait_for_timeout(700)
    check("再読み込み後も画像が残る", not pg.evaluate("document.querySelector('.card .av').hidden"))
    # 書き出し・読み込み
    pg.click("#fileBtn")
    with pg.expect_download() as dl:
        pg.click("#exportBtn")
    path = tmp / "out.json"; dl.value.save_as(str(path))
    data = json.loads(path.read_text(encoding="utf-8")); card = data["maps"][0]["cards"][0]
    check("書き出したJSONに画像が含まれる", card["img"].startswith("data:image/jpeg"))
    pg2 = new_page(b)
    pg2.click("#fileBtn")
    with pg2.expect_file_chooser() as fc2:
        pg2.click("#importBtn")
    fc2.value.set_files(str(path)); pg2.wait_for_timeout(1000)
    check("読み込むと画像が復元される", pg2.evaluate("!!document.querySelector('.card .av img') && !document.querySelector('.card .av').hidden"))
    pg2.context.close()
    # ドロップ
    box = card_box(pg, "蒼真")
    b64 = __import__("base64").b64encode(png.read_bytes()).decode()
    pg.evaluate("""([x,y,b64]) => { const bin=atob(b64); const u=new Uint8Array(bin.length); for(let i=0;i<bin.length;i++) u[i]=bin.charCodeAt(i);
        const dt=new DataTransfer(); dt.items.add(new File([u],'a.png',{type:'image/png'}));
        document.getElementById('canvas').dispatchEvent(new DragEvent('drop',{dataTransfer:dt,clientX:x,clientY:y,bubbles:true,cancelable:true})); }""", [box[0] + 100, box[1] + 40, b64])
    pg.wait_for_timeout(800)
    check("画像をカードの上にドロップしても設定できる", by_name(cur(pg), "蒼真")["img"].startswith("data:image/jpeg"))
    # 削除
    box = card_box(pg, "灯"); pg.mouse.click(box[0] + box[2] / 2, box[1] + 40); pg.wait_for_timeout(300)
    pg.click("[data-role=img-delete]"); pg.wait_for_timeout(300)
    check("画像を削除できる", by_name(cur(pg), "灯")["img"] == "")
    # 画像でないファイル
    bad = tmp / "bad.txt"; bad.write_text("not an image")
    with pg.expect_file_chooser() as fc3:
        pg.click("[data-role=img-choose]")
    fc3.value.set_files(str(bad)); pg.wait_for_timeout(500)
    check("画像でないファイルは受け付けず、案内が出る", by_name(cur(pg), "灯")["img"] == "" and "画像を読み込めませんでした" in pg.evaluate("document.getElementById('toast').textContent"))
    check("JSエラーなし", not pg.errors, pg.errors)
    pg.context.close()

def t_arrows(b):
    print("\n[矢印・線がカードに被らない]")
    pg = new_page(b)
    pg.click("#sampleBtn"); pg.wait_for_timeout(900)
    probs = geometry_problems(pg)
    check("サンプルの全リンクで、線と矢印がカードのふちの外にある", not probs, probs)
    # 双方向・片方向の矢印をすべての向きで
    for d in ("ab", "ba", "both"):
        pg.evaluate("""d => { const sel=document.querySelectorAll('.ltag'); }""", d)
    pg = new_page(b)
    add_card(pg, 140, 420, "A"); add_card(pg, 520, 440, "C"); add_card(pg, 900, 420, "B")
    connect(pg, "A", "B", "遠い関係")
    box = card_box(pg, "C")
    m = cur(pg); l = m["links"][0]
    probs = pg.evaluate("""() => { const el=[...document.querySelectorAll('.card')].find(c=>c.getAttribute('aria-label')==='C');
        const t=/translate\\(([-\\d.]+)px,\\s*([-\\d.]+)px\\)/.exec(el.style.transform); const cx=+t[1]+el.offsetWidth/2, cy=+t[2]+el.offsetHeight/2, hw=el.offsetWidth/2, hh=el.offsetHeight/2;
        const g=document.querySelector('.lk'); const n=(g.children[0].getAttribute('d').match(/-?\\d+(?:\\.\\d+)?/g)||[]).map(Number);
        const bad=[]; for(let i=0;i<n.length;i+=2) if(Math.abs(n[i]-cx)<hw+10 && Math.abs(n[i+1]-cy)<hh+10) bad.push([n[i],n[i+1]]); return bad; }""")
    check("間にほかのカードがあっても、線はそのカードの上を通らず避ける", not probs, probs[:3])
    check("避けた場合も、両端はカードの外にある", not geometry_problems(pg))
    # 矢印の向き（片方向・逆・双方向）を切り替えても被らない
    open_link_detail(pg, "遠い関係")
    pg.click("[data-role=edit-basic]"); pg.wait_for_timeout(250)
    for d in ("ab", "ba", "both"):
        pg.click(f".dirs button[data-d={d}]"); pg.wait_for_timeout(200)
        check(f"矢印（{d}）でもカードに被らない", not geometry_problems(pg))
        ah = pg.evaluate("[...document.querySelector('.lk').children].slice(2).map(e=>!!e.getAttribute('d'))")
        check(f"矢印（{d}）の頭が正しい側に出る", ah == {"ab": [False, True], "ba": [True, False], "both": [True, True]}[d], ah)
    # カードを動かしても被らない
    box = card_box(pg, "B"); pg.mouse.move(box[0] + 100, box[1] + 50); pg.mouse.down(); pg.mouse.move(box[0] - 160, box[1] + 150, steps=8); pg.mouse.up(); pg.wait_for_timeout(300)
    check("カードを動かした後も被らない", not geometry_problems(pg))
    check("JSエラーなし", not pg.errors, pg.errors)
    pg.context.close()

def t_free_line(b):
    print("\n[自由な線（曲げの点・形の切り替え）]")
    pg = two_linked(b, "幼なじみ")
    def mid_screen():
        m = cur(pg); v = m["view"]
        P = poly_points(pg.evaluate("document.querySelector('.lk .hit').getAttribute('d')"))
        seg = [((P[i][0] - P[i-1][0]) ** 2 + (P[i][1] - P[i-1][1]) ** 2) ** .5 for i in range(1, len(P))]
        half, acc = sum(seg) / 2, 0.0
        for i, d in enumerate(seg, 1):                     # 線の長さの中央の点
            if acc + d >= half:
                r = (half - acc) / d if d else 0
                w = (P[i-1][0] + (P[i][0] - P[i-1][0]) * r, P[i-1][1] + (P[i][1] - P[i-1][1]) * r); break
            acc += d
        return v["x"] + w[0] * v["k"], v["y"] + w[1] * v["k"]
    check("初期状態では曲げの点がない", cur(pg)["links"][0]["pts"] == [])
    m0 = cur(pg); v0 = m0["view"]
    P0 = poly_points(pg.evaluate("document.querySelector('.lk .hit').getAttribute('d')"))
    q = P0[len(P0) // 4]                                   # 荷札から離れた、線の上の点
    sx, sy = v0["x"] + q[0] * v0["k"], v0["y"] + q[1] * v0["k"]
    pg.mouse.move(sx, sy); pg.mouse.down(); pg.mouse.move(sx + 6, sy + 40, steps=4); pg.mouse.move(sx + 30, sy + 150, steps=8); pg.mouse.up(); pg.wait_for_timeout(300)
    pts = cur(pg)["links"][0]["pts"]
    check("線をつかんで引くと、曲げの点ができる", len(pts) == 1 and abs(pts[0]["v"]) > 0.05, pts)
    check("曲げの点の目印が表示される", pg.evaluate("document.querySelectorAll('.wp').length") == 1)
    wp = pg.evaluate("(()=>{const r=document.querySelector('.wp').getBoundingClientRect();return [r.left+r.width/2,r.top+r.height/2]})()")
    P = poly_points(pg.evaluate("document.querySelector('.lk .hit').getAttribute('d')")); v = cur(pg)["view"]
    dmin = min(((v["x"] + p[0] * v["k"] - wp[0]) ** 2 + (v["y"] + p[1] * v["k"] - wp[1]) ** 2) ** .5 for p in P)
    check("線は曲げの点を通る", dmin < 4, dmin)
    check("曲げた線も両端はカードの外にある", not geometry_problems(pg))
    before = dict(pts[0])
    pg.mouse.move(*wp); pg.mouse.down(); pg.mouse.move(wp[0] + 40, wp[1] - 60, steps=8); pg.mouse.up(); pg.wait_for_timeout(300)
    after = cur(pg)["links"][0]["pts"]
    check("曲げの点をドラッグで動かせる", len(after) == 1 and (abs(after[0]["u"] - before["u"]) > .01 or abs(after[0]["v"] - before["v"]) > .01))
    # カードを動かしても、曲げ方が基準線についてくる
    box = card_box(pg, "蒼真"); pg.mouse.move(box[0] + 100, box[1] + 50); pg.mouse.down(); pg.mouse.move(box[0] + 100, box[1] + 170, steps=8); pg.mouse.up(); pg.wait_for_timeout(300)
    check("カードを動かしても曲げ方（相対位置）が保たれる", cur(pg)["links"][0]["pts"] == after)
    pg.reload(wait_until="load"); pg.wait_for_timeout(700)
    check("再読み込み後も曲げ方が残る", len(cur(pg)["links"][0]["pts"]) == 1)
    open_link_detail(pg, "幼なじみ")
    wp = pg.evaluate("(()=>{const r=document.querySelector('.wp').getBoundingClientRect();return [r.left+r.width/2,r.top+r.height/2]})()")
    pg.mouse.dblclick(*wp); pg.wait_for_timeout(300)
    check("曲げの点はダブルクリックで消せる", cur(pg)["links"][0]["pts"] == [])
    # 形の切り替え
    pg.click("[data-role=edit-basic]"); pg.wait_for_timeout(250)
    pg.click(".dirs button[data-s=straight]"); pg.wait_for_timeout(250)
    P = poly_points(pg.evaluate("document.querySelector('.lk .hit').getAttribute('d')"))
    (x0, y0), (x1, y1) = P[0], P[-1]; L = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** .5
    dev = max(abs((x1 - x0) * (y0 - py) - (x0 - px) * (y1 - y0)) / L for px, py in P)
    check("「まっすぐな線」にすると直線になる", cur(pg)["links"][0]["shape"] == "straight" and dev < 1.5, dev)
    # まっすぐな線でも、曲げの点を足せば折れ線になり、リセットで戻る
    sx, sy = mid_screen()
    pg.mouse.move(sx, sy); pg.mouse.down(); pg.mouse.move(sx + 5, sy + 40, steps=4); pg.mouse.move(sx + 10, sy + 120, steps=6); pg.mouse.up(); pg.wait_for_timeout(300)
    check("まっすぐな線でも曲げの点を足せる", len(cur(pg)["links"][0]["pts"]) == 1)
    pg.click("[data-role=edit-basic]"); pg.wait_for_timeout(250)
    pg.click("text=曲げをリセット"); pg.wait_for_timeout(250)
    check("「曲げをリセット」で曲げの点が消える", cur(pg)["links"][0]["pts"] == [])
    # 点の数の上限
    for i in range(9):
        sx, sy = mid_screen()
        pg.mouse.move(sx, sy); pg.mouse.down(); pg.mouse.move(sx + 5, sy + 30 + i * 3, steps=3); pg.mouse.move(sx + 8, sy + 60 + i * 4, steps=3); pg.mouse.up(); pg.wait_for_timeout(120)
    check("曲げの点は8個まで", len(cur(pg)["links"][0]["pts"]) <= 8)
    check("JSエラーなし", not pg.errors, pg.errors)
    pg.context.close()

def t_mobile(b):
    print("\n[スマホ幅]")
    pg = new_page(b, 390, 844, touch=True)
    pg.tap("#sampleBtn"); pg.wait_for_timeout(900)
    check("横にはみ出さない", pg.evaluate("document.documentElement.scrollWidth") == 390)
    pg.tap("#drawerBtn"); pg.wait_for_timeout(500)
    pg.tap(".prow >> nth=0"); pg.wait_for_timeout(600)
    pg.tap("[data-role=rel-detail] >> nth=0"); pg.wait_for_timeout(500)
    check("スマホでも、人物カードから関係の詳細を開ける", pg.evaluate("document.getElementById('drTitle').textContent") == "関係の詳細")
    check("スマホでも変化記録を追加できる", (pg.tap("[data-role=add-change]"), pg.wait_for_timeout(300), pg.evaluate("document.querySelectorAll('.chg').length") >= 1)[2])
    check("JSエラーなし", not pg.errors, pg.errors)
    pg.context.close()

def main():
    with sync_playwright() as p:
        b = p.chromium.launch()
        for t in (t_existing_features, t_attitudes_and_diffs, t_changes, t_person_view, t_delete, t_legacy, t_image, t_arrows, t_free_line, t_mobile):
            try:
                t(b)
            except Exception as e:
                check(f"{t.__name__} が最後まで実行できた", False, repr(e)[:300])
        b.close()
    failed = [n for n, ok in results if not ok]
    print(f"\n合計 {len(results)} 件中 {len(results) - len(failed)} 件成功、{len(failed)} 件失敗")
    for n in failed: print("  失敗:", n)
    sys.exit(1 if failed else 0)

if __name__ == "__main__":
    main()
