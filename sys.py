# -*- coding: utf-8 -*-
"""
final_optional.py — RFP/契約 審查（資訊處檢核版）
新增：檢核模式三選一：
- 快：ABCDE 全部一起（最快，但較簡略）
- 中：AB 一起、CDE 一起（中等）
- 慢：逐題檢核（最慢但最精細）
"""
import os, re, json, io
from typing import List, Dict, Any, Tuple
import streamlit as st
import fitz  # PyMuPDF
import pandas as pd
from dotenv import load_dotenv
import google.generativeai as genai

# ---------------- LLM ----------------
load_dotenv()
if os.getenv('GOOGLE_API_KEY'):
    genai.configure(api_key=os.getenv('GOOGLE_API_KEY'))
model = genai.GenerativeModel("gemini-2.5-flash")

# ---------------- 檢核清單 ----------------
def build_rfp_checklist() -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    def add(cat, code, text): items.append({"category":cat, "id":code, "item":text})
    # A
    add("A 基本與前案", "A0", "本案屬開發建置、系統維運、功能增修、套裝軟體、硬體、其他?")
    add("A 基本與前案", "A1", "本案為延續性合約，前案採購簽陳影本已附。")
    add("A 基本與前案", "A2.1", "本案事前曾與資訊處討論：本案相關技術文件由資訊處協助撰寫。")
    add("A 基本與前案", "A2.2", "本案事前曾與資訊處討論：規劃階段曾與資訊處開會討論採購內容並有會議紀錄。")
    add("A 基本與前案", "A2.3", "本案簽辦之前，已以請辦單遞交契約書、需求說明書等相關文件，送請資訊處檢視，並保留至少5個工作天之審閱期後取得回覆。")
    add("A 基本與前案", "A2.4", "本案事前未與資訊處討論（無）。")
    # B
    add("B 現況說明", "B1.1", "提供最新版硬體設備及網路之架構圖(不含IP Address)：明確表達硬體放置區域（含機房/區域）。")
    add("B 現況說明", "B1.2", "提供網路介接方式與開發工具之廠牌、型號、版本等資訊。")
    add("B 現況說明", "B2", "置於本部機房之系統，如另設對外連線線路者，提供連線對象、種類及規格清單。")
    add("B 現況說明", "B3", "提供使用者或使用機關之示意圖或說明。")
    add("B 現況說明", "B4", "提供最新網站網址。")
    add("B 現況說明", "B5", "提供應用系統功能清單或架構圖（含 OS、DB 名稱與版本）。")
    # C
    add("C 資安需求", "C1.1", "符合本部採購契約規範之資訊安全與個資保護要求：已填列安全等級且與最新核定等級相符。")
    add("C 資安需求", "C1.2", "要求系統符合《資通安全責任等級分級辦法》之『資通系統防護基準』、SSDLC 各階段安全工作；要求廠商提交『資通系統防護基準自評表』並增列罰則。")
    add("C 資安需求", "C1.3", "要求廠商之服務水準滿足系統最大可容忍中斷時間（RTO）。")
    add("C 資安需求", "C1.4", "非置於本部機房之核心資通系統，納入 SOC 範圍。")
    add("C 資安需求", "C1.5", "委外需求涉及資通技術服務（如雲端）已評估合法性、技術維運、法遵與權利義務歸屬。")
    add("C 資安需求", "C1.6", "要求廠商不得使用或設計不符安全規範之帳號密碼。")
    add("C 資安需求", "C2.1", "巨額/資安採購或高級安全等級案件：投標廠商具備安全軟體開發能力並通過資安管理系統驗證。")
    add("C 資安需求", "C2.2", "巨額/資安/高級：專案管理人員至少1人具資訊安全專業認證。")
    add("C 資安需求", "C2.3", "巨額/資安/高級：專案技術人員至少1人具網路安全技能之訓練證書或證照。")
    add("C 資安需求", "C3.1", "允許分包者：分包廠商須比照承包廠商共同遵守資安規定。")
    add("C 資安需求", "C3.2", "允許分包者：投標廠商於建議書敘明分包廠商基本資料。")
    add("C 資安需求", "C4", "不得採用大陸廠牌資通訊產品（契約草案第八條(六)及(二 五)）。")
    add("C 資安需求", "C5", "符合『資通系統籌獲各階段資安強化措施執行檢核表』（開發附表1/維運附表2）。")
    add("C 資安需求", "C6", "資料庫中機敏資料已採用或規劃適當加密技術。")
    # D（節錄）
    add("D 作業需求", "D1", "列出所需軟硬體與網路設備清單，說明使用資訊處設備/既有設備或另行採購（優先 VM/共同供應契約）。")
    add("D 作業需求", "D2", "系統開發或功能增修應列出所需系統功能（地方政府系統建議提供資料下載或介接）。")
    add("D 作業需求", "D3", "敘明資訊系統與其他軟體系統之相互關係並說明所有利害關係人。")
    add("D 作業需求", "D4", "提供民眾下載檔案者，增加 ODF 格式。")
    add("D 作業需求", "D5", "開發 App 已閱讀並遵循國發會相關規定（附件2）。")
    add("D 作業需求", "D6", "開發 App 符合通傳會『App 無障礙開發指引』並填報檢核表（附件3）。")
    add("D 作業需求", "D7", "網站服務之系統符合國發會『政府網站服務管理規範』並填報檢核表（附件4）。")
    add("D 作業需求", "D8", "針對業務或個人資料，提供後續 OpenData 或 MyData 服務建議。")
    add("D 作業需求", "D9", "系統維護包含定期到場、緊急到場、諮詢服務；SLA 與績效指標連動並設計滿意度調查。")
    add("D 作業需求", "D10", "履約服務銜接契約期間。")
    add("D 作業需求", "D11", "開發及測試設備與環境需求說明。")
    add("D 作業需求", "D12", "教育訓練及客服服務。")
    add("D 作業需求", "D13", "保固服務。")
    add("D 作業需求", "D14", "產品授權 (License) 符合需求。")
    add("D 作業需求", "D15", "作業需求必須納入之制式文句（詳註5）。")
    add("D 作業需求", "D16", "如有 GIS / OpenData / MyData 作業需求，納入之制式文句（詳註6）。")
    add("D 作業需求", "D17", "上線前完成需求訪談、需求確認與測試（含效能測試）；提交測試計畫與測試報告。")
    add("D 作業需求", "D18", "涉及醫療/健康資料交換者，納入 FHIR 交換標準。")
    add("D 作業需求", "D19", "功能需求設計考量導入 AI 以節省人力/避免錯誤與決策分析及風險預警。")
    # E
    add("E 產品交付", "E1", "交付時程合理，並與開發方式（瀑布/敏捷）一致。")
    add("E 產品交付", "E2", "開發/增修交付品完整（專案計畫、需求/設計、測試計畫/報告、建置計畫、手冊、教育訓練、保固紀錄、原始碼/執行碼、最高權限帳密、自評表與電子檔）。")
    add("E 產品交付", "E3", "維護交付品（專案執行計畫、維護工作報告、最新版設計/手冊、最新版原始碼/執行碼、自評表與電子檔）。")
    add("E 產品交付", "E4", "必須納入之制式文句（詳註8）：交付之原始程式碼、執行碼，本部得要求承包廠商於本部指定之環境進行再生測試，並應提供所使用之開發工具，以驗證其正確性。")
    add("E 產品交付", "E5", "網路設備購置時，驗收以彌封方式交付帳密、設定檔、規則列表與架構等。")
    return items

