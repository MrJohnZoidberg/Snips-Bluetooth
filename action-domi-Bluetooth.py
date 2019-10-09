#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import bluetooth  # install libbluetooth-dev
import paho.mqtt.client as mqtt
import json
import toml
import threading
import configparser


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
        self.nearby_devices = list()
        self.scan_thread = None
        synonym_list = config['global']['device_synonyms'].split(',')
        self.synonyms = {synonym.split('::')[0]: synonym.split('::')[1] for synonym in synonym_list}
        self.socket = bluetooth.BluetoothSocket()

    def scan_devices(self):
        self.nearby_devices = bluetooth.discover_devices(lookup_names=True)
        device_names = [name for addr, name in self.nearby_devices]
        if device_names:
            inject('bluetooth_devices', device_names, "add_devices")
        else:
            notify("Ich habe kein Gerät gefunden.")

    def connect_device(self, addr):
        self.socket.connect(addr)


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


def on_message_scan(client, userdata, msg):
    data = json.loads(msg.payload.decode("utf-8"))
    session_id = data['sessionId']

    bluetooth_cls.scan_thread = threading.Thread(target=bluetooth_cls.scan_devices)
    bluetooth_cls.scan_thread.start()

    say(session_id, "Die Bluetooth Suche wurde gestartet.")


def on_message_devices_say(client, userdata, msg):
    data = json.loads(msg.payload.decode("utf-8"))
    session_id = data['sessionId']

    devices = bluetooth_cls.nearby_devices

    part = ""
    for addr, name in devices:
        if name in bluetooth_cls.synonyms:
            part += bluetooth_cls.synonyms[name]
        else:
            part += name
        if name != devices[-1][1]:
            part += ", "

    if len(devices) > 1:
        say(session_id, "Die Geräte {devices} .".format(devices=part))
    elif len(devices) == 1:
        bluetooth_cls.connect_device(devices[0][0])
        say(session_id, "Das Gerät {devices} .".format(devices=part))
    else:
        say(session_id, "Kein Gerät.")


def on_message_injection_complete(client, userdata, msg):
    data = json.loads(msg.payload.decode("utf-8"))

    if data['requestId'] == "add_devices":
        if bluetooth_cls.scan_thread:
            del bluetooth_cls.scan_thread
        if len(bluetooth_cls.nearby_devices) > 1:
            notify("Ich habe {num} Geräte gefunden.".format(num=len(bluetooth_cls.nearby_devices)))
        else:
            notify("Ich habe ein Gerät gefunden.")


def say(session_id, text):
    mqtt_client.publish('hermes/dialogueManager/endSession', json.dumps({'text': text,
                                                                         'sessionId': session_id}))


def end_session(session_id):
    mqtt_client.publish('hermes/dialogueManager/endSession', json.dumps({'sessionId': session_id}))


def notify(text):
    mqtt_client.publish('hermes/dialogueManager/startSession', json.dumps({'init': {'type': 'notification',
                                                                                    'text': text}}))


def inject(entity_name, values, request_id, operation_kind='addFromVanilla'):
    operation_data = {entity_name: values}
    operation = (operation_kind, operation_data)
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
    default_config = read_configuration_file('config.ini.default')

    bluetooth_cls = Bluetooth()
    mqtt_client = mqtt.Client()
    mqtt_client.message_callback_add('hermes/intent/' + add_prefix('BluetoothDevicesScan'), on_message_scan)
    mqtt_client.message_callback_add('hermes/intent/' + add_prefix('BluetoothDevicesSay'), on_message_devices_say)
    mqtt_client.message_callback_add('hermes/injection/complete', on_message_injection_complete)
    mqtt_client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    mqtt_client.connect(MQTT_BROKER_ADDRESS.split(":")[0], int(MQTT_BROKER_ADDRESS.split(":")[1]))
    mqtt_client.subscribe('hermes/intent/' + add_prefix('BluetoothDevicesScan'))
    mqtt_client.subscribe('hermes/intent/' + add_prefix('BluetoothDevicesSay'))
    mqtt_client.subscribe('hermes/injection/complete')
    mqtt_client.loop_forever()
