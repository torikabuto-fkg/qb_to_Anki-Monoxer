#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
qb_to_monoxer.py — QB Scraper JSON + 画像 → Monoxer 用 Excel + 画像ZIP 変換
=============================================================================

QB_Scrape_Ver.5.js で出力された JSON と画像フォルダを読み込み、
Monoxer にインポート可能な Excel (.xlsx) と 画像 ZIP を生成する。

使い方:
    python qb_to_monoxer.py "C 循環器"
    python qb_to_monoxer.py "C 循環器" --output "C循環器_monoxer.xlsx"

前提:
    pip install pandas openpyxl
"""

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path

import pandas as pd


# ============================================================
# ヘルパー関数
# ============================================================

def get_image_list(problem_number: str, category: str, image_dir: Path) -> list[str]:
    """画像フォルダから該当ファイル名のリストを返す（ソート済み）"""
    if not image_dir or not image_dir.exists():
        return []

    pattern = re.compile(
        rf"^{re.escape(problem_number)}_{re.escape(category)}_(\d+)\.png$"
    )
    matched = []
    for f in image_dir.iterdir():
        m = pattern.match(f.name)
        if m:
            matched.append((int(m.group(1)), f.name))

    matched.sort(key=lambda x: x[0])
    return [name for _, name in matched]


def format_choices(choices: list) -> list[str]:
    """選択肢リストを5つに正規化（5択を想定、不足分は空文字）"""
    result = []
    for c in choices:
        if isinstance(c, str):
            result.append(c)
        elif isinstance(c, dict):
            result.append(c.get("text", ""))
        else:
            result.append(str(c))
    # 5つに満たない場合は空文字で埋める
    while len(result) < 5:
        result.append("")
    return result[:5]


# ============================================================
# メイン変換ロジック
# ============================================================

def convert_to_monoxer(
    json_path: Path,
    image_dir: Path | None,
    output_path: Path,
    zip_path: Path | None,
):
    """JSON + 画像フォルダ → Monoxer用 Excel + 画像ZIP"""

    print(f"📖 JSON 読み込み中: {json_path}")
    with open(json_path, "r", encoding="utf-8") as f:
        questions = json.load(f)

    print(f"   {len(questions)} 問を読み込みました")

    rows = []
    all_referenced_images: list[str] = []  # ZIP に含める画像ファイル名
    max_image_cols = 0  # 画像列の最大数を追跡

    skipped = 0

    for q in questions:
        prob = q.get("problem", {})
        result = q.get("result", {})
        expl = q.get("explanation") or {}
        basic = q.get("basic") or {}
        med_input = q.get("medicalInput") or {}

        prob_num = prob.get("problemNumber", "")
        if not prob_num:
            skipped += 1
            continue

        # ── 1. 問題画像 ──
        prob_images = get_image_list(prob_num, "問題", image_dir) if image_dir else []

        # ── 2. 解説テキストの連結（指定の順序）──
        sections = [
            ("【主要所見】", expl.get("findings")),
            ("【KEYWORD】", expl.get("keyword")),
            ("【画像診断】", expl.get("imageDiagnosisText")),
            ("【診断】", expl.get("diagnosis")),
            ("【解法の要点】", expl.get("explanationPoints")),
            ("【選択肢解説】", expl.get("optionAnalysis")),
            ("【ガイドライン】", expl.get("guideline")),
            ("【基本事項】", basic.get("textContent")),
            ("【医ンプット】", med_input.get("text")),
        ]

        full_explanation = ""
        for title, content in sections:
            if content and content.strip():
                full_explanation += f"{title}\n{content.strip()}\n\n"

        # ── 3. 解説側画像リスト（解説 → 基本事項 → 医ンプット の順）──
        expl_images = []
        if image_dir:
            expl_images.extend(get_image_list(prob_num, "解説", image_dir))
            expl_images.extend(get_image_list(prob_num, "基本事項", image_dir))
            expl_images.extend(get_image_list(prob_num, "医ンプット", image_dir))

        # 全画像を統合（問題画像 + 解説画像）
        all_images = prob_images + expl_images
        all_referenced_images.extend(all_images)
        max_image_cols = max(max_image_cols, len(all_images))

        # ── 4. 選択肢の処理 ──
        choice_list = format_choices(prob.get("choices", []))

        # ── 5. 正答率テキスト ──
        accuracy = result.get("accuracyRate", "")
        accuracy_text = f"（正答率 {accuracy}）" if accuracy else ""

        # ── データ行の構築 ──
        row = {
            "問題番号": prob_num,
            "問題文": prob.get("questionText", ""),
            "選択肢1": choice_list[0],
            "選択肢2": choice_list[1],
            "選択肢3": choice_list[2],
            "選択肢4": choice_list[3],
            "選択肢5": choice_list[4],
            "正解": result.get("correctAnswer", ""),
            "正答率": accuracy_text,
            "解説": full_explanation.strip(),
        }

        # 画像列を動的に追加
        for i, img_name in enumerate(all_images):
            row[f"画像{i + 1}"] = img_name

        rows.append(row)

    # ── DataFrame → Excel 出力 ──
    # 画像列を最大数に揃える（空セルで埋める）
    for row in rows:
        for i in range(max_image_cols):
            col = f"画像{i + 1}"
            if col not in row:
                row[col] = ""

    # 列順を固定
    base_cols = [
        "問題番号", "問題文",
        "選択肢1", "選択肢2", "選択肢3", "選択肢4", "選択肢5",
        "正解", "正答率", "解説",
    ]
    img_cols = [f"画像{i + 1}" for i in range(max_image_cols)]
    all_cols = base_cols + img_cols

    df = pd.DataFrame(rows, columns=all_cols)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(str(output_path), index=False, engine="openpyxl")

    print(f"\n✅ Monoxer 用 Excel: {output_path}")
    print(f"   カード数: {len(df)}")
    if skipped:
        print(f"   スキップ: {skipped} 問（問題番号なし）")
    print(f"   画像列数: {max_image_cols}")

    # ── 画像 ZIP 生成 ──
    if image_dir and image_dir.exists() and all_referenced_images:
        if zip_path is None:
            zip_path = output_path.with_suffix(".zip")

        # 重複を除去しつつ順序を保持
        unique_images = list(dict.fromkeys(all_referenced_images))

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            added = 0
            for img_name in unique_images:
                img_file = image_dir / img_name
                if img_file.exists():
                    # ZIP 内ではフラットに（フォルダ階層なし）格納
                    zf.write(img_file, img_name)
                    added += 1
                else:
                    print(f"  ⚠ 画像なし: {img_name}")

        size_mb = zip_path.stat().st_size / 1024 / 1024
        print(f"\n📦 画像 ZIP: {zip_path}")
        print(f"   画像数: {added} / {len(unique_images)}")
        print(f"   サイズ: {size_mb:.1f} MB")
    else:
        print("\n⚠ 画像なし（ZIPは生成しませんでした）")

    print(f"\n💡 Monoxer にインポート:")
    print(f"   1. {output_path.name} をアップロード")
    if zip_path and zip_path.exists():
        print(f"   2. {zip_path.name} を画像としてアップロード")


# ============================================================
# CLI
# ============================================================

def main():
    ap = argparse.ArgumentParser(
        description="QB Scraper JSON + 画像 → Monoxer 用 Excel + 画像ZIP 変換",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  python qb_to_monoxer.py "C 循環器"
  python qb_to_monoxer.py "C 循環器" --output "C循環器_monoxer.xlsx"
  python qb_to_monoxer.py "A 消化管" --json "A 消化管/A 消化管.json"

入力フォルダの構成（QB_Scrape_Ver.5.js の出力そのまま）:
  C 循環器/
  ├── C 循環器.json
  └── C 循環器_images/
      ├── 111B18_問題_1.png
      ├── 111B18_解説_1.png
      └── ...

出力:
  C 循環器_monoxer.xlsx   ← Monoxer にインポートする Excel
  C 循環器_monoxer.zip    ← 画像ファイルの ZIP（Monoxer にアップロード）
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
        help="出力 Excel ファイルパス（省略時: <input_dir>_monoxer.xlsx）",
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
        print("  画像なしで Excel を生成します")
        image_dir = None

    output_path = Path(args.output) if args.output else Path(f"{dir_name}_monoxer.xlsx")
    zip_path = output_path.with_suffix(".zip")

    # ── 実行 ──
    print(f"🚀 QB → Monoxer 変換")
    print(f"   入力JSON  : {json_path}")
    print(f"   画像フォルダ: {image_dir}")
    print(f"   出力Excel : {output_path}")
    print(f"   出力ZIP   : {zip_path}")
    print()

    convert_to_monoxer(
        json_path=json_path,
        image_dir=image_dir,
        output_path=output_path,
        zip_path=zip_path,
    )


if __name__ == "__main__":
    main()
