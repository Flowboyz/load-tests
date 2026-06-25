# device_manager.py — Device Type and OS Configuration Manager

import random

# OS versions database for realistic User-Agent strings
OS_VERSIONS = {
    "windows": ["10.0; Win64; x64", "11.0; Win64; x64"],
    "macos": ["Intel Mac OS X 10_15_7", "Intel Mac OS X 11_12_0", "Macintosh; Intel Mac OS X 12_4_0", "Macintosh; Intel Mac OS X 14_2_1"],
    "linux": ["X11; Linux x86_64", "X11; Ubuntu; Linux x86_64"],
    "ios": ["16_4", "17_0_2", "17_2_1", "17_4_1"],
    "android": ["11", "12", "13", "14"]
}

# Android device models for realistic Chrome Mobile/Samsung/Opera Mobile user agents
ANDROID_DEVICES = [
    "SM-G991B",   # Samsung Galaxy S21
    "SM-S911B",   # Samsung Galaxy S23
    "Pixel 6",    # Google Pixel 6
    "Pixel 7",    # Google Pixel 7
    "Pixel 8 Pro",# Google Pixel 8 Pro
    "M2101K6G",   # Xiaomi Redmi Note 10 Pro
    "KB2003"      # OnePlus 8T
]

# Tablet models
TABLET_DEVICES = {
    "android": [
        "SM-X700",   # Samsung Galaxy Tab S8
        "SM-T870",   # Samsung Galaxy Tab S7
        "Lenovo TB-125FU" # Lenovo Tab M10
    ],
    "ios": [
        "iPad",
        "iPad Pro",
        "iPad Air"
    ]
}

# Default resolutions (Width x Height) and Viewports
RESOLUTIONS = {
    "desktop": [
        {"screen": "1920x1080", "viewport": "1920x940"},
        {"screen": "1536x864", "viewport": "1536x730"},
        {"screen": "1440x900", "viewport": "1440x790"},
        {"screen": "1366x768", "viewport": "1366x660"},
        {"screen": "2560x1440", "viewport": "2560x1300"}
    ],
    "mobile": [
        {"screen": "390x844", "viewport": "390x664"},    # iPhone 12/13/14 Pro
        {"screen": "412x915", "viewport": "412x735"},    # Samsung Galaxy S20+ / S21
        {"screen": "360x800", "viewport": "360x620"},    # Older Android
        {"screen": "430x932", "viewport": "430x752"},    # iPhone 14/15 Pro Max
        {"screen": "375x812", "viewport": "375x635"}     # iPhone X/XS/11 Pro
    ],
    "tablet": [
        {"screen": "820x1180", "viewport": "820x1000"},   # iPad Air 4
        {"screen": "768x1024", "viewport": "768x844"},    # iPad
        {"screen": "800x1280", "viewport": "800x1100"},   # Samsung Tab A
        {"screen": "1024x1366", "viewport": "1024x1186"}  # iPad Pro 12.9
    ]
}

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
        Avoids impossible combinations (e.g. Mobile device running Windows OS, or Desktop running iOS).
        """
        # 1. Sample Device Type
        device_choices = list(self.device_dist.keys())
        device_weights = list(self.device_dist.values())
        device_type = random.choices(device_choices, weights=device_weights)[0]

        # 2. Filter OS options based on Device Type
        os_options = list(self.os_dist.keys())
        os_weights = [self.os_dist[k] for k in os_options]

        if device_type == "desktop":
            # Filter for desktop OS
            valid_os = ["windows", "macos", "linux"]
        elif device_type in ("mobile", "tablet"):
            valid_os = ["ios", "android"]
        else:
            valid_os = ["windows"]

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

        # 4. Select random OS version and details
        raw_os_ver = random.choice(OS_VERSIONS.get(os_type, ["1.0"]))
        os_details = raw_os_ver
        os_version = raw_os_ver.split(";")[0] if ";" in raw_os_ver else raw_os_ver

        device_model = ""
        if os_type == "android":
            if device_type == "tablet":
                device_model = random.choice(TABLET_DEVICES["android"])
            else:
                device_model = random.choice(ANDROID_DEVICES)
        elif os_type == "ios":
            if device_type == "tablet":
                device_model = random.choice(TABLET_DEVICES["ios"])
            else:
                device_model = "iPhone"

        # 5. Select Screen Resolution & Viewport
        res_info = random.choice(RESOLUTIONS.get(device_type, RESOLUTIONS["desktop"]))

        return {
            "device_type": device_type,
            "os_type": os_type,
            "os_version": os_version,
            "os_details": os_details,
            "device_model": device_model,
            "browser_type": browser_type,
            "screen_resolution": res_info["screen"],
            "viewport": res_info["viewport"]
        }
