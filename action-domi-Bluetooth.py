#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import paho.mqtt.client as mqtt
import json
import toml
import uuid


USERNAME_INTENTS = "domi"
MQTT_BROKER_ADDRESS = "localhost:1883"
MQTT_USERNAME = None
MQTT_PASSWORD = None


def add_prefix(intent_name):
    return USERNAME_INTENTS + ":" + intent_name


class Bluetooth:
    def __init__(self):
        self.sites_info = dict()
        self.inject_requestids = dict()

    def get_discoverable_devices(self, site_id):
        available_devices = self.sites_info[site_id]['available_devices']
        paired_devices = self.sites_info[site_id]['paired_devices']
        return [d for d in available_devices if d not in paired_devices]

    def get_addr_from_name(self, name, site_id):
        addr_list = [d['mac_address'] for d in self.sites_info[site_id]['available_devices']
                     if d['name'] == self.get_real_device_name(name, self.sites_info[site_id]['device_names'])]
        if addr_list:
            return None, addr_list[0]
        else:
            return "Ich kenne das Gerät nicht.", None

    @staticmethod
    def get_real_device_name(name, device_names):
        found_real_name = None
        for real_name in device_names:
            synonyms = device_names[real_name]
            if isinstance(synonyms, str) and synonyms == name:
                found_real_name = real_name
                break
            elif isinstance(synonyms, list):
                for synonym in synonyms:
                    if synonym == name:
                        found_real_name = real_name
                        break
            if found_real_name:
                break
        if found_real_name:
            return found_real_name
        else:
            return name

    def get_name_from_addr(self, addr, site_id):
        addr_dict = dict()
        available_devices = self.sites_info[site_id]['available_devices']
        device_names = self.sites_info[site_id]['device_names']
        for device in available_devices:
            synonyms = device_names.get(device['name'])
            if synonyms:
                if isinstance(synonyms, str):
                    addr_dict[device['mac_address']] = synonyms
                elif isinstance(synonyms, list):
                    addr_dict[device['mac_address']] = synonyms[0]
            else:
                addr_dict[device['mac_address']] = device['name']
        return addr_dict.get(addr)

    def get_name_list(self, devices, site_id):
        names = list()
        device_names = self.sites_info[site_id]['device_names']
        for device in devices:
            synonyms = device_names.get(device['name'])
            if synonyms:
                if isinstance(synonyms, str) and synonyms not in names:
                    names.append(synonyms)
                elif isinstance(synonyms, list):
                    if synonyms[0] not in names:
                        names.append(synonyms[0])
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
        slot_dict = {}
    return slot_dict


def get_site_info(slot_dict, request_siteid):
    site_info = {'err': None, 'room_name': None, 'site_id': None}
    if 'room' in slot_dict:
        if request_siteid in bl.sites_info and slot_dict['room'] == bl.sites_info[request_siteid]['room_name'] \
                or slot_dict['room'] == "hier":
            site_info['site_id'] = request_siteid
        elif request_siteid in bl.sites_info and slot_dict['room'] != bl.sites_info[request_siteid]['room_name']:
            dict_rooms = {bl.sites_info[siteid]['room_name']: siteid for siteid in bl.sites_info}
            site_info['site_id'] = dict_rooms[slot_dict['room']]
        else:
            site_info['err'] = f"Der Raum {slot_dict['room']} wurde noch nicht konfiguriert."
    else:
        site_info['site_id'] = request_siteid
    if site_info['site_id'] in bl.sites_info and 'room_name' in bl.sites_info[site_info['site_id']]:
        site_info['room_name'] = bl.sites_info[site_info['site_id']]['room_name']
    elif 'room' in slot_dict:
        site_info['err'] = f"Der Raum {slot_dict['room']} wurde noch nicht konfiguriert."
    else:
        site_info['err'] = "Es gab einen Fehler."
    return site_info


def msg_site_info(client, userdata, msg):
    data = json.loads(msg.payload.decode("utf-8"))
    bl.sites_info[data['site_id']] = data


def msg_ask_discover(client, userdata, msg):
    data = json.loads(msg.payload.decode("utf-8"))
    site_info = get_site_info(get_slots(data), data['siteId'])
    end_session(client, data['sessionId'], site_info['err'])
    site_id = site_info['site_id']
    client.publish(f'bluetooth/request/oneSite/{site_id}/devicesDiscover')


def msg_result_discover(client, userdata, msg):
    data = json.loads(msg.payload.decode("utf-8"))
    if data['result']:
        notify(client, "Es wird 30 Sekunden nach neuen Geräten gesucht.", data['siteId'])
    else:
        notify(client, "Die Gerätesuche konnte nicht gestartet werden.", data['siteId'])


