"""
Dashboard Widget Registry

This registry maps widget keys stored in the database
to their corresponding widget classes.
"""

WIDGET_REGISTRY = {}


def register_widget(widget_class):
    """
    Register a widget class in the global registry.
    """
    if not widget_class.key:
        raise ValueError("Widget must define a 'key' attribute")

    WIDGET_REGISTRY[widget_class.key] = widget_class
    return widget_class


def get_widget(widget_key):
    """
    Retrieve widget class by key.
    """
    return WIDGET_REGISTRY.get(widget_key)