#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import paho.mqtt.client as mqtt
import json
import toml
import threading
import configparser
import bluetoothctl
import time


USERNAME_INTENTS = "domi"
MQTT_BROKER_ADDRESS = "localhost:1883"
MQTT_USERNAME = None
MQTT_PASSWORD = None


def add_prefix(intent_name):
    return USERNAME_INTENTS + ":" + intent_name


def read_configuration_file(configuration_file):
    try:
        cp = configparser.ConfigParser()
        with open(configuration_file, encoding="utf-8") as f:
            cp.read_file(f)
        return {section: {option_name: option for option_name, option in cp.items(section)}
                for section in cp.sections()}
    except (IOError, configparser.Error):
        return dict()


class Bluetooth:
    def __init__(self):
        self.discoverable_devices = list()
        self.scan_thread = None
        synonym_list = config['global']['device_synonyms'].split(',')
        self.synonyms = {synonym.split(':')[0]: synonym.split(':')[1] for synonym in synonym_list}
        self.ctl = bluetoothctl.Bluetoothctl()

    def scan_devices(self):
        self.scan_thread = threading.Thread(target=self.thread_scan)
        self.scan_thread.start()

    def get_name_list(self, devices):
        names = []
        for device in devices:
            if device['name'] in self.synonyms:
                names.append(self.synonyms[device['name']])
            else:
                names.append(device['name'])
        return names

    def thread_scan(self):
        self.ctl.start_scan()
        for i in range(30):
            current_scan_devices = self.ctl.get_discoverable_devices()
            if len(current_scan_devices) > len(self.discoverable_devices):
                new_devices = [device for device in current_scan_devices if device not in self.discoverable_devices]
                print("Found new bluetooth device(s): %s" % ", ".join(self.get_name_list(new_devices)))
            self.discoverable_devices = current_scan_devices
            time.sleep(1)

        if self.discoverable_devices:
            names = self.get_name_list(self.discoverable_devices)
            inject('bluetooth_devices', names, "add_devices")
        else:
            notify("Ich habe kein Gerät gefunden.")


def get_slots(data):
    slot_dict = {}
    try:
        for slot in data['slots']:
            if slot['value']['kind'] in ["InstantTime", "TimeInterval", "Duration"]:
                slot_dict[slot['slotName']] = slot['value']
            elif slot['value']['kind'] == "Custom":
                slot_dict[slot['slotName']] = slot['value']['value']
    except (KeyError, TypeError, ValueError) as e:
        print("Error: ", e)
        slot_dict = {}
    return slot_dict


def get_addr(name):
    if name in bluetooth_cls.synonyms.values():
        name = [real_name for real_name in bluetooth_cls.synonyms if name == bluetooth_cls.synonyms[real_name]][0]
    addr = [device['mac_address'] for device in bluetooth_cls.discoverable_devices if name == device['name']][0]
    return addr


def msg_scan(client, userdata, msg):
    data = json.loads(msg.payload.decode("utf-8"))
    session_id = data['sessionId']

    bluetooth_cls.scan_devices()
    say(session_id, "Ich suche jetzt 30 Sekunden lang nach Geräten.")


def msg_known(client, userdata, msg):
    data = json.loads(msg.payload.decode("utf-8"))
    session_id = data['sessionId']

    names = bluetooth_cls.get_name_list(bluetooth_cls.ctl.get_available_devices())
    if len(names) > 1:
        say(session_id, "Ich kenne die Geräte %s ." % ", ".join(names))
    elif len(names) == 1:
        say(session_id, "Ich kenne das Gerät %s ." % names[0])
    else:
        say(session_id, "Ich kenne noch kein Gerät.")


def msg_connect(client, userdata, msg):
    data = json.loads(msg.payload.decode("utf-8"))
    slots = get_slots(data)
    session_id = data['sessionId']

    bluetooth_cls.ctl.connect(slots['device_name'])
    say(session_id, "%s ist jetzt verbunden." % slots['device_name'])


def msg_disconnect(client, userdata, msg):
    data = json.loads(msg.payload.decode("utf-8"))
    slots = get_slots(data)
    session_id = data['sessionId']

    bluetooth_cls.ctl.disconnect(get_addr(slots['device_name']))
    say(session_id, "%s ist jetzt getrennt." % slots['device_name'])


