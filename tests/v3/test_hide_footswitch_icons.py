"""Hiding LCD icons preserves hardware actions, LED state and config overlays."""

from unittest.mock import patch

import pytest
import yaml

from common.parameter import BYPASS_SYMBOL
from pistomp.config import parse
from pistomp.config.adapt_v1 import adapt
from pistomp.config.schema_v1 import merge
from pistomp.input.event import SwitchEvent, SwitchEventKind


def _load_board(system, tmp_path, entries):
    board = system.handler.pedalboards["/path/to/rig.pedalboard"]
    board.bundle = str(tmp_path)
    (tmp_path / "config.yml").write_text(yaml.safe_dump({"hardware": {"footswitches": entries}}))
    system.handler.set_current_pedalboard(board)
    return board


@pytest.mark.parametrize("hidden_ids", [set(), {0}, {1}, {0, 1, 2, 3}])
def test_hidden_icons_compact_bound_and_unbound_switches(v3_system, tmp_path, make_plugin, hidden_ids):
    system = v3_system
    board = system.handler.pedalboards["/path/to/rig.pedalboard"]
    plugin = make_plugin("Drive", category="Distortion", has_footswitch=True)
    plugin.parameters[BYPASS_SYMBOL].binding = f"{system.hw.midi_channel}:61"
    board.plugins = [plugin]
    _load_board(system, tmp_path, [{"id": i, "hide_icon": True} for i in hidden_ids])
    widgets = system.handler.lcd.w_footswitches
    visible_ids = [i for i in range(4) if i not in hidden_ids]
    assert [w.object.id for w in widgets] == visible_ids
    if visible_ids:
        pitch = 320 // len(visible_ids)
        assert [w.box.x0 for w in widgets] == [pitch * i for i in range(len(visible_ids))]
        assert all(w.box.width == pitch for w in widgets)
    assert all(not fs.disabled for fs in system.hw.footswitches)
    assert system.hw.footswitches[1].parameter is plugin.parameters[BYPASS_SYMBOL]

    # Reloading a board without the override restores all four icons.
    _load_board(system, tmp_path, [])
    assert [w.object.id for w in system.handler.lcd.w_footswitches] == [0, 1, 2, 3]


def test_hidden_snapshot_switch_keeps_led_and_press_action(v3_system, tmp_path):
    handler = v3_system.handler
    fs = v3_system.hw.footswitches[0]
    with patch.object(fs, "set_led") as set_led:
        _load_board(v3_system, tmp_path, [{"id": 0, "hide_icon": True, "preset": 1}])
        assert all(w.object is not fs for w in handler.lcd.w_footswitches)
        assert not fs.toggled
        set_led.assert_called_with(False)
        event = SwitchEvent(controller=fs, kind=SwitchEventKind.PRESS, timestamp=1000.0)
        assert handler.handle(event) is True
        assert handler.current.preset_index == 1
        assert fs.toggled
        set_led.assert_called_with(True)
        handler.preset_change(0)
        assert not fs.toggled
        set_led.assert_called_with(False)


def test_global_hide_icon_can_be_overridden_and_restored(v3_system):
    hw = v3_system.hw
    global_doc = parse({"hardware": {"footswitches": [{"id": 0, "hide_icon": True}]}}, "<global>")
    base = global_doc
    hw.reinit(adapt(merge(base)))
    assert hw.footswitches[0].hide_icon
    override = parse({"hardware": {"footswitches": [{"id": 0, "hide_icon": False}]}}, "<board>")
    hw.reinit(adapt(merge(base, override)))
    assert not hw.footswitches[0].hide_icon
    hw.reinit(adapt(merge(base)))
    assert hw.footswitches[0].hide_icon


def test_create_footswitch_reads_hide_icon(v3_system):
    hw = v3_system.hw
    document = parse({"hardware": {"footswitches": [{"id": 9, "gpio_input": 17, "hide_icon": True}]}}, "<test>")
    hw.create_footswitches(adapt(merge(document)))
    assert hw.footswitches[-1].id == 9
    assert hw.footswitches[-1].hide_icon
