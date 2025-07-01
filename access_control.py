# access_control.py

# Словарь ролей и их прав
ROLE_PERMISSIONS = {
    "admin": {
        "menu": ["orders", "reports", "settings"],
        "reports": ["sales", "clients", "inventory"]
    },
    "manager": {
        "menu": ["orders", "reports"],
        "reports": ["sales", "clients"]
    },
    "viewer": {
        "menu": ["reports"],
        "reports": ["sales"]
    }
}

def get_permissions(role):
    return ROLE_PERMISSIONS.get(role, {"menu": [], "reports": []})

def has_access(role, section, item=None):
    permissions = get_permissions(role)
    if item:
        return item in permissions.get(section, [])
    return section in permissions