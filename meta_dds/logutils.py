'''
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.
'''

import logging
import sys
from enum import Enum, auto
from logging import Formatter, Logger, LogRecord


class defer:
    def __init__(self, action):
        self.action = action

    def __str__(self):
        return self.action()


# From https://stackoverflow.com/a/35804945
def __addLoggingLevel(levelName, levelNum, methodName=None):
    """
    Comprehensively adds a new logging level to the `logging` module and the
    currently configured logging class.

    `levelName` becomes an attribute of the `logging` module with the value
    `levelNum`. `methodName` becomes a convenience method for both `logging`
    itself and the class returned by `logging.getLoggerClass()` (usually just
    `logging.Logger`). If `methodName` is not specified, `levelName.lower()` is
    used.

    To avoid accidental clobberings of existing attributes, this method will
    raise an `AttributeError` if the level name is already an attribute of the
    `logging` module or if the method name is already present

    Example
    -------
    >>> addLoggingLevel('TRACE', logging.DEBUG - 5)
    >>> logging.getLogger(__name__).setLevel("TRACE")
    >>> logging.getLogger(__name__).trace('that worked')
    >>> logging.trace('so did this')
    >>> logging.TRACE
    5

    """
    if not methodName:
        methodName = levelName.lower()

    if hasattr(logging, levelName):
        raise AttributeError(
            '{} already defined in logging module'.format(levelName))
    if hasattr(logging, methodName):
        raise AttributeError(
            '{} already defined in logging module'.format(methodName))
    if hasattr(logging.getLoggerClass(), methodName):
        raise AttributeError(
            '{} already defined in logger class'.format(methodName))

    # This method was inspired by the answers to Stack Overflow post
    # http://stackoverflow.com/q/2183233/2988730, especially
    # http://stackoverflow.com/a/13638084/2988730
    def logForLevel(self, message, *args, **kwargs):
        if self.isEnabledFor(levelNum):
            self._log(levelNum, message, args, **kwargs)

    def logToRoot(message, *args, **kwargs):
        logging.log(levelNum, message, *args, **kwargs)

    logging.addLevelName(levelNum, levelName)
    setattr(logging, levelName, levelNum)
    setattr(logging.getLoggerClass(), methodName, logForLevel)
    setattr(logging, methodName, logToRoot)


__addLoggingLevel('TRACE', logging.DEBUG - 5)


_META_DDS_LOG_FORMAT = '[{levelname}] [{name:<20}] {message}'
_ADJUST_LEVEL = '{:<5}'


class MetaDDSFormatter(Formatter):
    def __init__(self, fmt: str = _META_DDS_LOG_FORMAT, style: str = '{'):
        super().__init__(fmt=fmt, style=style)

    def format(self, record: LogRecord):
        record.levelname = _ADJUST_LEVEL.format(record.levelname.lower())
        record = self._post_adjust(record)
        return super().format(record)

    def _post_adjust(self, record: LogRecord) -> LogRecord:
        return record


_RESET = '\033[m'
_GREEN = '\033[32m'
_CYAN = '\033[36m'
_WHITE = '\033[37m'
_BOLD_YELLOW = '\033[33m\033[1m'
_BOLD_RED = '\033[31m\033[1m'
_BOLD_RED_BG = '\033[1m\033[41m'


def _colored(color: str, msg: str) -> str:
    if color == '':
        return msg
    return f'{color}{msg}{_RESET}'


_COLORMAP = {
    logging.TRACE: _WHITE,
    logging.DEBUG: _CYAN,
    logging.INFO: _GREEN,
    logging.WARNING: _BOLD_YELLOW,
    logging.ERROR: _BOLD_RED,
    logging.CRITICAL: _BOLD_RED_BG,
}


class ColoredMetaDDSFormatter(MetaDDSFormatter):
    def __init__(self, fmt: str = _META_DDS_LOG_FORMAT, style: str = '{'):
        super().__init__(fmt=fmt, style=style)

    def _post_adjust(self, record: LogRecord) -> LogRecord:
        record.levelname = _colored(
            _COLORMAP[record.levelno], record.levelname)
        return record


class ColorMode(Enum):
    NO = auto()
    YES = auto()
    AUTO = YES if sys.stderr.isatty() else NO


def get_formatter(mode: ColorMode) -> Formatter:
    if mode is ColorMode.NO:
        return MetaDDSFormatter()
    else:
        assert mode is ColorMode.YES
        return ColoredMetaDDSFormatter()


def unimplemented(logger: Logger, message: str = ''):
    logger.critical('Internal error: feature is unimplemented!%s%s',
                    ' With message: ' if message else '', message)
    exit(1)
