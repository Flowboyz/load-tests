# device_manager.py — Device Type, Hardware and OS Configuration Manager

import random

# OS versions database for realistic User-Agent strings
OS_VERSIONS = {
    "windows": [
        "Windows NT 5.1; Win32",                     # Windows XP
        "Windows NT 6.1; Win64; x64",                # Windows 7
        "Windows NT 10.0; Win64; x64",               # Windows 10
        "Windows NT 11.0; Win64; x64"                # Windows 11
    ],
    "macos": [
        "Macintosh; Intel Mac OS X 10_10_5",         # Yosemite
        "Macintosh; Intel Mac OS X 10_15_7",         # Catalina
        "Macintosh; Intel Mac OS X 11_12_0",         # Big Sur
        "Macintosh; Intel Mac OS X 12_6_3",         # Monterey
        "Macintosh; Intel Mac OS X 13_5_2",         # Ventura
        "Macintosh; Intel Mac OS X 14_4_1"          # Sonoma
    ],
    "linux": [
        "X11; Ubuntu; Linux x86_64; rv:18.04",       # Ubuntu 18.04
        "X11; Ubuntu; Linux x86_64; rv:20.04",       # Ubuntu 20.04
        "X11; Ubuntu; Linux x86_64; rv:22.04",       # Ubuntu 22.04
        "X11; Ubuntu; Linux x86_64; rv:24.04"        # Ubuntu 24.04
    ],
    "ios": [
        "12_4_1", "13_7", "14_8", "15_7_9", "16_6_1", "17_4_1"
    ],
    "android": [
        "8.0", "9.0", "10", "11", "12", "13", "14"
    ]
}

# Predefined specific device models with hardware specifications
LAPTOP_PROFILES = [
    {"brand": "MacBook", "cpu": "Apple M3 Max", "ram": "36GB", "gpu": "Apple M3 GPU (30-core)", "dpr": 2.0},
    {"brand": "MacBook", "cpu": "Apple M2 Pro", "ram": "16GB", "gpu": "Apple M2 GPU (16-core)", "dpr": 2.0},
    {"brand": "MacBook", "cpu": "Apple M1", "ram": "8GB", "gpu": "Apple M1 GPU (8-core)", "dpr": 2.0},
    {"brand": "Dell XPS", "cpu": "Intel Core i7-13700H", "ram": "16GB", "gpu": "Intel Iris Xe", "dpr": 1.5},
    {"brand": "HP Spectre", "cpu": "Intel Core i7-12700H", "ram": "16GB", "gpu": "Intel Iris Xe", "dpr": 2.0},
    {"brand": "Lenovo ThinkPad", "cpu": "AMD Ryzen 7 PRO 6850U", "ram": "32GB", "gpu": "AMD Radeon 680M", "dpr": 1.25},
    {"brand": "ASUS ZenBook", "cpu": "Intel Core i9-13900H", "ram": "32GB", "gpu": "NVIDIA RTX 4060", "dpr": 1.5},
    {"brand": "Acer Aspire", "cpu": "Intel Core i5-1240P", "ram": "8GB", "gpu": "Intel Iris Xe", "dpr": 1.0},
    {"brand": "Surface Laptop", "cpu": "Intel Core i7-1265U", "ram": "16GB", "gpu": "Intel Iris Xe", "dpr": 2.0}
]

