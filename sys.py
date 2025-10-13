# === 自動生成建議回覆內容 ===
st.subheader("📝 建議回覆內容（LLM自動生成）")

def make_reply_prompt(corpus_text: str) -> str:
    return f"""
你是政府機關資訊處之採購/RFP/契約審查委員，請用繁體中文撰寫『建議回覆內容』，風格需正式、精簡、可直接貼用，並以編號條列。
請包含：
1) 本案採購金額（若文件中有提及，請引用並換算為萬元）。
2) 資訊系統之維運費用應逐年遞減，並於期末報告提供效益指標。
3) 其餘依文件差異或缺漏，給出具體補充/修正建議。
禁止輸出任何聯絡資訊（姓名、電話、Email 等）。
僅輸出條列文字，不要加入前言或落款。

【RFP/契約全文】{corpus_text}
""".strip()

try:
    prompt = make_reply_prompt(corpus_text)
    resp = model.generate_content(prompt)
    reply_text = (resp.text or "").strip()
    st.text_area("回覆內容（LLM輸出）", reply_text, height=300)
except Exception as e:
    st.warning(f"LLM 產生失敗：{e}")
