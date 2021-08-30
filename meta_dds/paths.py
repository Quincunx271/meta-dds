'''
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.
'''

import logging
import sys
from abc import ABC, abstractmethod, abstractmethod
from dataclasses import dataclass
from os import getenv
from pathlib import Path

from meta_dds import logutils

_logger = logging.getLogger(__name__)

'''
Dirs & logic ported from DDS proper
'''

class _Paths(ABC):
    @abstractmethod
    def user_home_dir(self) -> Path:
        ...

    @abstractmethod
    def user_data_dir(self) -> Path:
        ...

    @abstractmethod
    def user_cache_dir(self) -> Path:
        ...

    @abstractmethod
    def user_config_dir(self) -> Path:
        ...

    def dds_data_dir(self) -> Path:
        return self.user_data_dir() / 'dds'

    def dds_cache_dir(self) -> Path:
        return self.user_cache_dir() / 'dds-cache'

    def dds_config_dir(self) -> Path:
        return self.user_config_dir() / 'dds'


class _WindowsPaths(_Paths):
    def user_home_dir(self) -> Path:
        return Path(getenv('UserProfile', '/')).resolve()

    def user_data_dir(self) -> Path:
        return Path(getenv('LocalAppData', '/')).resolve()

    def user_cache_dir(self) -> Path:
        return Path(getenv('LocalAppData', '/')).resolve()

    def user_config_dir(self) -> Path:
        return Path(getenv('AppData', '/')).resolve()


@dataclass
class _UnixPaths(_Paths):
    data: str
    cache: str
    config: str

    def user_home_dir(self) -> Path:
        home = getenv('HOME')
        if home is not None:
            return Path(home).resolve()
        _logger.error('No HOME environment variable set!')
        return Path('/')

    def user_data_dir(self) -> Path:
        return Path(getenv('XDG_DATA_HOME', self.user_home_dir() / self.data)).resolve()

    def user_cache_dir(self) -> Path:
        return Path(getenv('XDG_CACHE_HOME', self.user_home_dir() / self.cache)).resolve()

    def user_config_dir(self) -> Path:
        return Path(getenv('XDG_CONFIG_HOME', self.user_home_dir() / self.config)).resolve()


if sys.platform.startswith('win32'):
    _PATHS = _WindowsPaths()
elif sys.platform.startswith('linux'):
    _PATHS = _UnixPaths(
        data='.local/share',
        cache='.cache',
        config='.config',
    )
elif sys.platform.startswith('darwin'):
    _PATHS = _UnixPaths(
        data='Library/Application Support',
        cache='Library/Caches',
        config='Library/Preferences',
    )
else:
    _logger.critical('Unsupported platform %s', sys.platform())
    exit(logutils.EXIT_INTERNAL_ERROR)

sys.modules[__name__] = _PATHS