MOBILE_PROFILES = {
    "ios": [
        {"model": "iPhone 6", "os_version": "12.4.1", "screen": "375x667", "viewport": "375x553", "dpr": 2.0, "cpu": "Apple A8", "ram": "1GB", "gpu": "PowerVR GX6450"},
        {"model": "iPhone 7", "os_version": "13.7", "screen": "375x667", "viewport": "375x553", "dpr": 2.0, "cpu": "Apple A10 Fusion", "ram": "2GB", "gpu": "PowerVR GT7600 Plus"},
        {"model": "iPhone X", "os_version": "14.8", "screen": "375x812", "viewport": "375x635", "dpr": 3.0, "cpu": "Apple A11 Bionic", "ram": "3GB", "gpu": "Apple GPU (3-core)"},
        {"model": "iPhone 12", "os_version": "15.7.9", "screen": "390x844", "viewport": "390x664", "dpr": 3.0, "cpu": "Apple A14 Bionic", "ram": "4GB", "gpu": "Apple GPU (4-core)"},
        {"model": "iPhone 13 Pro", "os_version": "16.6.1", "screen": "390x844", "viewport": "390x664", "dpr": 3.0, "cpu": "Apple A15 Bionic", "ram": "6GB", "gpu": "Apple GPU (5-core)"},
        {"model": "iPhone 14 Pro Max", "os_version": "16.6.1", "screen": "430x932", "viewport": "430x752", "dpr": 3.0, "cpu": "Apple A16 Bionic", "ram": "6GB", "gpu": "Apple GPU (5-core)"},
        {"model": "iPhone 15 Pro", "os_version": "17.4.1", "screen": "393x852", "viewport": "393x672", "dpr": 3.0, "cpu": "Apple A17 Pro", "ram": "8GB", "gpu": "Apple GPU (6-core)"}
    ],
    "android": [
        {"brand": "Samsung", "model": "SM-G920F (Galaxy S6)", "os_version": "8.0", "screen": "360x640", "viewport": "360x520", "dpr": 3.0, "cpu": "Exynos 7420", "ram": "3GB", "gpu": "Mali-T760 MP8"},
        {"brand": "Samsung", "model": "SM-G960F (Galaxy S9)", "os_version": "10", "screen": "360x740", "viewport": "360x620", "dpr": 3.0, "cpu": "Exynos 9810", "ram": "4GB", "gpu": "Mali-G72 MP18"},
        {"brand": "Samsung", "model": "SM-G991B (Galaxy S21)", "os_version": "12", "screen": "360x800", "viewport": "360x680", "dpr": 3.0, "cpu": "Exynos 2100", "ram": "8GB", "gpu": "Mali-G78 MP14"},
        {"brand": "Samsung", "model": "SM-S911B (Galaxy S23)", "os_version": "13", "screen": "390x844", "viewport": "390x724", "dpr": 3.0, "cpu": "Snapdragon 8 Gen 2", "ram": "8GB", "gpu": "Adreno 740"},
        {"brand": "Samsung", "model": "SM-S928B (Galaxy S24 Ultra)", "os_version": "14", "screen": "385x854", "viewport": "385x734", "dpr": 3.0, "cpu": "Snapdragon 8 Gen 3", "ram": "12GB", "gpu": "Adreno 750"},
        {"brand": "Google", "model": "Pixel 3", "os_version": "11", "screen": "412x846", "viewport": "412x726", "dpr": 3.0, "cpu": "Snapdragon 845", "ram": "4GB", "gpu": "Adreno 630"},
        {"brand": "Google", "model": "Pixel 6 Pro", "os_version": "12", "screen": "412x892", "viewport": "412x772", "dpr": 3.5, "cpu": "Google Tensor", "ram": "12GB", "gpu": "Mali-G78 MP20"},
        {"brand": "Google", "model": "Pixel 8 Pro", "os_version": "14", "screen": "412x892", "viewport": "412x772", "dpr": 3.5, "cpu": "Google Tensor G3", "ram": "12GB", "gpu": "Immortalis-G715s MC10"},
        {"brand": "Xiaomi", "model": "M2101K6G (Redmi Note 10 Pro)", "os_version": "12", "screen": "393x873", "viewport": "393x753", "dpr": 2.75, "cpu": "Snapdragon 732G", "ram": "6GB", "gpu": "Adreno 618"},
        {"brand": "OnePlus", "model": "KB2003 (OnePlus 8T)", "os_version": "11", "screen": "412x915", "viewport": "412x795", "dpr": 3.0, "cpu": "Snapdragon 865", "ram": "12GB", "gpu": "Adreno 650"},
        {"brand": "OnePlus", "model": "CPH2581 (OnePlus 12)", "os_version": "14", "screen": "450x960", "viewport": "450x840", "dpr": 3.0, "cpu": "Snapdragon 8 Gen 3", "ram": "16GB", "gpu": "Adreno 750"},
        {"brand": "Huawei", "model": "VOG-L29 (P30 Pro)", "os_version": "10", "screen": "360x780", "viewport": "360x660", "dpr": 3.0, "cpu": "Kirin 980", "ram": "8GB", "gpu": "Mali-G76 MP10"},
        {"brand": "Motorola", "model": "Moto G Play", "os_version": "11", "screen": "360x800", "viewport": "360x680", "dpr": 2.0, "cpu": "Snapdragon 460", "ram": "3GB", "gpu": "Adreno 610"},
        {"brand": "Nokia", "model": "Nokia 5.4", "os_version": "11", "screen": "360x800", "viewport": "360x680", "dpr": 2.0, "cpu": "Snapdragon 662", "ram": "4GB", "gpu": "Adreno 610"},
        {"brand": "Sony", "model": "Xperia 1 V", "os_version": "13", "screen": "384x864", "viewport": "384x744", "dpr": 3.75, "cpu": "Snapdragon 8 Gen 2", "ram": "12GB", "gpu": "Adreno 740"}
    ]
}

