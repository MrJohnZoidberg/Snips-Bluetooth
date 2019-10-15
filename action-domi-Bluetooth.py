#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import paho.mqtt.client as mqtt
import json
import toml
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
        self.available_devices = dict()  # dictionary with siteId as key
        self.paired_devices = dict()  # dictionary with siteId as key

    def get_discoverable_devices(self):
        return [d for d in self.available_devices if d not in self.paired_devices]

    def get_addr_from_name(self, name):
        addr_list = [d['mac_address'] for d in self.available_devices if d['name'] == self.get_real_device_name(name)]
        if addr_list:
            return None, addr_list[0]
        else:
            return "Ich kenne das Gerät nicht.", None

    def get_name_from_addr(self, addr):
        addr_dict = dict()
        for device in self.available_devices:
            if device['name'] in device_synonyms:
                addr_dict[device['mac_address']] = device_synonyms[device['name']]
            else:
                addr_dict[device['mac_address']] = device['name']
        return addr_dict[addr]

    @staticmethod
    def get_real_device_name(name):
        if name in device_synonyms.values():
            return [device_synonyms[rn] for rn in device_synonyms if device_synonyms[rn] == name][0]
        else:
            return name

    @staticmethod
    def get_name_list(devices):
        names = list()
        for device in devices:
            if device['name'] in device_synonyms:
                names.append(device_synonyms[device['name']])
            else:
                names.append(device['name'])
        return names


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


def get_siteid(slot_dict, request_siteid):
    dict_siteids = {pair.split(":")[1]: pair.split(":")[0] for pair in config['global']['rooms_siteids'].split(",")}
    if 'room' in slot_dict:
        if request_siteid in dict_siteids and slot_dict['room'] == dict_siteids[request_siteid] \
                or slot_dict['room'] == "hier":
            siteid = request_siteid
        else:
            dict_rooms = {dict_siteids[siteid]: siteid for siteid in dict_siteids}
            siteid = dict_rooms[slot_dict['room']]
    else:
        siteid = request_siteid
    return siteid


def msg_device_lists(client, userdata, msg):
    data = json.loads(msg.payload.decode("utf-8"))
    site_id = data['siteId']
    bl.available_devices[site_id] = data['available_devices']
    bl.paired_devices[site_id] = data['paired_devices']


def msg_ask_discover(client, userdata, msg):
    data = json.loads(msg.payload.decode("utf-8"))
    end_session(client, data['sessionId'])
    site_id = get_siteid(get_slots(data), data['siteId'])
    topic_part = f'/{site_id}/devicesDiscover'
    client.message_callback_add('bluetooth/result' + topic_part, msg_result_discover)
    client.subscribe('bluetooth/result' + topic_part)
    client.publish('bluetooth/ask' + topic_part)


def msg_result_discover(client, userdata, msg):
    data = json.loads(msg.payload.decode("utf-8"))
    site_id = data['siteId']
    topic_part = f'/{site_id}/devicesDiscover'
    client.unsubscribe('bluetooth/result' + topic_part)
    client.message_callback_remove('bluetooth/result' + topic_part)
    if data['result']:
        topic_part = f'/{site_id}/devicesDiscovered'
        client.message_callback_add('bluetooth/result' + topic_part, msg_result_discovered)
        client.subscribe('bluetooth/result' + topic_part)
        notify(client, "Ich suche jetzt 30 Sekunden lang nach Geräten.")
    else:
        notify(client, "Ich konnte leider nicht nach Geräten suchen.")


def msg_result_discovered(client, userdata, msg):
    data = json.loads(msg.payload.decode("utf-8"))
    site_id = data['siteId']
    topic_part = f'/{site_id}/devicesDiscovered'
    client.unsubscribe('bluetooth/result' + topic_part)
    client.message_callback_remove('bluetooth/result' + topic_part)
    # TODO: Test whether the self.get_discoverable_devices() works here right now
    if data['discoverable_devices']:
        inject(client, 'bluetooth_devices', bl.get_name_list(data['discoverable_devices']), "add_devices")
    else:
        notify(client, "Ich habe kein Gerät gefunden.")


def msg_injection_complete(client, userdata, msg):
    data = json.loads(msg.payload.decode("utf-8"))
    if data['requestId'] == "add_devices":
        names = bl.get_name_list(bl.get_discoverable_devices())
        notify(client, "Ich habe folgende Geräte gefunden: %s" % ", ".join(names))


def msg_ask_discovered(client, userdata, msg):
    data = json.loads(msg.payload.decode("utf-8"))
    names = bl.get_name_list(bl.get_discoverable_devices())
    if names:
        answer = "Ich habe folgende Geräte entdeckt: %s" % ", ".join(names)
    else:
        answer = "Ich kein Gerät entdeckt."
    end_session(client, data['sessionId'], answer)


def msg_ask_paired(client, userdata, msg):
    data = json.loads(msg.payload.decode("utf-8"))
    names = bl.get_name_list(bl.paired_devices)
    if names:
        answer = "Ich bin mit folgenden Geräten gekoppelt: %s" % ", ".join(names)
    else:
        answer = "Ich bin mit keinem Gerät gekoppelt."
    end_session(client, data['sessionId'], answer)


