# -*- coding: utf-8 -*-
"""
sys.py — RFP/契約 審查（資訊處檢核版） + 預先審查表（PDF 專用）

功能：
- 上傳 RFP/契約 PDF（可複選）→ 依檢核清單檢核（一次性/批次/逐題）
- 上傳「執行單位預先審查表」PDF（可複選/可略過）→ LLM 結構化抽取
- 先顯示【預審辨識表】（固定 5 欄：編號/檢核項目/預審判定/"對應頁次/備註"）
- 產生【差異對照表】（預審 vs. 系統檢核），支援只顯示不一致/缺漏
- 匯出 Excel（三個工作表）：檢核結果 / 預審辨識 / 差異對照

規格重點：
- 預審判定僅允許：符合 / 不適用；未勾選顯示為空白（背景比對正規化為「未提及」）
- A0（案件性質）為六選一字面值，比對時採字面值比對，不走四態
- 編號標準化（compute_std_id）：中文章節→代碼（A..F）+ 數字（含小數）；「其他重點」→ F
- 檢核清單包含 F 類；批次審查分組為：AB｜CDEF
"""

import os, re, json, io
from typing import List, Dict, Any, Tuple
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode
import streamlit as st
import fitz  # PyMuPDF
import pandas as pd
from dotenv import load_dotenv
import google.generativeai as genai
from difflib import SequenceMatcher

# -------------------- LLM --------------------
load_dotenv()
if os.getenv('GOOGLE_API_KEY'):
    genai.configure(api_key=os.getenv('GOOGLE_API_KEY'))
model = genai.GenerativeModel("gemini-2.5-flash")

# -------------------- 檔案型態 --------------------
def is_pdf(name: str) -> bool:
    return name.lower().endswith(".pdf")

# ==================== 檢核清單（含 F 其他重點） ====================
def build_rfp_checklist() -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    def add(cat, code, text): items.append({"category":cat, "id":code, "item":text})

    # A 基本與前案
    add("A 基本與前案", "A0",   "本案屬開發建置、系統維運、功能增修、套裝軟體、硬體、其他?")
    add("A 基本與前案", "A1",   "本案為延續性合約，前案採購簽陳影本已附。")
    add("A 基本與前案", "A2.1", "本案事前曾與資訊處討論：本案相關技術文件由資訊處協助撰寫。")
    add("A 基本與前案", "A2.2", "本案事前曾與資訊處討論：規劃階段曾與資訊處開會討論採購內容並有會議紀錄。")
    add("A 基本與前案", "A2.3", "本案簽辦之前，已以請辦單遞交契約書、需求說明書等相關文件，送請資訊處檢視，並保留至少5個工作天之審閱期後取得回覆。")
    add("A 基本與前案", "A2.4", "本案事前未與資訊處討論（無）。")

    # B 現況說明
    add("B 現況說明", "B1.1", "提供最新版硬體設備及網路之架構圖(不含IP Address)：明確表達硬體放置區域（含機房/區域）。")
    add("B 現況說明", "B1.2", "提供網路介接方式與開發工具之廠牌、型號、版本等資訊。")
    add("B 現況說明", "B2",   "置於本部機房之系統，如另設對外連線線路者，提供連線對象、種類及規格清單。")
    add("B 現況說明", "B3",   "提供使用者或使用機關之示意圖或說明。")
    add("B 現況說明", "B4",   "提供最新網站網址。")
    add("B 現況說明", "B5",   "提供應用系統功能清單或架構圖（含 OS、DB 名稱與版本）。")

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
    add("C 資安需求", "C4",   "不得採用大陸廠牌資通訊產品（契約草案第八條(六)及(二 五)）。")
    add("C 資安需求", "C5",   "符合『資通系統籌獲各階段資安強化措施執行檢核表』（開發附表1/維運附表2）。")
    add("C 資安需求", "C6",   "資料庫中機敏資料已採用或規劃適當加密技術。")

    # D 作業需求（節錄）
    add("D 作業需求", "D1",  "列出所需軟硬體與網路設備清單，說明使用資訊處設備/既有設備或另行採購（優先 VM/共同供應契約）。")
    add("D 作業需求", "D2",  "系統開發或功能增修應列出所需系統功能（地方政府系統建議提供資料下載或介接）。")
    add("D 作業需求", "D3",  "敘明資訊系統與其他軟體系統之相互關係並說明所有利害關係人。")
    add("D 作業需求", "D4",  "提供民眾下載檔案者，增加 ODF 格式。")
    add("D 作業需求", "D5",  "開發 App 已閱讀並遵循國發會相關規定（附件2）。")
    add("D 作業需求", "D6",  "開發 App 符合通傳會『App 無障礙開發指引』並填報檢核表（附件3）。")
    add("D 作業需求", "D7",  "網站服務之系統符合國發會『政府網站服務管理規範』並填報檢核表（附件4）。")
    add("D 作業需求", "D8",  "針對業務或個人資料，提供後續 OpenData 或 MyData 服務建議。")
    add("D 作業需求", "D9",  "系統維護包含定期到場、緊急到場、諮詢服務；SLA 與績效指標連動並設計使用者滿意度調查。")
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

