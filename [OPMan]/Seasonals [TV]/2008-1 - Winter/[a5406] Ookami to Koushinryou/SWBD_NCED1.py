import os
from pathlib import Path
from typing import Any, Dict, List, Tuple, Union

import vapoursynth as vs
from lvsfunc.misc import source
from lvsfunc.types import Range
from vardautomation import FileInfo, PresetBD, PresetFLAC, VPath

from project_module import enc, flt

core = vs.core


shader_file = 'assets/FSRCNNX_x2_16-0-4-1.glsl'
if not Path(shader_file).exists():
    hookpath = r"mpv/shaders/FSRCNNX_x2_16-0-4-1.glsl"
    shader_file = os.path.join(str(os.getenv("APPDATA")), hookpath)


# Sources
JP_BD = FileInfo(r"E:/src/[BDMV] Spice and Wolf Blu-ray BOX Complete Edition R2J/[BDMV][130306] Spice and Wolf Disc2/BDMV/STREAM/00009.m2ts",  # noqa
                 [(24, -24)], idx=lambda x: source(x, force_lsmas=True, cachedir=''), preset=[PresetBD, PresetFLAC])
JP_BD.name_file_final = VPath(f"premux/{JP_BD.name} (Premux).mkv")
JP_BD.a_src_cut = VPath(JP_BD.name)
JP_BD.do_qpfile = True


strong_debanding: List[Range] = [  # Ranges for stronger debanding
]

zones: Dict[Tuple[int, int], Dict[str, Any]] = {  # Zoning for the encoder
}


def filterchain() -> Union[vs.VideoNode, Tuple[vs.VideoNode, ...]]:
    """Main VapourSynth filterchain"""
    import debandshit as dbs
    import havsfunc as haf
    import lvsfunc as lvf
    import rekt
    import vardefunc as vdf
    from awsmfunc import bbmod
    from ccd import ccd
    from muvsfunc import SSIM_downsample
    from vsutil import depth, get_w, get_y

    src = JP_BD.clip_cut

    ef = depth(src, 16)

    # cursed edgefixing, but seems to largely work?
    rkt = rekt.rektlvls(ef, [0, 1, -2], [15, -5, -5, 40])
    bb = bbmod(rkt, bottom=1, blur=50)
    fb_bot = core.fb.FillBorders(rkt, bottom=1, mode="fillmargins")
    ef_expr = core.std.Expr([bb, fb_bot], f'x {20 >> 8} < y x ?')

    fb_left = core.fb.FillBorders(ef_expr, left=1, mode="fillmargins")
    ef_uv = bbmod(fb_left, left=6, right=2, blur=5, y=False)
    ef_uv_limit = core.std.Expr([fb_left, ef_uv], f'x {120 << 8} > y x ?')

    ef = depth(ef_uv_limit, 32)
    src_y = get_y(ef)

    pre_den = core.dfttest.DFTTest(src_y, sigma=3.0)
    l_mask = vdf.mask.FDOG().get_mask(pre_den, lthr=0.125, hthr=0.050).rgsf.RemoveGrain(4).rgsf.RemoveGrain(4)
    l_mask = l_mask.std.Minimum().std.Deflate().std.Median().std.Convolution([1] * 9).std.Maximum()

    # Descaling.
    descaled = lvf.kernels.Catrom().descale(src_y, get_w(720, src_y.width/src_y.height), 720)
    descaled = core.resize.Bicubic(descaled, format=vs.YUV444P16)

    # Slight AA in an attempt to forcibly fix starved lineart.
    baa = lvf.aa.based_aa(descaled, shader_file)
    sraa = lvf.aa.upscaled_sraa(descaled, rfactor=1.45)
    clamp_aa = lvf.aa.clamp_aa(descaled, baa, sraa, strength=1.15)
    clamp_aa = depth(get_y(clamp_aa), 32)

    # Doing a mixed reupscale using nn3/fsrcnnx, grabbing the darkest parts of each
    rescaled_nn3 = vdf.scale.nnedi3cl_double(clamp_aa, use_znedi=True, pscrn=1)
    rescaled_fsrcnnx = vdf.scale.fsrcnnx_upscale(clamp_aa, rescaled_nn3.width, rescaled_nn3.height, shader_file)
    rescaled = core.std.Expr([rescaled_nn3, rescaled_fsrcnnx], "x y min")

    downscaled = SSIM_downsample(rescaled, src_y.width, src_y.height, smooth=((3 ** 2 - 1) / 12) ** 0.5,
                                 sigmoid=True, filter_param_a=-1/2, filter_param_b=1/4)
    downscaled = core.std.MaskedMerge(src_y, downscaled, l_mask)

    scaled = depth(vdf.misc.merge_chroma(downscaled, ef), 16)

    # Chroma warping to forcibly wrap it a bit nicer around the lineart. Also fixing slight shift. 4:2:0 was a mistake.
    cshift = flt.shift_chroma(scaled, src_left=0.5)
    cwarp = cshift.warp.AWarpSharp2(thresh=72, blur=3, type=1, depth=6, planes=[1, 2])

    # The textures and detail are very smeary, so gotta be careful not to make it even worse
    stab = haf.GSMC(cwarp, radius=3, planes=[0], thSAD=75)
    den_uv = ccd(stab, threshold=5, matrix='709')
    decs = vdf.noise.decsiz(den_uv, sigmaS=8.0, min_in=200 << 8, max_in=240 << 8)

    # Scenefiltered debanding. Not graining, since we kept most of the original grain anyway.
    deband_wk = dbs.debanders.dumb3kdb(decs, radius=16, threshold=[24, 0], grain=0)
    deband_wk = core.placebo.Deband(deband_wk, iterations=2, threshold=3.5, radius=12, grain=0, planes=2 | 4)

    # Strong denoising + debanding to hopefully deal with all the awful bands. Courtesy of :b:arde
    dft = core.dfttest.DFTTest(decs, sigma=7.0)
    ccd_uv = ccd(dft, threshold=10, matrix='709')
    plac = flt.masked_placebo(ccd_uv, rad=45, thr=8.5, itr=2, grain=3.0,
                              mask_args={'detail_brz': 100, 'lines_brz': 450})

    dft_diff = core.std.MakeDiff(decs, dft)
    plac_diff = core.std.MergeDiff(plac, dft_diff)

    deband = lvf.rfs(deband_wk, plac_diff, strong_debanding)

    return deband


if __name__ == '__main__':
    FILTERED = filterchain()
    enc.Encoder(JP_BD, FILTERED).run(clean_up=True, settings_name='x265_settings', zones=zones)
elif __name__ == '__vapoursynth__':
    FILTERED = filterchain()
    if not isinstance(FILTERED, vs.VideoNode):
        raise ImportError(
            f"Input clip has multiple output nodes ({len(FILTERED)})! Please output a single clip")
    else:
        enc.dither_down(FILTERED).set_output(0)
else:
    JP_BD.clip_cut.std.SetFrameProp('node', intval=0).set_output(0)
    FILTERED = filterchain()
    if not isinstance(FILTERED, vs.VideoNode):
        for i, clip_filtered in enumerate(FILTERED, start=1):
            clip_filtered.std.SetFrameProp('node', intval=i).set_output(i)
    else:
        FILTERED.std.SetFrameProp('node', intval=1).set_output(1)
