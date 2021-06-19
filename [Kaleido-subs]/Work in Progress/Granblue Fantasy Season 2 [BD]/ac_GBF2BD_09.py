#!/usr/bin/env python3
import os

import lvsfunc as lvf
from acsuite import eztrim

path = r"BDMV/GRANBLUE_FANTASY_SEASON2_5/BDMV/STREAM/00001.m2ts"
src = lvf.src(path, cachedir="")

if __name__ == "__main__":
    eztrim(src, (0, -25), path, f"{os.path.basename(__file__)[3:-3]}_cut.wav")
