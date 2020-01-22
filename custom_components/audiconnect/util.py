from functools import reduce
import logging

_LOGGER = logging.getLogger(__name__)


def get_attr(dictionary, keys, default=None):
    return reduce(
        lambda d, key: d.get(key, default) if isinstance(d, dict) else default,
        keys.split("."),
        dictionary,
    )


def to_byte_array(hexString: str):
    result = []
    for i in range(0, len(hexString), 2):
        result.append(int(hexString[i : i + 2], 16))

    return result


def log_exception(exception, message):
    err = message + ": " + str(exception).rstrip("\n")
    _LOGGER.error(err)


def parse_int(val: str):
    try:
        return int(val)
    except ValueError:
        return None


def parse_float(val: str):
    try:
        return float(val)
    except ValueError:
        return None
