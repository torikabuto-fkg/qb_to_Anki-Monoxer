#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
qb_to_anki.py — QB Scraper JSON + 画像 → Anki デッキ (.apkg) 変換
=====================================================================

QB_Scrape_Ver.5.js で出力された JSON と画像フォルダを読み込み、
Anki にインポート可能な .apkg ファイルを生成する。

使い方:
    python qb_to_anki.py "C 循環器"
    python qb_to_anki.py "C 循環器" --output "C循環器.apkg"
    python qb_to_anki.py "C 循環器" --deck "QB::C 循環器"

前提:
    pip install genanki
"""

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

import genanki


# ============================================================
# Anki モデル定義（カード表面・裏面のテンプレート）
# ============================================================

# モデルIDは固定値（同じモデルなら同じIDにしないとAnkiが混乱する）
MODEL_ID = 1607392319

QB_MODEL = genanki.Model(
    MODEL_ID,
    "QB問題カード",
    fields=[
        {"name": "問題番号"},
        {"name": "掲載頁"},
        {"name": "問題文"},
        {"name": "問題画像"},
        {"name": "選択肢"},
        {"name": "正解"},
        {"name": "正答率"},
        {"name": "解法の要点"},
        {"name": "選択肢解説"},
        {"name": "画像診断"},
        {"name": "解説画像"},
        {"name": "診断"},
        {"name": "主要所見"},
        {"name": "KEYWORD"},
        {"name": "ガイドライン"},
        {"name": "基本事項"},
        {"name": "基本事項画像"},
        {"name": "医ンプット"},
        {"name": "連問情報"},
    ],
    templates=[
        {
            "name": "QB問題",
            "qfmt": """
