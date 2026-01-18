from django.core.cache import cache


def _custom_record_list_version_key(user_id, object_name):
    return f"custom_record_list_version:{user_id}:{object_name}"


def get_custom_record_list_version(user_id, object_name):
    key = _custom_record_list_version_key(user_id, object_name)
    try:
        return int(cache.get(key, 1))
    except (TypeError, ValueError):
        cache.set(key, 1, None)
        return 1


def bump_custom_record_list_version(user_id, object_name):
    key = _custom_record_list_version_key(user_id, object_name)
    try:
        cache.incr(key)
    except ValueError:
        cache.set(key, 2, None)
