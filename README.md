# S2S Test (Speech-to-Speech 即時語音測試環境)

這是一個輕量級的 Web 語音互動測試專案，旨在展示如何透過網頁前端安全地連接 Google Gemini Multimodal Live API，並結合 n8n Webhook 進行 RAG (檢索增強生成)。

## 架構說明

為了保護 API Key 不被前端暴露，本專案採用以下架構：
1. **Frontend (HTML/JS):** 負責擷取麥克風音訊 (PCM/Base64) 並透過 WebSocket 傳送。
2. **Backend Proxy (FastAPI):** 作為中繼站，保護 Gemini API Key 與 n8n Webhook URL，並處理 `tool_call` 的攔截與資料庫查詢。
3. **Data Retrieval:** 透過 n8n 串接後端資料庫 (如 Supabase)，實現動態資料查詢。

## 本地端開發與測試 (Local Development)

### 1. 安裝環境依賴
請確保你的電腦已安裝 Python 3.8+，然後執行：
```bash
pip install -r requirements.txt