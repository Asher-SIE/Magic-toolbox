import datetime
import json
import os
import subprocess
import zipfile


ACTIVATION_DATE = datetime.date(2026, 4, 3)
EXPIRY_DAYS = 180
EXPIRY_WARNING_DAYS = 30

CURRENT_VERSION = "1.1.0"
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


def _remove_extended_attributes(path):
    if path.endswith('.app') and os.path.isdir(path):
        subprocess.run(['xattr', '-cr', path], check=False)
    elif os.path.isdir(path):
        for root, dirs, files in os.walk(path):
            for name in files:
                filepath = os.path.join(root, name)
                subprocess.run(['xattr', '-c', filepath], check=False)
            for name in dirs:
                dirpath = os.path.join(root, name)
                subprocess.run(['xattr', '-c', dirpath], check=False)
    else:
        subprocess.run(['xattr', '-c', path], check=False)


def _download_file(url, dest_path):
    try:
        subprocess.run(
            ['curl', '-L', '-o', dest_path, url],
            check=True, timeout=300
        )
        return True
    except Exception:
        return False


def _unzip_and_remove_extattr(zip_path):
    extract_dir = _get_desktop_path()
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(extract_dir)
        extracted_name = zip_ref.namelist()[0].split('/')[0]
    extracted_path = os.path.join(extract_dir, extracted_name)
    _remove_extended_attributes(extracted_path)
    return extracted_path


def start_download(latest_version, download_url):
    desktop = _get_desktop_path()
    filename = f"MagicToolbox-{latest_version}.zip"
    zip_path = os.path.join(desktop, filename)

    if not _download_file(download_url, zip_path):
        return None, False

    try:
        app_path = _unzip_and_remove_extattr(zip_path)
    except Exception:
        if os.path.exists(zip_path):
            os.remove(zip_path)
        return None, False

    if os.path.exists(zip_path):
        os.remove(zip_path)

    # 检查桌面是否已有同名 app，如有则重命名新版
    existing_app = os.path.join(desktop, "MagicToolbox.app")
    if os.path.exists(existing_app):
        rename_path = os.path.join(desktop, f"MagicToolbox-{latest_version}.app")
        os.rename(app_path, rename_path)
        app_path = rename_path
        need_manual_process = True
    else:
        need_manual_process = False

    return app_path, need_manual_process
