[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/htlin222/obs-voice-command)](https://github.com/htlin222/obs-voice-command/stargazers)
[![Python](https://img.shields.io/badge/Python-%3E%3D3.12-3776AB.svg?logo=python&logoColor=white)](https://www.python.org)

# obs-voice-command

macOS 上用語音指令控制 OBS 直播畫面縮放。說「來個特寫」時，畫面平滑 zoom 到滑鼠位置並持續追蹤滑鼠移動；說「退回全畫面」時緩動回全畫面。語音辨識在本機跑（串流中文 ASR），不需網路連線也不需訓練錄音樣本。

## 需求

- **macOS** 10.14+（使用 Quartz 框架取滑鼠座標）
- **OBS** 28+（內建 WebSocket server，無須額外外掛）
- **Python** 3.12+
- **uv** 套件管理工具

## 安裝

```bash
git clone https://github.com/htlin222/obs-voice-command.git
cd obs-voice-command
uv sync
```

首次執行時，ASR 模型會自動下載到 `~/.cache/obs-voice-command/`（約 488MB），之後不需重複下載。

## OBS 設定

1. 開啟 OBS
2. 前往 **工具 → WebSocket 伺服器設定**
3. 勾選 **啟用 WebSocket server**
4. 如果設了伺服器密碼，將密碼複製到本專案的 `config.toml` 的 `[obs]` 區塊內 `password` 欄位

## 快速開始

開啟 OBS 後，執行：

```bash
uv run obs-voice-command
```

程式會用預設設定連接 OBS（localhost:4455）。沒有 `config.toml` 時全部使用預設值；要自訂請見下方「自訂指令」。

**測試語音辨識** 而不實際動作 OBS：

```bash
uv run obs-voice-command --dry-run
```

**改用真 macOS 螢幕縮放**（輔助使用 Zoom，你和觀眾都看到放大；需開啟「使用鍵盤快速鍵來縮放」並給終端機輔助使用權限）：

```bash
uv run obs-voice-command --os
```

同一組語音詞；倍率由 `config.toml` 的 `[zoom] os_level` 控制（預設 1.5）。

**列出系統麥克風**：

```bash
uv run obs-voice-command --list-devices
```

## 自訂指令

將 `config.example.toml` 複製為 `config.toml`：

```bash
cp config.example.toml config.toml
```

編輯 `config.toml`，修改 `[[commands]]` 區塊：

```toml
[[commands]]
phrases = ["來個特寫", "放大一點"]
action = "zoom_in"

[[commands]]
phrases = ["退回全畫面", "拉遠"]
action = "zoom_out"
```

- `phrases`：字串陣列，關鍵詞列表（辨識時忽略聲調，同音字會相符）
- `action`：支援 `zoom_in`、`zoom_out`、`os_zoom_in`、`os_zoom_out`
  - `os_zoom_in` / `os_zoom_out`：改觸發真正的 macOS 螢幕縮放（輔助使用 Zoom，需開啟「使用鍵盤快速鍵來縮放」並給終端機輔助使用權限）；預設語音詞「螢幕放大」「螢幕縮小」

## 疑難排解

**「麥克風存取被拒」**

系統設定 → 隱私權與安全性 → 麥克風，將你的終端機 app 加入允許清單。

**「Display capture source not found」**

確認 OBS 已開啟，且設定好 scene。錯誤訊息會列出該 scene 裡所有可用的 source，複製正確的 source 名稱填入 `config.toml` 的 `[obs]` 區塊內 `source` 欄位。

**「WebSocket 連不上」**

檢查以下項目：
- OBS 是否執行中
- WebSocket server 是否已啟用（工具 → WebSocket 伺服器設定）
- `config.toml` 內的 `host`、`port`、`password` 是否正確

## 開發

```bash
uv run pytest
```

模組一覽：

- **config.py** — 設定檔解析、預設值管理
- **matcher.py** — 語音辨識結果與指令 phrase 的比對邏輯
- **zoom.py** — 縮放狀態管理（目標倍率、緩動計算）
- **mouse.py** — 系統滑鼠座標取得（macOS Quartz）
- **asr.py** — sherpa-onnx ASR 驅動、模型下載
- **obs_client.py** — OBS WebSocket 通訊、指令發送
- **main.py** — 主迴圈、語音→指令→OBS 協調

## Citation

If you use this project, please cite it:

**BibTeX:**

```bibtex
@software{lin2026obsvoicecommand,
  author = {Lin, Hsieh-Ting},
  title = {obs-voice-command: Voice-commanded zoom-to-mouse for OBS on macOS},
  year = {2026},
  url = {https://github.com/htlin222/obs-voice-command},
  version = {0.1.0}
}
```

<details>
<summary>AMA format</summary>

Lin HT. obs-voice-command: Voice-commanded zoom-to-mouse for OBS on macOS. Published online 2026. https://github.com/htlin222/obs-voice-command

</details>

<details>
<summary>APA format</summary>

Lin, H.-T. (2026). *obs-voice-command: Voice-commanded zoom-to-mouse for OBS on macOS* (Version 0.1.0) [Computer software]. https://github.com/htlin222/obs-voice-command

</details>

## License

This project is licensed under the [MIT License](LICENSE).