# ---------------- 分群工具 ----------------
def group_items_by_ABCDE(items: List[Dict[str, Any]]) -> List[Tuple[str, List[Dict[str, Any]]]]:
    return [("ABCDE", items)] if items else []

def group_items_by_AB_CDE(items: List[Dict[str, Any]]) -> List[Tuple[str, List[Dict[str, Any]]]]:
    ab  = [it for it in items if it['id'] and it['id'][0] in ('A','B')]
    cde = [it for it in items if it['id'] and it['id'][0] in ('C','D','E')]
    groups = []
    if ab:  groups.append(('AB', ab))
    if cde: groups.append(('CDE', cde))
    return groups

def group_items_by_AB_C_D_E(items: List[Dict[str, Any]]) -> List[Tuple[str, List[Dict[str, Any]]]]:
    ab = [it for it in items if it['id'] and it['id'][0] in ('A','B')]
    c  = [it for it in items if it['id'] and it['id'][0] == 'C']
    d  = [it for it in items if it['id'] and it['id'][0] == 'D']
    e  = [it for it in items if it['id'] and it['id'][0] == 'E']
    groups = []
    if ab: groups.append(('AB', ab))
    if c:  groups.append(('C', c))
    if d:  groups.append(('D', d))
    if e:  groups.append(('E', e))
    return groups