TABLET_PROFILES = {
    "ios": [
        {"model": "iPad Mini 6", "os_version": "15.7", "screen": "744x1133", "viewport": "744x980", "dpr": 2.0, "cpu": "Apple A15 Bionic", "ram": "4GB", "gpu": "Apple GPU (5-core)"},
        {"model": "iPad Air 5", "os_version": "16.6", "screen": "820x1180", "viewport": "820x1000", "dpr": 2.0, "cpu": "Apple M1", "ram": "8GB", "gpu": "Apple M1 GPU"},
        {"model": "iPad Pro 12.9 (M2)", "os_version": "17.4", "screen": "1024x1366", "viewport": "1024x1186", "dpr": 2.0, "cpu": "Apple M2", "ram": "16GB", "gpu": "Apple M2 GPU"}
    ],
    "android": [
        {"brand": "Samsung", "model": "SM-X700 (Galaxy Tab S8)", "os_version": "12", "screen": "800x1280", "viewport": "800x1100", "dpr": 2.0, "cpu": "Snapdragon 8 Gen 1", "ram": "8GB", "gpu": "Adreno 730"},
        {"brand": "Lenovo", "model": "TB-125FU (Tab M10)", "os_version": "11", "screen": "800x1280", "viewport": "800x1100", "dpr": 1.5, "cpu": "MediaTek Helio G80", "ram": "4GB", "gpu": "Mali-G52 MC2"},
        {"brand": "Google", "model": "Pixel Tablet", "os_version": "13", "screen": "800x1280", "viewport": "800x1100", "dpr": 2.0, "cpu": "Google Tensor G2", "ram": "8GB", "gpu": "Mali-G710 MP7"}
    ]
}

# Resolutions for raw desktop fallback configurations
DESKTOP_RESOLUTIONS = [
    {"screen": "1920x1080", "viewport": "1920x940"},
    {"screen": "1536x864", "viewport": "1536x730"},
    {"screen": "1440x900", "viewport": "1440x790"},
    {"screen": "2560x1440", "viewport": "2560x1300"}
]

