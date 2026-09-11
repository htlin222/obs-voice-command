"""測試環境補丁：非 macOS 沒有 Quartz，用假模組頂替讓純邏輯測試能跑。"""
import importlib.util
import sys
import types

if importlib.util.find_spec("Quartz") is None:
    fake = types.ModuleType("Quartz")
    fake.kCGEventFlagMaskCommand = 1 << 20
    fake.kCGEventFlagMaskAlternate = 1 << 19
    fake.kCGHIDEventTap = 0
    sys.modules["Quartz"] = fake
