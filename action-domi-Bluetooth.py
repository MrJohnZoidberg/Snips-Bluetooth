#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import bluetooth  # install libbluetooth-dev
import paho.mqtt.client as mqtt
import json
import toml
import threading


USERNAME_INTENTS = "domi"
MQTT_BROKER_ADDRESS = "localhost:1883"
MQTT_USERNAME = None
MQTT_PASSWORD = None


def add_prefix(intent_name):
    return USERNAME_INTENTS + ":" + intent_name


class Bluetooth:
    def __init__(self):
        self.nearby_devices = None
        self.scan_thread = None

    def scan_devices(self):
        self.nearby_devices = bluetooth.discover_devices(lookup_names=True)
        mqtt_client.publish('bluetooth/scan_finished')


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


def on_message_scan_finished(client, userdata, msg):
    if bluetooth_cls.scan_thread:
        del bluetooth_cls.scan_thread
    sentence = "Die Bluetooth Suche wurde beendet."
    if len(bluetooth_cls.nearby_devices) > 1:
        sentence += " Ich habe {num} Geräte gefunden.".format(num=len(bluetooth_cls.nearby_devices))
    elif len(bluetooth_cls.nearby_devices) == 1:
        sentence += " Ich habe ein Gerät gefunden."
    else:
        sentence += " Ich habe kein Gerät gefunden."
    notify(sentence)


def on_message_devices_say(client, userdata, msg):
    data = json.loads(msg.payload.decode("utf-8"))
    session_id = data['sessionId']

    devices = bluetooth_cls.nearby_devices

    part = ""
    for addr, name in devices:
        part += name
        if name != devices[-1][1]:
            part += ", "

    if len(devices) > 1:
        say(session_id, "Die Geräte {devices} .".format(devices=part))
    elif len(devices) == 1:
        say(session_id, "Das Gerät {devices} .".format(devices=part))
    else:
        say(session_id, "Kein Gerät.")


def say(session_id, text):
    mqtt_client.publish('hermes/dialogueManager/endSession', json.dumps({'text': text,
                                                                         'sessionId': session_id}))


def end_session(session_id):
    mqtt_client.publish('hermes/dialogueManager/endSession', json.dumps({'sessionId': session_id}))


def notify(text):
    mqtt_client.publish('hermes/dialogueManager/startSession', json.dumps({'init': {'type': 'notification',
                                                                                    'text': text}}))


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

    bluetooth_cls = Bluetooth()
    mqtt_client = mqtt.Client()
    mqtt_client.message_callback_add('hermes/intent/' + add_prefix('BluetoothDevicesScan'), on_message_scan)
    mqtt_client.message_callback_add('hermes/intent/' + add_prefix('BluetoothDevicesSay'), on_message_devices_say)
    mqtt_client.message_callback_add('bluetooth/scan_finished', on_message_scan_finished)
    mqtt_client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    mqtt_client.connect(MQTT_BROKER_ADDRESS.split(":")[0], int(MQTT_BROKER_ADDRESS.split(":")[1]))
    mqtt_client.subscribe('hermes/intent/' + add_prefix('BluetoothDevicesScan'))
    mqtt_client.subscribe('hermes/intent/' + add_prefix('BluetoothDevicesSay'))
    mqtt_client.subscribe('bluetooth/scan_finished')
    mqtt_client.loop_forever()