def extract_name_version(key):
    # Normalize key
    key_norm = key.strip().lower()
    
    # List of known browsers
    browsers = ["firefox_esr", "duckduckgo_mobile", "uc_browser_mobile", "chrome_mobile", "safari_mobile", "firefox_mobile", "opera_mobile", "edge_mobile", "samsung_internet", "samsung", "yandex_browser", "vivaldi", "chrome", "edge", "firefox", "safari", "brave", "opera", "chromium"]
    for b in browsers:
        if key_norm.startswith(b + "_") or key_norm == b:
            version = key[len(b)+1:] if len(key) > len(b) else None
            mapped_b = "samsung" if b == "samsung_internet" else b
            if mapped_b == "chromium": mapped_b = "chrome"
            return mapped_b, version
            
    # List of OS families
    os_prefixes = ["windows_server", "windows_11", "windows_10", "windows_8", "windows_7", "windows", "macos", "ios", "ipados", "android_go", "android_tv", "google_tv", "android_webview_os", "android", "harmonyos", "fireos", "kaios", "tizen_os", "webos", "tvos", "roku_os", "fire_tv_os", "watchos", "wearos", "visionos", "android_xr", "freebsd", "openbsd", "netbsd", "dragonfly_bsd", "solaris_illumos", "aix", "hp_ux", "qnx", "vxworks", "freertos", "zephyr", "threadx", "yocto_linux", "openwrt", "embedded_linux", "ios_webview_os", "pwa_runtime", "headless_os", "virtual_os", "unknown_other"]
    linux_prefixes = ["linux_ubuntu_server", "linux_ubuntu", "linux_debian_server", "linux_debian", "linux_rhel_server", "linux_rhel", "linux_rocky_server", "linux_rocky", "linux_almalinux_server", "linux_almalinux", "linux_centos_stream", "linux_centos", "linux_arch", "linux_manjaro", "linux_opensuse", "linux_suse_enterprise", "linux_mint", "linux_pop_os", "linux_elementary", "linux_zorin", "linux_kali", "linux_parrot", "linux_deepin", "linux_oracle", "linux_amazon", "linux_alpine", "linux_gentoo", "linux_nixos"]
    
    for prefix in os_prefixes + linux_prefixes:
        if key_norm.startswith(prefix + "_") or key_norm == prefix:
            version = key[len(prefix)+1:] if len(key) > len(prefix) else None
            family = "windows"
            if "macos" in prefix: family = "macos"
            elif any(k in prefix for k in ["linux", "ubuntu", "debian", "fedora", "centos", "arch", "mint", "alpine", "suse", "rhel", "rocky", "gentoo", "nixos"]): family = "linux"
            elif any(k in prefix for k in ["ios", "ipados", "watchos", "visionos"]): family = "ios"
            elif any(k in prefix for k in ["android", "harmony", "fire", "wear"]): family = "android"
            elif any(k in prefix for k in ["freebsd", "openbsd", "netbsd", "bsd"]): family = "linux"
            return family, version
            
    return key, None

def is_os_compatible_with_device(os_key, device_key):
    os_k = os_key.lower()
    dev_k = device_key.lower()
    
    if dev_k in ("iphone", "ios_webview", "ipad", "ipad_pro", "ipad_air", "ipad_standard", "ipad_mini", "ipad_legacy"):
        return "ios" in os_k or "ipados" in os_k or "watchos" in os_k or "visionos" in os_k
    if dev_k in ("android_phone", "android_tablet", "android_foldable", "phablet", "android_webview"):
        return "android" in os_k or "harmony" in os_k or "fire" in os_k or "kaios" in os_k
    if dev_k == "chromebook":
        return "chromeos" in os_k
    if dev_k in ("smart_tv", "conference_room_device", "kiosk"):
        return any(tv in os_k for tv in ["android_tv", "google_tv", "tizen", "webos", "tvos", "roku", "fire_tv", "openwrt", "embedded_linux"])
    if dev_k == "virtual_desktop":
        return "virtual_os" in os_k or "windows" in os_k or "linux" in os_k
    if dev_k == "headless_browser":
        return "headless" in os_k or "linux" in os_k
        
    return "windows" in os_k or "macos" in os_k or "linux" in os_k or "freebsd" in os_k or "openbsd" in os_k or "netbsd" in os_k or "solaris" in os_k or "aix" in os_k or "hp_ux" in os_k or "yocto" in os_k or "pwa_runtime_desktop" in os_k or "unknown" in os_k

