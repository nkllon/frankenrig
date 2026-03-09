#!/Users/lou/.hammerspoon/.venv_obsws/bin/python
import json
import websocket

URL = 'ws://127.0.0.1:4455'


def req(ws, t, data=None, rid='r'):
    ws.send(json.dumps({'op': 6, 'd': {'requestType': t, 'requestId': rid, 'requestData': data or {}}}))
    r = json.loads(ws.recv())
    d = r.get('d', {})
    ok = d.get('requestStatus', {}).get('result', False)
    return ok, d.get('responseData', {}), d.get('requestStatus', {})


def main():
    ws = websocket.create_connection(URL, timeout=3)
    hello = json.loads(ws.recv())
    ws.send(json.dumps({'op': 1, 'd': {'rpcVersion': 1}}))
    _ = json.loads(ws.recv())

    out = {}

    ok, data, st = req(ws, 'GetVersion', rid='version')
    out['version'] = {'ok': ok, 'status': st, 'data': data}

    ok, data, st = req(ws, 'GetSceneList', rid='scenes')
    out['scene_list'] = {'ok': ok, 'status': st, 'data': data}

    ok, data, st = req(ws, 'GetCurrentProgramScene', rid='prog')
    out['program_scene'] = {'ok': ok, 'status': st, 'data': data}

    inputs = []
    ok, data, st = req(ws, 'GetInputList', rid='inputs')
    out['input_list'] = {'ok': ok, 'status': st, 'data': data}
    if ok:
        for i in data.get('inputs', []):
            name = i.get('inputName')
            kind = i.get('inputKind')
            ok2, sdata, _ = req(ws, 'GetInputSettings', {'inputName': name}, rid=f'set_{name}')
            inputs.append({'inputName': name, 'inputKind': kind, 'settings_ok': ok2, 'settings': sdata.get('inputSettings', {}) if ok2 else {}})
    out['inputs_with_settings'] = inputs

    scenes = []
    if out['scene_list']['ok']:
        for s in out['scene_list']['data'].get('scenes', []):
            sn = s.get('sceneName')
            ok3, idata, _ = req(ws, 'GetSceneItemList', {'sceneName': sn}, rid=f'items_{sn}')
            scenes.append({'sceneName': sn, 'items_ok': ok3, 'items': idata.get('sceneItems', []) if ok3 else []})
    out['scene_items'] = scenes

    ok, data, st = req(ws, 'GetRecordStatus', rid='record')
    out['record_status'] = {'ok': ok, 'status': st, 'data': data}

    ok, data, st = req(ws, 'GetStreamStatus', rid='stream')
    out['stream_status'] = {'ok': ok, 'status': st, 'data': data}

    ws.close()
    print(json.dumps(out, indent=2))


if __name__ == '__main__':
    main()
