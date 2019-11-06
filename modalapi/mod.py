#!/usr/bin/env python

import json
import os
import requests as req
import sys

import modalapi.controller as Controller
import modalapi.pedalboard as Pedalboard

from modalapi.footswitch import Footswitch

sys.path.append('/usr/lib/python3.5/site-packages')  # TODO possibly /usr/local/modep/mod-ui
from mod.development import FakeHost as Host


class Mod:
    __single = None

    def __init__(self, lcd):
        print("Init mod")
        if Mod.__single:
            raise Mod.__single
        Mod.__single = self

        self.lcd = lcd
        self.root_uri = "http://localhost:80/"
        self.pedalboards = {}  # TODO make the ordering of entries deterministic
        #self.controllers = {}  # Keyed by midi_channel:midi_CC
        self.current_pedalboard = None
        self.current_preset_index = 0
        self.current_num_presets = 4  # TODO XXX

        self.selected_plugin_index = 0
        self.current_num_plugins = 9  # TODO XXX

        self.plugin_dict = {}

        # TODO should this be here?
        #self.load_pedalboards()

        # Create dummy host for obtaining pedalboard info
        self.host = Host(None, None, self.msg_callback)

        self.hardware = None

    def add_hardware(self, hardware):
        self.hardware = hardware

    def msg_callback(self, msg):
        print(msg)

    def load_pedalboards(self):
        url = self.root_uri + "pedalboard/list"

        try:
            resp = req.get(url)
        except:  # TODO
            print("Cannot connect to mod-host.")
            sys.exit()

        if resp.status_code != 200:
            print("Cannot connect to mod-host.  Status: %s" % resp.status_code)
            sys.exit()

        pbs = json.loads(resp.text)
        for pb in pbs:
            print("Loading pedalboard info: %s" % pb['title'])
            bundle = pb['bundle']
            title = pb['title']
            pedalboard = Pedalboard.Pedalboard(bundle, title)
            pedalboard.load_bundle(bundle, self.plugin_dict)
            self.pedalboards[bundle] = pedalboard
            #print("dump: %s" % pedalboard.to_json())

        # TODO - example of querying host
        #bund = self.get_current_pedalboard()
        #self.host.load(bund, False)
        #print("Preset: %s %d" % (bund, self.host.pedalboard_preset))  # this value not initialized
        #print("Preset: %s" % self.get_current_preset_name())

    def bind_current_pedalboard(self):
        # "current" being the pedalboard mod-host says is current
        # The pedalboard data has already been loaded, but this will overlay
        # any real time settings
        footswitch_plugins = []
        pb = self.get_current_pedalboard()
        if pb in self.pedalboards:
            self.current_pedalboard = self.pedalboards[pb]
            print("set current PB as: %s" % self.current_pedalboard)
            #print(self.current_pedalboard.to_json())
            for plugin in self.current_pedalboard.plugins:
                for sym, param in plugin.parameters.items():
                    if param.binding is not None:
                        controller = self.hardware.controllers.get(param.binding)
                        if controller is not None:
                            #print("Map: %s %s %s" % (plugin.instance_id, param.name, param.binding))
                            # TODO possibly use a setter instead of accessing var directly
                            # What if multiple params could map to the same controller?
                            controller.parameter = param
                            controller.set_value(param.value)
                            plugin.controllers.append(controller)
                            if isinstance(controller, Footswitch):
                                # TODO sort this list so selection orders correctly (sort on midi_CC?)
                                plugin.has_footswitch = True
                                footswitch_plugins.append(plugin)

            # Move Footswitch controlled plugins to the end of the list
            self.current_pedalboard.plugins = [elem for elem in self.current_pedalboard.plugins
                                               if elem.has_footswitch is False]
            self.current_pedalboard.plugins += footswitch_plugins


    # TODO change these functions ripped from modep
    def get_current_pedalboard(self):
        url = self.root_uri + "pedalboard/current"
        try:
            resp = req.get(url)
            # TODO pass code define
            if resp.status_code == 200:
                return resp.text
        except:
            return None

    def get_current_pedalboard_name(self):
        pb = self.get_current_pedalboard()
        return os.path.splitext(os.path.basename(pb))[0]

    # TODO remove
    def get_current_pedalboard_index(self, pedalboards, current):
        try:
            return pedalboards.index(current)
        except:
            return None

    def next_plugin(self, plugins, enc):
        test = self.selected_plugin_index
        found = 0
        for found in range(self.selected_plugin_index, len(plugins)):
            test = ((test - 1) if (enc is not 1)
                    else (test + 1)) % self.current_num_plugins
            plugin = plugins[test]  # TODO check index
            if len(plugin.controllers) == 0:
                found = test
                break
        print (found)
        return found

    def get_selected_instance(self):
        if self.current_pedalboard is not None:
            pb = self.current_pedalboard
            inst = pb.plugins[self.selected_plugin_index]
            if inst is not None:
                return inst
        return None

    def plugin_select(self, encoder, clk_pin):
        enc = encoder.get_data()
        if self.current_pedalboard is not None:
            pb = self.current_pedalboard
            index = ((self.selected_plugin_index - 1) if (enc is not 1)
                    else (self.selected_plugin_index + 1)) % len(pb.plugins)
            #index = self.next_plugin(pb.plugins, enc)
            plugin = pb.plugins[index]  # TODO check index
            self.selected_plugin_index = index
            self.lcd.draw_plugin_select(plugin)

    def bottom_encoder_sw(self, value):
        # TODO check mode here
        if value > 512:  # button up
            self.toggle_plugin_bypass()


    def toggle_plugin_bypass(self):
        inst = self.get_selected_instance()
        if inst is not None:
            if inst.has_footswitch:
                for c in inst.controllers:
                    if isinstance(c, Footswitch):
                        c.toggle(0)
                        return
            # Regular (non footswitch plugin)
            url = self.root_uri + "effect/parameter/set//graph%s/:bypass" % inst.instance_id
            value = inst.toggle_bypass()
            if value:
                resp = req.post(url, json={"value":"1"})
            else:
                resp = req.post(url, json={"value":"0"})
            if resp.status_code != 200:
                print("Bad Rest request: %s status: %d" % (url, resp.status_code))
                inst.toggle_bypass()  # toggle back to original value since request wasn't successful
            self.update_lcd_plugins()


    # TODO doesn't seem to work without host being properly initialized
    def get_current_preset_name(self):
        return self.host.pedalpreset_name(self.current_preset_index)

    def preset_change(self, encoder, clk_pin):
        enc = encoder.get_data()
        index = ((self.current_preset_index - 1) if (enc == 1)
                 else (self.current_preset_index + 1)) % self.current_num_presets
        print("preset change: %d" % index)
        url = "http://localhost/pedalpreset/load?id=%d" % index
        print(url)
        # req.get("http://localhost/reset")
        resp = req.get(url)
        if resp.status_code != 200:
            print("Bad Rest request: %s status: %d" % (url, resp.status_code))
        self.current_preset_index = index

        # TODO move formatting to common place
        # TODO name varaibles so they don't have to be calculated
        text = "%s-%s" % (self.get_current_pedalboard_name(), self.get_current_preset_name())
        self.lcd.draw_title(text)
        self.update_lcd()  # TODO just update zone0

    def update_lcd(self):
        print("draw LCD")
        pb_name = self.get_current_pedalboard_name()
        if pb_name is None:
            return
        title = "%s-%s" % (self.get_current_pedalboard_name(), self.get_current_preset_name())
        self.lcd.draw_title(title)
        self.lcd.refresh_zone(0)
        pb = self.get_current_pedalboard()
        if self.pedalboards[pb] is None:
            return
        self.lcd.draw_plugins(self.pedalboards[pb].plugins)
        self.lcd.refresh_zone(1)  # TODO mod module probably shouldn't know about specific zones
        self.lcd.refresh_zone(3)
        self.lcd.refresh_zone(5)

        self.lcd.draw_bound_plugins(self.pedalboards[pb].plugins)
        self.lcd.refresh_zone(7)

    def update_lcd_plugins(self):
        pb = self.get_current_pedalboard()
        if self.pedalboards[pb] is None:
            return
        self.lcd.draw_plugins(self.pedalboards[pb].plugins)
        self.lcd.refresh_zone(3)
        self.lcd.refresh_zone(5)

    def update_lcd_fs(self):
        pb = self.get_current_pedalboard()
        if self.pedalboards[pb] is None:
            return
        self.lcd.draw_bound_plugins(self.pedalboards[pb].plugins)
        self.lcd.refresh_zone(7)
