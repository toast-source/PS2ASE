# core/clipboard.py
import win32clipboard
import json
import logging

class BridgeClipboard:
    SIGNATURE_MARKER = "ase_ps_bridge_payload"

    @staticmethod
    def set_payload(payload_dict):
        try:
            payload_str = json.dumps(payload_dict, ensure_ascii=False)
            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(payload_str, win32clipboard.CF_UNICODETEXT)
            win32clipboard.CloseClipboard()
            return True
        except Exception as e:
            logging.error(f"Clipboard Write Failed: {e}")
            return False

    @staticmethod
    def get_payload():
        try:
            win32clipboard.OpenClipboard()
            data = None
            if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
                data = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
            win32clipboard.CloseClipboard()

            if data:
                payload = json.loads(data)
                if payload.get("signature") == BridgeClipboard.SIGNATURE_MARKER:
                    return payload
            return None
        except:
            return None