# ==================== 分群/排序工具（批次改為 AB｜CDEF） ====================
def group_items_by_ABCDE(items: List[Dict[str, Any]]) -> List[Tuple[str, List[Dict[str, Any]]]]:
    return [("ABCDE", items)] if items else []

def group_items_by_AB_CDE(items: List[Dict[str, Any]]) -> List[Tuple[str, List[Dict[str, Any]]]]:
    """保留函式名以相容，但第二組已擴充為 CDEF。"""
    ab   = [it for it in items if it['id'] and it['id'][0] in ('A','B')]
    cdef = [it for it in items if it['id'] and it['id'][0] in ('C','D','E','F')]
    groups = []
    if ab:   groups.append(('AB', ab))
    if cdef: groups.append(('CDEF', cdef))
    return groups

# 逐題排序（A→B→C→D→E→F）
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
    "evidence": {"file": "檔名", "page": 頁碼, "quote": "逐字引述"},
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

# （預審表抽取：預審判定僅允許【符合/不適用】，未勾選輸出空字串；A0 例外為六選一字面）
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
- "section_title": 章節標題（如「案件性質」「現況說明」「資安需求」「作業需求」「產品交付」「其他重點」）
- "main_no": 主號（如 1, 2, 3）
- "sub_no": 次號（如 1, 2；若無可省略）
- "std_id": 若能依下方規則直接計算出系統標準 ID（A..F + 數字[.數字]），請填；否則空字串
- "evidence": 每列至少一筆：{{"file": 檔名, "page": 頁碼, "quote": 引述短句}}

【重要版面規則（請嚴格遵循）】
1) 本表「表頭」通常為：「檢核內容｜符合｜不適用｜對應頁次/備註」。
2) 勾選符號採 **■=已勾、□=未勾**。
3) 當看到子項 (1)(2)(3)… 之後緊接著兩列或多列全是「■/□」的矩陣時：
   - **第一列**的每一格依序對應子項 (1)(2)(3)… 的 **「符合」** 欄結果；
   - **第二列**的每一格依序對應子項 (1)(2)(3)… 的 **「不適用」** 欄結果；
   - 將每個子項拆成獨立列（例如「A2.1」「A2.2」「A2.3」…），並依該子項在矩陣同序位格子的「■/□」決定 "status"。
   - 例如：若四個子項後面出現第一列：`□ □ □ □`、第二列：`■ ■ ■ ■`，則四個子項均為 **"不適用"**。
4) 若無矩陣、而是每列文字右側各自出現「符合/不適用」勾選，請就近判斷該列的 "status"。
5) **不得猜測**：若確實沒有任何「符合/不適用」的勾選跡象，"status" 請回空字串 ""，並提供 evidence。

【A0 特例（多選）】
- 若檢出「案件性質」類型勾選（開發建置/系統維運/功能增修/套裝軟體/硬體/其他），請額外新增一列 A0：
  {{
    "id": "A0", "item": "案件性質（多選）",
    "status": "（填被勾選的類型字樣）",   # A0 為字面值，非「符合/不適用」
    "biz_ref_note": "",
    "section_title": "案件性質", "main_no": 0, "std_id": "A0",
    "evidence": [{{"file":"...", "page": 頁碼, "quote":"..."}}]
  }}

【安全規範】
- 僅依文件明載內容；不可發明。
- **禁止輸出任何聯絡資訊（姓名、電話、Email 等），即使文件內有。**

