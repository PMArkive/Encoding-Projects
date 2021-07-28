import argparse  # noqa
import os
from typing import List, Optional, Tuple, Union

import vapoursynth as vs
from bvsfunc.util import ap_video_source
from lvsfunc.misc import source
from lvsfunc.types import Range
from vardautomation import (JAPANESE, AudioStream, FileInfo, Mux, PresetAAC,
                            PresetWEB, RunnerConfig, SelfRunner, VideoStream,
                            VPath, X264Encoder, Patch)

from kobayashi2_filters import flt, util, encode

core = vs.core

make_wraw: bool = False  # Create a workraw.

EP_NUM = __file__[-5:-3]


# Sources
JP_CR = FileInfo(f'sources/{EP_NUM}/Kobayashi-san Chi no Maid Dragon S E{EP_NUM} [1080p][AAC][JapDub][GerEngSub][Web-DL].mkv',
                 idx=lambda x: source(x, force_lsmas=True, cachedir=''))
JP_AOD = FileInfo(f'sources/{EP_NUM}/Kobayashi-san Chi no Maid Dragon S E{EP_NUM} [1080p+][AAC][JapDub][GerSub][Web-DL].mkv',
                  idx=lambda x: source(x, force_lsmas=True, cachedir=''),
                  preset=[PresetWEB, PresetAAC])
YT_NCOP = FileInfo('sources/【期間限定公開】TVアニメ『小林さんちのメイドラゴンＳ』ノンテロップオープニング映像-bEb4xT8lnYU.mkv',
                   idx=lambda x: source(x, force_lsmas=True, cachedir=''))
YT_NCED = FileInfo('sources/【期間限定公開】TVアニメ『小林さんちのメイドラゴンＳ』ノンテロップエンディング映像-kMWLe37SMBs.mp4',
                   idx=lambda x: source(x, force_lsmas=True, cachedir=''))
JP_AOD.name_file_final = VPath(fr"[Premux] Maid Dragon S2 - {EP_NUM}.mkv")
JP_AOD.name_clip_output = VPath(JP_AOD.name + '.264')
JP_AOD.a_src_cut = VPath(f"{JP_AOD.name}_cut.aac")
JP_AOD.do_qpfile = True


# Common variables
# OP/ED frames
opstart: Union[int, bool] = 600
edstart: Union[int, bool] = 31411
op_offset: int = 2
ed_offset: int = 3

hardsub_sign: List[Range] = [  # Leftover hardsubbed signs that need a stronger mask
    (3465, 3479), (11296, 11308), (12012, 12026), (12030, 12133), (13591, 13619), (14049, 14120), (14465, 14585),
    (16194, 16217), (18055, 18132), (19308, 19330), (20894, 20933), (21541, 21602), (21752, 21867), (22122, 22199),
    (22577, 22580), (22586, 22589), 22592, (23482, 23645), (24543, 24549), (25188, 25247), (33603, 33610), (33620, 33627),
    (33856, 33868), (33928, 34047)
]

replace_scenes: List[Range] = [  # List of scenes to replace
    34045  # idk what happens to this frame lol
]


def trim() -> Tuple[vs.VideoNode, Optional[vs.VideoNode], vs.VideoNode]:
    """Waka/Aod trimming"""
    from lvsfunc.comparison import diff, stack_compare  # noqa

    src_clean = JP_CR.clip_cut
    src_hard = JP_AOD.clip_cut
    hdiff = None

    dehardsubbed: vs.VideoNode = util.dehardsub(src_hard, src_clean, hardsub_sign, replace_scenes)
    scomp = stack_compare(src_clean, dehardsubbed)

    # Comment out after it's run because >lol wasting time in $(CURRENT YEAR)
    #hdiff = diff(src_clean, dehardsubbed, thr=80)

    return dehardsubbed, hdiff, scomp


