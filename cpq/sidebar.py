STANDARD_SIDENAV_ITEMS = [
    {
        "key": "products",
        "label": "Products",
        "view": "products",
        "icon": None,
        "css_class": "nav-link--no-icon",
    },
    {
        "key": "accounts",
        "label": "Accounts",
        "view": "accounts",
        "icon": "account_circle",
        "css_class": "",
    },
    {
        "key": "leads",
        "label": "Leads",
        "view": "agents",
        "icon": None,
        "css_class": "nav-link--no-icon",
        "auto_prompt": "show leads",
    },
    {
        "key": "opportunities",
        "label": "Opportunities",
        "view": "agents",
        "icon": None,
        "css_class": "nav-link--no-icon",
        "auto_prompt": "show opportunities",
    },
    {
        "key": "contacts",
        "label": "Contacts",
        "view": "agents",
        "icon": None,
        "css_class": "nav-link--no-icon",
        "auto_prompt": "show contacts",
    },
    {
        "key": "activities",
        "label": "Activities",
        "view": "agents",
        "icon": None,
        "css_class": "nav-link--no-icon",
        "auto_prompt": "show activities",
    },
]

SIDEBAR_STANDARD_COOKIE = "sidebar_standard_objects"


def default_standard_sidebar_keys():
    return [item["key"] for item in STANDARD_SIDENAV_ITEMS]


def parse_standard_sidebar_cookie(value: str):
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]