def is_browser_compatible_with_os(browser_key, os_key, device_key):
    b_k = browser_key.lower()
    o_k = os_key.lower()
    dev_k = device_key.lower()
    
    if dev_k == "android_webview" or "android_webview" in b_k:
        return "android_webview" in b_k or "chrome_mobile" in b_k
    if dev_k == "ios_webview" or "ios_webview" in b_k:
        return "ios_webview" in b_k or "safari_mobile" in b_k
        
    if "ios" in o_k or "ipados" in o_k:
        return "safari_mobile" in b_k or "chrome_mobile" in b_k or "firefox_mobile" in b_k or "duckduckgo_mobile" in b_k or "uc_browser" in b_k or "ios_webview" in b_k
    if "android" in o_k or "harmony" in o_k or "fire" in o_k:
        return "chrome_mobile" in b_k or "samsung" in b_k or "firefox_mobile" in b_k or "opera_mobile" in b_k or "uc_browser" in b_k or "android_webview" in b_k
    if "chromeos" in o_k:
        return "chrome" in b_k or "chromium" in b_k
    if "headless" in o_k:
        return "chrome" in b_k or "firefox" in b_k or "chromium" in b_k
        
    is_desktop_os = "windows" in o_k or "macos" in o_k or "linux" in o_k or "freebsd" in o_k or "openbsd" in o_k or "netbsd" in o_k or "solaris" in o_k
    if is_desktop_os:
        if "macos" in o_k:
            return "safari" in b_k or "chrome" in b_k or "firefox" in b_k or "edge" in b_k or "brave" in b_k or "opera" in b_k or "vivaldi" in b_k or "yandex" in b_k or "chromium" in b_k
        else:
            return ("chrome" in b_k or "firefox" in b_k or "edge" in b_k or "brave" in b_k or "opera" in b_k or "vivaldi" in b_k or "yandex" in b_k or "chromium" in b_k) and "safari" not in b_k
            
    return True