def msg_result_discovered(client, userdata, msg):
    data = json.loads(msg.payload.decode("utf-8"))
    if data['discoverable_devices']:
        site_id = data['siteId']
        request_id = str(uuid.uuid4())
        bl.inject_requestids[request_id] = site_id
        inject(client, 'audio_devices', bl.get_name_list(data['discoverable_devices'], site_id), request_id)
    else:
        notify(client, "Es wurde kein Gerät entdeckt.", data['siteId'])


def msg_injection_complete(client, userdata, msg):
    data = json.loads(msg.payload.decode("utf-8"))
    request_id = data['requestId']
    if request_id in bl.inject_requestids:
        site_id = bl.inject_requestids[request_id]
        del bl.inject_requestids[request_id]
        names = bl.get_name_list(bl.get_discoverable_devices(site_id), site_id)
        notify(client, "Es wurden folgende Geräte entdeckt: %s" % ", ".join(names), site_id)


def msg_ask_discovered(client, userdata, msg):
    data = json.loads(msg.payload.decode("utf-8"))
    site_info = get_site_info(get_slots(data), data['siteId'])
    if site_info['err']:
        end_session(client, data['sessionId'], site_info['err'])
        return
    site_id = site_info['site_id']
    names = bl.get_name_list(bl.get_discoverable_devices(site_id), site_id)
    if names:
        answer = "Folgende Geräte wurden entdeckt: %s" % ", ".join(names)
    else:
        answer = "Es wurde kein Gerät entdeckt."
    end_session(client, data['sessionId'], answer)


def msg_ask_paired(client, userdata, msg):
    data = json.loads(msg.payload.decode("utf-8"))
    site_info = get_site_info(get_slots(data), data['siteId'])
    if site_info['err']:
        end_session(client, data['sessionId'], site_info['err'])
        return
    site_id = site_info['site_id']
    names = bl.get_name_list(bl.sites_info[site_id]['paired_devices'], site_id)
    if names:
        answer = "Folgende Geräte sind gekoppelt: %s" % ", ".join(names)
    else:
        answer = "Es ist kein Gerät gekoppelt."
    end_session(client, data['sessionId'], answer)


def msg_ask_connected(client, userdata, msg):
    data = json.loads(msg.payload.decode("utf-8"))
    site_info = get_site_info(get_slots(data), data['siteId'])
    if site_info['err']:
        end_session(client, data['sessionId'], site_info['err'])
        return
    site_id = site_info['site_id']
    names = bl.get_name_list(bl.sites_info[site_id]['connected_devices'], site_id)
    if names:
        answer = "Folgende Geräte sind verbunden: %s" % ", ".join(names)
    else:
        answer = "Es ist kein Gerät verbunden."
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
        mqtt_client.publish(f'bluetooth/request/oneSite/{site_id}/siteInfo')


def msg_result_connect(client, userdata, msg):
    data = json.loads(msg.payload.decode("utf-8"))
    site_id = data['siteId']
    name = bl.get_name_from_addr(data['addr'], site_id)
    if not name:
        name = ""
    if data['result']:
        notify(client, "Das Gerät %s ist jetzt verbunden." % name, site_id)
    else:
        notify(client, "Das Gerät %s konnte nicht verbunden werden." % name, site_id)


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
        mqtt_client.publish(f'bluetooth/request/oneSite/{site_id}/siteInfo')


def msg_result_disconnect(client, userdata, msg):
    data = json.loads(msg.payload.decode("utf-8"))
    site_id = data['siteId']
    name = bl.get_name_from_addr(data['addr'], site_id)
    if not name:
        name = ""
    if data['result']:
        text = "Das Gerät %s wurde getrennt." % name
    else:
        text = "Das Gerät %s konnte nicht getrennt werden." % name
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
        mqtt_client.publish(f'bluetooth/request/oneSite/{site_id}/siteInfo')


def msg_result_remove(client, userdata, msg):
    data = json.loads(msg.payload.decode("utf-8"))
    site_id = data['siteId']
    name = bl.get_name_from_addr(data['addr'], site_id)
    if not name:
        name = ""
    if data['result']:
        notify(client, "Das Gerät %s wurde aus der Datenbank entfernt." % name, site_id)
    else:
        notify(client, "Das Gerät %s konnte nicht aus der Datenbank entfernt werden." % name, site_id)


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

    bl = Bluetooth()

    mqtt_client = mqtt.Client()
    mqtt_client.on_connect = on_connect
    mqtt_client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    mqtt_client.connect(MQTT_BROKER_ADDRESS.split(":")[0], int(MQTT_BROKER_ADDRESS.split(":")[1]))
    mqtt_client.publish('bluetooth/request/allSites/siteInfo')
    mqtt_client.loop_forever()
