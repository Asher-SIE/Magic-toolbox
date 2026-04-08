import datetime
import json
import os
import subprocess
import tempfile


ACTIVATION_DATE = datetime.date(2026, 4, 8)
EXPIRY_DAYS = 180
EXPIRY_WARNING_DAYS = 30

CURRENT_VERSION = "1.1.2"
GITHUB_REPO_OWNER = "Asher-SIE"
GITHUB_REPO_NAME = "Magic-toolbox"


def get_expiry_date():
    return ACTIVATION_DATE + datetime.timedelta(days=EXPIRY_DAYS)


def is_expired():
    return datetime.date.today() > get_expiry_date()


def is_expiring_soon():
    expiry = get_expiry_date()
    warning_start = expiry - datetime.timedelta(days=EXPIRY_WARNING_DAYS)
    return warning_start <= datetime.date.today() <= expiry


def days_until_expiry():
    delta = get_expiry_date() - datetime.date.today()
    return max(0, delta.days)


def get_current_version():
    return CURRENT_VERSION


def _parse_version(version_str):
    version_str = version_str.lstrip('vV')
    parts = version_str.split('.')
    return tuple(int(p) if p.isdigit() else 0 for p in parts)


def _compare_versions(v1, v2):
    parsed_v1 = _parse_version(v1)
    parsed_v2 = _parse_version(v2)
    if parsed_v1 > parsed_v2:
        return 1
    elif parsed_v1 < parsed_v2:
        return -1
    return 0


def get_latest_release_info():
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}/releases/latest"
        result = subprocess.run(
            ['curl', '-s', '-L', url],
            capture_output=True, text=True, timeout=15
        )
        data = json.loads(result.stdout)
        tag_name = data.get('tag_name', '')
        assets = data.get('assets', [])
        for asset in assets:
            if asset['name'].endswith('.zip'):
                return tag_name, asset['browser_download_url']
        return tag_name, None
    except Exception:
        return None, None


def is_new_version_available():
    latest_tag, _ = get_latest_release_info()
    if not latest_tag:
        return False
    return _compare_versions(latest_tag, CURRENT_VERSION) > 0


def check_for_updates():
    latest_tag, download_url = get_latest_release_info()
    if not latest_tag:
        return False, None, None
    if _compare_versions(latest_tag, CURRENT_VERSION) > 0:
        return True, latest_tag, download_url
    return False, latest_tag, download_url


def _get_desktop_path():
    return os.path.join(os.path.expanduser("~"), "Desktop")


def check_desktop_permission():
    desktop = _get_desktop_path()
    try:
        test_file = os.path.join(desktop, '.magic_toolbox_test_write')
        with open(test_file, 'w') as f:
            f.write('test')
        os.remove(test_file)
        return True
    except PermissionError:
        return False
    except Exception:
        return False


def open_privacy_settings():
    subprocess.run(['open', 'x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles'])


def start_download(latest_version, download_url):
    if not check_desktop_permission():
        return 'permission_denied'

    temp_dir = tempfile.gettempdir()
    zip_path = os.path.join(temp_dir, f"MagicToolbox-{latest_version}.zip")
    temp_extract = os.path.join(temp_dir, "MagicToolbox.app")
    desktop = _get_desktop_path()
    existing_app = os.path.join(desktop, "MagicToolbox.app")

    script = f'''
        set -e
        rm -rf "{temp_extract}"
        curl -L -o "{zip_path}" "{download_url}"
        unzip -q "{zip_path}" -d "{temp_dir}" -x "__MACOSX/*"
        if [ ! -d "{temp_extract}" ]; then
            echo "ERROR"
            exit 1
        fi
        if [ -d "{existing_app}" ]; then
            dest_app="{desktop}/MagicToolbox-{latest_version}.app"
        else
            dest_app="{existing_app}"
        fi
        rm -rf "$dest_app"
        cp -R "{temp_extract}" "$dest_app"
        rm -rf "{temp_extract}" "{zip_path}"
        echo "$dest_app"
    '''

    try:
        result = subprocess.run(
            ['bash', '-c', script],
            capture_output=True, text=True, timeout=300
        )
        if result.returncode != 0:
            return None, False
        dest_app = result.stdout.strip()
        need_manual_process = os.path.exists(existing_app)
        return dest_app, need_manual_process
    except Exception:
        return None, False
