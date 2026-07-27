def serialize(log):
    return {
        "timestamp": log.timestamp,
        "module":    log.module,
        "action":    log.action,
        "field":     log.field_name,
        "old":       log.old_value,
        "new":       log.new_value,
        "user":      getattr(log.user, "email", None),
        "source":    log.source,
        "metadata":  log.metadata,
    }