def msg_injection_complete(client, userdata, msg):
    data = json.loads(msg.payload.decode("utf-8"))
    if data['requestId'] == "add_devices":
        if bluetooth_cls.scan_thread:
            del bluetooth_cls.scan_thread
        names = bluetooth_cls.get_name_list(bluetooth_cls.discoverable_devices)
        if len(names) > 1:
            notify("Ich habe folgende Geräte gefunden: %s" % ", ".join(names))
        else:
            notify("Ich habe das Gerät %s gefunden." % names[0])


def msg_remove(client, userdata, msg):
    data = json.loads(msg.payload.decode("utf-8"))
    slots = get_slots(data)
    session_id = data['sessionId']

    bluetooth_cls.ctl.remove(get_addr(slots['device_name']))
    say(session_id, "%s wurde entfernt." % slots['device_name'])


def say(session_id, text):
    if text:
        data = {'text': text, 'sessionId': session_id}
    else:
        data = {'sessionId': session_id}
    mqtt_client.publish('hermes/dialogueManager/endSession', json.dumps(data))


def notify(text):
    data = {'type': 'notification', 'text': text}
    mqtt_client.publish('hermes/dialogueManager/startSession', json.dumps({'init': data}))


def inject(entity_name, values, request_id, operation_kind='addFromVanilla'):
    operation = (operation_kind, {entity_name: values})
    mqtt_client.publish('hermes/injection/perform', json.dumps({'id': request_id, 'operations': [operation]}))


def dialogue(session_id, text, intent_filter, custom_data=None):
    data = {'text': text,
            'sessionId': session_id,
            'intentFilter': intent_filter}
    if custom_data:
        data['customData'] = json.dumps(custom_data)
    mqtt_client.publish('hermes/dialogueManager/continueSession', json.dumps(data))


if __name__ == "__main__":
    snips_config = toml.load('/etc/snips.toml')
    if 'mqtt' in snips_config['snips-common'].keys():
        MQTT_BROKER_ADDRESS = snips_config['snips-common']['mqtt']
    if 'mqtt_username' in snips_config['snips-common'].keys():
        MQTT_USERNAME = snips_config['snips-common']['mqtt_username']
    if 'mqtt_password' in snips_config['snips-common'].keys():
        MQTT_PASSWORD = snips_config['snips-common']['mqtt_password']

    config = read_configuration_file('config.ini')

    bluetooth_cls = Bluetooth()

    mqtt_client = mqtt.Client()
    mqtt_client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    mqtt_client.connect(MQTT_BROKER_ADDRESS.split(":")[0], int(MQTT_BROKER_ADDRESS.split(":")[1]))
    mqtt_client.message_callback_add('hermes/intent/' + add_prefix('BluetoothDevicesScan'), msg_scan)
    mqtt_client.message_callback_add('hermes/intent/' + add_prefix('BluetoothDevicesKnown'), msg_known)
    mqtt_client.message_callback_add('hermes/intent/' + add_prefix('BluetoothDeviceConnect'), msg_connect)
    mqtt_client.message_callback_add('hermes/intent/' + add_prefix('BluetoothDeviceDisconnect'), msg_disconnect)
    mqtt_client.message_callback_add('hermes/intent/' + add_prefix('BluetoothDeviceDisconnectRemove'), msg_remove)
    mqtt_client.message_callback_add('hermes/injection/complete', msg_injection_complete)
    mqtt_client.subscribe('hermes/intent/' + add_prefix('BluetoothDevicesScan'))
    mqtt_client.subscribe('hermes/intent/' + add_prefix('BluetoothDevicesKnown'))
    mqtt_client.subscribe('hermes/intent/' + add_prefix('BluetoothDeviceConnect'))
    mqtt_client.subscribe('hermes/intent/' + add_prefix('BluetoothDeviceDisconnect'))
    mqtt_client.subscribe('hermes/intent/' + add_prefix('BluetoothDeviceRemove'))
    mqtt_client.subscribe('hermes/injection/complete')
    mqtt_client.loop_forever()
