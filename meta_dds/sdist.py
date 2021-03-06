'''
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.
'''

'''
Describes the source distributions dealt with by meta-dds.
'''

import shutil
from pathlib import Path
from typing import List
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from meta_dds.toolchain import DDSToolchain

@dataclass
class SDist(ABC):
    '''
    A "Source Distribution", or SDist, is a project setup consisting only of
    compilable files. This is what dds proper deals with.
    '''
    name: str
    project_root: Path

@dataclass
class ToolchainSpecificSDist(SDist):
    '''
    A toolchain specific SDist is an SDist for a particular toolchain. It is an
    invalid operation to distribute this as if it were toolchain-independent.
    '''
    pass

@dataclass
class SDistTemplate(ABC):
    '''
    A "Source Distribution Template", or SDistTemplate, is something that can
    be _instantiated_ to produce SDists. This may include running code
    generation tools.
    '''
    name: str

    @abstractmethod
    def instantiate(self, toolchain: DDSToolchain, tmp_dir: Path) -> ToolchainSpecificSDist:
        ...

@dataclass
class PureSDist(ToolchainSpecificSDist, SDistTemplate):
    '''
    A pure SDist is a source distribution that doesn't care about the specifics
    of what it's being used for. This is what dds alone knows how to handle.
    Instantiation is a no-op.
    '''
    def instantiate(self, toolchain: DDSToolchain, tmp_dir: Path) -> 'PureSDist':
        return self

