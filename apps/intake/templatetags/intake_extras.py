from django import template

register = template.Library()


@register.filter(name="get_item")
def get_item(dictionary, key):
    """
    Safe dict lookup for Django templates.
    Usage: {{ my_dict|get_item:variable_key }}
    Returns empty string for missing keys, not KeyError.
    """
    if not isinstance(dictionary, dict):
        return ""
    return dictionary.get(key, "")


@register.filter(name="value_in")
def value_in(value, dictionary):
    """
    Check if a value exists inside a dict value (for multiselect prefill).
    Usage: {% if opt.value|value_in:prefill_data[field_key] %}
    Returns True if value is in the provided list/set.
    """
    if not dictionary:
        return False
    if isinstance(dictionary, (list, tuple, set)):
        return value in dictionary
    return value == dictionary
