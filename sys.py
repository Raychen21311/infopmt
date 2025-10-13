# -*- coding: utf-8 -*-
"""
sys.py — RFP/契約 審查（資訊處檢核版） + 預先審查表（PDF 專用）

此次調整（2025-10-13）：
- 檢核模式：僅保留「一次性審查」，暫停批次與逐題模式。
- 顯示內容：只保留「差異對照表」與「建議回覆內容」兩個區塊。
- 建議回覆內容：
  * 新增『預算金額』規則式抽取（依文件判斷，轉換為「萬元」並附來源檔名/頁碼/引句）。
  * 固定參考項目（醫療資料標準、檢核表制式文句）以側邊展開顯示，預設不自動寫入草稿。
  * 保留可下載 Word 草稿（.docx）。
- Excel 匯出：僅輸出「差異對照」工作表。

保留原有流程：
- 上傳 RFP/契約 PDF（可複選）→ 依檢核清單一次性審查。
- 上傳「執行單位預先審查表」PDF（可複選/可略過）→ LLM 結構化抽取（顯示層面不再呈現，但用於差異對照）。

"""

import os
import re
import json
import io
import unicodedata
from typing import List, Dict, Any, Tuple

import streamlit as st
import fitz  # PyMuPDF
import pandas as pd
from difflib import SequenceMatcher
from docx import Document

from dotenv import load_dotenv
import google.generativeai as genai

# --------------------- LLM 初始化 ---------------------
load_dotenv()
if os.getenv('GOOGLE_API_KEY'):
    genai.configure(api_key=os.getenv('GOOGLE_API_KEY'))
model = genai.GenerativeModel("gemini-2.5-flash")

# --------------------- 檔案型態 ---------------------
def is_pdf(name: str) -> bool:
    return name.lower().endswith(".pdf")

# ==================== 檢核清單（含 F 其他重點） ====================
def build_rfp_checklist() -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    def add(cat, code, text):
        items.append({"category": cat, "id": code, "item": text})

    # A 基本與前案
    add("A 基本與前案", "A0", "本案屬開發建置、系統維運、功能增修、套裝軟體、硬體、其他?")
    add("A 基本與前案", "A1", "本案為延續性合約，前案採購簽陳影本已附。")
    add("A 基本與前案", "A2.1", "本案事前曾與資訊處討論：本案相關技術文件由資訊處協助撰寫。")
    add("A 基本與前案", "A2.2", "本案事前曾與資訊處討論：規劃階段曾與資訊處開會討論採購內容並有會議紀錄。")
    add("A 基本與前案", "A2.3", "本案簽辦之前，已以請辦單遞交契約書、需求說明書等相關文件，送請資訊處檢視，並保留至少5個工作天之審閱期後取得回覆。")
    add("A 基本與前案", "A2.4", "本案事前未與資訊處討論（無）。")

    # B 現況說明
    add("B 現況說明", "B1.1", "提供最新版硬體設備及網路之架構圖(不含IP Address)：明確表達硬體放置區域（含機房/區域）。")
    add("B 現況說明", "B1.2", "提供網路介接方式與開發工具之廠牌、型號、版本等資訊。")
    add("B 現況說明", "B2", "置於本部機房之系統，如另設對外連線線路者，提供連線對象、種類及規格清單。")
    add("B 現況說明", "B3", "提供使用者或使用機關之示意圖或說明。")
    add("B 現況說明", "B4", "提供最新網站網址。")
    add("B 現況說明", "B5", "提供應用系統功能清單或架構圖（含 OS、DB 名稱與版本）。")

    # C 資安需求
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
    add("C 資安需求", "C3.2", "允許分包者：投標廠商於服務建議書敘明分包廠商基本資料。")
    add("C 資安需求", "C4", "不得採用大陸廠牌資通訊產品（契約草案第八條(六)及(二五)）。")
    add("C 資安需求", "C5", "符合『資通系統籌獲各階段資安強化措施執行檢核表』（開發附表1/維運附表2）。")
    add("C 資安需求", "C6", "資料庫中機敏資料已採用或規劃適當加密技術。")

    # D 作業需求（節錄）
    add("D 作業需求", "D1", "列出所需軟硬體與網路設備清單，說明使用資訊處設備/既有設備或另行採購（優先 VM/共同供應契約）。")
    add("D 作業需求", "D2", "系統開發或功能增修應列出所需系統功能（地方政府系統建議提供資料下載或介接）。")
    add("D 作業需求", "D3", "敘明資訊系統與其他軟體系統之相互關係並說明所有利害關係人。")
    add("D 作業需求", "D4", "提供民眾下載檔案者，增加 ODF 格式。")
    add("D 作業需求", "D5", "開發 App 已閱讀並遵循國發會相關規定（附件2）。")
    add("D 作業需求", "D6", "開發 App 符合通傳會『App 無障礙開發指引』並填報檢核表（附件3）。")
    add("D 作業需求", "D7", "網站服務之系統符合國發會『政府網站服務管理規範』並填報檢核表（附件4）。")
    add("D 作業需求", "D8", "針對業務或個人資料，提供後續 OpenData 或 MyData 服務建議。")
    add("D 作業需求", "D9", "系統維護包含定期到場、緊急到場、諮詢服務；SLA 與績效指標連動並設計使用者滿意度調查。")
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

    # E 產品交付
    add("E 產品交付", "E1", "交付時程合理，並與開發方式（瀑布/敏捷）一致。")
    add("E 產品交付", "E2", "開發/增修交付品完整（專案計畫、需求/設計、測試計畫/報告、建置計畫、手冊、教育訓練、保固紀錄、原始碼/執行碼、最高權限帳密、自評表與電子檔）。")
    add("E 產品交付", "E3", "維護交付品（專案執行計畫、維護工作報告、最新版設計/手冊、最新版原始碼/執行碼、自評表與電子檔）。")
    add("E 產品交付", "E4", "必須納入之制式文句（詳註8）：交付之原始程式碼、執行碼，本部得要求承包廠商於本部指定之環境進行再生測試，並應提供所使用之開發工具，以驗證其正確性。")
    add("E 產品交付", "E5", "網路設備購置時，驗收以彌封方式交付帳密、設定檔、規則列表與架構等。")

    # F 其他重點（依預審表）
    add("F 其他重點", "F1", "使用本部機房 VM、共用資料庫，已完成評估及成本分攤表填寫，並已分攤經費。")
    add("F 其他重點", "F2", "經費預估之合理性及經資門歸類之正確性；維護費用計算比率應逐年遞減（不含既有擴增且過保固部分）。")
    add("F 其他重點", "F3", "採購內容無前後不一致情形。")
    add("F 其他重點", "F4", "對照作業需求檢查契約書「服務水準及績效違約金」之內容有無缺漏。")
    add("F 其他重點", "F5", "採購契約書「履約標的」內容正確，無缺漏。")
    add("F 其他重點", "F6", "開發或增修系統之介接內容，已洽相關單位同意，並確認對方系統增修及經費來源。")
    add("F 其他重點", "F7", "目前使用之硬體設備於履約完成後，如汰換或不再使用者，規劃下架日期。")
    add("F 其他重點", "F8", "準用最有利標之評選項目與配分，附錄可依需求調整整併並同步修正相關附錄。")

    return items

