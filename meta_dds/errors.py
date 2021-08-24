'''
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.
'''

import logging
from pathlib import Path


class MetaDDSException(Exception):
    '''
    A common base type for all MetaDDS exceptions
    '''
    pass


class FileNotFound(MetaDDSException, FileNotFoundError):
    def __init__(self, message: str, file: Path):
        self.file = file
        super().__init__(message)


def is_traceback() -> bool:
    return logging.root.isEnabledFor(logging.DEBUG)
