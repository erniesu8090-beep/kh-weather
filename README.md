# 高雄氣象即時監控

線上網站：[高雄氣象監控](https://erniesu8090-beep.github.io/kh-weather/)

提供高雄自選兩站雨量、林園降雨雷達、全臺雷達與衛星雲圖。桌機採測站側欄與大雷達，手機採可捲動版面，支援鍵盤、文字放大與 PWA 安裝。

## 資料與更新

- 網頁每 60 秒檢查更新，切回前景會重新檢查；重複請求會合併。
- 保留原有公開氣象署 API 金鑰，集中設定於 `config.json`。瀏覽器直接讀取官方 OpenData API（O-A0002-001），雷達及衛星讀取氣象署影像清單。
- `CWA_API_KEY` 環境變數或本機未追蹤的 `.env` 可覆寫公開設定；GitHub Actions 也支援同名 Secret，但不是網頁連線必要條件。
- GitHub Pages 同時提供部署時產生的 `weather.json` 作為雨量或影像來源失敗時的備援。工作流程每 10 分鐘排程更新，GitHub 排程可能延遲，並非即時服務保證。
- 顯示各測站的實際觀測時間。超過 30 分鐘、時間不明或明顯超前會提示；缺資料顯示 `—`，不當作無雨。
- 近 10 分鐘雨量為零才顯示「近10分鐘無雨」。大雨／豪雨／大豪雨／超大豪雨依氣象署累積雨量門檻計算，只代表觀測分級，**不是官方發布的特報**。頁尾提供官方特報連結。
- 雷達 dBZ 是回波強度，不能直接等同測站雨量或官方雨量分級；衛星模式不顯示雷達圖例。
- 動畫依實際影像時間篩選，預載下一張、等待載入完成再換圖；沒有影像或載入失敗會顯示提示。

## 本機啟動

需要 Python 3.12，雙擊 `啟動林園氣象監控.bat` 或執行：

```powershell
python server.py
```

使用標準函式庫提供多執行緒 HTTP 服務，僅綁定 `127.0.0.1`。若有安裝 pywebview，優先開啟原生視窗，否則開啟瀏覽器。氣象署資料以短時間快取避免重複請求，各影像清單平行下載，失敗保留原始觀測時間與上次資料。

## 測試

```powershell
node --test tests/weather.test.cjs tests/app.test.cjs
python -m unittest discover -s tests -p "test_*.py"
python scripts/build_site.py
```

前兩項不依賴網路；最後一項需連線氣象署，產生 `dist/` 靜態部署包，驗證雨量及林園影像都有資料。建置失敗時不部署，以保留前一次成功版本。

## GitHub Pages 部署

`.github/workflows/deploy.yml` 在 `main` 更新、手動執行或排程時，先測試再取得觀測資料並部署 `dist/`。儲存庫 Pages 的建置來源須設定為 **GitHub Actions**。

## 專案結構

| 檔案 | 用途 |
| --- | --- |
| `index.html` | 語意化介面與可存取控制項 |
| `styles.css` | 深藍介面、響應式版面、焦點與減少動態效果 |
| `app.js` | 請求合併、獨立來源備援、畫面更新與播放器 |
| `weather.js` | 雨量正規化、分級、時間解析及影格篩選 |
| `stations.js` | 高雄測站清單 |
| `config.json` | 原有公開氣象署 API 金鑰 |
| `server.py` | 本機代理、觀測解析與快取 |
| `scripts/build_site.py` | 靜態網站與備援觀測資料建置 |
| `sw.js` / `manifest.json` | PWA 安裝與離線介面快取 |
| `tests/` | 資料規則、前端流程與後端測試 |

PWA 可從瀏覽器選單加入主畫面。離線時只保留介面，氣象資料仍需連線；頁面會提示更新失敗。安裝網址與圖示使用相對路徑，支援本機與 GitHub Pages。

資料來源：[交通部中央氣象署](https://www.cwa.gov.tw/)
