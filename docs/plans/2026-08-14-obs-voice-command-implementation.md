# obs-voice-command Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 語音指令（「來個特寫」/「退回全畫面」）控制 OBS 對螢幕擷取 source 做 zoom-to-mouse 追蹤縮放。

**Architecture:** 外部 Python daemon：sounddevice 收麥克風 → sherpa-onnx 串流中文 ASR → pinyin 關鍵詞比對 → Zoom 控制器 30fps 讀滑鼠、算 transform、經 obs-websocket 送 `SetSceneItemTransform`。設計文件：`docs/plans/2026-08-14-obs-voice-command-design.md`（實作前先讀）。

**Tech Stack:** Python 3.12 + uv venv、sherpa-onnx、sounddevice、pypinyin、obsws-python、pyobjc-framework-Quartz、pytest。

**Conventions:** 所有程式碼在 `src/obs_voice_command/`，測試在 `tests/`。每個 task 結尾 commit。跑指令一律用 `uv run`。程式內註解與 docstring 用繁體中文或英文皆可，但要少而精。

---

### Task 1: 專案腳手架

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `src/obs_voice_command/__init__.py`, `tests/__init__.py`

**Step 1: 建立 pyproject.toml**

```toml
[project]
name = "obs-voice-command"
version = "0.1.0"
description = "Voice-commanded zoom-to-mouse for OBS on macOS"
requires-python = ">=3.12"
dependencies = [
    "sherpa-onnx>=1.10",
    "sounddevice>=0.4",
    "pypinyin>=0.50",
    "obsws-python>=1.7",
    "pyobjc-framework-Quartz>=10.0",
]

[dependency-groups]
dev = ["pytest>=8.0"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/obs_voice_command"]

[project.scripts]
obs-voice-command = "obs_voice_command.main:cli"
```

**Step 2: .gitignore**

```
.venv/
__pycache__/
*.pyc
.pytest_cache/
uv.lock
```

**Step 3: 建立空的 `src/obs_voice_command/__init__.py` 和 `tests/__init__.py`**

**Step 4: 驗證環境**

Run: `uv sync && uv run pytest --collect-only -q`
Expected: 成功（0 tests collected 沒關係）。若 `uv sync` 因某依賴失敗，回報錯誤全文，不要自行改依賴版本。

**Step 5: Commit**

```bash
git add -A && git commit -m "chore: 專案腳手架 (uv + pyproject)"
```

---

### Task 2: config.py — 設定載入

**Files:**
- Create: `src/obs_voice_command/config.py`
- Test: `tests/test_config.py`

**Step 1: 寫失敗測試 `tests/test_config.py`**

```python
from pathlib import Path
from obs_voice_command.config import load_config

def test_defaults_when_file_missing(tmp_path: Path):
    cfg = load_config(tmp_path / "nope.toml")
    assert cfg.obs.port == 4455
    assert cfg.zoom.level == 2.0
    assert cfg.zoom.deadzone == 0.15
    assert cfg.zoom.smoothing == 0.12
    # 預設指令表必須內建
    actions = {c.action for c in cfg.commands}
    assert actions == {"zoom_in", "zoom_out"}
    zi = next(c for c in cfg.commands if c.action == "zoom_in")
    assert "來個特寫" in zi.phrases

def test_partial_override(tmp_path: Path):
    p = tmp_path / "config.toml"
    p.write_text(
        '[zoom]\nlevel = 3.0\n\n'
        '[[commands]]\nphrases = ["放大"]\naction = "zoom_in"\n',
        encoding="utf-8",
    )
    cfg = load_config(p)
    assert cfg.zoom.level == 3.0
    assert cfg.zoom.deadzone == 0.15          # 未覆寫的用預設
    assert len(cfg.commands) == 1             # commands 整組覆寫，不合併
    assert cfg.obs.host == "localhost"

def test_invalid_action_raises(tmp_path: Path):
    p = tmp_path / "config.toml"
    p.write_text('[[commands]]\nphrases = ["x"]\naction = "explode"\n', encoding="utf-8")
    import pytest
    with pytest.raises(ValueError):
        load_config(p)
```

**Step 2: 跑測試確認失敗**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL（ImportError）

**Step 3: 實作 `config.py`**

用 stdlib `tomllib` + `dataclasses`。結構：

