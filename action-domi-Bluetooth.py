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
        self.site_info = dict()

    def get_discoverable_devices(self, site_id):
        available_devices = self.site_info[site_id]['available_devices']
        paired_devices = self.site_info[site_id]['paired_devices']
        return [d for d in available_devices if d not in paired_devices]

    def get_addr_from_name(self, name, site_id):
        print(self.site_info[site_id]['available_devices'])
        addr_list = [d['mac_address'] for d in self.site_info[site_id]['available_devices']
                     if d['name'] == self.get_real_device_name(name)]
        if addr_list:
            return None, addr_list[0]
        else:
            return "Ich kenne das Gerät nicht.", None

    def get_name_from_addr(self, addr, site_id):
        addr_dict = dict()
        available_devices = self.site_info[site_id]['available_devices']
        for device in available_devices:
            if device['name'] in device_synonyms:
                addr_dict[device['mac_address']] = device_synonyms[device['name']]
            else:
                addr_dict[device['mac_address']] = device['name']
        if addr in addr_dict:
            return addr_dict[addr]
        else:
            return None

    @staticmethod
    def get_real_device_name(name):
        if name in device_synonyms.values():
            print([rn for rn in device_synonyms if device_synonyms[rn] == name])
            return [rn for rn in device_synonyms if device_synonyms[rn] == name][0]
        else:
            print(name)
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


def get_site_info(slot_dict, request_siteid):
    site_info = {'err': None, 'room_name': None, 'site_id': None}
    if 'room' in slot_dict:
        if request_siteid in bl.site_info and slot_dict['room'] == bl.site_info[request_siteid]['room_name'] \
                or slot_dict['room'] == "hier":
            site_info['site_id'] = request_siteid
        elif request_siteid in bl.site_info and slot_dict['room'] != bl.site_info[request_siteid]['room_name']:
            dict_rooms = {bl.site_info[siteid]['room_name']: siteid for siteid in bl.site_info}
            site_info['site_id'] = dict_rooms[slot_dict['room']]
        else:
            site_info['err'] = f"Der Raum {slot_dict['room']} wurde noch nicht konfiguriert."
    else:
        site_info['site_id'] = request_siteid
    if 'room_name' in bl.site_info[site_info['site_id']]:
        site_info['room_name'] = bl.site_info[site_info['site_id']]['room_name']
    else:
        site_info['err'] = f"Der Raum {slot_dict['room']} wurde noch nicht konfiguriert."
    return site_info


def msg_device_lists(client, userdata, msg):
    data = json.loads(msg.payload.decode("utf-8"))
    site_id = data['siteId']
    available_devices = data['available_devices']
    paired_devices = data['paired_devices']
    connected_devices = data['connected_devices']
    if site_id in bl.site_info:
        bl.site_info[site_id]['available_devices'] = available_devices
        bl.site_info[site_id]['paired_devices'] = paired_devices
        bl.site_info[site_id]['connected_devices'] = connected_devices
    else:
        bl.site_info[site_id] = {'available_devices': available_devices, 'paired_devices': paired_devices,
                                 'connected_devices': connected_devices}


def msg_site_info(client, userdata, msg):
    data = json.loads(msg.payload.decode("utf-8"))
    site_id = data['site_id']
    if site_id in bl.site_info:
        bl.site_info[site_id]['room_name'] = data['room_name']
    else:
        bl.site_info[site_id] = {'room_name': data['room_name']}


def msg_ask_discover(client, userdata, msg):
    data = json.loads(msg.payload.decode("utf-8"))
    site_info = get_site_info(get_slots(data), data['siteId'])
    end_session(client, data['sessionId'], site_info['err'])
    site_id = site_info['site_id']
    client.publish(f'bluetooth/request/oneSite/{site_id}/devicesDiscover')


def msg_result_discover(client, userdata, msg):
    data = json.loads(msg.payload.decode("utf-8"))
    if data['result']:
        notify(client, "Ich suche jetzt 30 Sekunden lang nach Geräten.", data['siteId'])
    else:
        notify(client, "Ich konnte leider nicht nach Geräten suchen.", data['siteId'])