# ==================== 分群/排序工具（僅用一次性 ABCDE） ====================
def group_items_by_ABCDE(items: List[Dict[str, Any]]) -> List[Tuple[str, List[Dict[str, Any]]]]:
    return [("ABCDE", items)] if items else []

# 保留函式（目前不使用）
def group_items_by_AB_CDE(items: List[Dict[str, Any]]) -> List[Tuple[str, List[Dict[str, Any]]]]:
    ab = [it for it in items if it['id'] and it['id'][0] in ('A','B')]
    cdef = [it for it in items if it['id'] and it['id'][0] in ('C','D','E','F')]
    groups = []
    if ab: groups.append(('AB', ab))
    if cdef: groups.append(('CDEF', cdef))
    return groups

# 保留（逐題排序，目前不使用）
def order_items_AB_C_D_E(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    order_map = {'A':0,'B':1,'C':2,'D':3,'E':4,'F':5}
    return sorted(items, key=lambda it: (order_map.get(it['id'][0], 9), it['id']))

# ==================== PDF 解析 ====================
def extract_text_with_headers(pdf_bytes: bytes, filename: str) -> str:
    doc = fitz.open(stream=pdf_bytes, filetype='pdf')
    parts = []
    for i, page in enumerate(doc, start=1):
        text = page.get_text('text').strip()
        if not text:
            blocks = page.get_text('blocks')
            text = "\n\n".join([b[4].strip() for b in blocks if b[4].strip()])
        parts.append(f"\n\n===== 【檔案: {filename} 頁: {i}】 =====\n" + text)
    return "\n".join(parts)

# ==================== LLM Prompts ====================
def make_batch_prompt(batch_code: str, items: List[Dict[str, Any]], corpus_text: str) -> str:
    checklist_lines = "\n".join([f"{it['id']}｜{it['item']}" for it in items])
    return f"""
你是政府機關資訊處之採購/RFP/契約審查委員。請依下列「檢核條目（{batch_code} 批）」逐條審查文件內容並回傳**唯一 JSON 陣列**，陣列內每個元素對應一條條目。
【審查原則】
1) 僅依文件明載內容判斷；未提及即標示「未提及」。
2) 若屬不適用（例：未允許分包），請回「不適用」並說明依據。
3) 務必引用原文短句與檔名/頁碼作為 evidence。
4) ***嚴禁輸出任何與規格聯絡人、電話、姓名、聯繫方式有關的文字，即使原始文件內有。***
5) 若 id = 'A1'，請回復"請檢視是否已附前案採購簽陳影本，以確保採購流程的延續性與合法性檢視基礎。"
6) 若 id = 'A2.1、A2.2、A2.3 或 A2.4'，原則上預審表結果為不適用即為不適用，並提醒使用者再次核實。
【輸出格式 — 僅能輸出 JSON 陣列，無任何多餘文字/標記】
[
  {{
    "id": "A1",
    "category": "A 基本與前案",
    "item": "條目原文（請完整複製）",
    "compliance": "若 id = 'A0'：僅能輸出六選一【開發建置｜系統維運｜功能增修｜套裝軟體｜硬體｜其他】；若 id ≠ 'A0'：僅能輸出四選一【符合｜部分符合｜未提及｜不適用】；禁止同時輸出多個或其他文字",
    "evidence": {{ "file": "檔名", "page": "頁碼", "quote": "逐字引述" }},
    "recommendation": "若未提及/部分符合，請給具體補強方向；否則留空"
  }}
]
【本批檢核清單（id｜item）】
{checklist_lines}
【文件全文（含檔名/頁碼標註）】
{corpus_text}
""".strip()

def make_single_prompt(item: Dict[str, Any], corpus_text: str) -> str:
    return make_batch_prompt(item['id'], [item], corpus_text)

def make_precheck_parse_prompt(corpus_text: str) -> str:
    return f"""
你是政府機關資訊處之採購審查助理。以下是一份或多份「執行單位預先審查表」的 PDF 文字（已標註檔名與頁碼）。
請將表格/條列逐列轉為 **JSON 陣列**，每列一筆，欄位如下（顯示僅用到前五欄，其餘僅供判斷用）：
【顯示用必填 5 欄】
- "id": 先填你能辨識的粗編號（如「案件性質-1.」「現況說明-1.(2)」「A2.3」等；若無可留空）
- "item": 檢核項目（擷取要點，不要省略）
- "status": 僅能輸出二選一【符合｜不適用】；若該列未勾選任何選項，請輸出空字串 ""
- "biz_ref_note": 對應頁次或補充說明
【輔助判斷欄（可缺漏）】
- "section_title"、"main_no"、"sub_no"、"std_id"、"evidence": 至少一筆：{"file":"...", "page": 頁碼, "quote":"..."}
【重要版面規則（請嚴格遵循）】略（同原規則）
【A0 特例（多選）】略（同原規則）
【安全規範】禁止輸出任何聯絡資訊（姓名、電話、Email 等）。
【輸出格式 — 僅能輸出 JSON 陣列，無多餘文字】
[ {{ "id": "現況說明-1.(2)", "item": "...", "status": "符合", "biz_ref_note": "...", "std_id": "B1.2" }} ]
【文件全文（含檔名/頁碼標註）】
{corpus_text}
""".strip()

# ==================== 解析/轉表工具 ====================
def parse_json_array(text: str) -> List[Dict[str, Any]]:
    t = (text or "").strip()
    # 去除可能的 ```json 包裹
    t = re.sub(r'^```(?:json)?', '', t, flags=re.I).strip()
    t = re.sub(r'```$', '', t, flags=re.I).strip()
    # 嘗試擷取最外層陣列
    start = t.find('['); end = t.rfind(']')
    if start != -1 and end != -1 and end > start:
        t = t[start:end+1]
    try:
        data = json.loads(t)
        if isinstance(data, dict):
            data = [data]
        return data if isinstance(data, list) else []
    except Exception:
        return []

def _format_evidence_list(e_list: List[Dict[str, Any]]) -> str:
    lines = []
    for e in e_list or []:
        file = e.get('file','')
        page = e.get('page', None)
        quote = e.get('quote','')
        tag = f"p.{page}" if page not in (None, "", "n/a") else ""
        lines.append(f"{file} {tag}：{quote}".strip())
    return "\n".join(lines)

# 預審狀態正規化（兩態→四態比對用）
def normalize_status_equiv(s: str) -> str:
    if s is None: return "未提及"
    t = re.sub(r"\s+", "", str(s)).lower()
    if t == "": return "未提及"
    if t in ("符合", "ok", "pass", "通過"): return "符合"
    if t in ("不適用", "na", "n/a"): return "不適用"
    return "未提及"

SECTION_TO_LETTER = {
    "案件性質": "A",
    "現況說明": "B",
    "資安需求": "C",
    "作業需求": "D",
    "產品交付": "E",
    "其他重點": "F",
}
ROMAN_TO_LETTER = {"一":"A","二":"B","三":"C","四":"D","五":"E","六":"F"}
STD_ID_PATTERN = re.compile(r"^[A-F]\d+(?:\.\d+)?$")

def compute_std_id(raw_id: str, item: str) -> str:
    s = (raw_id or "").strip()
    if STD_ID_PATTERN.match(s):
        return s
    src = f"{raw_id} {item}".strip()
    sec_letter = ""
    for zh, letter in SECTION_TO_LETTER.items():
        if zh in src:
            sec_letter = letter; break
    if not sec_letter:
        for zh, letter in ROMAN_TO_LETTER.items():
            if f"{zh}、" in src or f"{zh} " in src:
                sec_letter = letter; break
    # 抓主號/次號（簡化版）
    m_main = re.search(r"-(\d+)", raw_id or "") or re.search(r"(\d+)", src)
    n1 = m_main.group(1) if m_main else None
    m_sub = re.search(r"\((\d+)\)", src)
    n2 = m_sub.group(1) if m_sub else None
    if sec_letter and n1:
        return f"{sec_letter}{n1}" + (f".{n2}" if n2 else "")
    return ""

# 解析預審 JSON → 製作 5 欄顯示表（目前僅供差異對照，UI不顯示）
def parse_precheck_json(text: str) -> List[Dict[str, Any]]:
    data = parse_json_array(text)
    rows = []
    for r in data if isinstance(data, list) else []:
        if not isinstance(r, dict):
            continue
        ev = []
        for e in r.get("evidence", []) or []:
            if not isinstance(e, dict):
                continue
            ev.append({"file": e.get("file",""), "page": e.get("page", None), "quote": e.get("quote","")})
        rows.append({
            "raw_id": (r.get("id","") or "").strip(),
            "item": (r.get("item","") or "").strip(),
            "status": (r.get("status","") or "").strip(),
            "biz_ref_note": (r.get("biz_ref_note","") or "").strip(),
            "section_title": (r.get("section_title","") or "").strip(),
            "main_no": r.get("main_no", None),
            "sub_no": r.get("sub_no", None),
            "std_id": (r.get("std_id","") or "").strip(),
            "evidence": ev,
        })
    return rows

def precheck_rows_to_df(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    std_ids = []
    for r in rows:
        sid = r.get("std_id", "")
        if not sid:
            sid = compute_std_id(r.get("raw_id",""), r.get("item",""))
        std_ids.append(sid)
    df = pd.DataFrame({
        "編號": std_ids,
        "檢核項目": [r.get("item","") for r in rows],
        "預審判定": [r.get("status","") for r in rows],
        "對應頁次/備註": [r.get("biz_ref_note","") for r in rows],
    })
    df["_預審等價級_隱藏"] = df["預審判定"].apply(normalize_status_equiv)
    df["_raw_id_隱藏"] = [r.get("raw_id","") for r in rows]
    df["_section_隱藏"] = [r.get("section_title","") for r in rows]
    return df

# ==================== 系統檢核 → DataFrame ====================
def to_dataframe(results: List[Dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for r in results:
        rows.append({
            "類別": r.get("category",""),
            "編號": r.get("id",""),
            "檢核項目": r.get("item",""),
            "符合情形": r.get("compliance",""),
            "主要證據": r.get("evidence",""),
            "改善建議": r.get("recommendation",""),
        })
    df = pd.DataFrame(rows)
    # 友善排序（A→B→C→D→E→F）
    try:
        df["主碼"] = df["編號"].str.extract(r"([A-F])")
        df["子碼值"] = pd.to_numeric(df["編號"].str.extract(r"(\d+(?:\.\d+)?)")[0], errors='coerce')
        code_order = {"A":0,"B":1,"C":2,"D":3,"E":4,"F":5}
        df["主序"] = df["主碼"].map(code_order).fillna(9)
        df = df.sort_values(["主序","子碼值","編號"], kind='mergesort').drop(columns=["主碼","子碼值","主序"])
    except Exception:
        pass
    return df

# ==================== 差異對照 ====================
def fuzzy_match(best_of: List[str], query: str) -> Tuple[str, float]:
    best_id, best_ratio = "", 0.0
    for cand in best_of:
        r = SequenceMatcher(a=query or "", b=cand or "").ratio()
        if r > best_ratio:
            best_ratio, best_id = r, cand
    return best_id, best_ratio

def build_compare_table(sys_df: pd.DataFrame, pre_df: pd.DataFrame) -> pd.DataFrame:
    sys_idx: Dict[str, Dict[str, Any]] = {}
    for _, row in sys_df.iterrows():
        rid = str(row.get("編號", "")).strip()
        if rid:
            sys_idx[rid] = row.to_dict()
    rows_out: List[Dict[str, Any]] = []
    if "_預審等價級_隱藏" not in pre_df.columns:
        pre_df["_預審等價級_隱藏"] = pre_df["預審判定"].apply(normalize_status_equiv)

    for _, prow in pre_df.iterrows():
        pid = str(prow.get("編號",""))
        pitem = str(prow.get("檢核項目",""))
        pori = str(prow.get("預審判定",""))
        peq = str(prow.get("_預審等價級_隱藏",""))
        matched = None
        matched_id = ""
        if pid and pid in sys_idx:
            matched = sys_idx[pid]; matched_id = pid
        else:
            best_id, best_ratio = fuzzy_match(list(sys_idx.keys()), pid or pitem)
            if best_ratio >= 0.85 and best_id in sys_idx:
                matched = sys_idx[best_id]; matched_id = best_id
        if matched:
            if matched_id == "A0":
                diff = "一致" if pori.strip() == str(matched.get("符合情形","")) else "不一致"
            else:
                diff = "一致" if matched.get("符合情形","") == peq else "不一致"
            rows_out.append({
                "類別": matched.get("類別",""),
                "編號": matched_id,
                "檢核項目（系統基準）": matched.get("檢核項目",""),
                "預審判定（原字）": pori,
                "預審等價級": peq,
                "系統檢核結果": matched.get("符合情形",""),
                "差異判定": diff,
                "差異說明/建議": matched.get("改善建議",""),
                "對應頁次/備註": prow.get("對應頁次/備註",""),
            })
        else:
            rows_out.append({
                "類別": "",
                "編號": pid or "（未識別）",
                "檢核項目（系統基準）": pitem,
                "預審判定（原字）": pori,
                "預審等價級": peq or "未提及",
                "系統檢核結果": "（無對應）",
                "差異判定": "預審多出",
                "差異說明/建議": "此預審項目在系統檢核清單中無直接對應；請人工確認是否需納入清單或為表述差異。",
                "對應頁次/備註": prow.get("對應頁次/備註",""),
            })
    pre_ids = set([str(x).strip() for x in pre_df.get("編號", pd.Series(dtype=str)).tolist() if str(x).strip()])
    for _, srow in sys_df.iterrows():
        sid = str(srow.get("編號","")).strip()
        if sid and sid not in pre_ids:
            rows_out.append({
                "類別": srow.get("類別",""),
                "編號": srow.get("編號",""),
                "檢核項目（系統基準）": srow.get("檢核項目",""),
                "預審判定（原字）": "",
                "預審等價級": "未提及",
                "系統檢核結果": srow.get("符合情形",""),
                "差異判定": "系統多出",
                "差異說明/建議": "預審未涵蓋此系統檢核項目，建議補列或於會審時提示承辦注意。",
                "對應頁次/備註": "",
            })
    out = pd.DataFrame(rows_out)
    try:
        out["主碼"] = out["編號"].str.extract(r"([A-F])")
        out["子碼值"] = pd.to_numeric(out["編號"].str.extract(r"(\d+(?:\.\d+)?)")[0], errors="coerce")
        code_order = {"A":0, "B":1, "C":2, "D":3, "E":4, "F":5}
        out["主序"] = out["主碼"].map(code_order).fillna(9)
        out = out.sort_values(["主序","子碼值","編號"], kind="mergesort").drop(columns=["主碼","子碼值","主序"])
    except Exception:
        pass
    return out

# ==================== 表格渲染（保留工具，現階段只用 data_editor） ====================
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

# ==================== 規則式抽取：預算金額（轉為萬元；附來源） ====================
BUDGET_HINT_PAT = re.compile(r"(預算|經費|採購預算|總預算|預算金額|預估金額|核定經費)", re.I)
MONEY_PAT = re.compile(r"(新[臺台]幣|NTD|NT\$)?\s*([0-9]{1,3}(?:,[0-9]{3})+|[0-9]+(?:\.[0-9]+)?)\s*(億|百萬|萬元|萬|元)", re.I)

def _to_wan(num_str: str, unit: str) -> float:
    n = float(str(num_str).replace(",", ""))
    u = unit.strip()
    if "億" in u:
        return n * 10000.0
    if "百萬" in u:
        return n * 100.0
    if "萬元" in u or u == "萬":
        return n
    return n / 10000.0  # 元

def detect_budget_million(corpus_text: str):
    """
    從含【檔名/頁碼】標註的全文中找出最可能的預算金額（萬元）與證據。
    回傳: (budget_wan:int|None, file:str|None, page:int|None, quote:str|None)
    """
    # 依 extract_text_with_headers 格式分塊
    blocks = re.split(r"\n+===== 【檔案: \s*(.*?)\s* 頁: \s*(\d+)】 =====\n", corpus_text)
    best = {"score": 0, "wan": None, "file": None, "page": None, "quote": None}
    def _score(has_hint: bool, wan: float):
        return (2.0 if has_hint else 1.0) + (min(wan, 50000.0) / 50000.0)
    i = 1
    while i + 2 < len(blocks):
        fname, pno, text = blocks[i], blocks[i+1], blocks[i+2]
        try:
            page = int(pno)
        except Exception:
            page = None
        lines = [x.strip() for x in (text or "").splitlines() if x.strip()]
        for ln in lines:
            has_hint = bool(BUDGET_HINT_PAT.search(ln))
            for m in MONEY_PAT.finditer(ln):
                unit = m.group(3) or ""
                wan = _to_wan(m.group(2), unit)
                sc = _score(has_hint, wan)
                if sc > best["score"]:
                    best = {"score": sc, "wan": wan, "file": fname, "page": page, "quote": ln[:200]}
        i += 3
    if best["wan"] is None:
        return None, None, None, None
    return int(round(best["wan"])), best["file"], best["page"], best["quote"]

# ==================== 主程式 ====================
def main():
    st.set_page_config("📑 資訊服務採購 RFP/契約審查系統(測試版)", layout="wide")
    st.title("📑 資訊服務採購 RFP/契約審查系統(測試版)")

    # RFP/契約 PDF（必填）
    uploaded_files = st.file_uploader("📥 上傳 RFP/契約 PDF（可複選）", type=["pdf"], accept_multiple_files=True)
    # 預先審查表 PDF（可略過）
    pre_files = st.file_uploader("📥 上傳『執行單位預先審查表』PDF（可複選/可略過）", type=["pdf"], accept_multiple_files=True)

    project_name = st.text_input("案件/專案名稱（將用於檔名）", value="未命名案件")

    # 檢核模式固定為一次性審查（暫停批次與逐題）
    st.caption("檢核模式：一次性審查（暫停批次/逐題）")

    if st.button("🚀 開始審查", disabled=not uploaded_files):
        checklist_all = build_rfp_checklist()
        # 進度條
        progress_text = st.empty(); progress_bar = st.progress(0)
        def set_progress(p, msg):
            progress_bar.progress(max(0, min(int(p), 100))); progress_text.write(msg)

        # 1) 解析 RFP/契約 PDF
        set_progress(5, "📄 解析與彙整 RFP/契約 文件文字…")
        corpora = []
        total_files = len(uploaded_files)
        st.info("📄 開始解析 RFP/契約 PDF 檔案…")
        for i, f in enumerate(uploaded_files):
            set_progress(int((i/max(1,total_files))*30), f"📄 解析 {f.name} ({i+1}/{total_files})…")
            pdf_bytes = f.read()
            text = extract_text_with_headers(pdf_bytes, f.name)
            if not text.strip():
                st.warning(f"⚠️ {f.name} 可能是掃描影像 PDF，無法直接抽文字。請提供可搜尋的 PDF。")
            corpora.append(text)
        corpus_text = "\n\n".join(corpora)

        # 1.1) 自動擷取預算金額（萬元）
        auto_budget_wan, auto_budget_file, auto_budget_page, auto_budget_quote = detect_budget_million(corpus_text)

        # 2) 解析 預先審查表 PDF（可略過；UI不顯示，僅供差異對照）
        set_progress(32, "🧩 處理預先審查表…")
        pre_df = pd.DataFrame()
        if pre_files:
            pre_texts = []
            for pf in pre_files:
                if is_pdf(pf.name):
                    st.write(f"📄 正在處理：{pf.name}")
                    pbytes = pf.read()
                    ptext = extract_text_with_headers(pbytes, pf.name)
                    if ptext.strip():
                        pre_texts.append(ptext)
                    else:
                        st.warning(f"⚠️ {pf.name} 可能是掃描影像 PDF，無法直接抽文字。請提供可搜尋 PDF。")
            if pre_texts:
                st.info("📄 開始解析預審表 PDF 檔案…")
                pre_corpus = "\n\n".join(pre_texts)
                prompt = make_precheck_parse_prompt(pre_corpus)
                try:
                    st.info("🤖 呼叫模型進行預審表結構化辨識…")
                    resp = model.generate_content(prompt)
                    st.info("📦 解析模型回傳的 JSON 結構…")
                    rows = parse_precheck_json(resp.text)
                    if rows:
                        st.info("📊 將預審表轉為 DataFrame 表格…")
                        pre_df = precheck_rows_to_df(rows)
                except Exception as e:
                    st.warning(f"⚠️ 預審表解析失敗：{e}，請稍後重試或改上傳另一份 PDF。")
        else:
            st.info("ℹ️ 未上傳或未成功辨識任何預審表內容.")

        set_progress(35, "🧠 檢核準備中…")

        # 3) 一次性審查
        all_results: List[Dict[str, Any]] = []
        st.info("🧪 執行系統檢核模式：一次性審查")
        groups = group_items_by_ABCDE(checklist_all)
        st.info("一次性審查中")
        total_batches = len(groups)
        for bi, (code, items) in enumerate(groups):
            set_progress(35 + int((bi/max(1,total_batches))*55), f"🔎 一次性審查（{code}）… 共 {len(items)} 項")
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
                    'recommendation': d.get('recommendation', '')
                })
            returned_ids = {x['id'] for x in normalized}
            for it in items:
                if it['id'] not in returned_ids:
                    normalized.append({
                        'id': it['id'], 'category': it['category'], 'item': it['item'],
                        'compliance': '未提及', 'evidence': [], 'recommendation': ''
                    })
            all_results.extend(normalized)

        # 4) 檢核結果 → DataFrame（UI不顯示）
        set_progress(92, "📦 彙整與轉表格…")
        df = to_dataframe(all_results)
        st.success("✅ 審查完成")

        # 5) 差異對照（僅顯示不一致/缺漏）
        cmp_df = pd.DataFrame()
        if not pre_df.empty and not df.empty:
            st.info("📋 建立預審與系統檢核的差異對照表…")
            cmp_df = build_compare_table(sys_df=df, pre_df=pre_df)
            st.subheader("🧾 差異對照表（只顯示不一致/缺漏）")
            view_df = cmp_df[cmp_df["差異判定"] != "一致"]
            cmp_display_cols = ["類別", "編號", "檢核項目（系統基準）", "預審判定（原字）", "對應頁次/備註", "系統檢核結果", "差異說明/建議"]
            view_df = view_df[cmp_display_cols]
            search_term = st.text_input("🔍 搜尋檢核項目")
            if search_term:
                view_df = view_df[view_df["檢核項目（系統基準）"].str.contains(search_term, case=False, na=False)]
            st.data_editor(
                view_df,
                use_container_width=True,
                hide_index=True,
                disabled=["類別", "編號", "檢核項目（系統基準）", "系統檢核結果"],
                column_config={
                    "預審判定（原字）": st.column_config.SelectboxColumn(
                        "預審判定", options=["符合", "不適用", ""], required=False)
                }
            )

            # === 建議回覆內容（不呼叫 LLM；加入預算抽取與固定參考項目） ===
            st.subheader("📝 建議回覆內容")

            with st.expander("📎 固定參考項目（僅供參考，不自動寫入草稿）", expanded=False):
                st.markdown(
                    """
- **醫療資料內容**：請參閱本部醫療資訊大平台之醫療資訊標準，如 **FHIR、LOINC、SNOMED CT、RxNorm**，並符合三大 AI 中心、**SMART on FHIR** 等作業事項。另如有 **TWCDI** 及 **IG** 需求，可至該平台提案。
- **檢核表**：已請**醫事司承辦人**酌修完畢制式文句檢核內容。
                    """
                )
                ref_insert = st.checkbox("（可選）將以上參考文字插入回覆草稿結尾", value=False)

            col1, col2, col3 = st.columns(3)
            with col1:
                audience = st.selectbox("對象", ["承辦", "執行單位", "廠商"])
            with col2:
                tone = st.selectbox("口吻", ["正式", "中性", "友善"], index=0)
            with col3:
                purpose = st.selectbox("目的", ["補件通知", "契約修正建議", "RFP內容補充", "技術澄清"], index=0)

            include_evidence = st.checkbox("每點後附『對應頁次/備註』（檔名/頁碼）", value=True)
            default_budget = str(auto_budget_wan) if auto_budget_wan is not None else "XXX"
            budget_million = st.text_input("預算金額（萬元；依文件判斷，未辨識則用 XXX）", value=default_budget)
            if auto_budget_wan is not None:
                st.caption(f"自動擷取來源：{auto_budget_file} p.{auto_budget_page} —— {auto_budget_quote}")
            force_common_items = st.checkbox("在結尾加入『必列事項』兩點", value=True)

            def build_reply_text_from_diff(_df: pd.DataFrame) -> str:
                lines = []
                lines.append(f"主旨：請協助{purpose}相關事項（{audience}）。")
                lines.append("說明：為確保採購文件之完整性與合規性，依本處檢核與預審對照結果，請協助補充/修正下列事項：")
                lines.append("請求事項：")
                for _, r in _df.iterrows():
                    item = str(r.get("檢核項目（系統基準）", "")).strip()
                    rec  = str(r.get("差異說明/建議", "")).strip()
                    ev   = str(r.get("對應頁次/備註", "")).strip()
                    ev_part = f"（參考：{ev}）" if include_evidence and ev else ""
                    lines.append(f"．[{r['編號']}] {item} —— 建議：{rec}{ev_part}")

                if force_common_items:
                    b = budget_million.strip() if budget_million.strip() else "XXX"
                    lines.append("")
                    lines.append("必列事項：")
                    lines.append(f"1. 本案預算金額{b}萬元，包含系統維運、功能增修等。")
                    lines.append("2. 資訊系統之維運費用應逐年遞減，廠商報價如有增長，可請廠商於本案之期末報告提供系統使用效益指標，做為次年維運費用成長之判斷。")

                if ref_insert:
                    lines.append("")
                    lines.append("參考事項：")
                    lines.append("－ 醫療資料內容：請參閱本部醫療資訊大平台之醫療資訊標準，如 FHIR、LOINC、SNOMED CT、RxNorm，並符合三大 AI 中心、SMART on FHIR 等作業事項。另如有 TWCDI 及 IG 需求，可至該平台提案。")
                    lines.append("－ 檢核表：已請醫事司承辦人酌修完畢制式文句檢核內容。")

                return "\n".join(lines)

            if st.button("✍️ 產生回覆草稿", disabled=view_df.empty):
                reply_text = build_reply_text_from_diff(view_df)
                st.text_area("回覆草稿（可複製）", reply_text, height=320)

                # 下載 Word
                def _build_reply_docx(text: str, title: str):
                    doc = Document()
                    doc.add_heading(f"{title} 建議回覆內容", level=1)
                    for line in text.split("\n"):
                        p = doc.add_paragraph(line)
                        p.paragraph_format.line_spacing = 1.5
                    bio = io.BytesIO(); doc.save(bio); bio.seek(0); return bio
                bio = _build_reply_docx(reply_text, project_name)
                st.download_button(
                    "⬇️ 下載 Word 回覆草稿 (.docx)",
                    data=bio.getvalue(),
                    file_name=f"{project_name}_建議回覆內容.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )

        # 6) Excel 匯出（僅差異對照）
        try:
            from openpyxl.styles import Alignment
            xbio = io.BytesIO()
            st.info("📁 匯出 Excel（僅差異對照）…")
            with pd.ExcelWriter(xbio, engine='openpyxl') as writer:
                if 'cmp_df' in locals() and not cmp_df.empty:
                    cmp_df.to_excel(writer, index=False, sheet_name='差異對照')
                    ws3 = writer.sheets['差異對照']
                    for row in ws3.iter_rows(min_row=1, max_row=ws3.max_row, min_col=1, max_col=ws3.max_column):
                        for cell in row:
                            cell.alignment = Alignment(wrap_text=True, vertical='top')
                else:
                    # 若無預審或無差異，仍輸出空表以利歸檔
                    empty_df = pd.DataFrame(columns=["類別","編號","檢核項目（系統基準）","預審判定（原字）","對應頁次/備註","系統檢核結果","差異說明/建議","差異判定"])
                    empty_df.to_excel(writer, index=False, sheet_name='差異對照')
            xbio.seek(0)
            st.download_button(
                label="📥 下載 Excel（差異對照）",
                data=xbio.getvalue(),
                file_name=f"{project_name}_RFP_Contract_Compare.xlsx",
                mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )
        except Exception as e:
            st.warning(f"Excel 匯出失敗：{e}")

        progress_text.empty(); progress_bar.empty()

if __name__ == '__main__':
    main()
