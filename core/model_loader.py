import os
import urllib.request
import sys

# Ensure root directory is in sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from config import YUNET_MODEL_PATH, SFACE_MODEL_PATH, YUNET_URL, SFACE_URL

def download_file(url: str, dest_path: str, description: str = "model", progress_callback=None):
    if os.path.exists(dest_path) and os.path.getsize(dest_path) > 10000:
        return True

    print(f"Downloading {description}...")
    temp_path = dest_path + ".download"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=30) as response, open(temp_path, 'wb') as out_file:
            total_size = response.headers.get('Content-Length')
            total_size = int(total_size) if total_size else None
            downloaded = 0
            block_size = 1024 * 64

            while True:
                buffer = response.read(block_size)
                if not buffer:
                    break
                downloaded += len(buffer)
                out_file.write(buffer)
                if total_size and progress_callback:
                    progress_callback(downloaded / total_size)
                elif total_size:
                    pct = (downloaded / total_size) * 100
                    sys.stdout.write(f"\rDownloading {description}: {pct:.1f}% ({downloaded // 1024} KB)")
                    sys.stdout.flush()

        os.replace(temp_path, dest_path)
        print(f"\nSuccessfully downloaded {description} to {dest_path}")
        return True
    except Exception as e:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        print(f"\nError downloading {description} from {url}: {e}")
        return False

def ensure_models_exist(progress_callback=None) -> bool:
    os.makedirs(os.path.dirname(YUNET_MODEL_PATH), exist_ok=True)
    
    # Download YuNet face detector (~335 KB)
    ok_yunet = download_file(YUNET_URL, YUNET_MODEL_PATH, "YuNet Face Detector", progress_callback)
    if not ok_yunet:
        return False

    # Download SFace face recognizer (~38 MB)
    ok_sface = download_file(SFACE_URL, SFACE_MODEL_PATH, "SFace Face Recognizer", progress_callback)
    if not ok_sface:
        return False

    return True

if __name__ == "__main__":
    ensure_models_exist()
