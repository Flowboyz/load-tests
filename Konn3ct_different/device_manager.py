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
        device_type = random.choices(device_choices, weights=device_weights)[0]

        # 2. Filter OS options based on Device Type
        valid_os = []
        if device_type == "desktop":
            valid_os = ["windows", "macos", "linux"]
        else: # mobile or tablet
            valid_os = ["ios", "android"]

        filtered_os_weights = [self.os_dist.get(o, 0) for o in valid_os]
        if sum(filtered_os_weights) == 0:
            filtered_os_weights = [1.0] * len(valid_os)
        os_type = random.choices(valid_os, weights=filtered_os_weights)[0]

        # 3. Filter Browser options based on Device Type & OS
        valid_browsers = []
        if device_type == "desktop":
            if os_type == "macos":
                valid_browsers = ["safari", "chrome", "firefox", "edge", "brave", "opera"]
            else:
                valid_browsers = ["chrome", "firefox", "edge", "brave", "opera"]
        else: # mobile or tablet
            if os_type == "ios":
                valid_browsers = ["safari_mobile", "chrome_mobile", "firefox_mobile"]
            else: # android
                valid_browsers = ["chrome_mobile", "samsung", "firefox_mobile", "opera_mobile"]

        filtered_browser_weights = [self.browser_dist.get(b, 0) for b in valid_browsers]
        if sum(filtered_browser_weights) == 0:
            filtered_browser_weights = [1.0] * len(valid_browsers)
        browser_type = random.choices(valid_browsers, weights=filtered_browser_weights)[0]

        # 4. Construct specific hardware parameters & screen resolutions
        device_model = ""
        cpu_class = "Standard CPU"
        ram_class = "8GB"
        gpu_class = "Standard Graphics"
        dpr = 1.0
        screen_res = "1920x1080"
        viewport = "1920x940"
        sampled_os_ver = ""
        
        if device_type == "desktop":
            # Laptop profiles
            laptop = random.choice(LAPTOP_PROFILES)
            # Filter brand matching OS type (e.g. MacBook only on macos)
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
            sampled_os_ver = random.choice(OS_VERSIONS[os_type])
            
        elif device_type == "mobile":
            mobile = random.choice(MOBILE_PROFILES[os_type])
            device_model = mobile["model"]
            cpu_class = mobile["cpu"]
            ram_class = mobile["ram"]
            gpu_class = mobile["gpu"]
            dpr = mobile["dpr"]
            screen_res = mobile["screen"]
            viewport = mobile["viewport"]
            sampled_os_ver = mobile["os_version"]
            
        elif device_type == "tablet":
            tablet = random.choice(TABLET_PROFILES[os_type])
            device_model = tablet["model"]
            cpu_class = tablet["cpu"]
            ram_class = tablet["ram"]
            gpu_class = tablet["gpu"]
            dpr = tablet["dpr"]
            screen_res = tablet["screen"]
            viewport = tablet["viewport"]
            sampled_os_ver = tablet["os_version"]

        # Parse OS Details for User-Agent template substitution
        os_details = sampled_os_ver
        if os_type == "windows" and ";" not in os_details:
            os_details = f"{os_details}; Win64; x64"
            
        return {
            "device_type": device_type,
            "os_type": os_type,
            "os_version": sampled_os_ver,
            "os_details": os_details,
            "device_model": device_model,
            "browser_type": browser_type,
            "screen_resolution": screen_res,
            "viewport": viewport,
            "device_pixel_ratio": dpr,
            "hardware_profile": {
                "cpu_class": cpu_class,
                "ram_class": ram_class,
                "gpu_class": gpu_class
            }
        }
