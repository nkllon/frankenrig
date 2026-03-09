#!/Users/lou/.hammerspoon/.venv_obsws/bin/python
import json
import sys

import websocket


def main() -> int:
    try:
        ws = websocket.create_connection('ws://127.0.0.1:4455', timeout=2)
        _ = json.loads(ws.recv())  # Hello
        ws.send(json.dumps({'op': 1, 'd': {'rpcVersion': 1}}))
        _ = json.loads(ws.recv())  # Identified
        ws.send(json.dumps({
            'op': 6,
            'd': {
                'requestType': 'OpenVideoMixProjector',
                'requestId': 'open-preview-projector',
                'requestData': {'videoMixType': 'OBS_WEBSOCKET_VIDEO_MIX_TYPE_PREVIEW'}
            }
        }))
        resp = json.loads(ws.recv())
        ws.close()
        ok = resp.get('d', {}).get('requestStatus', {}).get('result', False)
        if ok:
            print('ok')
            return 0
        print('error:' + str(resp.get('d', {}).get('requestStatus', {}).get('comment')))
        return 1
    except Exception as e:
        print('exception:' + str(e))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
