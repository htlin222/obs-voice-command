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
