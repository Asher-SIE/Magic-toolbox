import base64
import hashlib
import os
import pickle
import subprocess

from cryptography.fernet import Fernet


def _get_fernet():
    result = subprocess.run(
        ['ioreg', '-rd1', '-c', 'IOPlatformExpertDevice'],
        capture_output=True, text=True
    )
    for line in result.stdout.split('\n'):
        if 'IOPlatformUUID' in line:
            machine_id = line.split('"')[-2] + '@Asher'
            key = hashlib.sha256(machine_id.encode()).digest()
            key_b64 = base64.urlsafe_b64encode(key)
            return Fernet(key_b64)
    raise Exception("无法获取机器UUID")


_fernet = _get_fernet()

data_path = os.path.expanduser("~/Library/Application Support/MagicToolbox/.clipboard_data")

with open(data_path, "rb") as f:
    data = pickle.load(f)

pickled = pickle.dumps(data)
encrypted = _fernet.encrypt(pickled)

with open(data_path, "wb") as f:
    f.write(encrypted)

print(f"已加密 {len(data)} 条记录")