```python
@dataclass(frozen=True)
class ObsConfig: host="localhost"; port=4455; password=""; scene=""; source=""
@dataclass(frozen=True)
class ZoomConfig: level=2.0; deadzone=0.15; smoothing=0.12
@dataclass(frozen=True)
class AudioConfig: device=""
@dataclass(frozen=True)
class Command: phrases: tuple[str, ...]; action: str   # action ∈ {"zoom_in","zoom_out"}
@dataclass(frozen=True)
class Config: obs: ObsConfig; zoom: ZoomConfig; audio: AudioConfig; commands: tuple[Command, ...]

def load_config(path: Path) -> Config: ...
```

規則：檔案不存在 → 全預設。存在 → 逐區塊覆寫（區塊內未給的 key 用預設）。`commands` 一旦在檔案出現就整組取代預設。`action` 不在允許集合 → `ValueError`。預設 commands：`來個特寫/放大一點 → zoom_in`、`退回全畫面/拉遠 → zoom_out`。

**Step 4: 跑測試確認通過**

Run: `uv run pytest tests/test_config.py -v` → PASS

**Step 5: Commit** `git add -A && git commit -m "feat: config 載入與預設值"`

---

### Task 3: matcher.py — 關鍵詞比對器

**Files:**
- Create: `src/obs_voice_command/matcher.py`
- Test: `tests/test_matcher.py`

比對器職責：吃 ASR 的 partial 文字，回傳觸發的 action。**不**管 zoom 狀態（那是控制器的事）。

**Step 1: 寫失敗測試**

```python
from obs_voice_command.config import Command
from obs_voice_command.matcher import Matcher

CMDS = (
    Command(phrases=("來個特寫", "放大一點"), action="zoom_in"),
    Command(phrases=("退回全畫面",), action="zoom_out"),
)

def mk(cooldown=2.0):
    return Matcher(CMDS, cooldown=cooldown)

def test_exact_match_in_partial():
    m = mk()
    assert m.feed("這邊來個特寫", now=10.0) == "zoom_in"

def test_homophone_match():
    # ASR 同音錯字：「來個特些」pinyin 相同（忽略聲調）
    m = mk()
    assert m.feed("來個特些", now=10.0) == "zoom_in"

def test_no_match():
    m = mk()
    assert m.feed("今天天氣不錯", now=10.0) is None

def test_growing_partial_fires_once():
    # 同一 utterance 的 partial 逐步變長，只能觸發一次
    m = mk()
    assert m.feed("來個", now=10.0) is None
    assert m.feed("來個特寫", now=10.1) == "zoom_in"
    assert m.feed("來個特寫好", now=10.2) is None
    assert m.feed("來個特寫好不好", now=10.3) is None

def test_endpoint_resets_utterance_but_cooldown_holds():
    m = mk(cooldown=2.0)
    assert m.feed("來個特寫", now=10.0) == "zoom_in"
    m.reset_utterance()
    assert m.feed("來個特寫", now=11.0) is None      # 冷卻中
    assert m.feed("來個特寫", now=12.5) == "zoom_in"  # 冷卻過了

def test_different_actions_independent_cooldown():
    m = mk(cooldown=2.0)
    assert m.feed("來個特寫", now=10.0) == "zoom_in"
    m.reset_utterance()
    assert m.feed("退回全畫面", now=10.5) == "zoom_out"
```

**Step 2:** Run: `uv run pytest tests/test_matcher.py -v` → FAIL

**Step 3: 實作 `matcher.py`**（完整程式碼如下，照抄）

```python
"""ASR partial 文字 → 指令 action 的比對器。

比對走 pinyin（忽略聲調）子字串，容忍同音錯字。
同一 utterance（兩次 endpoint 之間）每個 action 只觸發一次，
另有跨 utterance 的 per-action 冷卻時間。
"""
from __future__ import annotations

from pypinyin import lazy_pinyin

from .config import Command


def _pin(text: str) -> str:
    return "".join(lazy_pinyin(text))


class Matcher:
    def __init__(self, commands: tuple[Command, ...], cooldown: float = 2.0):
        self._cooldown = cooldown
        # [(pinyin_phrase, action)]
        self._patterns = [
            (_pin(p), c.action) for c in commands for p in c.phrases
        ]
        self._fired_this_utterance: set[str] = set()
        self._last_fired: dict[str, float] = {}

    def feed(self, text: str, now: float) -> str | None:
        """吃一段 partial 文字，回傳觸發的 action 或 None。"""
        hay = _pin(text)
        for pat, action in self._patterns:
            if action in self._fired_this_utterance:
                continue
            if now - self._last_fired.get(action, float("-inf")) < self._cooldown:
                continue
            if pat and pat in hay:
                self._fired_this_utterance.add(action)
                self._last_fired[action] = now
                return action
        return None

    def reset_utterance(self) -> None:
        """ASR endpoint（句子結束）時呼叫。"""
        self._fired_this_utterance.clear()
```