def msg_result_discovered(client, userdata, msg):
    data = json.loads(msg.payload.decode("utf-8"))
    if data['discoverable_devices']:
        inject(client, 'bluetooth_devices', bl.get_name_list(data['discoverable_devices']), data['siteId'])
    else:
        notify(client, "Ich habe kein Gerät gefunden.", data['siteId'])


def msg_injection_complete(client, userdata, msg):
    data = json.loads(msg.payload.decode("utf-8"))
    names = bl.get_name_list(bl.get_discoverable_devices(data['requestId']))
    notify(client, "Ich habe folgende Geräte gefunden: %s" % ", ".join(names), data['siteId'])


def msg_ask_discovered(client, userdata, msg):
    data = json.loads(msg.payload.decode("utf-8"))
    site_info = get_site_info(get_slots(data), data['siteId'])
    if site_info['err']:
        end_session(client, data['sessionId'], site_info['err'])
        return
    site_id = site_info['site_id']
    names = bl.get_name_list(bl.get_discoverable_devices(site_id))
    if names:
        answer = "Ich habe folgende Geräte entdeckt: %s" % ", ".join(names)
    else:
        answer = "Ich kein Gerät entdeckt."
    end_session(client, data['sessionId'], answer)


def msg_ask_paired(client, userdata, msg):
    data = json.loads(msg.payload.decode("utf-8"))
    site_info = get_site_info(get_slots(data), data['siteId'])
    if site_info['err']:
        end_session(client, data['sessionId'], site_info['err'])
        return
    site_id = site_info['site_id']
    names = bl.get_name_list(bl.site_info[site_id]['paired_devices'])
    if names:
        answer = "Ich bin mit folgenden Geräten gekoppelt: %s" % ", ".join(names)
    else:
        answer = "Ich bin mit keinem Gerät gekoppelt."
    end_session(client, data['sessionId'], answer)


def msg_ask_connected(client, userdata, msg):
    data = json.loads(msg.payload.decode("utf-8"))
    site_info = get_site_info(get_slots(data), data['siteId'])
    if site_info['err']:
        end_session(client, data['sessionId'], site_info['err'])
        return
    site_id = site_info['site_id']
    names = bl.get_name_list(bl.site_info[site_id]['connected_devices'])
    if names:
        answer = "Ich bin mit folgenden Geräten verbunden: %s" % ", ".join(names)
    else:
        answer = "Ich bin mit keinem Gerät verbunden."
    end_session(client, data['sessionId'], answer)


def msg_ask_connect(client, userdata, msg):
    data = json.loads(msg.payload.decode("utf-8"))
    site_info = get_site_info(get_slots(data), data['siteId'])
    if site_info['err']:
        end_session(client, data['sessionId'], site_info['err'])
        return
    site_id = site_info['site_id']
    err, addr = bl.get_addr_from_name(get_slots(data)['device_name'], site_id)
    end_session(client, data['sessionId'], err)
    if not err:
        client.publish(f'bluetooth/request/oneSite/{site_id}/deviceConnect', json.dumps({'addr': addr}))
    else:
        mqtt_client.publish(f'bluetooth/request/oneSite/{site_id}/deviceLists')


def msg_result_connect(client, userdata, msg):
    data = json.loads(msg.payload.decode("utf-8"))
    site_id = data['siteId']
    name = bl.get_name_from_addr(data['addr'], site_id)
    if not name:
        name = ""
    if data['result']:
        notify(client, "Ich bin jetzt mit dem Gerät %s verbunden." % name, site_id)
    else:
        notify(client, "Ich konnte mich nicht mit dem Gerät %s verbinden." % name, site_id)


def msg_ask_disconnect(client, userdata, msg):
    data = json.loads(msg.payload.decode("utf-8"))
    site_info = get_site_info(get_slots(data), data['siteId'])
    if site_info['err']:
        end_session(client, data['sessionId'], site_info['err'])
        return
    site_id = site_info['site_id']
    err, addr = bl.get_addr_from_name(get_slots(data)['device_name'], site_id)
    end_session(client, data['sessionId'], err)
    if not err:
        client.publish(f'bluetooth/request/oneSite/{site_id}/deviceDisconnect', json.dumps({'addr': addr}))
    else:
        mqtt_client.publish('bluetooth/request/oneSite/deviceLists')