<div class="qb-card">
  <div class="header">
    <span class="problem-number">{{問題番号}}</span>
    <span class="reference">{{掲載頁}}</span>
  </div>

  <div class="question-text">{{問題文}}</div>

  {{#問題画像}}
  <div class="question-images">{{問題画像}}</div>
  {{/問題画像}}

  {{#連問情報}}
  <div class="serial-info">{{連問情報}}</div>
  {{/連問情報}}

  <div id="raw-choices" style="display:none">{{選択肢}}</div>
  <div id="raw-answer" style="display:none">{{正解}}</div>
  <div id="raw-accuracy" style="display:none">{{正答率}}</div>
  <div id="choices-area"></div>
  <div id="result-banner"></div>
</div>

<script>
(function() {
  var ce = document.getElementById('raw-choices');
  var ae = document.getElementById('raw-answer');
  var area = document.getElementById('choices-area');
  var banner = document.getElementById('result-banner');
  if (!ce || !ae || !area) return;
  var answer = ae.textContent.trim();
  var rawHTML = ce.innerHTML;
  // 連問はプレーン表示にフォールバック
  if (answer.indexOf(':') !== -1 && answer.indexOf('/') !== -1) {
    area.innerHTML = '<div class="choices">' + rawHTML + '</div>';
    return;
  }
  // 正解の文字を解析 ("c" or "a,c,e")
  var correct = {};
  answer.toLowerCase().split(',').forEach(function(a) {
    var t = a.trim(); if (t) correct[t] = true;
  });
  var isMulti = Object.keys(correct).length > 1;
  // 選択肢を行ごとに分割
  var lines = rawHTML.split('<br>').map(function(l) {
    return l.trim();
  }).filter(function(l) {
    return l.length > 0 && l.indexOf('\u2500\u2500') !== 0;
  });
  if (lines.length === 0) {
    area.innerHTML = '<div class="choices">' + rawHTML + '</div>';
    return;
  }
  var btns = [], done = false;
  // 複数選択のヒント
  if (isMulti) {
    var hint = document.createElement('div');
    hint.className = 'multi-hint';
    hint.textContent = '\u8907\u6570\u9078\u629e \u2192 \u300c\u56de\u7b54\u3059\u308b\u300d\u3092\u30bf\u30c3\u30d7';
    area.appendChild(hint);
  }
  lines.forEach(function(line) {
    var btn = document.createElement('div');
    btn.className = 'choice-btn';
    btn.innerHTML = line;
    var m = line.match(/^([a-e]) /i);
    var letter = m ? m[1].toLowerCase() : '';
    btn.setAttribute('data-letter', letter);
    btn.addEventListener('click', function(e) {
      e.stopPropagation(); if (done) return;
      if (isMulti) {
        btn.classList.toggle('selected');
      } else {
        done = true;
        if (correct[letter]) {
          btn.classList.add('correct'); showBanner(true);
        } else {
          btn.classList.add('wrong'); showCorrect(); showBanner(false);
        }
        lockAll();
      }
    });
    btns.push(btn); area.appendChild(btn);
  });
  // 複数選択の確認ボタン
  if (isMulti) {
    var cfm = document.createElement('div');
    cfm.className = 'confirm-btn';
    cfm.textContent = '\u56de\u7b54\u3059\u308b';
    cfm.addEventListener('click', function(e) {
      e.stopPropagation(); if (done) return; done = true;
      var sel = {};
      btns.forEach(function(b) {
        if (b.classList.contains('selected')) sel[b.getAttribute('data-letter')] = true;
      });
      var ok = Object.keys(correct).length === Object.keys(sel).length;
      if (ok) Object.keys(correct).forEach(function(k) { if (!sel[k]) ok = false; });
      btns.forEach(function(b) {
        var l = b.getAttribute('data-letter');
        if (correct[l]) b.classList.add('correct');
        else if (sel[l]) b.classList.add('wrong');
      });
      showBanner(ok); lockAll(); cfm.style.display = 'none';
      var h = area.querySelector('.multi-hint'); if (h) h.style.display = 'none';
    });
    area.appendChild(cfm);
  }
  function showCorrect() {
    btns.forEach(function(b) {
      if (correct[b.getAttribute('data-letter')]) b.classList.add('correct');
    });
  }
  function lockAll() {
    btns.forEach(function(b) { b.classList.add('done'); });
  }
  function showBanner(ok) {
    var acc = document.getElementById('raw-accuracy');
    var at = acc ? acc.textContent.trim() : '';
    var ah = at ? '<div class="banner-accuracy">\u6b63\u7b54\u7387: ' + at + '</div>' : '';
    banner.innerHTML = ok
      ? '<div class="banner-correct">\u2b55 \u6b63\u89e3\uff01</div>' + ah
      : '<div class="banner-wrong">\u274c \u4e0d\u6b63\u89e3</div>' + ah;
    banner.style.display = 'block';
  }
})();
</script>
""",
            "afmt": """
<div class="qb-card">
  <div class="header">
    <span class="problem-number">{{問題番号}}</span>
    <span class="reference">{{掲載頁}}</span>
  </div>

  <div class="question-text">{{問題文}}</div>

  {{#問題画像}}
  <div class="question-images">{{問題画像}}</div>
  {{/問題画像}}

  {{#連問情報}}
  <div class="serial-info">{{連問情報}}</div>
  {{/連問情報}}

  <div class="choices">{{選択肢}}</div>

  <hr id="answer">

  <div class="answer-section">
    <div class="correct-answer">正解: {{正解}}</div>
    {{#正答率}}<div class="accuracy">正答率: {{正答率}}</div>{{/正答率}}
  </div>

  {{#主要所見}}
  <div class="section">
    <div class="section-title">主要所見</div>
    <div class="section-body">{{主要所見}}</div>
  </div>
  {{/主要所見}}

  {{#KEYWORD}}
  <div class="section">
    <div class="section-title">KEYWORD</div>
    <div class="section-body keyword">{{KEYWORD}}</div>
  </div>
  {{/KEYWORD}}

  {{#画像診断}}
  <div class="section">
    <div class="section-title">画像診断</div>
    <div class="section-body">{{画像診断}}</div>
  </div>
  {{/画像診断}}

  {{#解説画像}}
  <div class="explanation-images">{{解説画像}}</div>
  {{/解説画像}}

  {{#診断}}
  <div class="section">
    <div class="section-title">診断</div>
    <div class="section-body">{{診断}}</div>
  </div>
  {{/診断}}

  {{#解法の要点}}
  <div class="section">
    <div class="section-title">解法の要点</div>
    <div class="section-body">{{解法の要点}}</div>
  </div>
  {{/解法の要点}}

  {{#選択肢解説}}
  <div class="section">
    <div class="section-title">選択肢解説</div>
    <div class="section-body option-analysis">{{選択肢解説}}</div>
  </div>
  {{/選択肢解説}}

  {{#ガイドライン}}
  <div class="section">
    <div class="section-title">ガイドライン</div>
    <div class="section-body">{{ガイドライン}}</div>
  </div>
  {{/ガイドライン}}

  {{#基本事項}}
  <div class="section">
    <div class="section-title">基本事項</div>
    <div class="section-body">{{基本事項}}</div>
  </div>
  {{/基本事項}}

  {{#基本事項画像}}
  <div class="basic-images">{{基本事項画像}}</div>
  {{/基本事項画像}}

  {{#医ンプット}}
  <div class="section">
    <div class="section-title">医ンプット</div>
    <div class="section-body">{{医ンプット}}</div>
  </div>
  {{/医ンプット}}
</div>
""",
        },
    ],
    css="""
.qb-card {
    font-family: "Hiragino Kaku Gothic Pro", "Noto Sans JP", "Yu Gothic", sans-serif;
    font-size: 15px;
    line-height: 1.6;
    max-width: 720px;
    margin: 0 auto;
    padding: 12px;
    color: #1a1a1a;
}
.header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 10px;
    padding-bottom: 6px;
    border-bottom: 2px solid #4472C4;
}
.problem-number {
    font-size: 18px;
    font-weight: bold;
    color: #4472C4;
}
.reference {
    font-size: 12px;
    color: #888;
}
.question-text {
    margin: 10px 0;
    white-space: pre-wrap;
}
.question-images img, .explanation-images img, .basic-images img {
    max-width: 100%;
    height: auto;
    margin: 6px 0;
    border-radius: 4px;
    border: 1px solid #ddd;
}
.choices {
    margin: 12px 0;
    padding: 8px 12px;
    background: #f8f9fa;
    border-radius: 6px;
    white-space: pre-wrap;
}
.serial-info {
    margin: 8px 0;
    padding: 8px 12px;
    background: #fff3cd;
    border-left: 4px solid #ffc107;
    border-radius: 4px;
    font-size: 13px;
    white-space: pre-wrap;
}
hr#answer {
    border: none;
    border-top: 3px solid #D32F2F;
    margin: 16px 0;
}
.answer-section {
    text-align: center;
    margin: 12px 0;
}
.correct-answer {
    font-size: 22px;
    font-weight: bold;
    color: #D32F2F;
}
.accuracy {
    font-size: 14px;
    color: #666;
    margin-top: 4px;
}
.section {
    margin: 14px 0;
}
.section-title {
    font-size: 14px;
    font-weight: bold;
    color: #fff;
    background: #4472C4;
    padding: 4px 10px;
    border-radius: 4px 4px 0 0;
}
.section-body {
    padding: 8px 10px;
    background: #f0f4f8;
    border-radius: 0 0 4px 4px;
    white-space: pre-wrap;
    font-size: 14px;
}
.option-analysis {
    font-size: 13px;
}
.keyword {
    font-weight: bold;
    color: #D32F2F;
}
/* ── 5択インタラクティブボタン ── */
#raw-choices, #raw-answer, #raw-accuracy { display: none !important; }
#choices-area { margin: 12px 0; }
.choice-btn {
    display: block; width: 100%; padding: 14px 16px; margin: 8px 0;
    background: #ffffff; border: 2px solid #dee2e6; border-radius: 10px;
    text-align: left; font-size: 15px; line-height: 1.5;
    cursor: pointer; transition: all 0.15s ease;
    -webkit-tap-highlight-color: transparent;
    user-select: none; box-sizing: border-box;
}
.choice-btn:active { transform: scale(0.98); }
.choice-btn.selected {
    border-color: #4472C4; background: #e8f0fe;
    box-shadow: 0 0 0 3px rgba(68,114,196,0.2);
}
.choice-btn.correct {
    border-color: #28a745 !important; background: #d4edda !important; color: #155724;
}
.choice-btn.correct::after { content: ' \2713'; font-weight: bold; color: #28a745; }
.choice-btn.wrong {
    border-color: #dc3545 !important; background: #f8d7da !important; color: #721c24;
}
.choice-btn.wrong::after { content: ' \2717'; color: #dc3545; }
.choice-btn.done { pointer-events: none; }
.choice-btn.done:not(.correct):not(.wrong):not(.selected) { opacity: 0.4; }
.multi-hint {
    text-align: center; color: #856404; font-size: 13px;
    margin: 8px 0; padding: 8px; background: #fff3cd; border-radius: 6px;
}
.confirm-btn {
    display: block; width: 100%; padding: 14px; margin: 12px 0;
    background: #4472C4; color: #fff; border: none; border-radius: 10px;
    font-size: 16px; font-weight: bold; text-align: center;
    cursor: pointer; -webkit-tap-highlight-color: transparent;
}
.confirm-btn:active { background: #3461b0; transform: scale(0.98); }
#result-banner { display: none; margin: 16px 0; text-align: center; }
.banner-correct {
    font-size: 26px; font-weight: bold; color: #28a745;
    padding: 20px; background: #d4edda; border-radius: 12px;
    animation: popIn 0.3s ease;
}
.banner-wrong {
    font-size: 26px; font-weight: bold; color: #dc3545;
    padding: 20px; background: #f8d7da; border-radius: 12px;
    animation: popIn 0.3s ease;
}
.banner-accuracy { font-size: 14px; color: #666; margin-top: 6px; }
@keyframes popIn {
    0% { transform: scale(0.8); opacity: 0; }
    100% { transform: scale(1); opacity: 1; }
}
""",
)


# ============================================================
# ヘルパー関数
# ============================================================

def stable_id(text: str) -> int:
    """文字列から安定した整数IDを生成（Ankiのノート重複判定用）"""
    h = hashlib.md5(text.encode("utf-8")).hexdigest()
    return int(h[:10], 16)


def nl2br(text: str) -> str:
    """改行を <br> に変換"""
    if not text:
        return ""
    return text.replace("\n", "<br>\n")


def escape_html(text: str) -> str:
    """基本的なHTMLエスケープ"""
    if not text:
        return ""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def build_image_tags(
    problem_number: str,
    category: str,
    image_dir: Path,
    media_files: list[str],
) -> str:
    """
    画像フォルダから該当する画像ファイルを探して <img> タグを生成。
    category: "問題", "解説", "基本事項", "医ンプット"
    """
    # パターン: 111B18_問題_1.png, 111B18_問題_2.png, ...
    pattern = re.compile(
        rf"^{re.escape(problem_number)}_{re.escape(category)}_(\d+)\.png$"
    )

    matched = []
    for f in image_dir.iterdir():
        m = pattern.match(f.name)
        if m:
            matched.append((int(m.group(1)), f))

    if not matched:
        return ""

    matched.sort(key=lambda x: x[0])

    tags = []
    for _, fpath in matched:
        media_files.append(str(fpath))
        tags.append(f'<img src="{fpath.name}">')

    return "\n".join(tags)


def format_choices(choices: list) -> str:
    """選択肢リストを整形（文字列 or pdfmakeオブジェクト両対応）"""
    if not choices:
        return ""
    lines = []
    for c in choices:
        if isinstance(c, str):
            lines.append(c)
        elif isinstance(c, dict) and "text" in c:
            lines.append(c["text"])
        else:
            lines.append(str(c))
    return "\n".join(lines)


def format_serial_info(data: dict) -> str:
    """連問情報を整形"""
    if not data.get("isSerial"):
        return ""

    sub_qs = data.get("subQuestions", [])
    if not sub_qs:
        return ""

    parts = ["【連問】"]
    for sq in sub_qs:
        num = sq.get("serialNum", "")
        body = sq.get("body", "")
        choices = sq.get("choices", [])
        parts.append(f"\n■ {num}")
        if body:
            parts.append(body)
        if choices:
            parts.append("\n".join(choices))

    return "\n".join(parts)


# ============================================================
# メイン変換ロジック
# ============================================================

def convert_to_anki(
    json_path: Path,
    image_dir: Path,
    deck_name: str,
    output_path: Path,
    tags: list[str] | None = None,
):
    """JSON + 画像フォルダ → .apkg"""

    print(f"📖 JSON 読み込み中: {json_path}")
    with open(json_path, "r", encoding="utf-8") as f:
        questions = json.load(f)

    print(f"   {len(questions)} 問を読み込みました")

    # デッキID を名前から安定生成
    deck_id = stable_id(deck_name)
    deck = genanki.Deck(deck_id, deck_name)

    media_files: list[str] = []  # apkg に同梱する画像ファイルパス
    card_tags = tags or []

    skipped = 0

    for i, q in enumerate(questions):
        prob = q.get("problem", {})
        result = q.get("result", {})
        expl = q.get("explanation") or {}
        basic = q.get("basic") or {}
        med_input = q.get("medicalInput") or {}

        problem_number = prob.get("problemNumber", "")
        if not problem_number:
            skipped += 1
            continue

        # ── フィールド値を構築 ──
        question_text = nl2br(escape_html(prob.get("questionText", "")))
        reference = escape_html(prob.get("reference", ""))
        choices = nl2br(escape_html(format_choices(prob.get("choices", []))))
        correct_answer = escape_html(result.get("correctAnswer", ""))
        accuracy_rate = escape_html(result.get("accuracyRate", ""))

        # 解説フィールド
        explanation_points = nl2br(escape_html(expl.get("explanationPoints", "")))
        option_analysis = nl2br(escape_html(expl.get("optionAnalysis", "")))
        image_diagnosis = nl2br(escape_html(expl.get("imageDiagnosisText", "")))
        diagnosis = nl2br(escape_html(expl.get("diagnosis", "")))
        findings = nl2br(escape_html(expl.get("findings", "")))
        keyword = nl2br(escape_html(expl.get("keyword", "")))
        guideline = nl2br(escape_html(expl.get("guideline", "")))

        # 基本事項
        basic_text = nl2br(escape_html(basic.get("textContent", "")))

        # 医ンプット
        med_text = nl2br(escape_html(med_input.get("text", "")))

        # 連問
        serial_info = nl2br(escape_html(format_serial_info(q)))

        # ── 画像タグ ──
        prob_images = build_image_tags(problem_number, "問題", image_dir, media_files)
        expl_images = build_image_tags(problem_number, "解説", image_dir, media_files)
        basic_images = build_image_tags(problem_number, "基本事項", image_dir, media_files)

        # ── ノート作成 ──
        # guid にデッキ名を含めて、通常版と1周目を別ノートとして扱う
        note = genanki.Note(
            model=QB_MODEL,
            fields=[
                problem_number,         # 問題番号
                reference,              # 掲載頁
                question_text,          # 問題文
                prob_images,            # 問題画像
                choices,                # 選択肢
                correct_answer,         # 正解
                accuracy_rate,          # 正答率
                explanation_points,     # 解法の要点
                option_analysis,        # 選択肢解説
                image_diagnosis,        # 画像診断
                expl_images,            # 解説画像
                diagnosis,              # 診断
                findings,               # 主要所見
                keyword,                # KEYWORD
                guideline,              # ガイドライン
                basic_text,             # 基本事項
                basic_images,           # 基本事項画像
                med_text,               # 医ンプット
                serial_info,            # 連問情報
            ],
            tags=card_tags,
            guid=genanki.guid_for(f"{deck_name}_{problem_number}"),
        )

        deck.add_note(note)

    # ── パッケージ生成 ──
    print(f"\n📦 Anki パッケージ生成中...")
    print(f"   カード数: {len(deck.notes)}")
    print(f"   画像数: {len(media_files)}")
    if skipped:
        print(f"   スキップ: {skipped} 問（問題番号なし）")

    package = genanki.Package(deck)
    package.media_files = media_files

    output_path.parent.mkdir(parents=True, exist_ok=True)
    package.write_to_file(str(output_path))

    print(f"\n✅ 完了: {output_path}")
    print(f"   ファイルサイズ: {output_path.stat().st_size / 1024 / 1024:.1f} MB")
    print(f"\n💡 Anki で「ファイル → インポート」から {output_path.name} を選択してください")


# ============================================================
# CLI
# ============================================================

def main():
    ap = argparse.ArgumentParser(
        description="QB Scraper JSON + 画像 → Anki デッキ (.apkg) 変換",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  python qb_to_anki.py "C 循環器"
  python qb_to_anki.py "C 循環器" --deck "QB::C 循環器" --tags QB 循環器
  python qb_to_anki.py "C 循環器" --output "my_deck.apkg"

入力フォルダの構成（QB_Scrape_Ver.5.js の出力そのまま）:
  C 循環器/
  ├── C 循環器.json
  └── C 循環器_images/
      ├── 111B18_問題_1.png
      ├── 111B18_解説_1.png
      └── ...
""",
    )

    ap.add_argument(
        "input_dir",
        help="QB Scraper の出力フォルダ（例: 'C 循環器'）",
    )
    ap.add_argument(
        "--json",
        default="",
        help="JSON ファイルパス（省略時: <input_dir>/<input_dir>.json）",
    )
    ap.add_argument(
        "--images",
        default="",
        help="画像フォルダパス（省略時: <input_dir>/<input_dir>_images）",
    )
    ap.add_argument(
        "--output", "-o",
        default="",
        help="出力 .apkg ファイルパス（省略時: <input_dir>.apkg）",
    )
    ap.add_argument(
        "--deck", "-d",
        default="",
        help="Anki デッキ名（省略時: QB::<フォルダ名>）",
    )
    ap.add_argument(
        "--tags", "-t",
        nargs="*",
        default=[],
        help="カードに付けるタグ（スペース区切り）",
    )

    args = ap.parse_args()

    # ── パスの解決 ──
    input_dir = Path(args.input_dir)
    if not input_dir.is_dir():
        print(f"❌ フォルダが見つかりません: {input_dir}", file=sys.stderr)
        sys.exit(1)

    dir_name = input_dir.name

    json_path = Path(args.json) if args.json else input_dir / f"{dir_name}.json"
    if not json_path.is_file():
        print(f"❌ JSON が見つかりません: {json_path}", file=sys.stderr)
        sys.exit(1)

    image_dir = Path(args.images) if args.images else input_dir / f"{dir_name}_images"
    if not image_dir.is_dir():
        print(f"⚠ 画像フォルダが見つかりません: {image_dir}")
        print("  画像なしでカードを生成します")
        image_dir = None

    output_path = Path(args.output) if args.output else Path(f"{dir_name}.apkg")
    deck_name = args.deck if args.deck else f"QB::{dir_name}"

    # ── タグ ──
    tags = args.tags if args.tags else ["QB"]

    # ── 実行 ──
    print(f"🚀 QB → Anki 変換")
    print(f"   入力JSON : {json_path}")
    print(f"   画像フォルダ: {image_dir}")
    print(f"   デッキ名  : {deck_name}")
    print(f"   出力ファイル: {output_path}")
    print(f"   タグ      : {', '.join(tags)}")
    print()

    convert_to_anki(
        json_path=json_path,
        image_dir=image_dir,
        deck_name=deck_name,
        output_path=output_path,
        tags=tags,
    )


if __name__ == "__main__":
    main()