def filterchain() -> Union[vs.VideoNode, Tuple[vs.VideoNode, ...]]:
    """Regular VapourSynth filterchain"""
    import lvsfunc as lvf
    import vardefunc as vdf
    from vsutil import depth, get_y

    src, *_ = trim()
    src_NCOP, src_NCED = YT_NCOP.clip, YT_NCED.clip
    b = core.std.BlankClip(src, length=1)

    # OP/ED stack comps to check that it lines up
    op_scomp = lvf.scomp(src[opstart:opstart+src_NCOP.num_frames-1]+b, src_NCOP[:-op_offset]+b)  # noqa
    ed_scomp = lvf.scomp(src[edstart:edstart+src_NCED.num_frames-1]+b, src_NCED[:-ed_offset]+b)  # noqa

    # Blurring clips
    blur_src = core.bilateral.Gaussian(src, sigma=2.5)
    blur_NCOP = core.bilateral.Gaussian(src_NCOP, sigma=2.5)
    blur_NCED = core.bilateral.Gaussian(src_NCED, sigma=2.5)

    # Masking credits
    op_mask = vdf.dcm(
        blur_src, blur_src[opstart:opstart+src_NCOP.num_frames-op_offset], blur_NCOP[:-op_offset],
        start_frame=opstart, thr=28, prefilter=False) if opstart is not False \
        else get_y(core.std.BlankClip(src))
    ed_mask = vdf.dcm(
        blur_src, blur_src[edstart:edstart+src_NCED.num_frames-ed_offset], blur_NCED[:-ed_offset],
        start_frame=edstart, thr=25, prefilter=False) if edstart is not False \
        else get_y(core.std.BlankClip(src))
    credit_mask = core.std.Expr([op_mask, ed_mask], expr='x y +')
    credit_mask = depth(credit_mask, 16).std.Binarize()

    src = depth(src, 16)
    line_mask = vdf.mask.FDOG().get_mask(get_y(src))

    src_y = get_y(src)
    denoise_y = flt.bm3d_ref(src_y, bm3d_sigma=1, dec_sigma=8, dec_min=192 << 8)
    denoise_y = core.std.MaskedMerge(denoise_y, src_y, line_mask)
    merged = vdf.misc.merge_chroma(denoise_y, src)

    dehalo = flt.bidehalo(merged, sigma=1, mask_args={'brz': 0.25})

    cmerged = core.std.MaskedMerge(dehalo, src, credit_mask)

    deband = flt.masked_f3kdb(cmerged, thr=20, grain=12, mask_args={'brz': (1500, 3500)})
    grain = flt.default_grain(deband)

    return grain  # type: ignore


def wraw_filterchain() -> vs.VideoNode:
    """Workraw filterchain with minimal filtering"""
    from vsutil import depth

    src, *_ = trim()
    src = depth(src, 16)

    deband = flt.masked_f3kdb(src, thr=30, grain=16, mask_args={'brz': (1500, 3500)})
    grain = flt.default_grain(deband)

    return grain  # type: ignore


if __name__ == '__main__':
    FILTERED = filterchain() if not make_wraw else wraw_filterchain()
    encode.Encoder(JP_AOD, FILTERED).run(wraw=make_wraw, make_comp=False)  # type: ignore
elif __name__ == '__vapoursynth__':
    FILTERED = filterchain()
    if not isinstance(FILTERED, vs.VideoNode):
        for i, CLIP_FILTERED in enumerate(FILTERED, start=1):
            CLIP_FILTERED.set_output(i)
    else:
        FILTERED.set_output(1)
else:
    JP_AOD.clip_cut.std.SetFrameProp('node', intval=0).set_output(0)
    #FILTERED = trim()
    FILTERED = filterchain()
    if not isinstance(FILTERED, vs.VideoNode):
        for i, clip_filtered in enumerate(FILTERED, start=1):
            if clip_filtered:
                clip_filtered.std.SetFrameProp('node', intval=i).set_output(i)
    else:
        FILTERED.std.SetFrameProp('node', intval=1).set_output(1)
