from urllib.parse import urlparse


PLATFORMS = {
    "douyin": {
        "label": "抖音",
        "domains": ("douyin.com",),
        "profile": True,
        "comments": True,
        "anonymous": False,
        "support": "specialized",
    },
    "tiktok": {
        "label": "TikTok",
        "domains": ("tiktok.com",),
        "profile": True,
        "comments": False,
        "anonymous": True,
        "support": "standard",
    },
    "xiaohongshu": {
        "label": "小红书",
        "domains": ("xiaohongshu.com", "xhslink.com", "rednote.com"),
        "profile": False,
        "comments": False,
        "anonymous": True,
        "support": "limited",
    },
    "weibo": {
        "label": "微博",
        "domains": ("weibo.com", "weibo.cn", "weibocdn.com"),
        "profile": False,
        "comments": False,
        "anonymous": True,
        "support": "standard",
    },
    "kuaishou": {
        "label": "快手",
        "domains": ("kuaishou.com", "gifshow.com"),
        "profile": False,
        "comments": False,
        "anonymous": True,
        "support": "experimental",
    },
    "youtube": {
        "label": "YouTube",
        "domains": ("youtube.com", "youtu.be"),
        "profile": True,
        "comments": False,
        "anonymous": True,
        "support": "standard",
    },
    "bilibili": {
        "label": "哔哩哔哩",
        "domains": ("bilibili.com", "b23.tv"),
        "profile": True,
        "comments": False,
        "anonymous": True,
        "support": "standard",
    },
    "twitter": {
        "label": "X / Twitter",
        "domains": ("twitter.com", "x.com"),
        "profile": False,
        "comments": False,
        "anonymous": True,
        "support": "standard",
    },
    "instagram": {
        "label": "Instagram",
        "domains": ("instagram.com",),
        "profile": True,
        "comments": False,
        "anonymous": True,
        "support": "standard",
    },
}


def detect_platform(url):
    hostname = (urlparse(url).hostname or "").lower().removeprefix("www.")
    for platform_id, details in PLATFORMS.items():
        if any(hostname == domain or hostname.endswith(f".{domain}") for domain in details["domains"]):
            return platform_id
    return "generic"


def platform_details(platform_id):
    return PLATFORMS.get(
        platform_id,
        {
            "label": "其他平台",
            "profile": False,
            "comments": False,
            "anonymous": True,
            "support": "experimental",
        },
    )