【輸出格式 — 僅能輸出 JSON 陣列，無多餘文字】
[
  {{
    "id": "現況說明-1.(2)",
    "item": "透過何種網路架構…並說明廠牌、型號、版本等。",
    "status": "符合",        # 或 "不適用"；若未勾選則輸出 ""
    "biz_ref_note": "需求說明書 P.11-12等文字",
    "section_title": "現況說明",
    "main_no": 1,
    "sub_no": 2,
    "std_id": "B1.2",
    "evidence": [{{"file":"xxx.pdf","page":2,"quote":"…"}}]
  }}
]

【文件全文（含檔名/頁碼標註）】
{corpus_text}
""".strip()

# ==================== 解析/轉表工具 ====================
def parse_json_array(text: str) -> List[Dict[str, Any]]:
    t = text.strip()
    # 去除可能的 ```json / ``` 包裹
    t = re.sub(r'^```(?:json)?', '', t, flags=re.I).strip()
    t = re.sub(r'```$', '', t, flags=re.I).strip()
    if t.startswith('{') and t.endswith('}'):
        try:
            d = json.loads(t); return [d]
        except Exception:
            pass
    start = t.find('['); end = t.rfind(']')
    if start != -1 and end != -1 and end > start:
        t = t[start:end+1]
    data = json.loads(t)
    if isinstance(data, dict):
        data = [data]
    return data

def _format_evidence_list(e_list: List[Dict[str, Any]]) -> str:
    lines = []
    for e in e_list:
        file = e.get('file','')
        page = e.get('page', None)
        quote = e.get('quote','')
        tag = f"p.{page}" if page not in (None, "", "n/a") else ""
        lines.append(f"{file} {tag}：{quote}".strip())
    return "\n".join(lines)

def normalize_status_equiv(s: str) -> str:
    """
    預審端僅兩態（符合/不適用），其餘/空白一律視為「未提及」以利與系統四態比對。
    """
    if s is None:
        return "未提及"
    t = re.sub(r"\s+", "", str(s)).lower()
    if t == "":
        return "未提及"
    if t in ("符合", "ok", "pass", "通過"):
        return "符合"
    if t in ("不適用", "na", "n/a"):
        return "不適用"
    # 任何其它字眼（如不符合/需補件/改善等）一律視為「未提及」（因預審正式只用兩態）
    return "未提及"

# 章節 → 代號（含 F）
SECTION_TO_LETTER = {
    "案件性質": "A",
    "現況說明": "B",
    "資安需求": "C",
    "作業需求": "D",
    "產品交付": "E",
    "其他重點": "F",
}
ROMAN_TO_LETTER = {
    "一": "A", "二": "B", "三": "C", "四": "D", "五": "E", "六": "F"
}
STD_ID_PATTERN = re.compile(r"^[A-F]\d+(?:\.\d+)?$")

def compute_std_id(raw_id: str, item: str) -> str:
    """
    將預審列的原始編號/文字，轉換成系統標準 ID（A..F + 數字[.數字]）。
    若無法可靠判定，回傳空字串（在對照表會落為『預審多出』）。
    """
    s = (raw_id or "").strip()
    # 已是標準 ID
    if STD_ID_PATTERN.match(s):
        return s

    # 從內容推斷章節
    src = f"{raw_id} {item}".strip()
    sec_letter = ""
    for zh, letter in SECTION_TO_LETTER.items():
        if zh in src:
            sec_letter = letter
            break
    if not sec_letter:
        for zh, letter in ROMAN_TO_LETTER.items():
            if f"{zh}、" in src or f"{zh} " in src:
                sec_letter = letter
                break

    # 抓主號（優先匹配 "X-1.(2)" 之第一個數字；否則抓文中第一個數字）
    m_main = re.search(r"-\s*(\d+)", raw_id or "") or re.search(r"(\d+)\s*[、\.．)]", src)
    n1 = m_main.group(1) if m_main else None

    # 抓次號 "(1)" "(2)"
    m_sub = re.search(r"\((\d+)\)", src)
    n2 = m_sub.group(1) if m_sub else None

    if sec_letter and n1:
        return f"{sec_letter}{n1}" + (f".{n2}" if n2 else "")
    return ""

# 解析預審 JSON → 製作 5 欄顯示表，並保留隱藏欄位供比對/除錯
def parse_precheck_json(text: str) -> List[Dict[str, Any]]:
    data = parse_json_array(text)
    rows = []
    for r in data if isinstance(data, list) else []:
        if not isinstance(r, dict):
            continue
        ev = []
        for e in r.get("evidence", []):
            if not isinstance(e, dict): 
                continue
            ev.append({
                "file": e.get("file",""),
                "page": e.get("page", None),
                "quote": e.get("quote","")
            })
        rows.append({
            "raw_id": r.get("id","").strip(),                 # LLM 粗編號（原樣）
            "item": r.get("item","").strip(),
            "status": r.get("status","").strip(),             # 僅允許：符合/不適用/""(未勾)
            "biz_ref_note": r.get("biz_ref_note","").strip(),
            "section_title": r.get("section_title","").strip(),
            "main_no": r.get("main_no", None),
            "sub_no": r.get("sub_no", None),
            "std_id": r.get("std_id","").strip(),             # 若模型已算出
            "evidence": r.get("evidence","")                                    # 保留但不顯示
        }
                   )
    return rows

def precheck_rows_to_df(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    # 先求出標準 ID（若 LLM 沒給 std_id，就用 compute_std_id 推斷）
    std_ids = []
    for r in rows:
        sid = r.get("std_id","")
        if not sid:
            sid = compute_std_id(r.get("raw_id",""), r.get("item",""))
        std_ids.append(sid)

    # 顯示專用 5 欄（「預審判定」為原字：符合/不適用/空白）
    df = pd.DataFrame({
        "編號":     std_ids,                         # 使用標準 ID；空白代表無對應
        "檢核項目": [r.get("item","") for r in rows],
        "預審判定": [r.get("status","") for r in rows],
        "對應頁次/備註": [r.get("biz_ref_note","") for r in rows]  # 

    })

    # 背景隱藏欄位（供差異對照與除錯）——不顯示、不匯出
    df["_預審等價級_隱藏"] = df["預審判定"].apply(normalize_status_equiv)  # 符合/不適用/未提及
    df["_raw_id_隱藏"] = [r.get("raw_id","") for r in rows]
    df["_section_隱藏"] = [r.get("section_title","") for r in rows]
    return df

# ==================== 系統檢核 → DataFrame（排序含 F） ====================
def to_dataframe(results: List[Dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for r in results:
        ev_text = "\n".join([f"{e.get('file','')} p.{e.get('page','')}：{e.get('quote','')}" for e in r.get('evidence', [])])
        rows.append({
            "類別": r.get("category",""),
            "編號": r.get("id",""),
            "檢核項目": r.get("item",""),
            "符合情形": r.get("compliance",""),
            "主要證據": r.get("evidence",""),
            "改善建議": r.get("recommendation","")
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

# ==================== 預審 vs 系統 檢核：差異對照（已修正 KeyError） ====================
def fuzzy_match(best_of: List[str], query: str) -> Tuple[str, float]:
    best_id, best_ratio = "", 0.0
    for cand in best_of:
        r = SequenceMatcher(a=query, b=cand).ratio()
        if r > best_ratio:
            best_ratio, best_id = r, cand
    return best_id, best_ratio

def build_compare_table(sys_df: pd.DataFrame, pre_df: pd.DataFrame) -> pd.DataFrame:
    """
    sys_df 來自 to_dataframe(): 欄位 [類別, 編號, 檢核項目, 符合情形, 主要證據, 改善建議]
    pre_df 來自預審辨識：      欄位 [編號, 檢核項目, 預審判定, 對應頁次/備註, _預審等價級_隱藏]
    """
    # 關鍵修正：不要用 set_index("編號").to_dict(...) 以免列 dict 失去「編號」欄
    sys_idx: Dict[str, Dict[str, Any]] = {}
    for _, row in sys_df.iterrows():
        rid = str(row.get("編號", "")).strip()
        if rid:
            sys_idx[rid] = row.to_dict()

    rows_out: List[Dict[str, Any]] = []

    # 確保有等價級欄位
    if "_預審等價級_隱藏" not in pre_df.columns:
        pre_df["_預審等價級_隱藏"] = pre_df["預審判定"].apply(normalize_status_equiv)

    for _, prow in pre_df.iterrows():
        pid   = str(prow.get("編號","")).strip()
        pitem = str(prow.get("檢核項目",""))
        pori  = str(prow.get("預審判定",""))             # 顯示用：符合/不適用/空白；A0 = 六選一字面
        peq   = str(prow.get("_預審等價級_隱藏",""))     # 正規化：符合/不適用/未提及

        matched = None
        matched_id = ""

        if pid and pid in sys_idx:
            matched = sys_idx[pid]; matched_id = pid
        else:
            # 若編號空白或不在系統清單，嘗試以文字相似度
            best_id, best_ratio = fuzzy_match(list(sys_idx.keys()), pid or pitem)
            if best_ratio >= 0.85 and best_id in sys_idx:
                matched = sys_idx[best_id]; matched_id = best_id

        if matched:
            # ★ A0 用字面比對（六選一）；其餘用四態（等價級）比對
            if matched_id == "A0":
                diff = "一致" if pori.strip() == str(matched.get("符合情形","")).strip() else "不一致"
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
                "差異說明/建議": matched.get("改善建議","") if diff=="不一致" else "",
                "對應頁次/備註": prow.get("對應頁次/備註","")
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
                "對應頁次/備註": prow.get("對應頁次/備註","")
            })

    # 系統有但預審沒有（針對 A~F）
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
                "對應頁次/備註": ""
            })

    out = pd.DataFrame(rows_out)
    # 依 A→B→C→D→E→F 與編號排序
    try:
        out["主碼"] = out["編號"].str.extract(r"([A-F])")
        out["子碼值"] = pd.to_numeric(out["編號"].str.extract(r"(\d+(?:\.\d+)?)")[0], errors="coerce")
        code_order = {"A":0, "B":1, "C":2, "D":3, "E":4, "F":5}
        out["主序"] = out["主碼"].map(code_order).fillna(9)
        out = out.sort_values(["主序","子碼值","編號"], kind="mergesort").drop(columns=["主碼","子碼值","主序"])
    except Exception:
        pass
    return out

# ==================== 表格渲染 ====================
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

# ==================== 主程式 ====================
def main():
    st.set_page_config("📑 資訊服務採購 RFP/契約審查系統(測試版)", layout="wide")
    st.title("📑 資訊服務採購 RFP/契約審查系統(測試版)")

    # RFP/契約 PDF（必填）
    uploaded_files = st.file_uploader("📥 上傳 RFP/契約 PDF（可複選）", type=["pdf"], accept_multiple_files=True)

    # 預先審查表 PDF（可略過）
    pre_files = st.file_uploader("📥 上傳『執行單位預先審查表』PDF（可複選/可略過）", 
                                 type=["pdf"], accept_multiple_files=True)

    project_name = st.text_input("案件/專案名稱（將用於檔名）", value="未命名案件")
    mode = st.radio(
        "檢核模式",
        ("一次性審查", "批次審查", "逐題審查"),
        horizontal=True
    )

    if st.button("🚀 開始審查", disabled=not uploaded_files):
        
        checklist_all = build_rfp_checklist()

        # 進度條
        progress_text = st.empty(); progress_bar = st.progress(0)
        def set_progress(p, msg):
            progress_bar.progress(max(0, min(int(p), 100))); progress_text.write(msg)

        # 1) 解析 RFP/契約 PDF
        set_progress(5, "📄 解析與彙整 RFP/契約 文件文字…")
        corpora = []; total_files = len(uploaded_files)
        st.info("📄 開始解析 RFP/契約 PDF 檔案…")

        for i, f in enumerate(uploaded_files):
            set_progress(int((i/max(1,total_files))*30), f"📄 解析 {f.name} ({i+1}/{total_files})…")
            pdf_bytes = f.read(); text = extract_text_with_headers(pdf_bytes, f.name)
            if not text.strip():
                st.warning(f"⚠️ {f.name} 看起來是掃描影像 PDF，無法直接抽文字。請提供可搜尋的 PDF。")
            corpora.append(text)
        corpus_text = "\n\n".join(corpora)

        # 2) 解析 預先審查表 PDF（可略過）
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

            if not pre_df.empty:
                st.subheader("🔎 預審辨識表（請先檢視是否正確）")
                pre_display_cols = ["編號", "檢核項目", "預審判定", "對應頁次/備註"]
                render_wrapped_table(pre_df[pre_display_cols], height_vh=40)
            else:
                st.info("ℹ️ 未上傳或未成功辨識任何預審表內容。")

        set_progress(35, "🧠 檢核準備中…")

        # 3) 依模式執行檢核（一次性｜批次 AB/CDEF｜逐題）
        all_results: List[Dict[str, Any]] = []
        st.info(f"🧪 執行系統檢核模式：{mode}")
        if mode.startswith("一"):
            groups = group_items_by_ABCDE(checklist_all); st.info("一次性審查中")
        elif mode.startswith("批"):
            groups = group_items_by_AB_CDE(checklist_all); st.info("批次審查中（AB｜CDEF）")
        else:
            groups = None  # 逐題

        if groups is not None:
            total_batches = len(groups)
            for bi, (code, items) in enumerate(groups):
                set_progress(35 + int((bi/max(1,total_batches))*55), f"🔎 第 {bi+1}/{total_batches} 批（{code}）… 共 {len(items)} 項")
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
            # 逐題模式
            items_ordered = order_items_AB_C_D_E(checklist_all)
            total_items = len(items_ordered)
            st.info("逐題檢核中")
            for i, it in enumerate(items_ordered):
                set_progress(35 + int((i/max(1,total_items))*55), f"🧩 第 {i+1}/{total_items} 題：{it['id']} …")
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

        # 4) 檢核結果 → 表格
        set_progress(92, "📦 彙整與轉表格…")
        df = to_dataframe(all_results)
        st.success("✅ 審查完成")
        render_wrapped_table(df, height_vh=52)

        # 5) 差異對照（若有預審）
        cmp_df = pd.DataFrame()
        if not pre_df.empty and not df.empty:
            st.info("📋 建立預審與系統檢核的差異對照表…")
            cmp_df = build_compare_table(sys_df=df, pre_df=pre_df)
            st.subheader("🧾 差異對照表（預審 vs. 系統檢核）")
            show_only_diff = st.checkbox("只顯示『不一致/缺漏』", value=True)
            view_df = cmp_df[cmp_df["差異判定"] != "一致"] if show_only_diff else cmp_df
            
            # 只保留指定欄位
            cmp_display_cols = ["類別", "編號", "檢核項目（系統基準）", "預審判定（原字）", "對應頁次/備註", "系統檢核結果", "差異說明/建議"]
            view_df = view_df[cmp_display_cols]


            # 可加上搜尋欄位（選用）
            search_term = st.text_input("🔍 搜尋檢核項目")
            if search_term:
                view_df = view_df[view_df["檢核項目（系統基準）"].str.contains(search_term, case=False, na=False)]

            # 顯示互動表格
            st.data_editor(
                view_df,
                use_container_width=True,
                hide_index=True,
                disabled=["類別", "編號", "檢核項目（系統基準）", "系統檢核結果"],  # 禁止編輯這些欄位
                column_config={
                    "預審判定（原字）": st.column_config.SelectboxColumn(
                        "預審判定", options=["符合", "不適用", ""], required=False)})
            # 匯出 CSV
            csv = view_df.to_csv(index=False).encode("utf-8-sig")
            st.download_button("📥 下載差異對照表 CSV", data=csv, file_name="compare_table.csv", mime="text/csv")


           # render_wrapped_table(view_df, height_vh=40)

        # 6) Excel 匯出（3 工作表）
        try:
            from openpyxl.styles import Alignment
            xbio = io.BytesIO()
            st.info("📁 匯出 Excel（檢核結果＋預審辨識＋差異對照）…")
            with pd.ExcelWriter(xbio, engine='openpyxl') as writer:
                # Sheet1: 檢核結果
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

                # Sheet2: 預審辨識（只輸出五欄）
                if not pre_df.empty:
                    pre_display_cols = ["編號", "檢核項目", "預審判定", "對應頁次/備註"]
                    pre_df[pre_display_cols].to_excel(writer, index=False, sheet_name='預審辨識')
                    ws2 = writer.sheets['預審辨識']
                    for row in ws2.iter_rows(min_row=1, max_row=ws2.max_row, min_col=1, max_col=ws2.max_column):
                        for cell in row:
                            cell.alignment = Alignment(wrap_text=True, vertical='top')

                # Sheet3: 差異對照
                if not cmp_df.empty:
                    cmp_df.to_excel(writer, index=False, sheet_name='差異對照')
                    ws3 = writer.sheets['差異對照']
                    for row in ws3.iter_rows(min_row=1, max_row=ws3.max_row, min_col=1, max_col=ws3.max_column):
                        for cell in row:
                            cell.alignment = Alignment(wrap_text=True, vertical='top')

            xbio.seek(0)
            st.download_button(
                label='📥 下載 Excel（檢核＋預審＋對照）',
                data=xbio.getvalue(),
                file_name=f"{project_name}_RFP_Contract_Checklist_Compare.xlsx",
                mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )
        except Exception as e:
            st.warning(f"Excel 匯出失敗：{e}")

        progress_text.empty(); progress_bar.empty()

if __name__ == '__main__':
    main()