def msg_ask_connect(client, userdata, msg):
    # TODO: Trust/untrust
    data = json.loads(msg.payload.decode("utf-8"))
    site_id = get_siteid(get_slots(data), data['siteId'])
    topic_part = f'/{site_id}/deviceConnect'
    client.message_callback_add('bluetooth/result' + topic_part, msg_result_connect)
    client.subscribe('bluetooth/result' + topic_part)
    err, addr = bl.get_addr_from_name(get_slots(data)['device_name'])
    end_session(client, data['sessionId'], err)
    client.publish('bluetooth/ask' + topic_part, {'addr': addr})


def msg_result_connect(client, userdata, msg):
    data = json.loads(msg.payload.decode("utf-8"))
    site_id = data['siteId']
    topic_part = f'/{site_id}/deviceConnect'
    client.unsubscribe('bluetooth/result' + topic_part)
    client.message_callback_remove('bluetooth/result' + topic_part)
    name = bl.get_name_from_addr(data['addr'])
    if data['result']:
        notify(client, "Ich bin jetzt bin dem Gerät %s verbunden." % name)
    else:
        notify(client, "Ich konnte mich nicht mit dem Gerät %s verbinden." % name)


def msg_disconnect(client, userdata, msg):
    data = json.loads(msg.payload.decode("utf-8"))
    slots = get_slots(data)

    err, addr = bl.get_addr_from_name(slots['device_name'])
    end_session(client, data['sessionId'], err)


def msg_remove(client, userdata, msg):
    data = json.loads(msg.payload.decode("utf-8"))
    slots = get_slots(data)

    err, addr = bl.get_addr_from_name(slots['device_name'])
    end_session(client, data['sessionId'], err)


def end_session(client, session_id, text=None):
    if text:
        data = {'text': text, 'sessionId': session_id}
    else:
        data = {'sessionId': session_id}
    client.publish('hermes/dialogueManager/endSession', json.dumps(data))


def notify(client, text):
    data = {'type': 'notification', 'text': text}
    client.publish('hermes/dialogueManager/startSession', json.dumps({'init': data}))


def inject(client, entity_name, values, request_id, operation_kind='addFromVanilla'):
    operation = (operation_kind, {entity_name: values})
    client.publish('hermes/injection/perform', json.dumps({'id': request_id, 'operations': [operation]}))


def dialogue(client, session_id, text, intent_filter, custom_data=None):
    data = {'text': text,
            'sessionId': session_id,
            'intentFilter': intent_filter}
    if custom_data:
        data['customData'] = json.dumps(custom_data)
    client.publish('hermes/dialogueManager/continueSession', json.dumps(data))


def on_connect(client, userdata, flags, rc):
    client.message_callback_add('hermes/intent/' + add_prefix('BluetoothDevicesScan'), msg_ask_discover)
    client.message_callback_add('hermes/intent/' + add_prefix('BluetoothDevicesPaired'), msg_ask_paired)
    client.message_callback_add('hermes/intent/' + add_prefix('BluetoothDevicesDiscovered'), msg_ask_discovered)
    client.message_callback_add('hermes/intent/' + add_prefix('BluetoothDeviceConnect'), msg_ask_connect)
    client.message_callback_add('hermes/intent/' + add_prefix('BluetoothDeviceDisconnect'), msg_disconnect)
    client.message_callback_add('hermes/intent/' + add_prefix('BluetoothDeviceRemove'), msg_remove)
    client.message_callback_add('hermes/injection/complete', msg_injection_complete)
    client.message_callback_add('bluetooth/update/deviceLists', msg_device_lists)
    client.subscribe('hermes/intent/' + add_prefix('BluetoothDevicesScan'))
    client.subscribe('hermes/intent/' + add_prefix('BluetoothDevicesPaired'))
    client.subscribe('hermes/intent/' + add_prefix('BluetoothDevicesDiscovered'))
    client.subscribe('hermes/intent/' + add_prefix('BluetoothDeviceConnect'))
    client.subscribe('hermes/intent/' + add_prefix('BluetoothDeviceDisconnect'))
    client.subscribe('hermes/intent/' + add_prefix('BluetoothDeviceRemove'))
    client.subscribe('hermes/injection/complete')
    client.subscribe('bluetooth/update/deviceLists')


if __name__ == "__main__":
    snips_config = toml.load('/etc/snips.toml')
    if 'mqtt' in snips_config['snips-common'].keys():
        MQTT_BROKER_ADDRESS = snips_config['snips-common']['mqtt']
    if 'mqtt_username' in snips_config['snips-common'].keys():
        MQTT_USERNAME = snips_config['snips-common']['mqtt_username']
    if 'mqtt_password' in snips_config['snips-common'].keys():
        MQTT_PASSWORD = snips_config['snips-common']['mqtt_password']

    config = read_configuration_file('config.ini')

    device_synonyms = list()
    if 'device_synonyms' in config['global']:
        device_synonyms = {pair.split(':')[0]: pair.split(':')[1]
                           for pair in config['global']['device_synonyms'].split(',')}

    bl = Bluetooth()

    mqtt_client = mqtt.Client()
    mqtt_client.on_connect = on_connect
    mqtt_client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    mqtt_client.connect(MQTT_BROKER_ADDRESS.split(":")[0], int(MQTT_BROKER_ADDRESS.split(":")[1]))
    mqtt_client.loop_forever()
