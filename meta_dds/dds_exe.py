'''
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.
'''

import logging
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List

from meta_dds import logutils
from meta_dds.errors import MetaDDSException
from meta_dds.util import IfExists

_logger = logging.getLogger(__name__)


class DDSRunFailed(MetaDDSException):
    pass


@dataclass
class DDS:
    dds_exe: Path

    def pkg(self):
        dds = self

        class Pkg:
            def create(self, *, project: Path, output: Path, if_exists: IfExists):
                dds._run(['pkg', 'create', '--project', str(project),
                          '--output', str(output), '--if-exists', if_exists.value])

        return Pkg()

    def _run(self, cmd: List[str]):
        cmd = [str(self.dds_exe)] + cmd
        _logger.debug('Running DDS as: %s', logutils.defer(
            lambda: shlex.join(cmd)))

        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            raise DDSRunFailed(
                f'{self.dds_exe} exited with non-zero exit status {e.returncode}') from e
