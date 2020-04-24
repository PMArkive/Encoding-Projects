#!/usr/bin/env python3
import vapoursynth as vs
import acsuite as acs
import lvsfunc as lvf
core = vs.core
ac = acs.AC()


path = r'BDMV/[BDMV][191127] Fate／kaleid liner Prisma☆Illya Prisma☆Phantasm/PRISMAPHANTASM_SP/BDMV/STREAM/00005.m2ts'
src = lvf.src(path)

if __name__ == "__main__":
    ac.eztrim(src, [([24, -24])], path[:-4]+"wav", "IllyaOVABD_NCOP1_cut.wav")

src.set_output()