**Step 4:** Run: `uv run pytest tests/test_matcher.py -v` → PASS

**Step 5: Commit** `git add -A && git commit -m "feat: pinyin 關鍵詞比對器"`

---

### Task 4: zoom.py — Transform 純數學

**Files:**
- Create: `src/obs_voice_command/zoom.py`
- Test: `tests/test_zoom.py`

純函數模組，**不碰** OBS/滑鼠/時間。所有座標單位是「source 像素」除非另註明。

**Step 1: 寫失敗測試**

```python
import math
from obs_voice_command.zoom import (
    Transform, compute_transform, apply_deadzone, smooth,
)

# 情境：1920x1080 canvas，source 3840x2160（Retina 2x），
# 原始 transform 把 source 縮到剛好鋪滿 canvas：scale 0.5, pos (0,0)
ORIG = Transform(pos_x=0.0, pos_y=0.0, scale_x=0.5, scale_y=0.5)
CANVAS = (1920.0, 1080.0)
SRC = (3840.0, 2160.0)

def test_zoom_centers_mouse():
    # 滑鼠在 source 正中央 → zoom 後 position 應讓中央對準 canvas 中心
    t = compute_transform(ORIG, CANVAS, SRC, z=2.0, cx=1920.0, cy=1080.0)
    assert math.isclose(t.scale_x, 1.0)
    # canvas_center(960) - 1920*1.0 = -960，但 clamp 下限 = 1920-3840 = -1920 → -960 合法
    assert math.isclose(t.pos_x, -960.0)
    assert math.isclose(t.pos_y, -540.0)

def test_zoom_corner_is_clamped():
    # 滑鼠在 (0,0) 角落 → 未 clamp 會是正值（露黑邊），必須 clamp 到 0
    t = compute_transform(ORIG, CANVAS, SRC, z=2.0, cx=0.0, cy=0.0)
    assert t.pos_x == 0.0 and t.pos_y == 0.0

def test_zoom_far_corner_clamped():
    t = compute_transform(ORIG, CANVAS, SRC, z=2.0, cx=3840.0, cy=2160.0)
    assert math.isclose(t.pos_x, 1920.0 - 3840.0)   # canvas_w - src_w*scale
    assert math.isclose(t.pos_y, 1080.0 - 2160.0)

def test_z1_returns_original():
    t = compute_transform(ORIG, CANVAS, SRC, z=1.0, cx=123.0, cy=456.0)
    # z=1 時不管滑鼠在哪都應回到原始鋪滿狀態
    assert math.isclose(t.scale_x, 0.5) and math.isclose(t.pos_x, 0.0)

def test_deadzone_inside_no_move():
    assert apply_deadzone(cx=100.0, cy=100.0, mx=110.0, my=100.0, radius=50.0) == (100.0, 100.0)

def test_deadzone_outside_moves_to_edge():
    # 滑鼠在右方 100px、半徑 50 → 目標往滑鼠方向移到「距滑鼠 50」處
    cx, cy = apply_deadzone(cx=100.0, cy=100.0, mx=200.0, my=100.0, radius=50.0)
    assert math.isclose(cx, 150.0) and math.isclose(cy, 100.0)

def test_smooth_converges():
    v = 0.0
    for _ in range(200):
        v = smooth(v, 100.0, 0.12)
    assert abs(v - 100.0) < 1.0

def test_smooth_snaps_when_close():
    assert smooth(99.999, 100.0, 0.12) == 100.0   # 距離 < 0.01 直接貼齊
```

**Step 2:** Run: `uv run pytest tests/test_zoom.py -v` → FAIL

**Step 3: 實作 `zoom.py`**（完整程式碼，照抄）

