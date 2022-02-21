'''
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.
'''

'''
Internal utilities for working with tempfiles.
'''

import shutil
import tempfile
from pathlib import Path
from contextlib import contextmanager

@contextmanager
def TemporaryDirectory(scratch_dir=None, **kwargs):
    '''
    Create a temporary directory.
    
    :param scratch_dir: If specified, this directory is used instead of a
        temporary directory. The directory will *not* be removed when finished;
        instead, it will be removed upfront if it exists.
    '''
    if scratch_dir is not None:
        scratch_dir = Path(scratch_dir)
        if scratch_dir.exists():
            shutil.rmtree(scratch_dir)
        scratch_dir.mkdir(parents=True)
        
        yield scratch_dir
    else:
        if 'prefix' not in kwargs:
            kwargs['prefix'] = 'meta-dds-'
        with tempfile.TemporaryDirectory(**kwargs) as f:
            yield Path(f)

@contextmanager
def TemporaryFile(**kwargs):
    if 'prefix' not in kwargs:
        kwargs['prefix'] = 'meta-dds-f-'

    with tempfile.NamedTemporaryFile(**kwargs) as f:
        yield Path(f.name)