def msg_result_disconnect(client, userdata, msg):
    data = json.loads(msg.payload.decode("utf-8"))
    site_id = data['siteId']
    name = bl.get_name_from_addr(data['addr'], site_id)
    if not name:
        name = ""
    if data['result']:
        text = "Das Gerät %s wurde getrennt." % name
    else:
        text = "Ich konnte das Gerät %s nicht trennen." % name
    notify(client, text, site_id)


def msg_ask_remove(client, userdata, msg):
    data = json.loads(msg.payload.decode("utf-8"))
    site_info = get_site_info(get_slots(data), data['siteId'])
    if site_info['err']:
        end_session(client, data['sessionId'], site_info['err'])
        return
    site_id = site_info['site_id']
    err, addr = bl.get_addr_from_name(get_slots(data)['device_name'], site_id)
    end_session(client, data['sessionId'], err)
    if not err:
        client.publish(f'bluetooth/request/oneSite/{site_id}/deviceRemove', json.dumps({'addr': addr}))
    else:
        mqtt_client.publish('bluetooth/request/oneSite/deviceLists')


def msg_result_remove(client, userdata, msg):
    data = json.loads(msg.payload.decode("utf-8"))
    site_id = data['siteId']
    name = bl.get_name_from_addr(data['addr'], site_id)
    if not name:
        name = ""
    if data['result']:
        notify(client, "Das Gerät %s wurde aus der Datenbank entfernt." % name, site_id)
    else:
        notify(client, "Ich konnte das Gerät %s nicht entfernen." % name, site_id)


def end_session(client, session_id, text=None):
    if text:
        data = {'text': text, 'sessionId': session_id}
    else:
        data = {'sessionId': session_id}
    client.publish('hermes/dialogueManager/endSession', json.dumps(data))


def notify(client, text, site_id):
    data = {'type': 'notification', 'text': text}
    if site_id:
        payload = {'siteId': site_id, 'init': data}
    else:
        payload = {'init': data}
    client.publish('hermes/dialogueManager/startSession', json.dumps(payload))


def inject(client, entity_name, values, request_id, operation_kind='add'):
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
    client.message_callback_add('hermes/intent/' + add_prefix('BluetoothDevicesConnected'), msg_ask_connected)
    client.message_callback_add('hermes/intent/' + add_prefix('BluetoothDevicesDiscovered'), msg_ask_discovered)
    client.message_callback_add('hermes/intent/' + add_prefix('BluetoothDeviceConnect'), msg_ask_connect)
    client.message_callback_add('hermes/intent/' + add_prefix('BluetoothDeviceDisconnect'), msg_ask_disconnect)
    client.message_callback_add('hermes/intent/' + add_prefix('BluetoothDeviceRemove'), msg_ask_remove)
    client.message_callback_add('hermes/injection/complete', msg_injection_complete)
    client.subscribe('hermes/intent/' + add_prefix('BluetoothDevicesScan'))
    client.subscribe('hermes/intent/' + add_prefix('BluetoothDevicesPaired'))
    client.subscribe('hermes/intent/' + add_prefix('BluetoothDevicesConnected'))
    client.subscribe('hermes/intent/' + add_prefix('BluetoothDevicesDiscovered'))
    client.subscribe('hermes/intent/' + add_prefix('BluetoothDeviceConnect'))
    client.subscribe('hermes/intent/' + add_prefix('BluetoothDeviceDisconnect'))
    client.subscribe('hermes/intent/' + add_prefix('BluetoothDeviceRemove'))
    client.subscribe('hermes/injection/complete')

    client.message_callback_add('bluetooth/answer/deviceLists', msg_device_lists)
    client.message_callback_add('bluetooth/answer/siteInfo', msg_site_info)
    client.message_callback_add('bluetooth/answer/devicesDiscover', msg_result_discover)
    client.message_callback_add('bluetooth/answer/devicesDiscovered', msg_result_discovered)
    client.message_callback_add('bluetooth/answer/deviceConnect', msg_result_connect)
    client.message_callback_add('bluetooth/answer/deviceDisconnect', msg_result_disconnect)
    client.message_callback_add('bluetooth/answer/deviceRemove', msg_result_remove)
    client.subscribe('bluetooth/answer/#')


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
    mqtt_client.publish('bluetooth/request/allSites/deviceLists')
    mqtt_client.publish('bluetooth/request/allSites/siteInfo')
    mqtt_client.loop_forever()