```python
"""Zoom transform 純數學。座標單位：source 像素（除非註明 canvas）。"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Transform:
    pos_x: float
    pos_y: float
    scale_x: float
    scale_y: float


def compute_transform(
    orig: Transform,
    canvas: tuple[float, float],
    src: tuple[float, float],
    z: float,
    cx: float,
    cy: float,
) -> Transform:
    """以 source 內的點 (cx, cy) 為中心、倍率 z 計算 scene item transform。

    z=1 時回傳原始 transform。position 會 clamp 避免露出畫布外黑邊。
    """
    if math.isclose(z, 1.0):
        return orig
    sx = orig.scale_x * z
    sy = orig.scale_y * z
    cw, ch = canvas
    px = cw / 2.0 - cx * sx
    py = ch / 2.0 - cy * sy
    px = _clamp(px, cw - src[0] * sx, 0.0)
    py = _clamp(py, ch - src[1] * sy, 0.0)
    return Transform(pos_x=px, pos_y=py, scale_x=sx, scale_y=sy)


def apply_deadzone(
    cx: float, cy: float, mx: float, my: float, radius: float
) -> tuple[float, float]:
    """滑鼠 (mx,my) 在目前中心 (cx,cy) 的 deadzone 內 → 中心不動；
    在外 → 中心沿連線移到距滑鼠 radius 處（畫面追上但不過衝）。"""
    dx, dy = mx - cx, my - cy
    dist = math.hypot(dx, dy)
    if dist <= radius:
        return cx, cy
    k = (dist - radius) / dist
    return cx + dx * k, cy + dy * k


def smooth(current: float, target: float, factor: float) -> float:
    """指數平滑一步；距離 < 0.01 直接貼齊避免抖動不收斂。"""
    nxt = current + (target - current) * factor
    if abs(nxt - target) < 0.01:
        return target
    return nxt


def _clamp(v: float, lo: float, hi: float) -> float:
    if lo > hi:  # source 比 canvas 小的退化情況：置中不 clamp
        return v
    return max(lo, min(hi, v))
```

**Step 4:** Run: `uv run pytest tests/test_zoom.py -v` → PASS

**Step 5: Commit** `git add -A && git commit -m "feat: zoom transform 純數學模組"`

---

### Task 5: mouse.py — 滑鼠座標（macOS Quartz）

**Files:**
- Create: `src/obs_voice_command/mouse.py`
- Test: `tests/test_mouse.py`（僅測純邏輯部分）

**規格**：

```python
@dataclass(frozen=True)
class DisplayInfo:
    origin_x: float; origin_y: float   # 全域座標中的螢幕原點（points）
    width_pts: float; height_pts: float
    width_px: int; height_px: int      # 實際像素（Retina 下 = pts × 2）

def get_displays() -> list[DisplayInfo]:
    # Quartz.CGGetActiveDisplayList → 每顆用 CGDisplayBounds（points）
    # + CGDisplayPixelsWide/High（pixels）
def get_mouse_pos() -> tuple[float, float]:
    # Quartz.CGEventCreate(None) + CGEventGetLocation → 全域 points，
    # 原點在主螢幕左上、y 向下（與 CGDisplayBounds 同座標系，可直接比）
def locate(pos: tuple[float, float], displays: list[DisplayInfo]) -> tuple[DisplayInfo, float, float] | None:
    # 純函數：判斷滑鼠在哪顆螢幕，回傳 (display, 螢幕內像素 x, 螢幕內像素 y)
    # 像素 = (pos − origin) × (width_px / width_pts)；不在任何螢幕 → None
```

**Step 1: 只為 `locate` 寫測試**（`get_*` 是 thin wrapper，不測）：構造兩顆假 DisplayInfo（主螢幕 0,0 1512×982 pts / 3024×1964 px；外接 1512,0 1920×1080 pts / 1920×1080 px），驗證：滑鼠在主螢幕內回傳 2x 像素座標；在外接螢幕回傳 1x；在範圍外回傳 None；邊界點 (0,0) 屬於主螢幕。

**Step 2:** 跑測試 → FAIL。 **Step 3:** 實作。 **Step 4:** 跑測試 → PASS。

**Step 5: 手動 smoke test**

Run: `uv run python -c "from obs_voice_command.mouse import *; d=get_displays(); print(d); print(get_mouse_pos()); print(locate(get_mouse_pos(), d))"`
Expected: 印出至少一顆螢幕、目前滑鼠座標、locate 結果非 None。把輸出貼回報告。

**Step 6: Commit** `git add -A && git commit -m "feat: Quartz 滑鼠座標與多螢幕定位"`