class DeviceManager:
    def __init__(self, device_dist=None, browser_dist=None, os_dist=None):
        self.device_dist = self._parse_distribution(device_dist, {"desktop": 70, "mobile": 20, "tablet": 10})
        self.browser_dist = self._parse_distribution(browser_dist, {
            "chrome": 25, "safari": 15, "firefox": 15, "edge": 10, "brave": 8, "opera": 5,
            "chrome_mobile": 10, "safari_mobile": 7, "samsung": 5, "firefox_mobile": 3, "opera_mobile": 2
        })
        self.os_dist = self._parse_distribution(os_dist, {"windows": 35, "macos": 25, "linux": 10, "ios": 15, "android": 15})

    def _parse_distribution(self, dist_str, default_dict):
        if not dist_str:
            return default_dict
        try:
            parsed = {}
            for item in dist_str.split(","):
                key, val = item.split(":")
                parsed[key.strip().lower()] = float(val.strip())
            return parsed
        except Exception:
            return default_dict

    def sample_profile(self):
        """
        Samples a valid combination of Device Type, Operating System, and Browser.
        Injects expanded hardware (CPU, RAM, GPU) classes and WebRTC capabilities.
        """
        # 1. Sample Device Type
        device_choices = list(self.device_dist.keys())
        device_weights = list(self.device_dist.values())
        sampled_device = random.choices(device_choices, weights=device_weights)[0]
        
        # Maps device keys to broad device types (desktop, mobile, tablet)
        device_type = "desktop"
        if sampled_device in ("android_phone", "iphone", "phablet", "android_webview", "ios_webview", "mobile"):
            device_type = "mobile"
        elif sampled_device in ("android_tablet", "ipad", "android_foldable", "ipad_pro", "ipad_air", "ipad_standard", "ipad_mini", "tablet"):
            device_type = "tablet"

        # 2. Filter OS options based on sampled device
        valid_os_choices = []
        valid_os_weights = []
        for os_k, weight in self.os_dist.items():
            if is_os_compatible_with_device(os_k, sampled_device):
                valid_os_choices.append(os_k)
                valid_os_weights.append(weight)
                
        if not valid_os_choices or sum(valid_os_weights) == 0:
            # Fallbacks
            if device_type == "desktop":
                valid_os_choices = ["windows_11_24h2"]
                valid_os_weights = [1.0]
            elif sampled_device in ("iphone", "ipad"):
                valid_os_choices = ["ios_18"]
                valid_os_weights = [1.0]
            else:
                valid_os_choices = ["android_15"]
                valid_os_weights = [1.0]
                
        sampled_os_key = random.choices(valid_os_choices, weights=valid_os_weights)[0]
        os_type, os_version = extract_name_version(sampled_os_key)
        
        # 3. Filter Browser options based on OS & Device
        valid_browser_choices = []
        valid_browser_weights = []
        for b_k, weight in self.browser_dist.items():
            if is_browser_compatible_with_os(b_k, sampled_os_key, sampled_device):
                valid_browser_choices.append(b_k)
                valid_browser_weights.append(weight)
                
        if not valid_browser_choices or sum(valid_browser_weights) == 0:
            # Fallbacks
            if device_type == "desktop":
                valid_browser_choices = ["chrome_149"]
                valid_browser_weights = [1.0]
            else:
                valid_browser_choices = ["chrome_mobile_149"]
                valid_browser_weights = [1.0]
                
        sampled_browser_key = random.choices(valid_browser_choices, weights=valid_browser_weights)[0]
        browser_type, browser_version = extract_name_version(sampled_browser_key)

        # 4. Construct specific hardware parameters & screen resolutions
        device_model = ""
        cpu_class = "Standard CPU"
        ram_class = "8GB"
        gpu_class = "Standard Graphics"
        dpr = 1.0
        screen_res = "1920x1080"
        viewport = "1920x940"
        
        # Determine actual OS version/format string
        sampled_os_ver = os_version or "10.0"
        
        if device_type == "desktop":
            laptop = random.choice(LAPTOP_PROFILES)
            if os_type == "macos":
                laptop = next((p for p in LAPTOP_PROFILES if p["brand"] == "MacBook"), laptop)
            else:
                laptop = next((p for p in LAPTOP_PROFILES if p["brand"] != "MacBook"), laptop)
                
            device_model = f"{laptop['brand']} Laptop"
            cpu_class = laptop["cpu"]
            ram_class = laptop["ram"]
            gpu_class = laptop["gpu"]
            dpr = laptop["dpr"]
            
            res_info = random.choice(DESKTOP_RESOLUTIONS)
            screen_res = res_info["screen"]
            viewport = res_info["viewport"]
            
        elif device_type == "mobile":
            # Map mobile profiles
            profiles = MOBILE_PROFILES.get(os_type, MOBILE_PROFILES["android"])
            mobile = random.choice(profiles)
            device_model = mobile["model"]
            cpu_class = mobile["cpu"]
            ram_class = mobile["ram"]
            gpu_class = mobile["gpu"]
            dpr = mobile["dpr"]
            screen_res = mobile["screen"]
            viewport = mobile["viewport"]
            
        elif device_type == "tablet":
            profiles = TABLET_PROFILES.get(os_type, TABLET_PROFILES["android"])
            tablet = random.choice(profiles)
            device_model = tablet["model"]
            cpu_class = tablet["cpu"]
            ram_class = tablet["ram"]
            gpu_class = tablet["gpu"]
            dpr = tablet["dpr"]
            screen_res = tablet["screen"]
            viewport = tablet["viewport"]

        # Parse OS Details for User-Agent template
        os_details = sampled_os_key.replace("_", " ")
        if os_type == "windows":
            # Format realistic NT version
            nt_ver = "10.0"
            if "windows_8_1" in sampled_os_key: nt_ver = "6.3"
            elif "windows_8" in sampled_os_key: nt_ver = "6.2"
            elif "windows_7" in sampled_os_key: nt_ver = "6.1"
            os_details = f"Windows NT {nt_ver}; Win64; x64"
            
        elif os_type == "macos":
            # Macintosh; Intel Mac OS X 10_15_7
            ver_clean = sampled_os_ver.replace(".", "_")
            os_details = f"Macintosh; Intel Mac OS X {ver_clean}"
            
        elif os_type == "linux":
            os_details = f"X11; Linux x86_64"

        return {
            "device_type": device_type,
            "os_type": os_type,
            "os_version": sampled_os_ver,
            "os_details": os_details,
            "device_model": device_model,
            "browser_type": browser_type,
            "browser_version_spec": browser_version,
            "screen_resolution": screen_res,
            "viewport": viewport,
            "device_pixel_ratio": dpr,
            "hardware_profile": {
                "cpu_class": cpu_class,
                "ram_class": ram_class,
                "gpu_class": gpu_class
            }
        }