# 逐題排序（AB→C→D→E）
def order_items_AB_C_D_E(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    order_map = {'A':0,'B':1,'C':2,'D':3,'E':4}
    return sorted(items, key=lambda it: (order_map.get(it['id'][0], 9), it['id']))

# ---------------- PDF 解析 ----------------
def extract_text_with_headers(pdf_bytes: bytes, filename: str) -> str:
    doc = fitz.open(stream=pdf_bytes, filetype='pdf')
    parts = []
    for i, page in enumerate(doc, start=1):
        text = page.get_text('text').strip()
        if not text:
            blocks = page.get_text('blocks')
            text = "\n\n".join([b[4].strip() for b in blocks if b[4].strip()])
        parts.append(f"\n\n===== 【檔案: {filename} | 頁: {i}】 =====\n" + text)
    return "\n".join(parts)

# ---------------- Prompts ----------------
def make_batch_prompt(batch_code: str, items: List[Dict[str, Any]], corpus_text: str) -> str:
    checklist_lines = "\n".join([f"{it['id']}｜{it['item']}" for it in items])
    return f"""
你是政府機關資訊處之採購/RFP/契約審查委員。請依下列「檢核條目（{batch_code} 批）」逐條審查文件內容並回傳**唯一 JSON 陣列**，陣列內每個元素對應一條條目。
【審查原則】
1) 僅依文件明載內容判斷；未提及即標示「未提及」。
2) 若屬不適用（例：未允許分包），請回「不適用」並說明依據。
3) 務必引用原文短句與檔名/頁碼作為 evidence。
4) ***嚴禁輸出任何與規格聯絡人、電話、姓名、聯繫方式有關的文字，即使原始文件內有。*******

【輸出格式 — 僅能輸出 JSON 陣列，無任何多餘文字/標記】
[
  {{
    "id": "A1",
    "category": "A 基本與前案",
    "item": "條目原文（請完整複製）",
    "compliance": ""compliance": "若 id = 'A0'：僅能輸出六選一【開發建置｜系統維運｜功能增修｜套裝軟體｜硬體｜其他】；若 id ≠ 'A0'：僅能輸出四選一【符合｜部分符合｜未提及｜不適用】；禁止同時輸出多個或其他文字"
",
    "evidence": [{{"file": "檔名", "page": 頁碼, "quote": "逐字引述"}}],
    "recommendation": "若未提及/部分符合，請給具體補強方向；否則留空"
  }}
]
【本批檢核清單（id｜item）】
{checklist_lines}
【文件全文（含檔名/頁碼標註）】
{corpus_text}
"""

def make_single_prompt(item: Dict[str, Any], corpus_text: str) -> str:
    return make_batch_prompt(item['id'], [item], corpus_text)

# ---------------- 解析 ----------------
def parse_json_array(text: str) -> List[Dict[str, Any]]:
    t = text.strip()
    t = re.sub(r'^```(?:json)?', '', t, flags=re.I).strip()
    t = re.sub(r'```$', '', t, flags=re.I).strip()
    if t.startswith('{') and t.endswith('}'):
        try:
            d = json.loads(t)
            return [d]
        except Exception:
            pass
    start = t.find('[')
    end = t.rfind(']')
    if start != -1 and end != -1 and end > start:
        t = t[start:end+1]
    data = json.loads(t)
    if isinstance(data, dict):
        data = [data]
    return data

# ---------------- 報表 ----------------
def to_dataframe(results: List[Dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for r in results:
        ev_text = "\n".join([f"{e.get('file','')} p.{e.get('page','')}：{e.get('quote','')}" for e in r.get('evidence', [])])
        rows.append({
            "類別": r.get("category",""),
            "編號": r.get("id",""),
            "檢核項目": r.get("item",""),
            "符合情形": r.get("compliance",""),
            "主要證據": ev_text,
            "改善建議": r.get("recommendation",""),
        })
    df = pd.DataFrame(rows)
    try:
        df["主碼"] = df["編號"].str.extract(r"([A-Z])")
        df["子碼值"] = pd.to_numeric(df["編號"].str.extract(r"(\d+(?:\.\d+)?)")[0], errors='coerce')
        df = df.sort_values(["主碼","子碼值"], kind='mergesort').drop(columns=["主碼","子碼值"])
    except Exception:
        pass
    return df

# ---------------- 表格 ----------------
def render_wrapped_table(df: pd.DataFrame, height_vh: int = 80):
    df2 = df.copy()
    for c in df2.columns:
        df2[c] = df2[c].astype(str).str.replace('\n','<br>')
    style = f"""
    <style>
    .wrap-table-container {{max-height:{height_vh}vh; overflow:auto; border:1px solid #e5e7eb; border-radius:8px;}}
    .wrap-table-container table {{width:100%; border-collapse:collapse; table-layout:fixed; font-size:14px;}}
    .wrap-table-container th, .wrap-table-container td {{border:1px solid #efefef; padding:6px 10px; text-align:left; vertical-align:top; white-space:pre-wrap; word-break:break-word;}}
    .wrap-table-container thead th {{position:sticky; top:0; background:#fafafa; z-index:1;}}
    </style>
    """
    st.markdown(style, unsafe_allow_html=True)
    html = df2.to_html(index=False, escape=False)
    st.markdown(f'<div class="wrap-table-container">{html}</div>', unsafe_allow_html=True)

# ---------------- 主程式（三種模式） ----------------
def main():
    st.set_page_config("📑 RFP/契約審查系統", layout="wide")
    st.title("📑 資訊服務採購 RFP/契約審查系統")

    uploaded_files = st.file_uploader("📥 上傳 RFP/契約 PDF（可複選）", type=["pdf"], accept_multiple_files=True)
    project_name = st.text_input("案件/專案名稱（將用於檔名）", value="未命名案件")
    
    mode = st.radio(
        "檢核模式",
        (
            "一次性審查",
            "批次審查",
            "逐題審查",
        ),
        horizontal=True,
    )

    if st.button("🚀 開始審查", disabled=not uploaded_files):
        checklist_all = build_rfp_checklist()

        # 進度條設定
        progress_text = st.empty(); progress_bar = st.progress(0)
        def set_progress(p, msg):
            progress_bar.progress(max(0, min(int(p), 100))); progress_text.write(msg)

        # 1) 解析 PDF（至 35%）
        set_progress(5, "📄 解析與彙整文件文字…")
        corpora = []; total_files = len(uploaded_files)
        for i, f in enumerate(uploaded_files):
            set_progress(int((i/ max(1,total_files))*30), f"📄 解析 {f.name} ({i+1}/{total_files})…")
            pdf_bytes = f.read(); text = extract_text_with_headers(pdf_bytes, f.name)
            corpora.append(text)
        corpus_text = "\n\n".join(corpora)
        set_progress(35, "🧩 檢核準備中…")

        all_results: List[Dict[str, Any]] = []

        if mode.startswith("一"):
            # ---- 全部一起（1 批） ----
            groups = group_items_by_ABCDE(checklist_all)
            st.info("一次性審查中")
        elif mode.startswith("批"):
            # ---- 兩批：AB + CDE ----
            groups = group_items_by_AB_CDE(checklist_all)
            st.info("批次審查中")
        else:
            groups = None  # 逐題模式不用 groups

        if groups is not None:
            # 批次模式（快 or 中）
            total_batches = len(groups)
            for bi, (code, items) in enumerate(groups):
                set_progress(35 + int((bi/ max(1,total_batches))*55), f"🔎 第 {bi+1}/{total_batches} 批（{code}）… 共 {len(items)} 項")
                prompt = make_batch_prompt(code, items, corpus_text)
                try:
                    resp = model.generate_content(prompt)
                    arr = parse_json_array(resp.text)
                except Exception:
                    arr = []
                allowed_ids = {it['id'] for it in items}
                id_to_meta = {it['id']: it for it in items}
                normalized = []
                for d in arr if isinstance(arr, list) else []:
                    if not isinstance(d, dict):
                        continue
                    rid = d.get('id')
                    if rid not in allowed_ids:
                        continue
                    meta = id_to_meta[rid]
                    normalized.append({
                        'id': rid,
                        'category': d.get('category', meta['category']),
                        'item': d.get('item', meta['item']),
                        'compliance': d.get('compliance', ''),
                        'evidence': d.get('evidence', []),
                        'recommendation': d.get('recommendation', ''),
                    })
                returned_ids = {x['id'] for x in normalized}
                for it in items:
                    if it['id'] not in returned_ids:
                        normalized.append({
                            'id': it['id'], 'category': it['category'], 'item': it['item'],
                            'compliance': '未提及', 'evidence': [], 'recommendation': ''
                        })
                all_results.extend(normalized)
        else:
            # 逐題模式（慢）
            items_ordered = order_items_AB_C_D_E(checklist_all)
            total_items = len(items_ordered)
            st.info("逐題檢核中")
            for i, it in enumerate(items_ordered):
                set_progress(35 + int((i/ max(1,total_items))*55), f"🧾 第 {i+1}/{total_items} 題：{it['id']} …")
                prompt = make_single_prompt(it, corpus_text)
                try:
                    resp = model.generate_content(prompt)
                    arr = parse_json_array(resp.text)
                except Exception:
                    arr = []
                picked = None
                for d in arr if isinstance(arr, list) else []:
                    if isinstance(d, dict) and d.get('id') == it['id']:
                        picked = d; break
                if picked is None:
                    picked = {
                        'id': it['id'], 'category': it['category'], 'item': it['item'],
                        'compliance': '未提及', 'evidence': [], 'recommendation': ''
                    }
                else:
                    picked.setdefault('category', it['category'])
                    picked.setdefault('item', it['item'])
                    picked.setdefault('compliance', '')
                    picked.setdefault('evidence', [])
                    picked.setdefault('recommendation', '')
                all_results.append(picked)

        set_progress(92, "📦 彙整與轉表格…")
        df = to_dataframe(all_results)
        st.success("✅ 審查完成")
        render_wrapped_table(df, height_vh=80)

        # Excel（自動換行）
        try:
            from openpyxl.styles import Alignment
            xbio = io.BytesIO()
            with pd.ExcelWriter(xbio, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='檢核結果')
                ws = writer.sheets['檢核結果']
                for row in ws.iter_rows(min_row=1, max_row=ws.max_row, min_col=1, max_col=ws.max_column):
                    for cell in row:
                        cell.alignment = Alignment(wrap_text=True, vertical='top')
                for col_cells in ws.columns:
                    max_len = 12
                    for c in col_cells:
                        val = str(c.value) if c.value is not None else ''
                        max_len = max(max_len, min(80, len(val)))
                    ws.column_dimensions[col_cells[0].column_letter].width = min(60, max_len * 1.2)
            xbio.seek(0)
            st.download_button(
                label='📥 下載 Excel（自動換行）',
                data=xbio.getvalue(),
                file_name=f"{project_name}_RFP_Contract_Checklist.xlsx",
                mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )
        except Exception as e:
            st.warning(f"Excel 匯出失敗：{e}")

        progress_text.empty(); progress_bar.empty()

if __name__ == '__main__':
    main()
