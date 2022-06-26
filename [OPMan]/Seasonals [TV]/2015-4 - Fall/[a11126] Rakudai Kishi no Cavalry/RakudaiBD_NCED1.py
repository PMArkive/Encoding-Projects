from __future__ import annotations

from typing import Any, Dict, Tuple

import vapoursynth as vs
import vsencode as vse
from vardefunc import initialise_input

from project_module import flt

ini = vse.generate.init_project()

core = vse.util.get_vs_core(reserve_core=ini.reserve_core)

shader = vse.get_shader("FSRCNNX_x2_56-16-4-1.glsl")


# Sources
SRC = vse.FileInfo(f"{ini.bdmv_dir}/RAKUDAI_KISHI_NO_CAVALRY_VOL2/BDROM/BDMV/STREAM/00002.m2ts", (24, -24))


zones: Dict[Tuple[int, int], Dict[str, Any]] = {  # Zones for the encoder
}


@initialise_input(bits=32)
def filterchain(src: vs.VideoNode = SRC.clip_cut) -> vs.VideoNode | Tuple[vs.VideoNode, ...]:
    """Main filterchain"""
    import havsfunc as haf
    import jvsfunc as jvf
    import kagefunc as kgf
    import lvsfunc as lvf
    import vardefunc as vdf
    from vsutil import depth, get_w, get_y, insert_clip

    assert src.format

    src_y = get_y(src)

    l_mask = vdf.mask.FDOG().get_mask(src_y, lthr=0.175, hthr=0.175).rgsf.RemoveGrain(4).rgsf.RemoveGrain(4)
    l_mask = l_mask.std.Minimum().std.Deflate().std.Median().std.Convolution([1] * 9)

    descale = lvf.kernels.Bicubic(b=.2, c=.4).descale(src_y, get_w(720), 720)
    upscale = vdf.scale.fsrcnnx_upscale(descale, 1920, 1080, shader,
                                        downscaler=lvf.scale.ssim_downsample,
                                        undershoot=1.1, overshoot=1.5)
    upscale_min = core.akarin.Expr([src_y, upscale], "x y min")
    rescale = core.std.MaskedMerge(src_y, upscale_min, l_mask)
    scaled = depth(vdf.misc.merge_chroma(rescale, src), 16)

    smd = haf.SMDegrain(scaled, tr=3, thSAD=50)
    ccd_uv = jvf.ccd(smd, threshold=3)
    decs = vdf.noise.decsiz(ccd_uv, min_in=192 << 8, max_in=240 << 8)

    deband = flt.masked_f3kdb(decs, rad=18, thr=[24, 12], grain=[24, 12])

    deb_trim = deband[1985:-1]
    crossfade = kgf.crossfade(deb_trim, deband[-1] * deb_trim.num_frames, deb_trim.num_frames - 1)
    crossfade = insert_clip(deband, crossfade, 1985)

    return crossfade


FILTERED = filterchain()


if __name__ == '__main__':
    vse.EncodeRunner(SRC, FILTERED).video('x265', 'settings/x265_settings', zones=zones) \
        .audio('flac').mux('LightArrowsEXE@Kaleido').run()
elif __name__ == '__vapoursynth__':
    if not isinstance(FILTERED, vs.VideoNode):
        raise vs.Error(f"Input clip has multiple output nodes ({len(FILTERED)})! Please output a single clip")
    else:
        vse.video.finalize_clip(FILTERED).set_output(0)
else:
    SRC.clip_cut.set_output(0)

    if not isinstance(FILTERED, vs.VideoNode):
        for i, clip_filtered in enumerate(FILTERED, start=1):
            clip_filtered.set_output(i)
    else:
        FILTERED.set_output(1)

    for i, audio_node in enumerate(SRC.audios_cut, start=10):
        audio_node.set_output(i)