---

### Task 6: obs_client.py — OBS websocket 封裝

**Files:**
- Create: `src/obs_voice_command/obs_client.py`
- Test: 無 unit test（全是 IO），Task 9 手動驗證

**規格**：用 `obsws_python` 的 `ReqClient`。類別 `ObsClient`：

```python
class ObsClient:
    def __init__(self, host, port, password): ...
    def connect(self) -> None                      # 建 ReqClient；失敗丟 ConnectionError
    def get_canvas_size(self) -> tuple[float, float]
        # get_video_settings() → base_width/base_height
    def find_display_capture(self, scene: str, source: str) -> "SceneItem"
        # scene 空 → get_current_program_scene()
        # source 空 → get_scene_item_list(scene) 找第一個
        #   input_kind 含 "display_capture" 或 "screen_capture" 的 item
        # 找不到 → raise RuntimeError（訊息含該 scene 的所有 source 名，幫使用者除錯）
        # 回傳 SceneItem(scene_name, item_id, source_width, source_height)
        #   source 尺寸用 get_scene_item_transform 的 source_width/source_height
    def get_transform(self, item) -> Transform      # 讀 position_x/y, scale_x/y → zoom.Transform
    def set_transform(self, item, t: Transform) -> None
        # set_scene_item_transform(scene_name, item_id,
        #   {"positionX":…, "positionY":…, "scaleX":…, "scaleY":…})
```

注意：obsws-python 的回傳屬性是 snake_case（`base_width`）；送出的 transform dict key 是 camelCase（`positionX`）。**不確定 API 名稱時，先 `uv run python -c "import obsws_python, inspect; ..."` 查原始碼確認，不要用猜的。**

**Step 1:** 實作。 **Step 2:** `uv run python -c "from obs_voice_command.obs_client import ObsClient"` 確認 import 無誤。

**Step 3: Commit** `git add -A && git commit -m "feat: obs-websocket 客戶端封裝"`

---

### Task 7: asr.py — sherpa-onnx 串流 ASR

**Files:**
- Create: `src/obs_voice_command/asr.py`
- Test: 無 unit test（模型 IO），Task 9 驗證

**規格**：

```python
MODEL_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/"
             "asr-models/sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20.tar.bz2")
CACHE_DIR = Path.home() / ".cache" / "obs-voice-command"

def ensure_model() -> Path:
    # 目錄已存在且含 tokens.txt → 直接回傳
    # 否則 urllib 下載 tar.bz2（印進度）→ tarfile 解到 CACHE_DIR → 回傳模型目錄

class Asr:
    def __init__(self, model_dir: Path): ...
        # sherpa_onnx.OnlineRecognizer.from_transducer(
        #   tokens=…/tokens.txt,
        #   encoder=…/encoder-epoch-99-avg-1.int8.onnx,
        #   decoder=…/decoder-epoch-99-avg-1.onnx,      # decoder 沒有 int8 版
        #   joiner=…/joiner-epoch-99-avg-1.int8.onnx,
        #   enable_endpoint_detection=True, sample_rate=16000, feature_dim=80)
        # self._stream = recognizer.create_stream()
    def feed(self, samples: "np.ndarray") -> tuple[str, bool]:
        # accept_waveform(16000, samples)；while is_ready: decode
        # text = get_result(stream)（str）
        # endpoint = is_endpoint(stream)；若 endpoint → reset(stream)
        # 回傳 (text, endpoint)
```

檔名以解壓出來的實際檔案為準（先 `ls` 確認再寫死）。`from_transducer` 參數名不確定就先查：`uv run python -c "import sherpa_onnx, inspect; print(inspect.signature(sherpa_onnx.OnlineRecognizer.from_transducer))"`。

**Step 1:** 實作 `ensure_model` 並跑 `uv run python -c "from obs_voice_command.asr import ensure_model; print(ensure_model())"`（下載約 100-200MB，需時數分鐘）。
**Step 2:** 實作 `Asr`，用 1 秒靜音 smoke test：`uv run python -c "import numpy as np; from obs_voice_command.asr import *; a=Asr(ensure_model()); print(a.feed(np.zeros(16000, dtype=np.float32)))"` → 印 `('', False)` 之類即可。
**Step 3: Commit** `git add -A && git commit -m "feat: sherpa-onnx 串流 ASR 與模型自動下載"`

---

### Task 8: main.py — 主程式組裝

