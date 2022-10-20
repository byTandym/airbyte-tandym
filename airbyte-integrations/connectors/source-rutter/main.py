#
# Copyright (c) 2022 Airbyte, Inc., all rights reserved.
#


import sys

from airbyte_cdk.entrypoint import launch
from source_rutter import SourceRutter

if __name__ == "__main__":
    source = SourceRutter()
    launch(source, sys.argv[1:])