**Files:**
- Create: `src/obs_voice_command/main.py`
- Test: 無 unit test（Task 9 手動 E2E）

**規格**（單一檔案，兩個執行緒 + 主執行緒）：

1. **CLI**：`argparse`，參數 `--config`（預設 `config.toml`）、`--dry-run`、`--list-devices`（印 `sounddevice.query_devices()` 後退出）。
2. **啟動順序**：load_config → ensure_model/Asr → （非 dry-run 時）ObsClient.connect + find_display_capture + get_transform（存為 `orig`）+ get_canvas_size → get_displays → 開音訊 stream。
3. **音訊執行緒**：`sounddevice.InputStream(samplerate=16000, channels=1, dtype="float32", callback=…)`，callback 把資料丟 `queue.Queue`；主迴圈從 queue 取出餵 `asr.feed`，text 有變化就印 `\r[ASR] {text}`；endpoint → `matcher.reset_utterance()` + 換行。`matcher.feed(text, now=time.monotonic())` 回傳 action → 丟給 zoom 控制器（thread-safe：用 `threading.Event`/簡單屬性即可）。
4. **Zoom 控制器執行緒**（30fps 迴圈）：
   - 狀態：`target_z`（1.0 或 cfg.zoom.level）、`cur_z`、`cur_cx/cur_cy`（source 像素）
   - 收到 `zoom_in` 且 `target_z == 1.0` → target_z = level，中心初始化為目前滑鼠位置；收到 `zoom_out` 且 target_z > 1 → target_z = 1.0（其餘情況忽略，並印「已在該狀態，忽略」）
   - 每 tick：`mouse.locate(...)` 取滑鼠 source 像素（None → 沿用上次）；追蹤中（target_z>1）先過 `apply_deadzone`（radius = canvas_w/level×deadzone 換算成 source 像素：`radius = src_w / z * deadzone`）；`cur_z = smooth(cur_z, target_z, smoothing)`、`cur_cx/cy = smooth(...)`；`compute_transform(orig, canvas, src, cur_z, cur_cx, cur_cy)` → `set_transform`（dry-run 就印出來）
   - `cur_z == 1.0` 且 target 也是 1.0 → set_transform(orig) 一次後 idle（不再送，省 websocket 流量）
5. **清理**：`try/finally` + `signal.SIGINT/SIGTERM` handler → 停迴圈、`set_transform(orig)`、關 stream。OBS 斷線（set_transform 拋例外）→ 印警告、每 3 秒重連，重連成功後 `set_transform(orig)` 復原再繼續。
6. **麥克風權限**：開 InputStream 失敗 → 印「系統設定 → 隱私權與安全性 → 麥克風」指引後退出。

**Step 1:** 實作。 **Step 2:** `uv run obs-voice-command --list-devices` 印出裝置列表。
**Step 3:** `uv run obs-voice-command --dry-run` 跑起來，對麥克風講「來個特寫」，終端機應印 ASR 文字與 `[TRIGGER] zoom_in` 與 dry-run transform。講「退回全畫面」→ `[TRIGGER] zoom_out`。Ctrl-C 正常退出。把終端輸出貼回報告。
**Step 4: Commit** `git add -A && git commit -m "feat: 主程式組裝（音訊/ASR/zoom 迴圈/清理）"`

---

### Task 9: README 與收尾

**Files:**
- Create: `README.md`, `config.example.toml`

**Step 1:** `config.example.toml` = 設計文件裡的完整範例設定。
**Step 2:** `README.md`：一段是什麼、需求（macOS、OBS ≥ 30 開 websocket server：工具 → WebSocket 伺服器設定）、安裝（`uv sync`）、快速開始（開 OBS → `uv run obs-voice-command`）、指令表怎麼改、疑難排解（麥克風權限、找不到 display capture、websocket 密碼）。
**Step 3:** 全部測試最後一遍：`uv run pytest -v` → 全 PASS。
**Step 4: Commit** `git add -A && git commit -m "docs: README 與範例設定"`

---

## 驗收清單（全部完成後）

- [ ] `uv run pytest -v` 全綠
- [ ] `uv run obs-voice-command --dry-run` 語音觸發 zoom_in/zoom_out 事件正常
- [ ] 開著 OBS 實跑：說「來個特寫」畫面 zoom 到滑鼠並追蹤、「退回全畫面」復原、Ctrl-C 後 transform 完整復原
